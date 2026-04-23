#!/usr/bin/env python3
"""
골든 데이터셋 200명 기준 ECG /predict 테스트

- sampled_200_goldendataset.jsonl 의 subject_id와 manifest.csv 매칭
- 환자당 첫 ECG 1건 사용 (study_id 오름차순)
- 신호 파일 경로: 컨테이너 내 /data/{npy_file}
- 결과 저장: test_results.jsonl
"""

import json
import csv
import time
import requests
import argparse
from pathlib import Path
from collections import defaultdict

parser = argparse.ArgumentParser()
parser.add_argument('--url',      default='http://localhost:8000')
parser.add_argument('--golden',   default='sampled_200_goldendataset.jsonl')
parser.add_argument('--manifest', default='processed/manifest.csv')
parser.add_argument('--output',   default='test_results.jsonl')
parser.add_argument('--limit',    type=int, default=None, help='테스트할 최대 환자 수')
args = parser.parse_args()


# ── 1. 골든셋 로드 ────────────────────────────────────────────
golden = {}
for line in open(args.golden):
    rec = json.loads(line)
    sid = rec['join_keys']['subject_id']
    golden[sid] = rec

print(f"골든셋 환자 수: {len(golden)}")


# ── 2. manifest에서 subject_id별 첫 ECG 뽑기 ─────────────────
# 환자당 여러 ECG가 있을 수 있으므로 study_id 오름차순 첫 번째만
by_subject: dict[str, list] = defaultdict(list)
with open(args.manifest) as f:
    for row in csv.DictReader(f):
        if row['subject_id'] in golden:
            by_subject[row['subject_id']].append(row)

test_cases = []
for sid, rows in by_subject.items():
    rows.sort(key=lambda r: int(r['study_id']))
    test_cases.append(rows[0])   # 첫 번째 ECG

test_cases.sort(key=lambda r: r['subject_id'])
if args.limit:
    test_cases = test_cases[:args.limit]

print(f"매칭 환자: {len(test_cases)} / {len(golden)}")


# ── 3. /health 확인 ───────────────────────────────────────────
try:
    r = requests.get(f"{args.url}/health", timeout=5)
    assert r.status_code == 200
    print(f"서버 연결 OK: {args.url}")
except Exception as e:
    print(f"❌ 서버 연결 실패: {e}")
    exit(1)


# ── 4. 요청 실행 ──────────────────────────────────────────────
results = []
ok, err = 0, 0

for i, row in enumerate(test_cases, 1):
    age_norm   = float(row['age_norm'])
    gender_enc = float(row['gender_enc'])
    age        = round(age_norm * 83 + 18, 1)
    sex        = 'M' if gender_enc == 1.0 else 'F' if gender_enc == 0.0 else 'Unknown'

    # S3 WFDB record_path 조합
    subject_id = row['subject_id']
    study_id   = row['study_id']
    p_prefix   = 'p' + subject_id[:4]
    record_path = (
        f"s3://say2-6team/mimic/ecg/waveforms/files"
        f"/{p_prefix}/p{subject_id}/s{study_id}/{study_id}"
    )

    # 골든셋에서 임상 정보 가져오기
    g = golden[row['subject_id']]
    symptoms = g['ml_features'].get('1_symptoms_and_history', '')
    _dx_raw  = g['ml_features'].get('3_diagnosis', {})
    dx       = _dx_raw.get('primary', '') if isinstance(_dx_raw, dict) else str(_dx_raw or '')

    payload = {
        "patient_id": study_id,
        "patient_info": {
            "age":              age,
            "sex":              sex,
            "chief_complaint":  symptoms[:200] if symptoms else "",
            "history":          [],
        },
        "data": {"record_path": record_path, "leads": 12},
        "context": {"subject_id": subject_id, "golden_dx": dx},
    }

    t0 = time.perf_counter()
    try:
        resp = requests.post(f"{args.url}/predict", json=payload, timeout=30)
        latency = round((time.perf_counter() - t0) * 1000, 1)
        body    = resp.json()

        result = {
            "subject_id":  row['subject_id'],
            "study_id":    row['study_id'],
            "age":         age,
            "sex":         sex,
            "golden_dx":   dx,
            "status":      body.get("status"),
            "risk_level":  body.get("risk_level"),
            "num_detected":body.get("metadata", {}).get("num_detected", 0),
            "findings":    [f["name"] for f in body.get("findings", [])],
            "summary":     body.get("summary"),
            "latency_ms":  latency,
            "http_code":   resp.status_code,
        }
        results.append(result)

        if resp.status_code == 200:
            ok += 1
            detected_str = ", ".join(result["findings"]) or "없음"
            print(f"[{i:3d}/{len(test_cases)}] {row['study_id']} | {age}세 {sex} | "
                  f"risk={result['risk_level']} | {detected_str} ({latency}ms)")
        else:
            err += 1
            print(f"[{i:3d}/{len(test_cases)}] ❌ {row['study_id']} HTTP {resp.status_code}: "
                  f"{body.get('detail')}")

    except Exception as e:
        err += 1
        latency = round((time.perf_counter() - t0) * 1000, 1)
        print(f"[{i:3d}/{len(test_cases)}] ❌ {row['study_id']} 오류: {e}")
        results.append({"subject_id": row['subject_id'], "study_id": row['study_id'],
                         "status": "error", "error": str(e), "latency_ms": latency})


# ── 5. 결과 저장 & 요약 ──────────────────────────────────────
with open(args.output, 'w') as f:
    for r in results:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

print(f"\n{'='*55}")
print(f"총 {len(test_cases)}건 | 성공 {ok} | 실패 {err}")
if results:
    lats = [r['latency_ms'] for r in results if 'latency_ms' in r]
    print(f"평균 지연: {sum(lats)/len(lats):.1f}ms | 최대: {max(lats):.1f}ms")

    risk_count = {}
    for r in results:
        lv = r.get('risk_level', 'unknown')
        risk_count[lv] = risk_count.get(lv, 0) + 1
    print("위험도 분포:", " | ".join(f"{k}={v}" for k, v in sorted(risk_count.items())))

print(f"결과 저장: {args.output}")
