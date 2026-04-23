"""
골든셋 200건 → Lab-svc Rule Engine 테스트
sampled_200_goldendataset.jsonl에서 혈액검사 수치를 파싱하여
Lab-svc pipeline을 직접 호출하고 결과를 출력한다.

사용법:
  cd Lab-svc
  python test_golden.py
"""

import json
import re
import sys
from pathlib import Path

# Lab-svc 모듈 임포트
sys.path.insert(0, str(Path(__file__).parent))

from shared.schemas import LabValues, LabData, PatientInfo, PredictRequest
from pipeline import LabPipeline

# ── 골든셋 파일 경로 ──────────────────────────────────────────────
GOLDEN_PATH = Path(__file__).parent.parent / "sampled_200_goldendataset.jsonl"

# ── 혈액검사 수치 파싱 매핑 ───────────────────────────────────────
# 골든셋 텍스트 → LabValues 필드명
LAB_PARSE_MAP = {
    "wbc": ["wbc", "white blood cell", "leukocyte"],
    "hemoglobin": ["hemoglobin", "hgb", "hb"],
    "platelet": ["platelet", "plt"],
    "creatinine": ["creatinine", "cr"],
    "bun": ["bun", "blood urea nitrogen"],
    "sodium": ["sodium", "na"],
    "potassium": ["potassium", "k"],
    "glucose": ["glucose", "glu"],
    "ast": ["ast", "aspartate aminotransferase", "sgot"],
    "albumin": ["albumin", "alb"],
    "lactate": ["lactate", "lactic acid"],
    "calcium": ["calcium", "ca"],
}

# 수치 추출 정규식 패턴들
PATTERNS = [
    # "WBC (15.2)" or "WBC 15.2"
    re.compile(r"^(.+?)\s*[\(\[]?\s*([\d.]+)\s*[\)\]]?\s*(?:\[status:.*\])?$", re.IGNORECASE),
    # "WBC 15.2 [status:auto_added]"
    re.compile(r"^(.+?)\s+([\d.]+)\.?\s*(?:\[status:.*\])?$", re.IGNORECASE),
    # "Platelet count (2k on admission)" → 2000
    re.compile(r"^(.+?)\s*[\(\[]?\s*([\d.]+)k\b", re.IGNORECASE),
]


def parse_lab_value(test_str: str) -> tuple:
    """검사 문자열에서 (검사명, 수치)를 추출한다."""
    test_str = test_str.strip()

    for pattern in PATTERNS:
        m = pattern.match(test_str)
        if m:
            name = m.group(1).strip().lower()
            try:
                val = float(m.group(2))
                # "2k" 패턴 처리
                if "k" in test_str.lower() and val < 100:
                    val *= 1000
                return name, val
            except ValueError:
                continue

    return None, None


def match_to_lab_field(name: str) -> str:
    """파싱된 검사명을 LabValues 필드명으로 매핑한다."""
    if not name:
        return None
    name_lower = name.lower().strip()
    for field, aliases in LAB_PARSE_MAP.items():
        for alias in aliases:
            if alias in name_lower:
                return field
    return None


def extract_lab_values(performed_tests: list) -> dict:
    """2_performed_tests 리스트에서 혈액검사 수치를 추출한다."""
    lab_vals = {}
    for test_str in performed_tests:
        name, val = parse_lab_value(test_str)
        if name is None or val is None:
            continue
        field = match_to_lab_field(name)
        if field:
            lab_vals[field] = val
    return lab_vals


def extract_chief_complaint(symptoms: str) -> str:
    """1_symptoms_and_history에서 주호소를 추출한다."""
    if not symptoms or not isinstance(symptoms, str):
        return ""
    # 첫 문장 또는 "presented with" 이후 텍스트 추출
    m = re.search(r"present(?:ed|s|ing)\s+with\s+(.+?)(?:\.|,\s+and|\s+in\s+)", symptoms, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 첫 문장 사용
    first_sentence = symptoms.split(".")[0].strip()
    return first_sentence[:200]



def run_test():
    """골든셋 200건 전체 테스트 실행."""
    if not GOLDEN_PATH.exists():
        print(f"❌ 골든셋 파일 없음: {GOLDEN_PATH}")
        return

    pipeline = LabPipeline()
    print(f"✅ Lab Pipeline 초기화 완료 (ready={pipeline.ready})")
    print(f"📂 골든셋: {GOLDEN_PATH}")
    print("=" * 80)

    records = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"총 {len(records)}건 로드\n")

    # 통계
    total = len(records)
    has_lab = 0
    risk_counts = {"critical": 0, "urgent": 0, "watch": 0, "routine": 0}
    profile_counts = {}
    total_findings = 0
    total_actions = 0

    results = []

    for i, rec in enumerate(records):
        join = rec.get("join_keys", {})
        ml = rec.get("ml_features", {})

        patient_id = join.get("subject_id", f"unknown_{i}")
        hadm_id = join.get("hadm_id", "")
        symptoms = ml.get("1_symptoms_and_history", "")
        tests = ml.get("2_performed_tests", [])
        diagnosis = ml.get("3_diagnosis", {})

        # 혈액검사 수치 파싱
        lab_vals = extract_lab_values(tests)
        chief_complaint = extract_chief_complaint(symptoms)

        # PredictRequest 구성
        request = PredictRequest(
            patient_id=patient_id,
            patient_info=PatientInfo(chief_complaint=chief_complaint),
            data=LabData(lab_values=LabValues(**lab_vals)),
            context={},
        )

        # Pipeline 실행
        response = pipeline.predict(request)

        # 통계 수집
        if lab_vals:
            has_lab += 1
        risk_counts[response.risk_level] = risk_counts.get(response.risk_level, 0) + 1
        profile_counts[response.complaint_profile] = profile_counts.get(response.complaint_profile, 0) + 1
        total_findings += len(response.findings)
        total_actions += len(response.suggested_next_actions)

        # 결과 저장
        result_entry = {
            "index": i + 1,
            "patient_id": patient_id,
            "hadm_id": hadm_id,
            "chief_complaint": chief_complaint[:80],
            "parsed_lab_values": lab_vals,
            "num_lab_values": len(lab_vals),
            "complaint_profile": response.complaint_profile,
            "risk_level": response.risk_level,
            "num_findings": len(response.findings),
            "findings": [
                {"name": f.name, "category": f.category, "severity": f.severity, "detail": f.detail[:100]}
                for f in response.findings
            ],
            "suggested_next_actions": [
                {"target": a.target_modal, "reason": a.reason[:80], "priority": a.priority}
                for a in response.suggested_next_actions
            ],
            "summary": response.summary,
            "gold_diagnosis": diagnosis if isinstance(diagnosis, dict) else str(diagnosis)[:200],
            "latency_ms": response.metadata.get("latency_ms", 0),
        }
        results.append(result_entry)

        # 개별 결과 출력 (혈액검사 있는 건만 상세)
        if lab_vals:
            print(f"[{i+1:3d}] patient={patient_id} | profile={response.complaint_profile:15s} | "
                  f"risk={response.risk_level:8s} | findings={len(response.findings):2d} | "
                  f"labs={lab_vals}")
            if response.findings:
                for f in response.findings[:3]:
                    print(f"      → [{f.category:9s}] {f.name}: {f.detail[:70]}")
            if response.suggested_next_actions:
                for a in response.suggested_next_actions[:2]:
                    print(f"      ⚡ {a.target_modal} (p={a.priority}): {a.reason[:60]}")
            print()

    # ── 전체 통계 ─────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("📊 전체 통계")
    print("=" * 80)
    print(f"  총 건수: {total}")
    print(f"  혈액검사 수치 있는 건: {has_lab} ({has_lab/total*100:.1f}%)")
    print(f"  혈액검사 없는 건: {total - has_lab} ({(total-has_lab)/total*100:.1f}%)")
    print(f"\n  Risk Level 분포:")
    for level in ["critical", "urgent", "watch", "routine"]:
        cnt = risk_counts.get(level, 0)
        print(f"    {level:10s}: {cnt:3d} ({cnt/total*100:.1f}%)")
    print(f"\n  Complaint Profile 분포:")
    for profile, cnt in sorted(profile_counts.items(), key=lambda x: -x[1]):
        print(f"    {profile:15s}: {cnt:3d} ({cnt/total*100:.1f}%)")
    print(f"\n  총 Findings: {total_findings} (평균 {total_findings/total:.1f}건/환자)")
    print(f"  총 Suggested Actions: {total_actions}")

    # ── 결과 JSON 저장 ────────────────────────────────────────────
    output_path = Path(__file__).parent / "golden_test_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 전체 결과 저장: {output_path}")


if __name__ == "__main__":
    run_test()
