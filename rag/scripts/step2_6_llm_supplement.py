#!/usr/bin/env python3
"""
2.6단계: LLM 기반 QC 보강 (Supplement, Not Replace)
- step2 결과 중 랜덤 샘플링하여 Haiku 4.5가 원문 대비 누락/오분류를 판단
- 기존 데이터를 수정하지 않고 qc_supplement 필드로 보강 내용만 추가
- 최종 출력: step2_supplemented.jsonl
"""

import json
import csv
import time
import os
import sys
import random
import boto3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from botocore.exceptions import ClientError

try:
    from tqdm import tqdm
except ImportError:
    print("tqdm 미설치. pip install tqdm 후 재실행하세요.")
    sys.exit(1)

# ── 설정 ───────────────────────────────────────────────────
STEP1_FILE      = "data/step1_parsed_radiology.jsonl"
STEP2_FILE      = "data/step2_bedrock_extracted.jsonl"
FLAGGED_CSV     = "data/qc_flagged_rules.csv"  # 2.5단계 결과
OUTPUT_FILE     = "data/step2_supplemented.jsonl"
CHECKPOINT_FILE = "data/supplement_done_ids.txt"
STATS_JSON      = "data/qc_supplement_summary.json"

MODEL_ID    = "us.anthropic.claude-haiku-4-5-20251001-v1:0"  # Haiku 4.5 (inference profile)
REGION      = "us-east-1"
MAX_WORKERS = 5
MAX_RETRIES = 5

SAMPLE_RATE = 0.10  # 통과 건 중 10% 샘플링

file_lock = threading.Lock()
bedrock = boto3.client(service_name="bedrock-runtime", region_name=REGION)

# ── LLM 보강 프롬프트 ──────────────────────────────────────
SUPPLEMENT_PROMPT = """You are an expert Clinical Data Quality Auditor. Your job is to SUPPLEMENT (not replace) a previous AI extraction by finding what was MISSED.

[Original Radiology Text]
{raw_text}

[Previous AI Extraction]
- Modality: {modality}
- Clinical Status: {clinical_status}
- Positive Findings: {positive_findings}
- Negative Findings: {negative_findings}

[QC Flag Reason]
{flag_reason}

[Your Task — STRICT RULES]
1. Compare the original text against the previous extraction.
2. Pay special attention to the QC Flag Reason above. If it says "Negation Leak", carefully check if any items in Positive Findings are actually normal/absent findings that belong in Negative Findings.
3. Find ONLY what is MISSING from the extraction. Do NOT repeat items already extracted.
4. For each category below, list ONLY NEW items to ADD:

   - added_positive: Abnormalities PRESENT in the text but MISSING from positive_findings.
     IMPORTANT: Include measurements (cm/mm) if the original text has them.
   
   - added_negative: Normal/absent findings in the text but MISSING from negative_findings.
     Also include any items currently in positive_findings that should actually be negative
     (e.g., "No pneumothorax" was put in positive — add it here as a correction note).
   
   - negation_corrections: Items currently in positive_findings that contain negation language
     (no, without, normal, unremarkable, clear, absent) and should NOT be there.
     List the exact string from positive_findings that is wrong.

5. If the previous extraction is already complete and correct, return empty lists.

Return ONLY valid JSON, no markdown:
{{"added_positive": [...], "added_negative": [...], "negation_corrections": [...]}}"""


def call_bedrock(prompt):
    """Bedrock converse API + 지수 백오프"""
    for attempt in range(MAX_RETRIES):
        try:
            response = bedrock.converse(
                modelId=MODEL_ID,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 1500, "temperature": 0.0}
            )
            raw = response["output"]["message"]["content"][0]["text"].strip()

            # 마크다운 블록 제거
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            data = json.loads(raw)

            # Sanitization
            for key in ["added_positive", "added_negative", "negation_corrections"]:
                if key not in data:
                    data[key] = []
                elif isinstance(data[key], list):
                    data[key] = [
                        str(item).strip() for item in data[key]
                        if item is not None and str(item).strip()
                    ]

            return data

        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("ThrottlingException", "TooManyRequestsException"):
                time.sleep(min(2 ** attempt + 0.5, 30))
                continue
            elif code == "ModelTimeoutException":
                time.sleep(5)
                continue
            else:
                raise
        except (json.JSONDecodeError, Exception):
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            return None
    return None


def process_one(note_id, raw_text, ai_analysis, flag_reason="None — sampled for random QC check"):
    """단일 레코드 LLM 보강"""
    pos = ai_analysis.get("positive_findings", [])
    neg = ai_analysis.get("negative_findings", [])

    prompt = SUPPLEMENT_PROMPT.format(
        raw_text=raw_text[:3000],  # 토큰 절약
        modality=ai_analysis.get("modality", ""),
        clinical_status=ai_analysis.get("clinical_status", ""),
        positive_findings=", ".join(pos) if pos else "None",
        negative_findings=", ".join(neg) if neg else "None",
        flag_reason=flag_reason,
    )

    result = call_bedrock(prompt)
    return note_id, result


def main():
    # ── 1) 체크포인트 로드 ─────────────────────────────────
    print("[1/6] 체크포인트 로드 중...")
    done_ids = set()
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            done_ids = {line.strip() for line in f if line.strip()}
    print(f"  → 이미 보강 완료: {len(done_ids):,}건")

    # ── 2) Step1 원문 로드 ─────────────────────────────────
    print("[2/6] Step1 원문 로드 중...")
    raw_texts = {}
    with open(STEP1_FILE, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            findings = data.get("raw_findings", "").strip()
            impression = data.get("raw_impression", "").strip()
            raw_texts[data["note_id"]] = f"{findings} {impression}".strip()
    print(f"  → {len(raw_texts):,}건")

    # ── 3) 2.5단계 flagged 목록 로드 ──────────────────────
    print("[3/6] 규칙 QC flagged 목록 로드 중...")
    flagged_map = {}  # note_id -> violation_type
    if os.path.exists(FLAGGED_CSV):
        with open(FLAGGED_CSV, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                flagged_map[row["note_id"]] = row["violation_type"]
    flagged_ids = set(flagged_map.keys())
    print(f"  → Flagged: {len(flagged_ids):,}건 (전수 보강 대상)")

    # ── 4) Step2 데이터 로드 & 보강 대상 선정 ──────────────
    print("[4/6] Step2 데이터 로드 및 보강 대상 선정 중...")
    all_records = {}  # note_id -> record
    supplement_targets = []  # (note_id, raw_text, ai_analysis)

    with open(STEP2_FILE, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            nid = rec["note_id"]
            all_records[nid] = rec

    # 보강 대상 선정
    passed_ids = []
    for nid, rec in all_records.items():
        ai = rec.get("ai_analysis", {})
        raw = raw_texts.get(nid, "")

        # 빈 입력은 스킵
        if ai.get("_flag") == "empty_input" or not raw:
            continue

        if nid in flagged_ids:
            # Flagged 건: 전수 보강 (사유 포함)
            supplement_targets.append((nid, raw, ai, flagged_map[nid]))
        else:
            passed_ids.append(nid)

    # 통과 건 중 샘플링
    sample_size = int(len(passed_ids) * SAMPLE_RATE)
    sampled = random.sample(passed_ids, min(sample_size, len(passed_ids)))
    for nid in sampled:
        rec = all_records[nid]
        raw = raw_texts.get(nid, "")
        if raw:
            supplement_targets.append((nid, raw, rec.get("ai_analysis", {}), "None — sampled for random QC check"))

    # 이미 완료된 건 제외
    supplement_targets = [
        (nid, raw, ai, reason) for nid, raw, ai, reason in supplement_targets
        if nid not in done_ids
    ]

    total_targets = len(supplement_targets)
    print(f"  → 전체 레코드: {len(all_records):,}건")
    print(f"  → 보강 대상: {total_targets:,}건 (flagged 전수 + passed {SAMPLE_RATE*100:.0f}% 샘플)")

    if total_targets == 0:
        print("  → 보강 대상 없음. 바로 최종 파일 생성으로 이동.")
    else:
        # ── 5) LLM 보강 실행 ──────────────────────────────
        print(f"[5/6] Haiku 4.5 보강 실행 중 (workers={MAX_WORKERS})...")

        supplement_results = {}  # note_id -> supplement data

        # 이전 결과 로드 (재시작 시)
        # done_ids에 있는 건의 supplement 결과는 최종 병합 시 step2_supplemented에서 읽음

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(process_one, nid, raw, ai, reason): nid
                for nid, raw, ai, reason in supplement_targets
            }

            for future in tqdm(as_completed(futures), total=len(futures), desc="  LLM 보강"):
                nid = futures[future]
                try:
                    _, result = future.result()
                    if result:
                        supplement_results[nid] = result
                        # 체크포인트 기록
                        with file_lock:
                            with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
                                f.write(nid + "\n")
                except Exception as e:
                    print(f"\n  [에러] {nid}: {e}")

        print(f"  → 보강 완료: {len(supplement_results):,}건")

        # 보강 내용이 있는 건 통계
        has_additions = sum(
            1 for v in supplement_results.values()
            if v.get("added_positive") or v.get("added_negative") or v.get("negation_corrections")
        )
        print(f"  → 실제 보강 내용 있음: {has_additions:,}건")

    # ── 6) 최종 파일 생성 ─────────────────────────────────
    print(f"[6/6] 최종 파일 생성 중: {OUTPUT_FILE}")

    # 이전 실행에서 저장된 supplement 결과도 로드
    prev_supplements = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec.get("qc_supplement"):
                        prev_supplements[rec["note_id"]] = rec["qc_supplement"]
                except:
                    continue

    # 현재 실행 결과와 병합
    if total_targets > 0:
        all_supplements = {**prev_supplements}
        for nid, result in supplement_results.items():
            all_supplements[nid] = {
                "added_positive": result.get("added_positive", []),
                "added_negative": result.get("added_negative", []),
                "negation_corrections": result.get("negation_corrections", []),
                "model": "haiku-4.5",
            }
    else:
        all_supplements = prev_supplements

    # 최종 JSONL 생성
    written = 0
    supplemented = 0
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fout:
        for nid in all_records:
            rec = all_records[nid]

            if nid in all_supplements:
                supp = all_supplements[nid]
                rec["qc_supplement"] = supp
                # 보강 내용이 실제로 있는 경우만 카운트
                if supp.get("added_positive") or supp.get("added_negative") or supp.get("negation_corrections"):
                    supplemented += 1

            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1

    # 통계 저장
    summary = {
        "total_records": written,
        "supplement_targets": total_targets,
        "supplemented_with_content": supplemented,
        "sample_rate": SAMPLE_RATE,
        "model": MODEL_ID,
    }
    with open(STATS_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"  LLM 보강 QC 결과")
    print(f"{'='*50}")
    print(f"  총 레코드:       {written:,}건")
    print(f"  보강 대상:       {total_targets:,}건")
    print(f"  실제 보강 적용:  {supplemented:,}건")
    print(f"{'='*50}")
    print(f"  → {OUTPUT_FILE}")
    print(f"  → {STATS_JSON}")


if __name__ == "__main__":
    main()
