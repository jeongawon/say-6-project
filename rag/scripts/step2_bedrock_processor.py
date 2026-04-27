#!/usr/bin/env python3
"""
2단계: Bedrock LLM 시계열 의미 추출 (v2 - 강화 프롬프트)
- step1 결과를 환자별 시계열 정렬 후 Bedrock Claude Haiku로 구조화 추출
- 개선사항: Negation Leak 방지, 수치 보존, Temporal baseline 강제, hadm_id 보존
"""

import json
import time
import os
import sys
import re
import boto3
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from botocore.exceptions import ClientError

try:
    from tqdm import tqdm
except ImportError:
    print("tqdm 미설치. pip install tqdm 후 재실행하세요.")
    sys.exit(1)

# ── 설정 ───────────────────────────────────────────────────
INPUT_FILE      = "data/step1_parsed_radiology.jsonl"
OUTPUT_FILE     = "data/step2_bedrock_extracted.jsonl"
CHECKPOINT_FILE = "data/processed_note_ids.txt"
ERROR_LOG       = "logs/step2_errors.log"

MODEL_ID    = "anthropic.claude-3-haiku-20240307-v1:0"
REGION      = "us-east-1"
MAX_WORKERS = 15
MAX_RETRIES = 5
TEST_LIMIT  = 0  # 0 = 전체 처리, N > 0 = 환자 N명만 테스트

# 스레드 안전
file_lock = threading.Lock()
error_lock = threading.Lock()

# Bedrock 클라이언트
bedrock = boto3.client(service_name="bedrock-runtime", region_name=REGION)

# ── 통계 카운터 ────────────────────────────────────────────
stats = {"success": 0, "skipped_empty": 0, "skipped_done": 0, "errors": 0}
stats_lock = threading.Lock()


# ── 시스템 프롬프트 (강화 버전) ─────────────────────────────
SYSTEM_PROMPT = """You are an expert Clinical Data Architect. Extract structured data from a radiology report into JSON.
CRITICAL: All output MUST be in English.

[Input Context]
- Prior Context: {prior_text}
- Current Exam Tech: {current_tech}
- Current Findings: {current_findings}
- Current Impression: {current_impression}

[Extraction Rules — STRICT]

1. MODALITY: Classify the imaging modality as EXACTLY ONE of: ["CXR", "CT", "MRI", "US", "XR", "PET", "Other"].
   - CXR = chest X-ray, chest radiograph, PA and lateral chest
   - XR = any non-chest plain radiograph (extremity, spine, abdomen)
   - US = ultrasound, Doppler, sonogram, echocardiogram
   - CT = CT scan, CTA, CT angiography
   - MRI = MR, MRA, magnetic resonance
   - PET = PET, PET-CT
   - Other = fluoroscopy, lumbar puncture, swallow study, angiogram/interventional procedures

2. POSITIVE FINDINGS: Extract ONLY abnormalities that are actually PRESENT.
   - Process the text SENTENCE BY SENTENCE.
   - NEVER include items described as absent, normal, unremarkable, negative, or ruled out.
   - If a sentence contains "without X", "no X", "negative for X", the X part goes to negative_findings ONLY.
   - PRESERVE ALL MEASUREMENTS: Always include numeric values with units (e.g., "4.5 cm mass", "2.3 mm nodule", "12.7 cm kidney").

3. NEGATIVE FINDINGS: Extract ONLY items explicitly stated as ABSENT, NORMAL, or RULED OUT.
   - Examples: "No pneumothorax", "lungs are clear", "unremarkable liver", "negative for DVT"
   - NEVER duplicate items between positive and negative lists.

4. CLINICAL STATUS: Compare against Prior Context.
   - If Prior Context is "None (Initial Exam)" → MUST use "baseline". No exceptions.
   - Otherwise choose EXACTLY ONE of: ["new", "stable", "worsening", "improving", "resolved"].
   - "worsening" or "improving" are IMPOSSIBLE when Prior Context is "None (Initial Exam)".

Return ONLY a valid JSON object. No markdown, no explanation:
{{"modality": "...", "clinical_status": "...", "positive_findings": ["..."], "negative_findings": ["..."]}}"""


def call_bedrock(prompt):
    """Bedrock converse API 호출 + 지수 백오프 재시도"""
    for attempt in range(MAX_RETRIES):
        try:
            response = bedrock.converse(
                modelId=MODEL_ID,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 1500, "temperature": 0.0}
            )
            raw_text = response["output"]["message"]["content"][0]["text"]

            # 마크다운 블록 제거
            clean = raw_text.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()

            data = json.loads(clean)

            # Sanitization: 리스트 내 dict → string 변환
            for key in ["positive_findings", "negative_findings"]:
                if key in data and isinstance(data[key], list):
                    sanitized = []
                    for item in data[key]:
                        if isinstance(item, dict):
                            sanitized.append(json.dumps(item, ensure_ascii=False))
                        elif item is None:
                            continue
                        else:
                            sanitized.append(str(item).strip())
                    data[key] = [s for s in sanitized if s]

            # 필수 키 검증
            for required_key in ["modality", "clinical_status", "positive_findings", "negative_findings"]:
                if required_key not in data:
                    data[required_key] = [] if "findings" in required_key else "Other"

            return data

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ("ThrottlingException", "TooManyRequestsException"):
                wait = min(2 ** attempt + 0.5, 30)
                time.sleep(wait)
                continue
            elif error_code == "ModelTimeoutException":
                time.sleep(5)
                continue
            else:
                raise
        except json.JSONDecodeError:
            # JSON 파싱 실패 시 재시도
            if attempt < MAX_RETRIES - 1:
                time.sleep(2)
                continue
            return None
        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            return None

    return None


def build_prompt(prior_text, tech, findings, impression):
    """프롬프트 조립"""
    return SYSTEM_PROMPT.format(
        prior_text=prior_text or "None (Initial Exam)",
        current_tech=tech or "(Not provided)",
        current_findings=findings or "(Not provided)",
        current_impression=impression or "(Not provided)",
    )


def build_prior_context(analysis):
    """다음 리포트를 위한 prior context 문자열 생성"""
    if not analysis or "error" in analysis:
        return "None (Prior extraction failed)"

    status = analysis.get("clinical_status", "unknown")
    pos = analysis.get("positive_findings", [])
    neg = analysis.get("negative_findings", [])

    pos_str = ", ".join(pos) if pos else "None"
    neg_str = ", ".join(neg) if neg else "None"

    return (
        f"Prior status was '{status}' with positive findings: {pos_str} "
        f"and negative findings: {neg_str}."
    )


def log_error(note_id, error_msg):
    """에러 로그 기록"""
    with error_lock:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{note_id}\t{error_msg}\n")


def process_patient(subject_id, reports, processed_ids, existing_results):
    """한 환자의 리포트를 시계열 순서로 직렬 처리"""
    prior_context = "None (Initial Exam)"

    for report in reports:
        note_id = report["note_id"]

        # 이미 처리된 건: prior context만 업데이트하고 스킵
        if note_id in processed_ids:
            with stats_lock:
                stats["skipped_done"] += 1
            if note_id in existing_results:
                prior_context = build_prior_context(existing_results[note_id])
            continue

        # findings + impression 모두 비어있으면 스킵
        findings = report.get("raw_findings", "").strip()
        impression = report.get("raw_impression", "").strip()
        exam_tech = report.get("raw_exam_tech", "").strip()

        if not findings and not impression:
            # 빈 결과 저장 (시계열 연속성 유지)
            empty_result = {
                "note_id": note_id,
                "subject_id": subject_id,
                "hadm_id": report.get("hadm_id", ""),
                "charttime": report.get("charttime", ""),
                "ai_analysis": {
                    "modality": "Other",
                    "clinical_status": "baseline" if prior_context == "None (Initial Exam)" else "stable",
                    "positive_findings": [],
                    "negative_findings": [],
                    "_flag": "empty_input"
                }
            }
            with file_lock:
                with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(empty_result, ensure_ascii=False) + "\n")
                with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
                    f.write(note_id + "\n")
            with stats_lock:
                stats["skipped_empty"] += 1
            # prior context는 변경하지 않음 (빈 리포트이므로)
            continue

        # Bedrock 호출
        prompt = build_prompt(prior_context, exam_tech, findings, impression)
        analysis = call_bedrock(prompt)

        if analysis is None:
            log_error(note_id, "Bedrock call failed after max retries")
            with stats_lock:
                stats["errors"] += 1
            continue

        # Temporal Mismatch 방어: 첫 검사인데 baseline이 아닌 경우 강제 교정
        if prior_context == "None (Initial Exam)" and analysis.get("clinical_status") not in ("baseline",):
            analysis["clinical_status"] = "baseline"
            analysis["_corrected"] = "temporal_forced_baseline"

        # 결과 저장
        result = {
            "note_id": note_id,
            "subject_id": subject_id,
            "hadm_id": report.get("hadm_id", ""),
            "charttime": report.get("charttime", ""),
            "ai_analysis": analysis
        }

        with file_lock:
            with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
            with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
                f.write(note_id + "\n")

        with stats_lock:
            stats["success"] += 1

        # 다음 리포트를 위한 prior context 업데이트
        prior_context = build_prior_context(analysis)


def main():
    os.makedirs("logs", exist_ok=True)

    # ── 1) 체크포인트 로드 ─────────────────────────────────
    print("[1/5] 체크포인트 로드 중...")
    processed_ids = set()
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            processed_ids = {line.strip() for line in f if line.strip()}
    print(f"  → 이미 처리된 note_id: {len(processed_ids):,}건")

    # ── 2) 기존 결과 로드 (Resume 시 prior context 복원용) ──
    print("[2/5] 기존 결과 로드 중...")
    existing_results = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    existing_results[data["note_id"]] = data.get("ai_analysis", {})
                except:
                    continue
    print(f"  → 기존 결과: {len(existing_results):,}건")

    # ── 3) 데이터 로드 & 환자별 그룹화 ────────────────────
    print("[3/5] step1 데이터 로드 및 환자별 그룹화 중...")
    patient_groups = defaultdict(list)
    total_records = 0
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            report = json.loads(line)
            patient_groups[report["subject_id"]].append(report)
            total_records += 1

    # ── 4) 환자별 시계열 정렬 ─────────────────────────────
    for sid in patient_groups:
        patient_groups[sid].sort(key=lambda x: x.get("charttime", ""))

    num_patients = len(patient_groups)
    remaining = total_records - len(processed_ids)
    print(f"  → 총 레코드: {total_records:,}건 / 환자: {num_patients:,}명")
    print(f"  → 남은 처리 대상: ~{max(remaining, 0):,}건")

    # ── 5) 환자 단위 병렬 처리 ────────────────────────────
    print(f"[4/5] Bedrock 처리 시작 (workers={MAX_WORKERS})...")
    subject_ids = sorted(patient_groups.keys(), key=lambda sid: len(patient_groups[sid]), reverse=True)

    # 테스트 모드: 환자 수 제한
    if TEST_LIMIT > 0:
        subject_ids = subject_ids[:TEST_LIMIT]
        test_record_count = sum(len(patient_groups[sid]) for sid in subject_ids)
        print(f"  ⚠ 테스트 모드: 환자 {len(subject_ids)}명 / 레코드 {test_record_count}건만 처리")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for sid in subject_ids:
            futures.append(
                executor.submit(
                    process_patient, sid, patient_groups[sid],
                    processed_ids, existing_results
                )
            )

        for _ in tqdm(
            [f.result() for f in futures] if False else futures,
            total=len(futures),
            desc="  환자 처리"
        ):
            try:
                _.result()
            except Exception as e:
                with stats_lock:
                    stats["errors"] += 1

    # ── 6) 결과 요약 ─────────────────────────────────────
    print(f"\n[5/5] 완료!")
    print(f"  → 신규 처리: {stats['success']:,}건")
    print(f"  → 빈 입력 스킵: {stats['skipped_empty']:,}건")
    print(f"  → 이미 완료 스킵: {stats['skipped_done']:,}건")
    print(f"  → 에러: {stats['errors']:,}건")
    print(f"  → 출력 파일: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
