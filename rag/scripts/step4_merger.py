#!/usr/bin/env python3
"""
4단계: 이기종 의료 데이터셋 최종 병합 (Heterogeneous Dataset Merging)
- step3_final_chunks.jsonl (radiology) + final_10000_v4.jsonl (discharge)
- subject_id 기반 Temporal Join (radiology_charttime <= discharge_charttime)
- 출력: step4_integrated_knowledge.jsonl
"""

import json
import sys
from collections import defaultdict
from datetime import datetime

try:
    from tqdm import tqdm
except ImportError:
    print("tqdm 미설치. pip install tqdm 후 재실행하세요.")
    sys.exit(1)

# ── 경로 설정 ───────────────────────────────────────────────
RAD_CHUNKS_FILE  = "data/step3_final_chunks.jsonl"
DISCHARGE_FILE   = "data/final_10000_v4.jsonl"
OUTPUT_FILE      = "data/step4_integrated_knowledge.jsonl"

# ── 1) 영상의학 데이터 로드 & subject_id 기반 해시맵 ───────
print("[1/4] 영상의학 청크 로드 중...")
rad_by_subject = defaultdict(list)
seen_note_ids = set()
rad_total = 0

with open(RAD_CHUNKS_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        chunk = json.loads(line)
        meta = chunk.get("metadata", {})
        note_id = meta.get("note_id", "")

        # 중복 제거 (note_id 기준)
        if note_id in seen_note_ids:
            continue
        seen_note_ids.add(note_id)

        sid = meta.get("subject_id", "")
        if sid:
            rad_by_subject[sid].append(chunk)
            rad_total += 1

print(f"  → 영상의학 청크: {rad_total:,}건 / 환자: {len(rad_by_subject):,}명")

# ── 2) 시계열 정렬 (안전한 datetime 파싱) ──────────────────
print("[2/4] 환자별 시계열 정렬 중...")


def safe_parse_datetime(dt_str):
    """datetime 파싱 실패 시 원본 문자열로 폴백"""
    try:
        return datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return dt_str


for sid in rad_by_subject:
    rad_by_subject[sid].sort(
        key=lambda x: safe_parse_datetime(x.get("metadata", {}).get("charttime", ""))
    )

# ── 3) 퇴원 요약지 스트리밍 병합 ──────────────────────────
print("[3/4] 퇴원 요약지와 병합 중...")

# 퇴원 요약지 총 건수 카운트
dc_total = sum(1 for _ in open(DISCHARGE_FILE, encoding="utf-8"))

matched_count = 0
empty_count = 0
written = 0

with open(DISCHARGE_FILE, "r", encoding="utf-8") as fin, \
     open(OUTPUT_FILE, "w", encoding="utf-8") as fout:

    for line in tqdm(fin, total=dc_total, desc="  병합"):
        line = line.strip()
        if not line:
            continue

        dc_rec = json.loads(line)
        jk = dc_rec.get("join_keys", {})
        sid = jk.get("subject_id", "")
        dc_charttime_str = jk.get("charttime", "")
        dc_time = safe_parse_datetime(dc_charttime_str)

        # 해당 환자의 영상의학 리스트 가져오기
        rad_list = rad_by_subject.get(sid, [])

        # Time Window 필터링: radiology_charttime <= discharge_charttime
        filtered = []
        for chunk in rad_list:
            rad_time_str = chunk.get("metadata", {}).get("charttime", "")
            rad_time = safe_parse_datetime(rad_time_str)

            # 둘 다 datetime 객체인 경우만 비교
            if isinstance(dc_time, datetime) and isinstance(rad_time, datetime):
                if rad_time <= dc_time:
                    filtered.append(chunk)
            else:
                # 파싱 실패 시 문자열 비교 (ISO 포맷이면 정상 작동)
                if rad_time_str <= dc_charttime_str:
                    filtered.append(chunk)

        # radiology_history 삽입
        dc_rec["radiology_history"] = filtered

        if filtered:
            matched_count += 1
        else:
            empty_count += 1

        fout.write(json.dumps(dc_rec, ensure_ascii=False) + "\n")
        written += 1

# ── 4) 통계 출력 ──────────────────────────────────────────
print(f"\n{'='*50}")
print(f"  4단계 최종 병합 완료")
print(f"{'='*50}")
print(f"  총 퇴원 요약지:          {written:,}건")
print(f"  영상의학 1건+ 매칭:      {matched_count:,}건 ({matched_count/max(written,1)*100:.1f}%)")
print(f"  영상의학 0건 (빈 리스트): {empty_count:,}건 ({empty_count/max(written,1)*100:.1f}%)")
print(f"{'='*50}")
print(f"  → {OUTPUT_FILE}")
