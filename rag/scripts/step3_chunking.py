#!/usr/bin/env python3
"""
3단계: 보강 데이터 병합 및 초정밀 청킹 (Supplement Merge & High-Precision Chunking)
- step2_supplemented.jsonl을 읽어 qc_supplement 병합
- Two-Pass Normalcy Filter로 과잉 보강 제거
- Fuzzy Dedup으로 positive/negative 중복 제거
- 환자별 시계열 정렬 후 embedding_text + metadata 조립
- 출력: step3_final_chunks.jsonl
"""

import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher

try:
    from tqdm import tqdm
except ImportError:
    print("tqdm 미설치. pip install tqdm 후 재실행하세요.")
    sys.exit(1)

# ── 경로 설정 ───────────────────────────────────────────────
INPUT_FILE  = "data/step2_supplemented.jsonl"
OUTPUT_FILE = "data/step3_final_chunks.jsonl"


# ── 유틸리티 함수 ───────────────────────────────────────────
def is_normalcy(text):
    """positive에서 negative로 이동해야 하는 정상 소견인지 판별 (2단계 필터링)"""
    t = text.lower()
    # 'normal' 매칭 (단, 'abnormal', 'reversal of normal' 제외)
    if re.search(r'\bnormal\b', t):
        if not any(ex in t for ex in ['abnormal', 'reversal of normal']):
            return True
    # 'clear' 매칭 (단, 'unclear', 'cleared', 'clear cell' 제외)
    if re.search(r'\bclear\b', t):
        if not any(ex in t for ex in ['unclear', 'cleared', 'clear cell']):
            return True
    # 일반 키워드 매칭
    if re.search(r'\b(unremarkable|within normal limits|no evidence|unaltered)\b', t):
        return True
    return False


def fuzzy_match(a, b):
    """A가 B에 포함되거나 85% 이상 유사하면 True"""
    if a in b:
        return True
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.85


# ── 1) 데이터 로드 ─────────────────────────────────────────
print("[1/6] 데이터 로드 중...")
records = []
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
print(f"  → 총 레코드: {len(records):,}건")

# ── 2) qc_supplement 병합 + 클렌징 ─────────────────────────
print("[2/6] qc_supplement 병합 및 스마트 클렌징 중...")

stats = {
    "negation_corrections_exact": 0,
    "negation_corrections_substring": 0,
    "negation_corrections_unmatched": 0,
    "normalcy_moved": 0,
    "fuzzy_dedup_removed": 0,
    "empty_input_skipped": 0,
}

for rec in tqdm(records, desc="  병합+클렌징"):
    ai = rec.get("ai_analysis", {})
    supplement = rec.get("qc_supplement")

    pos = list(ai.get("positive_findings", []))
    neg = list(ai.get("negative_findings", []))

    # ── 0단계: qc_supplement 병합 ──────────────────────────
    if supplement:
        # added_positive 추가 (중복 방지)
        for item in supplement.get("added_positive", []):
            if item and item not in pos:
                pos.append(item)

        # added_negative 추가 (중복 방지)
        for item in supplement.get("added_negative", []):
            if item and item not in neg:
                neg.append(item)

        # negation_corrections: positive에서 제거 → negative로 이동
        for corr in supplement.get("negation_corrections", []):
            if isinstance(corr, dict):
                corr_text = corr.get("original", "")
            else:
                corr_text = str(corr).strip()

            if not corr_text:
                continue

            # 완전 일치 시도
            if corr_text in pos:
                pos.remove(corr_text)
                if corr_text not in neg:
                    neg.append(corr_text)
                stats["negation_corrections_exact"] += 1
            else:
                # 부분 문자열 매칭: pos 항목이 corr_text에 포함되거나 그 반대
                matched = False
                for p in pos[:]:
                    if p in corr_text or corr_text in p:
                        pos.remove(p)
                        if p not in neg:
                            neg.append(p)
                        stats["negation_corrections_substring"] += 1
                        matched = True
                        break
                if not matched:
                    stats["negation_corrections_unmatched"] += 1

    # ── 1단계: Two-Pass Normalcy Filter ────────────────────
    moved_to_neg = []
    remaining_pos = []
    for p in pos:
        if is_normalcy(p):
            moved_to_neg.append(p)
            stats["normalcy_moved"] += 1
        else:
            remaining_pos.append(p)
    pos = remaining_pos
    for item in moved_to_neg:
        if item not in neg:
            neg.append(item)

    # ── 2단계: Fuzzy Dedup ─────────────────────────────────
    dedup_pos = []
    for a in pos:
        is_dup = False
        for b in neg:
            if fuzzy_match(a, b):
                is_dup = True
                stats["fuzzy_dedup_removed"] += 1
                break
        if not is_dup:
            dedup_pos.append(a)
    pos = dedup_pos

    # 클렌징 결과를 레코드에 저장 (원본 ai_analysis는 보존, 별도 필드)
    rec["_cleaned_positive"] = pos
    rec["_cleaned_negative"] = neg

# ── 3) 환자별 시계열 그룹화 & 정렬 ────────────────────────
print("[3/6] 환자별 시계열 그룹화 및 정렬 중...")
patient_groups = defaultdict(list)
for rec in records:
    patient_groups[rec["subject_id"]].append(rec)

for sid in patient_groups:
    patient_groups[sid].sort(key=lambda x: x.get("charttime", ""))

print(f"  → 환자: {len(patient_groups):,}명")

# ── 4) 이벤트 청킹 ────────────────────────────────────────
print("[4/6] 이벤트 청킹 중...")
chunks = []

for sid, recs in tqdm(patient_groups.items(), desc="  청킹", total=len(patient_groups)):
    total_exams = len(recs)

    for seq_idx, rec in enumerate(recs, start=1):
        ai = rec.get("ai_analysis", {})

        # 빈 입력 스킵
        if ai.get("_flag") == "empty_input":
            stats["empty_input_skipped"] += 1
            continue

        pos = rec["_cleaned_positive"]
        neg = rec["_cleaned_negative"]
        modality = ai.get("modality", "Other")
        clinical_status = ai.get("clinical_status", "baseline")

        # embedding_text 조립
        pos_str = ", ".join(pos) if pos else "None"
        neg_str = ", ".join(neg) if neg else "None"

        embedding_text = (
            f"Exam Type: {modality}. "
            f"Clinical Status: {clinical_status}. "
            f"Positive Findings: {pos_str}. "
            f"Explicitly Ruled Out: {neg_str}."
        )

        # metadata 구성
        metadata = {
            "note_id": rec.get("note_id", ""),
            "subject_id": sid,
            "hadm_id": rec.get("hadm_id", ""),
            "charttime": rec.get("charttime", ""),
            "modality": modality,
            "clinical_status": clinical_status,
            "event_sequence": seq_idx,
            "total_exams": total_exams,
        }

        chunks.append({
            "embedding_text": embedding_text,
            "metadata": metadata,
        })

print(f"  → 생성된 청크: {len(chunks):,}건")

# ── 5) 출력 ────────────────────────────────────────────────
print(f"[5/6] 저장 중: {OUTPUT_FILE}")
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    for chunk in chunks:
        f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

# ── 6) 통계 출력 ──────────────────────────────────────────
modality_counts = defaultdict(int)
status_counts = defaultdict(int)
for c in chunks:
    modality_counts[c["metadata"]["modality"]] += 1
    status_counts[c["metadata"]["clinical_status"]] += 1

print(f"\n{'='*60}")
print(f"  3단계 보강 병합 & 초정밀 청킹 완료")
print(f"{'='*60}")
print(f"  총 청크:          {len(chunks):,}건")
print(f"  환자 수:          {len(patient_groups):,}명")
print(f"  빈 입력 스킵:     {stats['empty_input_skipped']:,}건")
print(f"  ─────────────────────────────────────")
print(f"  [클렌징 통계]")
print(f"  negation_corrections 정확 매칭:   {stats['negation_corrections_exact']:,}건")
print(f"  negation_corrections 부분 매칭:   {stats['negation_corrections_substring']:,}건")
print(f"  negation_corrections 매칭 불가:   {stats['negation_corrections_unmatched']:,}건")
print(f"  normalcy filter 이동:             {stats['normalcy_moved']:,}건")
print(f"  fuzzy dedup 제거:                 {stats['fuzzy_dedup_removed']:,}건")
print(f"  ─────────────────────────────────────")
print(f"  모달리티 분포:")
for m, c in sorted(modality_counts.items(), key=lambda x: -x[1]):
    print(f"    {m}: {c:,}건 ({c/len(chunks)*100:.1f}%)")
print(f"  ─────────────────────────────────────")
print(f"  Clinical Status 분포:")
for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
    print(f"    {s}: {c:,}건 ({c/len(chunks)*100:.1f}%)")
print(f"{'='*60}")
print(f"  → {OUTPUT_FILE}")
