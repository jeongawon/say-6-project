#!/usr/bin/env python3
"""
1단계: 구조적 섹셔닝 (Structural Sectioning)
- radiology.csv에서 타겟 환자만 필터링
- 딕셔너리 기반 정규식으로 EXAM_TECH / FINDINGS / IMPRESSION 섹션 분리
- 출력: step1_parsed_radiology.jsonl
"""

import csv
import json
import re
import sys
import os
from collections import OrderedDict

try:
    from tqdm import tqdm
except ImportError:
    print("tqdm 미설치. pip install tqdm 후 재실행하세요.")
    sys.exit(1)

# ── 경로 설정 ──────────────────────────────────────────────
TARGET_CSV    = "data/targeted_10000_hadm_ids_v2.csv"
DICT_JSON     = "data/radiology_sections_dictionary_v2.json"
RAD_CSV       = "ignore_large/radiology.csv"
OUTPUT_JSONL  = "data/step1_parsed_radiology.jsonl"

# ── 1) 타겟 hadm_id 로드 ─────────────────────────────────
print("[1/4] 타겟 hadm_id 로드 중...")
target_hadm_ids = set()
with open(TARGET_CSV, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        target_hadm_ids.add(row["hadm_id"].strip())
print(f"  → 타겟 hadm_id {len(target_hadm_ids):,}건 로드 완료")

# ── 2) 딕셔너리 로드 & 정규식 빌드 ────────────────────────
print("[2/4] 섹션 딕셔너리 로드 및 정규식 빌드 중...")
with open(DICT_JSON, encoding="utf-8") as f:
    dictionary = json.load(f)["radiology_sections"]

# 카테고리별 유의어 → 카테고리 매핑 (콜론 제거한 키워드)
keyword_to_category = {}
all_keywords = []

for category, info in dictionary.items():
    for syn in info["synonyms"]:
        # 딕셔너리의 유의어에서 끝 콜론 제거 (정규식에서 콜론을 별도 매칭)
        clean = syn.rstrip(":").strip()
        if clean:
            keyword_to_category[clean.upper()] = category
            all_keywords.append(clean)

# 길이 내림차순 정렬 (longest match first)
all_keywords.sort(key=len, reverse=True)

# 정규식 특수문자 이스케이프
escaped = [re.escape(kw) for kw in all_keywords]

# 패턴: 줄 시작 + 선택적 공백 + (키워드) + 선택적 공백 + 콜론
# 캡처 그룹으로 키워드를 잡아서 카테고리 라우팅에 사용
pattern_str = r"^\s*(" + "|".join(escaped) + r")\s*:"
section_regex = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)

print(f"  → 유의어 {len(all_keywords)}개로 정규식 빌드 완료")

# ── 3) 라우팅 카테고리 정의 ────────────────────────────────
# FINDINGS 또는 ORGAN_SPECIFIC_FINDINGS → raw_findings
# IMPRESSION → raw_impression
# EXAMINATION_TECHNIQUE → raw_exam_tech
# 나머지 (COMPARISON, INDICATION_HISTORY, ADMINISTRATIVE) → 무시

FINDINGS_CATS = {"FINDINGS", "ORGAN_SPECIFIC_FINDINGS"}
IMPRESSION_CATS = {"IMPRESSION"}
EXAM_TECH_CATS = {"EXAMINATION_TECHNIQUE"}


def parse_report(text):
    """리포트 텍스트를 섹션별로 분리하여 3개 필드로 반환"""
    raw_exam_tech = []
    raw_findings = []
    raw_impression = []

    # 정규식으로 분할: split은 캡처 그룹 포함 시 [텍스트, 매칭키워드, 텍스트, ...] 반환
    parts = section_regex.split(text)

    # parts[0]은 첫 번째 섹션 헤더 이전 텍스트 (보통 빈 문자열 또는 헤더 없는 서두)
    # 이후 (매칭키워드, 해당섹션텍스트) 쌍으로 반복
    i = 1  # 첫 번째 캡처 그룹부터
    while i < len(parts):
        matched_keyword = parts[i].strip().upper()
        section_text = parts[i + 1] if (i + 1) < len(parts) else ""
        section_text = section_text.strip()

        # 카테고리 라우팅
        category = keyword_to_category.get(matched_keyword)
        if category in EXAM_TECH_CATS:
            raw_exam_tech.append(section_text)
        elif category in FINDINGS_CATS:
            raw_findings.append(section_text)
        elif category in IMPRESSION_CATS:
            raw_impression.append(section_text)
        # else: 무시 (COMPARISON, INDICATION_HISTORY, ADMINISTRATIVE)

        i += 2

    return (
        " ".join(raw_exam_tech).strip(),
        " ".join(raw_findings).strip(),
        " ".join(raw_impression).strip(),
    )


# ── 4) CSV 스트리밍 처리 ───────────────────────────────────
print("[3/4] radiology.csv 스트리밍 처리 중...")

# 전체 행 수 카운트 (tqdm용)
total_lines = 0
with open(RAD_CSV, encoding="utf-8") as f:
    for _ in f:
        total_lines += 1
total_lines -= 1  # 헤더 제외
print(f"  → 전체 radiology 레코드: {total_lines:,}건")

processed = 0
skipped = 0
errors = 0

csv.field_size_limit(sys.maxsize)

with open(RAD_CSV, encoding="utf-8") as fin, \
     open(OUTPUT_JSONL, "w", encoding="utf-8") as fout:

    reader = csv.DictReader(fin)

    for row in tqdm(reader, total=total_lines, desc="  섹셔닝"):
        try:
            hadm_id = row["hadm_id"].strip()

            # 타겟 필터링: hadm_id 매칭
            if hadm_id not in target_hadm_ids:
                skipped += 1
                continue

            text = row.get("text", "")
            if not text or not text.strip():
                skipped += 1
                continue

            exam_tech, findings, impression = parse_report(text)

            record = OrderedDict([
                ("note_id",       row["note_id"].strip()),
                ("subject_id",    row["subject_id"].strip()),
                ("hadm_id",       hadm_id),
                ("charttime",     row["charttime"].strip()),
                ("raw_exam_tech", exam_tech),
                ("raw_findings",  findings),
                ("raw_impression", impression),
            ])

            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            processed += 1

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"\n  [에러] {e} | row keys: {list(row.keys())[:5]}")

# ── 5) 결과 요약 ──────────────────────────────────────────
print(f"\n[4/4] 완료!")
print(f"  → 처리 완료: {processed:,}건")
print(f"  → 스킵 (타겟 외 / 빈 텍스트): {skipped:,}건")
print(f"  → 에러: {errors:,}건")
print(f"  → 출력 파일: {OUTPUT_JSONL}")
