"""
blood-svc analyzer — 혈액검사 결과 분석 모듈.

참조 범위(reference_ranges.py)와 비교하여 각 검사항목의 정상/비정상/위급 여부를
판정하고, 복합 평가(심부전, 심근손상, 신기능, 빈혈, 감염/염증)를 수행합니다.

분석 패널:
  - CBC (일반혈액검사): WBC, RBC, Hemoglobin, Hematocrit, Platelets, MCV, MCH, MCHC
  - BMP (기초대사패널): Na, K, Cl, CO2, BUN, Creatinine, Glucose, Calcium
  - 심장 표지자: BNP, NT-proBNP, Troponin I/T, CK-MB
  - 간기능: AST, ALT, ALP, Bilirubin, Albumin
  - 응고: D-dimer, PT/INR
  - 염증: CRP, Procalcitonin, ESR

입력 데이터 형식 (req.data):
  패널별 중첩 구조와 플랫 구조 모두 지원합니다.
  {
    "cbc": {"wbc": 12.5, "rbc": 4.2, "hemoglobin": 11.0, ...},
    "bmp": {"sodium": 138, "potassium": 5.8, "creatinine": 1.8, ...},
    "cardiac": {"bnp": 1200, "troponin_i": 0.02, ...},
    "liver": {"ast": 45, "alt": 62, ...},
    "coag": {"d_dimer": 1.2, ...},
    "inflammatory": {"crp": 25.0, ...}
  }

각 패널 내 키 이름은 reference_ranges.py의 RANGES 딕셔너리 키와 일치해야 합니다.
"""

from __future__ import annotations

import logging
from typing import Any

import sys
sys.path.insert(0, "/app/shared")
from schemas import Finding, PatientInfo

from reference_ranges import (
    RANGES,              # 전체 검사항목 정상범위 테이블
    get_range,           # 성별/나이별 정상범위 조회
    get_critical_range,  # 위급값(panic value) 조회
    get_unit,            # 단위 조회
    get_display_name,    # 표시용 이름 조회
    get_category,        # 패널 카테고리 조회 (cbc, bmp 등)
    get_tiers,           # 단계별 구분 조회 (BNP, Procalcitonin 등)
)

logger = logging.getLogger("blood-svc.analyzer")

# ── 심각도 레벨 상수 ────────────────────────────────────────────────
SEVERITY_CRITICAL = "critical"   # 위급 (즉시 조치 필요)
SEVERITY_HIGH = "high"           # 높음 (정상범위 상한 초과)
SEVERITY_LOW = "low"             # 낮음 (정상범위 하한 미달)
SEVERITY_NORMAL = "normal"       # 정상


# ── 분석 진입점 ──────────────────────────────────────────────────────
def analyze_blood(data: dict, patient_info: PatientInfo) -> list[Finding]:
    """
    모든 혈액검사 수치를 참조 범위와 비교하여 분석합니다.

    처리 흐름:
      1) 중첩 패널 구조를 플랫 딕셔너리로 변환
      2) 각 검사항목을 개별 판정 (_evaluate_test)
      3) 복합 평가: 심부전, 심근손상, 신기능, 빈혈, 감염/염증
      4) Finding 목록 반환
    """
    findings: list[Finding] = []
    age = patient_info.age          # 환자 나이
    sex = patient_info.sex.upper()  # 환자 성별 (M/F)

    # 중첩 패널을 플랫 딕셔너리로 변환: {"cbc": {"wbc": 12}} → {"wbc": 12}
    lab_values = _flatten_data(data)

    if not lab_values:
        logger.warning("No lab values provided in request data")
        return [Finding(
            name="no_lab_data",
            detected=True,
            confidence=1.0,
            detail="No laboratory values were provided for analysis.",
        )]

    # 개별 검사항목 판정: 각 수치를 정상범위/위급값과 비교
    for test_name, value in lab_values.items():
        if test_name not in RANGES:
            logger.debug("Unknown test '%s', skipping", test_name)
            continue

        if value is None:
            continue

        try:
            value = float(value)
        except (ValueError, TypeError):
            logger.warning("Non-numeric value for %s: %s", test_name, value)
            continue

        finding = _evaluate_test(test_name, value, sex, age)
        findings.append(finding)

    # 복합 평가: 여러 검사항목을 종합하여 임상적 의미 도출
    findings.extend(_cardiac_assessment(lab_values, age))   # 심부전 + 심근손상
    findings.extend(_renal_assessment(lab_values, sex, age)) # 신기능 장애
    findings.extend(_anemia_assessment(lab_values, sex))     # 빈혈
    findings.extend(_infection_assessment(lab_values))        # 감염/염증

    return findings


# ── 중첩 데이터 → 플랫 변환 ──────────────────────────────────────────
def _flatten_data(data: dict) -> dict[str, float]:
    """
    패널별 중첩 구조와 플랫 구조 모두 처리합니다.
    예: {"cbc": {"wbc": 12}} → {"wbc": 12}
    예: {"wbc": 12} → {"wbc": 12}
    """
    flat: dict[str, float] = {}
    for key, val in data.items():
        if isinstance(val, dict):
            # 패널(cbc, bmp 등) 내부의 개별 검사항목 추출
            for test_name, test_val in val.items():
                flat[test_name.lower()] = test_val
        else:
            flat[key.lower()] = val
    return flat


# ── 개별 검사항목 판정 ───────────────────────────────────────────────
def _evaluate_test(test_name: str, value: float, sex: str, age: int) -> Finding:
    """
    하나의 검사항목을 정상범위, 위급값과 비교하여 판정합니다.

    판정 우선순위:
      1) 위급값(critical) 범위 밖 → CRITICAL
      2) 정상범위 하한 미달 → LOW
      3) 정상범위 상한 초과 → HIGH
      4) 정상범위 이내 → NORMAL
    """
    low, high = get_range(test_name, sex, age)         # 성별/나이별 정상범위
    crit_low, crit_high = get_critical_range(test_name) # 위급값 (panic value)
    unit = get_unit(test_name)                          # 단위 (예: mg/dL)
    display = get_display_name(test_name)               # 표시용 이름

    # 상태 판정
    is_critical = False
    status = SEVERITY_NORMAL
    direction = ""

    if crit_low is not None and value < crit_low:
        is_critical = True                      # 위급 저하
        status = SEVERITY_CRITICAL
        direction = "critically low"
    elif crit_high is not None and value > crit_high:
        is_critical = True                      # 위급 상승
        status = SEVERITY_CRITICAL
        direction = "critically high"
    elif value < low:
        status = SEVERITY_LOW                   # 정상범위 하한 미달
        direction = "low"
    elif value > high:
        status = SEVERITY_HIGH                  # 정상범위 상한 초과
        direction = "high"

    is_abnormal = status != SEVERITY_NORMAL
    confidence = _calc_confidence(value, low, high, crit_low, crit_high)

    # 상세 설명 문자열 구성
    if is_abnormal:
        detail = (
            f"{display}: {value} {unit} ({direction}) "
            f"[ref: {low}-{high} {unit}]"
        )
        if is_critical:
            detail += " *** CRITICAL ***"       # 위급값 강조 표시
    else:
        detail = f"{display}: {value} {unit} (normal) [ref: {low}-{high} {unit}]"

    # 단계별 분류가 있는 검사항목 처리 (예: BNP, Procalcitonin)
    tiers = get_tiers(test_name)
    if tiers and is_abnormal:
        for tier_name, (t_low, t_high) in tiers.items():
            if t_low <= value < t_high:
                detail += f" | tier: {tier_name}"
                break

    # 이상 여부에 따라 finding 이름에 접미사 추가
    finding_name = f"{test_name}_abnormal" if is_abnormal else f"{test_name}_normal"

    return Finding(
        name=finding_name,
        detected=is_abnormal,
        confidence=round(confidence, 2),
        detail=detail,
    )


def _calc_confidence(
    value: float, low: float, high: float,
    crit_low: float | None, crit_high: float | None,
) -> float:
    """
    판정(정상/비정상)의 신뢰도를 계산합니다.
    경계값에서 멀수록 높은 신뢰도, 위급값이면 0.99 반환.
    """
    if low <= value <= high:
        # 정상 범위 내 — 범위 중앙에 가까울수록 높은 신뢰도
        range_width = high - low if high > low else 1.0
        mid = (low + high) / 2.0
        dist_from_edge = min(value - low, high - value)
        return min(0.80 + 0.15 * (dist_from_edge / (range_width / 2)), 0.98)

    # 비정상 — 경계에서 멀수록 높은 신뢰도
    if value < low:
        deviation = low - value
        ref_span = low if low > 0 else 1.0
        ratio = deviation / ref_span
    else:
        deviation = value - high
        ref_span = high if high > 0 else 1.0
        ratio = deviation / ref_span

    # 위급값 범위 밖이면 최고 신뢰도
    if crit_low is not None and value < crit_low:
        return 0.99
    if crit_high is not None and value > crit_high:
        return 0.99

    return min(0.75 + ratio * 0.3, 0.98)


# ══════════════════════════════════════════════════════════════════════
# 복합 평가 (Composite Assessments)
# ──────────────────────────────────────────────────────────────────────
# 여러 검사항목을 종합하여 임상적으로 의미있는 상태를 평가합니다.
# ══════════════════════════════════════════════════════════════════════

def _cardiac_assessment(labs: dict, age: int) -> list[Finding]:
    """
    심장 관련 복합 평가: 심부전 + 심근 손상 지표.
    - 심부전: BNP, NT-proBNP (나이별 기준)
    - 심근 손상: Troponin I/T, CK-MB
    """
    findings = []
    bnp = labs.get("bnp")               # B형 나트륨이뇨펩티드
    nt_probnp = labs.get("nt_probnp")    # NT-proBNP
    trop_i = labs.get("troponin_i")      # 트로포닌 I (심근 손상 표지자)
    trop_t = labs.get("troponin_t")      # 트로포닌 T (심근 손상 표지자)
    ck_mb = labs.get("ck_mb")            # CK-MB (심근 효소)

    # ── 심부전 평가 ──
    # BNP와 NT-proBNP를 종합하여 심부전 가능성을 점수화
    hf_score = 0.0
    hf_reasons = []

    if bnp is not None:
        if bnp > 400:
            hf_score += 0.5                                       # 강한 상승 (+0.5)
            hf_reasons.append(f"BNP {bnp} pg/mL (strongly elevated)")
        elif bnp > 100:
            hf_score += 0.3                                       # 경도 상승 (+0.3)
            hf_reasons.append(f"BNP {bnp} pg/mL (elevated)")

    if nt_probnp is not None:
        # NT-proBNP는 나이별로 기준이 다름
        if age < 50 and nt_probnp > 450:
            hf_score += 0.4
            hf_reasons.append(f"NT-proBNP {nt_probnp} pg/mL (elevated for age < 50)")
        elif 50 <= age <= 75 and nt_probnp > 900:
            hf_score += 0.4
            hf_reasons.append(f"NT-proBNP {nt_probnp} pg/mL (elevated for age 50-75)")
        elif age > 75 and nt_probnp > 1800:
            hf_score += 0.4
            hf_reasons.append(f"NT-proBNP {nt_probnp} pg/mL (elevated for age > 75)")

    if hf_score >= 0.3:  # 0.3점 이상이면 심부전 지표로 보고
        findings.append(Finding(
            name="heart_failure_indicator",
            detected=True,
            confidence=round(min(hf_score + 0.3, 0.98), 2),
            detail="; ".join(hf_reasons),
        ))

    # ── 심근 손상 평가 ──
    # Troponin과 CK-MB를 종합하여 심근 손상(심근경색 등) 가능성을 점수화
    mi_score = 0.0
    mi_reasons = []

    if trop_i is not None and trop_i > 0.04:    # Troponin I 상승 (> 0.04 ng/mL)
        mi_score += 0.5
        mi_reasons.append(f"Troponin I {trop_i} ng/mL (> 0.04)")
    if trop_t is not None and trop_t > 0.01:    # Troponin T 상승 (> 0.01 ng/mL)
        mi_score += 0.5
        mi_reasons.append(f"Troponin T {trop_t} ng/mL (> 0.01)")
    if ck_mb is not None and ck_mb > 5.0:       # CK-MB 상승 (> 5.0 ng/mL)
        mi_score += 0.3
        mi_reasons.append(f"CK-MB {ck_mb} ng/mL (> 5.0)")

    if mi_score >= 0.3:  # 0.3점 이상이면 심근 손상 지표로 보고
        findings.append(Finding(
            name="myocardial_injury_indicator",
            detected=True,
            confidence=round(min(mi_score + 0.2, 0.98), 2),
            detail="; ".join(mi_reasons),
        ))

    return findings


def _renal_assessment(labs: dict, sex: str, age: int) -> list[Finding]:
    """
    신기능 복합 평가.
    - Creatinine 상승 정도로 경증/중등도/중증 분류
    - BUN/Creatinine 비율로 신전성(pre-renal) 원인 시사 여부 판단
    """
    findings = []
    cr = labs.get("creatinine")   # 크레아티닌
    bun = labs.get("bun")         # 혈중요소질소

    if cr is None:
        return findings

    cr_low, cr_high = get_range("creatinine", sex, age)

    if cr > cr_high:
        # 크레아티닌 상승 정도에 따라 심각도 분류
        severity = "mild"       # 경증: 정상 상한 ~ 2.0
        if cr > 2.0:
            severity = "moderate"  # 중등도: 2.0 ~ 4.0
        if cr > 4.0:
            severity = "severe"    # 중증: 4.0 이상

        detail = f"Creatinine {cr} mg/dL ({severity} elevation)"
        if bun is not None:
            # BUN/Creatinine 비율 — 20 초과 시 신전성(탈수, 심부전 등) 원인 시사
            bun_cr_ratio = bun / cr if cr > 0 else 0
            detail += f", BUN/Cr ratio = {bun_cr_ratio:.1f}"
            if bun_cr_ratio > 20:
                detail += " (suggests pre-renal cause)"

        findings.append(Finding(
            name="renal_impairment",
            detected=True,
            confidence=round(min(0.75 + (cr - cr_high) * 0.1, 0.98), 2),
            detail=detail,
        ))

    return findings


def _anemia_assessment(labs: dict, sex: str) -> list[Finding]:
    """
    빈혈 복합 평가.
    - Hemoglobin으로 빈혈 유무 및 심각도(경증/중등도/중증) 판별
    - MCV로 빈혈 유형 분류: 소적혈구(< 80 fL), 정적혈구, 대적혈구(> 100 fL)
    """
    findings = []
    hgb = labs.get("hemoglobin")   # 혈색소
    mcv = labs.get("mcv")          # 평균적혈구용적

    if hgb is None:
        return findings

    hgb_low, _ = get_range("hemoglobin", sex)

    if hgb < hgb_low:
        # 헤모글로빈 기준 심각도 분류
        severity = "mild"         # 경증: 정상 하한 ~ 10.0 g/dL
        if hgb < 10.0:
            severity = "moderate"  # 중등도: 7.0 ~ 10.0 g/dL
        if hgb < 7.0:
            severity = "severe"    # 중증: 7.0 미만 (수혈 고려)

        # MCV 기반 빈혈 유형 분류
        anemia_type = "normocytic"  # 정적혈구성 빈혈
        if mcv is not None:
            if mcv < 80:
                # 소적혈구성: 철결핍성 빈혈, 지중해빈혈(thalassemia) 가능
                anemia_type = "microcytic (consider iron deficiency, thalassemia)"
            elif mcv > 100:
                # 대적혈구성: 비타민 B12/엽산 결핍 가능
                anemia_type = "macrocytic (consider B12/folate deficiency)"

        findings.append(Finding(
            name="anemia",
            detected=True,
            confidence=round(min(0.80 + (hgb_low - hgb) * 0.05, 0.98), 2),
            detail=f"Hemoglobin {hgb} g/dL ({severity}), {anemia_type}",
        ))

    return findings


def _infection_assessment(labs: dict) -> list[Finding]:
    """
    감염/염증 복합 평가.
    - WBC: 백혈구증가증(> 11.0) 또는 백혈구감소증(< 4.5)
    - CRP: C-반응 단백 (> 10 mg/L 상승, > 100 mg/L 현저한 상승)
    - Procalcitonin: 세균 감염 중증도 단계별 평가
    """
    findings = []
    wbc = labs.get("wbc")              # 백혈구 수
    crp = labs.get("crp")              # C-반응 단백
    pct = labs.get("procalcitonin")    # 프로칼시토닌

    infection_score = 0.0
    reasons = []

    # WBC (백혈구) 평가
    if wbc is not None:
        if wbc > 11.0:
            infection_score += 0.25                              # 백혈구증가증 (+0.25)
            reasons.append(f"WBC {wbc} x10^3/uL (leukocytosis)")
        elif wbc < 4.5:
            infection_score += 0.2                               # 백혈구감소증 (+0.2)
            reasons.append(f"WBC {wbc} x10^3/uL (leukopenia)")

    # CRP (C-반응 단백) 평가
    if crp is not None and crp > 10.0:
        infection_score += 0.25                                  # CRP 상승 (+0.25)
        reasons.append(f"CRP {crp} mg/L (elevated)")
        if crp > 100:
            infection_score += 0.15                              # 현저한 상승 (+0.15 추가)
            reasons[-1] = f"CRP {crp} mg/L (markedly elevated)"

    # Procalcitonin (프로칼시토닌) — 세균 감염 중증도 단계별 평가
    if pct is not None:
        if pct > 2.0:
            infection_score += 0.35                              # 중증 세균 감염 가능성 높음
            reasons.append(f"Procalcitonin {pct} ng/mL (severe bacterial infection likely)")
        elif pct > 0.5:
            infection_score += 0.25                              # 세균 감염 가능
            reasons.append(f"Procalcitonin {pct} ng/mL (bacterial infection possible)")
        elif pct > 0.25:
            infection_score += 0.15                              # 국소 감염 가능
            reasons.append(f"Procalcitonin {pct} ng/mL (local infection possible)")

    if infection_score >= 0.25:  # 0.25점 이상이면 감염/염증 지표로 보고
        findings.append(Finding(
            name="infection_inflammation_indicator",
            detected=True,
            confidence=round(min(infection_score + 0.4, 0.98), 2),
            detail="; ".join(reasons),
        ))

    return findings
