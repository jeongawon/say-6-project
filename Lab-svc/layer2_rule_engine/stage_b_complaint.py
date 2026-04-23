"""Stage B: Complaint-Focused 해석 — Profile별 우선 확인 검사 규칙.

7개 Complaint Profile별로 정의된 우선 확인 검사 순서에 따라
수치를 임상 정상 범위와 비교하고, 이상 소견 Finding을 생성한다.

- Tier 2/3 미측정 항목에 대해 "미측정 경고" Finding 생성
- Tier 3 항목(troponin_t, bnp, amylase)은 임상적 중요성을 detail에 포함
- get_checked_features(profile): Stage B에서 검사한 Feature 집합 반환
"""

from __future__ import annotations

from typing import List, Set

from shared.schemas import Finding, ProcessedInput
from thresholds import NORMAL_RANGES

# ── Tier 분류 ─────────────────────────────────────────────────────
TIER2_FEATURES: set[str] = {"ast", "albumin", "lactate", "calcium"}
TIER3_FEATURES: set[str] = {"troponin_t", "bnp", "amylase"}

# Tier 3 항목의 임상적 중요성 설명
TIER3_CLINICAL_IMPORTANCE: dict[str, str] = {
    "troponin_t": "트로포닌 T는 심근 손상의 가장 민감한 바이오마커로, 급성 관상동맥 증후군(ACS) 진단에 필수적입니다.",
    "bnp": "BNP는 심부전 진단 및 중증도 평가의 핵심 바이오마커로, 호흡곤란의 심인성 원인 감별에 중요합니다.",
    "amylase": "아밀라아제는 급성 췌장염 진단의 핵심 검사로, 상복부 통증과 구토 동반 시 반드시 측정해야 합니다.",
}

# Indicator 이름 → Feature 이름 매핑 (역방향)
_FEATURE_TO_INDICATOR: dict[str, str] = {
    "ast": "has_ast",
    "albumin": "has_albumin",
    "lactate": "has_lactate",
    "calcium": "has_calcium",
    "troponin_t": "has_troponin_t",
    "bnp": "has_bnp",
    "amylase": "has_amylase",
}


# ── 7개 Profile별 우선 확인 검사 순서 ─────────────────────────────
# 각 항목: (feature_name, check_type)
#   check_type: "value" = 수치 비교, "indicator" = 측정 여부만 확인
PROFILE_PRIORITY_CHECKS: dict[str, list[tuple[str, str]]] = {
    "CARDIAC": [
        ("troponin_t", "indicator"),
        ("bnp", "indicator"),
        ("potassium", "value"),
        ("glucose", "value"),
        ("creatinine", "value"),
        ("hemoglobin", "value"),
    ],
    "SEPSIS": [
        ("lactate", "value"),
        ("wbc", "value"),
        ("platelet", "value"),
        ("creatinine", "value"),
        ("glucose", "value"),
    ],
    "GI": [
        ("amylase", "indicator"),
        ("ast", "value"),
        ("hemoglobin", "value"),
        ("bun", "value"),  # BUN/Cr ratio도 함께 검사
        ("calcium", "value"),
    ],
    "RENAL": [
        ("creatinine", "value"),
        ("bun", "value"),
        ("potassium", "value"),
        ("sodium", "value"),
        ("calcium", "value"),
    ],
    "RESPIRATORY": [
        ("wbc", "value"),
        ("lactate", "value"),
        ("hemoglobin", "value"),
    ],
    "NEUROLOGICAL": [
        ("glucose", "value"),
        ("sodium", "value"),
        ("calcium", "value"),
        ("potassium", "value"),
        ("wbc", "value"),
    ],
    "GENERAL": [
        ("wbc", "value"),
        ("hemoglobin", "value"),
        ("creatinine", "value"),
        ("glucose", "value"),
    ],
}


# ── Profile별 규칙 세트 ───────────────────────────────────────────

def _severity_by_level(value: float, mild_thresh: float, moderate_thresh: float,
                       severe_thresh: float, direction: str = "high") -> str:
    """수치 수준에 따라 severity를 결정한다."""
    if direction == "high":
        if value > severe_thresh:
            return "severe"
        if value > moderate_thresh:
            return "moderate"
        return "mild"
    else:  # low
        if value < severe_thresh:
            return "severe"
        if value < moderate_thresh:
            return "moderate"
        return "mild"


def _check_cardiac(values: dict, indicators: dict) -> List[Finding]:
    """CARDIAC Profile 규칙 세트 (6개 규칙)."""
    findings: List[Finding] = []

    # P1: Troponin T (indicator only — Tier 3)
    if indicators.get("has_troponin_t", 0) == 1:
        findings.append(Finding(
            name="cardiac_troponin_t_measured",
            detail="트로포닌 T 측정됨 — ACS(급성 관상동맥 증후군) 감별 진행 가능",
            severity="moderate",
            recommendation="트로포닌 T 수치에 따라 ACS 프로토콜 적용",
            category="primary",
        ))

    # P2: BNP (indicator only — Tier 3)
    if indicators.get("has_bnp", 0) == 1:
        findings.append(Finding(
            name="cardiac_bnp_measured",
            detail="BNP 측정됨 — 심부전 감별 진행 가능",
            severity="moderate",
            recommendation="BNP 수치에 따라 심부전 치료 프로토콜 적용",
            category="primary",
        ))

    # P3: K+
    k = values.get("potassium")
    if k is not None:
        nr = NORMAL_RANGES["potassium"]
        if k > 5.5:
            findings.append(Finding(
                name="cardiac_potassium_high",
                detail=f"칼륨 {k} {nr['unit']} — 부정맥 위험 증가",
                severity="severe" if k > 6.0 else "moderate",
                recommendation="심전도 모니터링, 칼륨 저하 치료 고려",
                category="primary",
            ))
        elif k < nr["low"]:
            findings.append(Finding(
                name="cardiac_potassium_low",
                detail=f"칼륨 {k} {nr['unit']} — QT 연장 위험",
                severity="moderate" if k < 3.0 else "mild",
                recommendation="칼륨 보충 및 심전도 QT 간격 확인",
                category="primary",
            ))

    # P4: Glucose — SageMaker: CARDIAC glucose 72.1% abnormal
    glu = values.get("glucose")
    if glu is not None:
        nr = NORMAL_RANGES["glucose"]
        if glu > 200:
            findings.append(Finding(
                name="cardiac_glucose_high",
                detail=f"혈당 {glu} {nr['unit']} — MI 예후 불량 인자 (SageMaker: 72.1% 이상률)",
                severity="moderate",
                recommendation="혈당 조절 및 심근경색 예후 평가에 반영",
                category="primary",
            ))
        elif glu < nr["low"]:
            findings.append(Finding(
                name="cardiac_glucose_low",
                detail=f"혈당 {glu} {nr['unit']} — 저혈당",
                severity="mild",
                recommendation="포도당 투여 고려",
                category="primary",
            ))

    # P5: Creatinine
    cr = values.get("creatinine")
    if cr is not None:
        nr = NORMAL_RANGES["creatinine"]
        if cr > 1.5:
            findings.append(Finding(
                name="cardiac_creatinine_high",
                detail=f"크레아티닌 {cr} {nr['unit']} — PCI 시 조영제 신독성 주의",
                severity="moderate" if cr > 2.0 else "mild",
                recommendation="조영제 사용 전 수액 전처치, 신기능 모니터링",
                category="primary",
            ))

    # P6: Hemoglobin
    hgb = values.get("hemoglobin")
    if hgb is not None:
        nr = NORMAL_RANGES["hemoglobin"]
        if hgb < 10:
            findings.append(Finding(
                name="cardiac_hemoglobin_low",
                detail=f"혈색소 {hgb} {nr['unit']} — 빈혈이 심근 허혈을 악화시킬 수 있음",
                severity="moderate" if hgb < 8 else "mild",
                recommendation="빈혈 원인 평가, 필요 시 수혈 고려",
                category="primary",
            ))

    return findings


def _check_sepsis(values: dict, indicators: dict) -> List[Finding]:
    """SEPSIS Profile 규칙 세트 (5개 규칙)."""
    findings: List[Finding] = []

    # P1: Lactate — SageMaker: lactate 핵심 지표
    lac = values.get("lactate")
    if lac is not None:
        if lac >= 4.0:
            findings.append(Finding(
                name="sepsis_lactate_very_high",
                detail=f"젖산 {lac} mmol/L — Septic shock 기준 충족",
                severity="severe",
                recommendation="즉시 수액 소생술 및 승압제 투여, 1시간 내 항생제 투여",
                category="primary",
            ))
        elif lac >= 2.0:
            findings.append(Finding(
                name="sepsis_lactate_high",
                detail=f"젖산 {lac} mmol/L — Sepsis-3 기준 충족, 조직 저관류 의심",
                severity="moderate",
                recommendation="수액 소생술 시작, 감염원 탐색, 항생제 투여",
                category="primary",
            ))

    # P2: WBC — SageMaker: wbc 53.8% abnormal
    wbc = values.get("wbc")
    if wbc is not None:
        nr = NORMAL_RANGES["wbc"]
        if wbc > 12:
            findings.append(Finding(
                name="sepsis_wbc_high",
                detail=f"백혈구 {wbc} {nr['unit']} — 감염 반응 (SageMaker: 53.8% 이상률)",
                severity="moderate" if wbc > 20 else "mild",
                recommendation="감염원 탐색, 혈액배양 시행",
                category="primary",
            ))
        elif wbc < 4:
            findings.append(Finding(
                name="sepsis_wbc_low",
                detail=f"백혈구 {wbc} {nr['unit']} — 면역저하 또는 중증 패혈증 의심",
                severity="severe",
                recommendation="즉시 광범위 항생제 투여, 호중구 수 확인",
                category="primary",
            ))

    # P3: Platelet
    plt_val = values.get("platelet")
    if plt_val is not None:
        if plt_val < 100:
            findings.append(Finding(
                name="sepsis_platelet_low",
                detail=f"혈소판 {plt_val} K/uL — DIC(파종성 혈관내 응고) 가능성",
                severity="severe" if plt_val < 50 else "moderate",
                recommendation="DIC 감별 검사(PT, aPTT, 피브리노겐, D-dimer) 시행",
                category="primary",
            ))

    # P4: Creatinine
    cr = values.get("creatinine")
    if cr is not None:
        if cr > 1.2:
            findings.append(Finding(
                name="sepsis_creatinine_high",
                detail=f"크레아티닌 {cr} mg/dL — 패혈증 관련 급성 신손상(AKI) 의심",
                severity="severe" if cr > 3.0 else "moderate",
                recommendation="수액 투여, 신독성 약물 중단, 소변량 모니터링",
                category="primary",
            ))

    # P5: Glucose
    glu = values.get("glucose")
    if glu is not None:
        if glu > 180:
            findings.append(Finding(
                name="sepsis_glucose_high",
                detail=f"혈당 {glu} mg/dL — 스트레스성 고혈당 (패혈증 동반)",
                severity="moderate",
                recommendation="인슐린 치료 고려, 혈당 모니터링 강화",
                category="primary",
            ))

    return findings


def _check_gi(values: dict, indicators: dict) -> List[Finding]:
    """GI Profile 규칙 세트 (5개 규칙)."""
    findings: List[Finding] = []

    # P1: AST
    ast_val = values.get("ast")
    if ast_val is not None:
        nr = NORMAL_RANGES["ast"]
        if ast_val > 200:
            findings.append(Finding(
                name="gi_ast_very_high",
                detail=f"AST {ast_val} {nr['unit']} — 현저한 간세포 손상",
                severity="severe",
                recommendation="간염 감별 검사(ALT, 빌리루빈, ALP), 간독성 약물 확인",
                category="primary",
            ))
        elif ast_val > nr["high"]:
            findings.append(Finding(
                name="gi_ast_high",
                detail=f"AST {ast_val} {nr['unit']} — 경도 간효소 상승",
                severity="mild",
                recommendation="추가 간기능 검사 고려",
                category="primary",
            ))

    # P2: Hemoglobin — SageMaker: hemoglobin 60% low
    hgb = values.get("hemoglobin")
    if hgb is not None:
        if hgb < 10:
            findings.append(Finding(
                name="gi_hemoglobin_low",
                detail=f"혈색소 {hgb} g/dL — 활동성 위장관 출혈 가능성",
                severity="severe" if hgb < 8 else "moderate",
                recommendation="출혈원 탐색(내시경 고려), 수혈 준비",
                category="primary",
            ))

    # P3: BUN + BUN/Cr ratio
    bun_val = values.get("bun")
    cr = values.get("creatinine")
    if bun_val is not None:
        nr = NORMAL_RANGES["bun"]
        if bun_val > nr["high"]:
            detail = f"BUN {bun_val} {nr['unit']} — 상승"
            severity = "mild"
            if cr is not None and cr > 0:
                ratio = bun_val / cr
                if ratio > 30:
                    detail = f"BUN {bun_val} {nr['unit']}, BUN/Cr 비율 {ratio:.1f} — 상부 위장관 출혈 시사"
                    severity = "moderate"
            findings.append(Finding(
                name="gi_bun_high",
                detail=detail,
                severity=severity,
                recommendation="상부 위장관 출혈 감별, 내시경 검사 고려",
                category="primary",
            ))

    # P4: Calcium (amylase 대신 — amylase는 Tier 3 indicator)
    ca = values.get("calcium")
    if ca is not None:
        nr = NORMAL_RANGES["calcium"]
        if ca < 8.0:
            findings.append(Finding(
                name="gi_calcium_low",
                detail=f"칼슘 {ca} {nr['unit']} — 중증 췌장염 합병증 의심",
                severity="moderate",
                recommendation="췌장염 중증도 평가(Ranson, APACHE II), 칼슘 보충",
                category="primary",
            ))

    return findings


def _check_renal(values: dict, indicators: dict) -> List[Finding]:
    """RENAL Profile 규칙 세트 (5개 규칙)."""
    findings: List[Finding] = []

    # P1: Creatinine — SageMaker: creatinine 47.3% abnormal
    cr = values.get("creatinine")
    if cr is not None:
        nr = NORMAL_RANGES["creatinine"]
        if cr > 4.0:
            findings.append(Finding(
                name="renal_creatinine_very_high",
                detail=f"크레아티닌 {cr} {nr['unit']} — 중증 신기능 저하 (SageMaker: 47.3% 이상률)",
                severity="severe",
                recommendation="긴급 신장내과 협진, 투석 필요성 평가",
                category="primary",
            ))
        elif cr > nr["high"]:
            findings.append(Finding(
                name="renal_creatinine_high",
                detail=f"크레아티닌 {cr} {nr['unit']} — 신기능 저하",
                severity="moderate" if cr > 2.0 else "mild",
                recommendation="신기능 추적 검사, 신독성 약물 중단",
                category="primary",
            ))

    # P2: BUN — SageMaker: bun 48.8% abnormal
    bun_val = values.get("bun")
    if bun_val is not None:
        nr = NORMAL_RANGES["bun"]
        if bun_val > nr["high"]:
            detail = f"BUN {bun_val} {nr['unit']} — 신기능 저하 (SageMaker: 48.8% 이상률)"
            severity = "mild"
            if cr is not None and cr > 0:
                ratio = bun_val / cr
                if ratio > 20:
                    detail += f", BUN/Cr 비율 {ratio:.1f} — 전신 원인(탈수, 출혈 등) 가능"
                    severity = "moderate"
            findings.append(Finding(
                name="renal_bun_high",
                detail=detail,
                severity=severity,
                recommendation="수액 투여 상태 평가, 전신 원인 감별",
                category="primary",
            ))

    # P3: K+
    k = values.get("potassium")
    if k is not None:
        if k > 5.5:
            findings.append(Finding(
                name="renal_potassium_high",
                detail=f"칼륨 {k} mEq/L — 고칼륨혈증 (신부전 합병증)",
                severity="severe" if k > 6.0 else "moderate",
                recommendation="심전도 확인, 칼륨 저하 치료, 투석 고려",
                category="primary",
            ))

    # P4: Na+
    na = values.get("sodium")
    if na is not None:
        nr = NORMAL_RANGES["sodium"]
        if na < 135:
            findings.append(Finding(
                name="renal_sodium_low",
                detail=f"나트륨 {na} {nr['unit']} — 저나트륨혈증",
                severity="moderate" if na < 130 else "mild",
                recommendation="수분 제한, 원인 감별(SIADH, 수분 과부하 등)",
                category="primary",
            ))
        elif na > 145:
            findings.append(Finding(
                name="renal_sodium_high",
                detail=f"나트륨 {na} {nr['unit']} — 고나트륨혈증",
                severity="moderate" if na > 150 else "mild",
                recommendation="수분 보충, 탈수 원인 평가",
                category="primary",
            ))

    # P5: Ca2+
    ca = values.get("calcium")
    if ca is not None:
        nr = NORMAL_RANGES["calcium"]
        if ca < nr["low"]:
            findings.append(Finding(
                name="renal_calcium_low",
                detail=f"칼슘 {ca} {nr['unit']} — 저칼슘혈증 (신부전 합병증)",
                severity="moderate" if ca < 7.5 else "mild",
                recommendation="칼슘 보충, 비타민 D 투여 고려",
                category="primary",
            ))

    return findings


def _check_respiratory(values: dict, indicators: dict) -> List[Finding]:
    """RESPIRATORY Profile 규칙 세트 (3개 규칙)."""
    findings: List[Finding] = []

    # P1: WBC
    wbc = values.get("wbc")
    if wbc is not None:
        nr = NORMAL_RANGES["wbc"]
        if wbc > 12:
            findings.append(Finding(
                name="respiratory_wbc_high",
                detail=f"백혈구 {wbc} {nr['unit']} — 감염 의심 (폐렴 등)",
                severity="moderate" if wbc > 20 else "mild",
                recommendation="흉부 X-ray 확인, 객담 배양 고려",
                category="primary",
            ))
        elif wbc < 4:
            findings.append(Finding(
                name="respiratory_wbc_low",
                detail=f"백혈구 {wbc} {nr['unit']} — 면역저하 상태",
                severity="moderate",
                recommendation="기회감염 가능성 평가, 호중구 수 확인",
                category="primary",
            ))

    # P2: Lactate
    lac = values.get("lactate")
    if lac is not None:
        if lac >= 2.0:
            findings.append(Finding(
                name="respiratory_lactate_high",
                detail=f"젖산 {lac} mmol/L — 조직 저관류 의심",
                severity="moderate" if lac >= 4.0 else "mild",
                recommendation="산소 공급 상태 평가, 혈역학적 모니터링",
                category="primary",
            ))

    # P3: Hemoglobin — SageMaker: hemoglobin 59.2% low
    hgb = values.get("hemoglobin")
    if hgb is not None:
        if hgb < 10:
            findings.append(Finding(
                name="respiratory_hemoglobin_low",
                detail=f"혈색소 {hgb} g/dL — 산소 운반 능력 저하 (SageMaker: 59.2% 저하)",
                severity="moderate" if hgb < 8 else "mild",
                recommendation="빈혈 원인 평가, 산소 요구량 증가에 대비",
                category="primary",
            ))

    return findings


def _check_neurological(values: dict, indicators: dict) -> List[Finding]:
    """NEUROLOGICAL Profile 규칙 세트 (5개 규칙)."""
    findings: List[Finding] = []

    # P1: Glucose
    glu = values.get("glucose")
    if glu is not None:
        nr = NORMAL_RANGES["glucose"]
        if glu < 60:
            findings.append(Finding(
                name="neuro_glucose_low",
                detail=f"혈당 {glu} {nr['unit']} — 저혈당 의식 변화 가능",
                severity="severe" if glu < 40 else "moderate",
                recommendation="즉시 포도당 투여, 의식 상태 재평가",
                category="primary",
            ))
        elif glu > 400:
            findings.append(Finding(
                name="neuro_glucose_very_high",
                detail=f"혈당 {glu} {nr['unit']} — DKA 의심, 의식 변화 원인 가능",
                severity="severe",
                recommendation="혈액가스 분석, 케톤 검사, 인슐린 치료",
                category="primary",
            ))

    # P2: Na+
    na = values.get("sodium")
    if na is not None:
        nr = NORMAL_RANGES["sodium"]
        if na < 125:
            findings.append(Finding(
                name="neuro_sodium_low",
                detail=f"나트륨 {na} {nr['unit']} — 저나트륨혈증 경련 위험",
                severity="severe" if na < 120 else "moderate",
                recommendation="3% NaCl 투여 고려, 경련 대비",
                category="primary",
            ))
        elif na > 155:
            findings.append(Finding(
                name="neuro_sodium_high",
                detail=f"나트륨 {na} {nr['unit']} — 고나트륨혈증, 의식 변화 원인 가능",
                severity="moderate",
                recommendation="서서히 수분 보충, 급격한 교정 주의",
                category="primary",
            ))

    # P3: Ca2+
    ca = values.get("calcium")
    if ca is not None:
        if ca < 7.0:
            findings.append(Finding(
                name="neuro_calcium_low",
                detail=f"칼슘 {ca} mg/dL — 저칼슘혈증 경련 위험",
                severity="severe",
                recommendation="칼슘 글루코네이트 IV 투여, 경련 대비",
                category="primary",
            ))

    # P4: K+
    k = values.get("potassium")
    if k is not None:
        if k > 6.0:
            findings.append(Finding(
                name="neuro_potassium_high",
                detail=f"칼륨 {k} mEq/L — 근력 약화 원인 가능",
                severity="moderate",
                recommendation="심전도 확인, 칼륨 저하 치료",
                category="primary",
            ))

    # P5: WBC
    wbc = values.get("wbc")
    if wbc is not None:
        if wbc > 15:
            findings.append(Finding(
                name="neuro_wbc_high",
                detail=f"백혈구 {wbc} K/uL — 감염 의심 (뇌수막염 등)",
                severity="moderate",
                recommendation="요추천자 고려, 경험적 항생제 투여",
                category="primary",
            ))

    return findings


def _check_general(values: dict, indicators: dict) -> List[Finding]:
    """GENERAL Profile 규칙 세트 (4개 규칙)."""
    findings: List[Finding] = []

    # P1: WBC
    wbc = values.get("wbc")
    if wbc is not None:
        nr = NORMAL_RANGES["wbc"]
        if wbc > 12:
            findings.append(Finding(
                name="general_wbc_high",
                detail=f"백혈구 {wbc} {nr['unit']} — 감염 또는 염증 반응",
                severity="moderate" if wbc > 20 else "mild",
                recommendation="감염원 탐색, 추가 검사 고려",
                category="primary",
            ))
        elif wbc < 4:
            findings.append(Finding(
                name="general_wbc_low",
                detail=f"백혈구 {wbc} {nr['unit']} — 면역 이상",
                severity="moderate",
                recommendation="호중구 수 확인, 감염 위험 평가",
                category="primary",
            ))

    # P2: Hemoglobin
    hgb = values.get("hemoglobin")
    if hgb is not None:
        if hgb < 10:
            findings.append(Finding(
                name="general_hemoglobin_low",
                detail=f"혈색소 {hgb} g/dL — 빈혈",
                severity="moderate" if hgb < 8 else "mild",
                recommendation="빈혈 원인 평가(철분, B12, 엽산 검사)",
                category="primary",
            ))

    # P3: Creatinine
    cr = values.get("creatinine")
    if cr is not None:
        nr = NORMAL_RANGES["creatinine"]
        if cr > nr["high"]:
            findings.append(Finding(
                name="general_creatinine_high",
                detail=f"크레아티닌 {cr} {nr['unit']} — 신기능 저하",
                severity="moderate" if cr > 2.0 else "mild",
                recommendation="신기능 추적 검사, 신독성 약물 확인",
                category="primary",
            ))

    # P4: Glucose
    glu = values.get("glucose")
    if glu is not None:
        nr = NORMAL_RANGES["glucose"]
        if glu > 200:
            findings.append(Finding(
                name="general_glucose_high",
                detail=f"혈당 {glu} {nr['unit']} — 고혈당",
                severity="moderate",
                recommendation="당뇨 감별, HbA1c 검사 고려",
                category="primary",
            ))
        elif glu < nr["low"]:
            findings.append(Finding(
                name="general_glucose_low",
                detail=f"혈당 {glu} {nr['unit']} — 저혈당",
                severity="moderate" if glu < 50 else "mild",
                recommendation="포도당 투여, 저혈당 원인 평가",
                category="primary",
            ))

    return findings


# ── Profile → 규칙 함수 매핑 ──────────────────────────────────────
_PROFILE_CHECKERS = {
    "CARDIAC": _check_cardiac,
    "SEPSIS": _check_sepsis,
    "GI": _check_gi,
    "RENAL": _check_renal,
    "RESPIRATORY": _check_respiratory,
    "NEUROLOGICAL": _check_neurological,
    "GENERAL": _check_general,
}


class ComplaintFocusedStage:
    """Stage B: Complaint-Focused 해석 — Profile별 우선 확인 검사 규칙 실행."""

    def get_checked_features(self, profile: str) -> Set[str]:
        """Stage B에서 검사하는 Value_Feature 집합을 반환한다.

        Stage C에서 이 집합을 제외하고 나머지를 스캔한다.
        Tier 3 indicator-only 항목(troponin_t, bnp, amylase)은
        12개 Value_Feature에 포함되지 않으므로 제외한다.
        """
        from layer2_rule_engine.stage_c_fullscan import ALL_VALUE_FEATURES

        checks = PROFILE_PRIORITY_CHECKS.get(profile, PROFILE_PRIORITY_CHECKS["GENERAL"])
        return {feat for feat, _ in checks if feat in ALL_VALUE_FEATURES}

    def run(self, processed_input: ProcessedInput) -> List[Finding]:
        """Profile별 규칙을 실행하고 Finding 리스트를 반환한다."""
        profile = processed_input.complaint_profile
        values = processed_input.normalized_values
        indicators = processed_input.indicators

        findings: List[Finding] = []

        # 1) Profile별 규칙 실행
        checker = _PROFILE_CHECKERS.get(profile, _check_general)
        findings.extend(checker(values, indicators))

        # 2) 미측정 경고 생성 (Tier 2/3 항목이 우선 검사에 포함되었으나 미측정인 경우)
        findings.extend(self._check_unmeasured(profile, indicators))

        return findings

    def _check_unmeasured(self, profile: str, indicators: dict) -> List[Finding]:
        """Tier 2/3 미측정 항목에 대한 경고 Finding 생성."""
        findings: List[Finding] = []
        checks = PROFILE_PRIORITY_CHECKS.get(profile, PROFILE_PRIORITY_CHECKS["GENERAL"])

        for feature, check_type in checks:
            # Tier 2 또는 Tier 3 항목만 미측정 경고 대상
            if feature not in TIER2_FEATURES and feature not in TIER3_FEATURES:
                continue

            indicator_name = _FEATURE_TO_INDICATOR.get(feature)
            if indicator_name is None:
                continue

            indicator_value = indicators.get(indicator_name, 0)
            if indicator_value == 0:
                # 미측정 경고 생성
                if feature in TIER3_FEATURES:
                    # Tier 3: 임상적 중요성 포함
                    importance = TIER3_CLINICAL_IMPORTANCE.get(feature, "")
                    findings.append(Finding(
                        name=f"unmeasured_{feature}",
                        detail=f"{feature} 미측정 — {profile} 프로파일에서 필수 검사 항목입니다. {importance}",
                        severity="mild",
                        recommendation=f"{feature} 검사 시행을 권고합니다.",
                        category="primary",
                    ))
                else:
                    # Tier 2: 기본 미측정 경고
                    findings.append(Finding(
                        name=f"unmeasured_{feature}",
                        detail=f"{feature} 미측정 — {profile} 프로파일에서 우선 확인 검사 항목이나 측정되지 않았습니다.",
                        severity="mild",
                        recommendation=f"{feature} 검사 시행을 권고합니다.",
                        category="primary",
                    ))

        return findings
