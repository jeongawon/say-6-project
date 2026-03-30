"""ECG 임계값 SSOT — Lambda inference.py와 동일 값 유지. 수정 시 이 파일만 변경."""

LABEL_NAMES: list[str] = [
    "stemi", "vfib_vtach", "avblock_3rd", "pe", "nstemi",
    "afib", "svt", "heart_failure", "sepsis", "hyperkalemia",
    "hypokalemia", "lbbb", "arrhythmia",
]

LABEL_THRESHOLDS: dict[str, float] = {
    "stemi": 0.250,         # 응급 — Sensitivity >= 80%
    "vfib_vtach": 0.170,    # 응급 — Sensitivity >= 80%
    "avblock_3rd": 0.470,   # 응급 — Sensitivity >= 80%
    "pe": 0.505,            # FP 완화(30%)
    "nstemi": 0.470,
    "afib": 0.425,
    "svt": 0.345,           # FP 완화(30%)
    "heart_failure": 0.440,
    "sepsis": 0.385,
    "hyperkalemia": 0.471,  # FP 완화(30%) — 55% FP 잔존
    "hypokalemia": 0.350,   # FP 완화(30%)
    "lbbb": 0.835,
    "arrhythmia": 0.445,
}

# margin 필터 미적용 레이블 (놓치면 안 됨 — 응급 + 멀티모달 트리거용)
EMERGENCY_LABELS: set[str] = {"stemi", "vfib_vtach", "avblock_3rd", "hyperkalemia"}
DETECTION_MARGIN: float = 0.10

# risk level 판정용 레이블 셋 (Lambda와 동일)
CRITICAL_LABELS: set[str] = {"stemi", "vfib_vtach", "avblock_3rd"}
URGENT_LABELS: set[str] = {"nstemi", "pe", "svt", "hyperkalemia"}

LABEL_KO: dict[str, str] = {
    "stemi": "ST분절 상승 심근경색", "vfib_vtach": "심실세동/심실빈맥",
    "avblock_3rd": "3도 방실차단", "pe": "폐색전증",
    "nstemi": "비ST분절 상승 심근경색", "afib": "심방세동",
    "svt": "발작성 상심실 빈맥", "heart_failure": "심부전",
    "sepsis": "패혈증", "hyperkalemia": "고칼륨혈증",
    "hypokalemia": "저칼륨혈증", "lbbb": "좌각차단",
    "arrhythmia": "부정맥",
}

# Finding.severity — Lambda LABEL_SEVERITY 동일
LABEL_SEVERITY: dict[str, str] = {
    "stemi": "critical", "vfib_vtach": "critical", "avblock_3rd": "critical",
    "pe": "severe", "nstemi": "severe", "hyperkalemia": "severe",
    "afib": "moderate", "svt": "moderate",
    "heart_failure": "moderate", "sepsis": "moderate",
    "hypokalemia": "mild", "lbbb": "mild", "arrhythmia": "mild",
}

LABEL_RECOMMENDATION: dict[str, str] = {
    "stemi": "즉시 PCI(관상동맥 중재술) 팀 호출",
    "vfib_vtach": "즉시 제세동 및 CPR 준비",
    "avblock_3rd": "즉시 임시 심박동기 삽입 고려",
    "pe": "CT 폐혈관조영술(CTPA) 시행",
    "nstemi": "심장내과 협진 및 트로포닌 재검",
    "hyperkalemia": "혈액 K+ 즉시 확인, 심전도 모니터링",
    "afib": "심박수 조절 및 항응고 요법 검토",
    "svt": "미주신경자극 또는 아데노신 투여 고려",
    "heart_failure": "BNP/NT-proBNP 검사 및 이뇨제 투여",
    "sepsis": "혈액배양 후 광범위 항생제 투여",
    "hypokalemia": "혈액 K+ 확인 및 전해질 보충",
    "lbbb": "심장내과 협진, STEMI equivalent 배제",
    "arrhythmia": "지속 심전도 모니터링",
}

# 감지 레이블 → 추천 다음 모달 매핑 (Lambda NEXT_MODAL_MAP 동일)
NEXT_MODAL_MAP: dict[str, dict] = {
    "nstemi": {"modal": "blood", "action": "트로포닌 I/T 검사", "description": "NSTEMI 의심 — 심근 바이오마커 확인 필요"},
    "heart_failure": {"modal": "blood", "action": "BNP/NT-proBNP 검사", "description": "심부전 의심 — 심장 바이오마커 확인 필요"},
    "sepsis": {"modal": "blood", "action": "혈액배양 + 젖산 검사", "description": "패혈증 의심 — 감염 바이오마커 확인 필요"},
    "hyperkalemia": {"modal": "blood", "action": "혈중 K+ 즉시 확인", "description": "고칼륨혈증 의심 — 전해질 검사 긴급 시행"},
    "hypokalemia": {"modal": "blood", "action": "혈중 K+ 확인", "description": "저칼륨혈증 의심 — 전해질 검사 시행"},
    "pe": {"modal": "chest", "action": "CT 폐혈관조영술(CTPA)", "description": "폐색전증 의심 — 흉부 영상 확인 필요"},
}

# ECG 파형으로 직접 확인 가능한 레이블
ECG_CONFIRMED_LABELS: set[str] = {"stemi", "vfib_vtach", "avblock_3rd", "afib", "lbbb", "arrhythmia", "svt"}
NEEDS_CONFIRMATION_LABELS: set[str] = {"pe", "nstemi", "heart_failure", "sepsis", "hyperkalemia", "hypokalemia"}
