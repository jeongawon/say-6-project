#!/usr/bin/env python3
"""
2.5단계: 규칙 기반 QC (확실한 오류만 잡기)
- Temporal Mismatch: 첫 검사인데 baseline이 아닌 것
- Empty Findings: 원문 있는데 추출 결과 비어있는 것
- Pos/Neg Overlap: 동일 항목이 양쪽에 들어간 것
- High Compression: 원문 대비 추출이 극단적으로 짧은 것
- 출력: qc_flagged_rules.csv (확실한 오류) + qc_passed.jsonl (통과 건)
"""

import json
import csv
import re
import sys
from collections import defaultdict

try:
    from tqdm import tqdm
except ImportError:
    print("tqdm 미설치. pip install tqdm 후 재실행하세요.")
    sys.exit(1)

# ── 경로 설정 ───────────────────────────────────────────────
STEP1_FILE    = "data/step1_parsed_radiology.jsonl"
STEP2_FILE    = "data/step2_bedrock_extracted.jsonl"
FLAGGED_CSV   = "data/qc_flagged_rules.csv"
STATS_JSON    = "data/qc_rules_summary.json"

# ── 1) Step1 원문 로드 ─────────────────────────────────────
print("[1/4] Step1 원문 데이터 로드 중...")
raw_texts = {}
with open(STEP1_FILE, "r", encoding="utf-8") as f:
    for line in tqdm(f, desc="  Step1 로드"):
        data = json.loads(line)
        findings = data.get("raw_findings", "").strip()
        impression = data.get("raw_impression", "").strip()
        raw_texts[data["note_id"]] = {
            "findings": findings,
            "impression": impression,
            "combined": f"{findings} {impression}".strip(),
        }
print(f"  → {len(raw_texts):,}건 로드")

# ── 2) Step2 데이터 로드 & 환자별 그룹화 ───────────────────
print("[2/4] Step2 추출 데이터 로드 중...")
records = []
subject_groups = defaultdict(list)
with open(STEP2_FILE, "r", encoding="utf-8") as f:
    for line in tqdm(f, desc="  Step2 로드"):
        rec = json.loads(line)
        records.append(rec)
        subject_groups[rec["subject_id"]].append(rec)

# 환자별 시계열 정렬
for sid in subject_groups:
    subject_groups[sid].sort(key=lambda x: x.get("charttime", ""))

print(f"  → {len(records):,}건 로드 / {len(subject_groups):,}명")

# ── 3) QC 규칙 검사 ────────────────────────────────────────
print("[3/4] 규칙 기반 QC 검사 중...")

flagged = []
stats = {
    "total": 0,
    "passed": 0,
    "flagged": 0,
    "by_type": {
        "temporal_mismatch": 0,
        "empty_findings": 0,
        "pos_neg_overlap": 0,
        "high_compression": 0,
        "negation_leak": 0,
    }
}

for rec in tqdm(records, desc="  QC 검사"):
    stats["total"] += 1
    note_id = rec["note_id"]
    ai = rec.get("ai_analysis", {})
    raw = raw_texts.get(note_id, {})
    raw_combined = raw.get("combined", "")
    violations = []

    pos = ai.get("positive_findings", [])
    neg = ai.get("negative_findings", [])

    # ── Rule 1: Temporal Mismatch ──────────────────────────
    # 첫 검사인데 baseline이 아닌 경우
    patient_exams = subject_groups.get(rec["subject_id"], [])
    if patient_exams and patient_exams[0]["note_id"] == note_id:
        status = ai.get("clinical_status", "")
        if status not in ("baseline", "new"):
            violations.append(f"Temporal Mismatch: {status} on 1st exam")
            stats["by_type"]["temporal_mismatch"] += 1

    # ── Rule 2: Empty Findings ─────────────────────────────
    # 원문이 100자 이상인데 추출 결과가 완전히 비어있는 경우
    if len(raw_combined) >= 100 and not pos and not neg:
        # _flag가 empty_input인 경우는 제외 (원래 빈 입력)
        if ai.get("_flag") != "empty_input":
            violations.append(f"Empty Findings (raw: {len(raw_combined)} chars)")
            stats["by_type"]["empty_findings"] += 1

    # ── Rule 3: Pos/Neg Overlap ────────────────────────────
    # 동일 문자열이 positive와 negative 양쪽에 존재
    pos_set = {p.strip().lower() for p in pos}
    neg_set = {n.strip().lower() for n in neg}
    overlap = pos_set & neg_set
    if overlap:
        violations.append(f"Pos/Neg Overlap: {list(overlap)[:3]}")
        stats["by_type"]["pos_neg_overlap"] += 1

    # ── Rule 4: High Compression ───────────────────────────
    # 원문 500자 이상인데 추출 텍스트가 50자 미만
    extracted_text = " ".join(pos + neg)
    if len(raw_combined) >= 500 and len(extracted_text) < 50:
        violations.append(
            f"High Compression (raw:{len(raw_combined)}, ext:{len(extracted_text)})"
        )
        stats["by_type"]["high_compression"] += 1

    # ── Rule 5: Negation Leak (정밀 패턴) ──────────────────
    # positive_findings에 정상/부재 소견이 들어간 경우만 잡음
    # 복합 문장("mass without retraction")은 오탐이므로 제외
    for p in pos:
        p_lower = p.lower().strip()
        is_leak = False

        # 패턴 A: "normal X", "unremarkable X", "clear X"로 시작
        if re.match(r"^(normal|unremarkable|clear|no |negative|absent)\b", p_lower):
            is_leak = True
        # 패턴 B: "X is/are/appears normal/unremarkable/clear"
        elif re.search(
            r"\b(is|are|was|were|appears?|remains?)\s+(normal|unremarkable|clear|negative|absent)\b",
            p_lower,
        ):
            is_leak = True
        # 패턴 C: "within normal limits"
        elif "within normal limits" in p_lower:
            is_leak = True

        if is_leak:
            violations.append(f"Negation Leak: '{p[:80]}'")
            stats["by_type"]["negation_leak"] += 1
            break  # 환자당 1건만 flag

    # ── 결과 분류 ──────────────────────────────────────────
    if violations:
        stats["flagged"] += 1
        flagged.append({
            "note_id": note_id,
            "subject_id": rec.get("subject_id", ""),
            "violation_type": " | ".join(violations),
        })
    else:
        stats["passed"] += 1

# ── 4) 결과 저장 ───────────────────────────────────────────
print("[4/4] 결과 저장 중...")

# Flagged CSV
with open(FLAGGED_CSV, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["note_id", "subject_id", "violation_type"])
    writer.writeheader()
    writer.writerows(flagged)

# 통계 JSON
with open(STATS_JSON, "w", encoding="utf-8") as f:
    json.dump(stats, f, ensure_ascii=False, indent=2)

# ── 요약 출력 ──────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"  규칙 기반 QC 결과")
print(f"{'='*50}")
print(f"  총 검사: {stats['total']:,}건")
print(f"  통과:    {stats['passed']:,}건 ({stats['passed']/max(stats['total'],1)*100:.1f}%)")
print(f"  Flagged: {stats['flagged']:,}건 ({stats['flagged']/max(stats['total'],1)*100:.1f}%)")
print(f"  ─────────────────────────────")
for k, v in stats["by_type"].items():
    print(f"    {k}: {v:,}건")
print(f"{'='*50}")
print(f"  → {FLAGGED_CSV}")
print(f"  → {STATS_JSON}")
