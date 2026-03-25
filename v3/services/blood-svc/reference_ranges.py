"""
blood-svc reference ranges — 혈액검사 정상 참조 범위 테이블.

각 검사항목의 정상범위, 위급값(panic value), 단위, 성별/나이별 범위를 정의합니다.
새로운 검사항목을 추가하려면 RANGES 딕셔너리에 항목을 추가하세요.

구조:
  RANGES[검사항목_키] = {
      "unit": str,                    # 단위 (예: "mg/dL", "mEq/L")
      "display_name": str,            # 표시용 이름
      "category": str,                # 패널 분류 (cbc, bmp, cardiac, liver, coag, inflammatory)
      "ranges": {
          "default": (하한, 상한),     # 기본 정상범위
          "M": (하한, 상한),           # 남성용 범위 (선택)
          "F": (하한, 상한),           # 여성용 범위 (선택)
      },
      "critical_low": float | None,   # 위급 하한값 (panic value) — 즉시 보고 필요
      "critical_high": float | None,  # 위급 상한값 (panic value)
      "tiers": dict | None,           # 단계별 분류 (선택, BNP/Procalcitonin 등)
  }

참조: 표준 임상 검사실 참조 범위 (standard clinical laboratory reference intervals)
"""

from __future__ import annotations
from typing import Any

# 타입 별칭
RangeSpec = dict[str, Any]

RANGES: dict[str, RangeSpec] = {

    # ══════════════════════════════════════════════════════════════════
    # CBC (Complete Blood Count, 일반혈액검사)
    # ──────────────────────────────────────────────────────────────────
    # 혈액의 세포 성분을 측정하는 기본 검사입니다.

    # WBC (백혈구) — 감염, 염증, 백혈병 등의 지표
    # 상승: 감염, 염증, 스트레스, 백혈병 / 하강: 면역억제, 항암치료, 바이러스 감염
    "wbc": {
        "unit": "x10^3/uL",                                    # 단위: 천/마이크로리터
        "display_name": "WBC (White Blood Cells)",
        "category": "cbc",
        "ranges": {"default": (4.5, 11.0)},                    # 정상: 4.5~11.0
        "critical_low": 2.0,                                    # 위급 저하: 중증 백혈구감소증
        "critical_high": 30.0,                                  # 위급 상승: 백혈병 등 의심
    },

    # RBC (적혈구) — 산소 운반 능력 지표
    # 하강: 빈혈 / 상승: 진성적혈구증가증, 탈수
    "rbc": {
        "unit": "x10^6/uL",                                    # 단위: 백만/마이크로리터
        "display_name": "RBC (Red Blood Cells)",
        "category": "cbc",
        "ranges": {
            "M": (4.5, 5.5),                                   # 남성 정상범위
            "F": (4.0, 5.0),                                   # 여성 정상범위
            "default": (4.0, 5.5),
        },
        "critical_low": 2.0,                                    # 위급 저하: 중증 빈혈
        "critical_high": None,
    },

    # Hemoglobin (혈색소) — 적혈구 내 산소 운반 단백질
    # 빈혈의 가장 중요한 지표. 7.0 미만: 수혈 고려
    "hemoglobin": {
        "unit": "g/dL",                                         # 단위: 그램/데시리터
        "display_name": "Hemoglobin",
        "category": "cbc",
        "ranges": {
            "M": (13.5, 17.5),                                 # 남성 정상범위
            "F": (12.0, 16.0),                                 # 여성 정상범위
            "default": (12.0, 17.5),
        },
        "critical_low": 7.0,                                    # 위급 저하: 수혈 고려 수준
        "critical_high": 20.0,                                  # 위급 상승: 진성적혈구증가증
    },

    # Hematocrit (적혈구용적률) — 혈액 중 적혈구가 차지하는 비율(%)
    "hematocrit": {
        "unit": "%",
        "display_name": "Hematocrit",
        "category": "cbc",
        "ranges": {
            "M": (38.0, 50.0),                                 # 남성 정상범위
            "F": (36.0, 44.0),                                 # 여성 정상범위
            "default": (36.0, 50.0),
        },
        "critical_low": 20.0,                                   # 위급 저하: 심한 빈혈/출혈
        "critical_high": 60.0,                                  # 위급 상승: 과점도 위험
    },

    # Platelets (혈소판) — 지혈/응고 기능 지표
    # 하강: 출혈 위험 / 상승: 혈전 위험
    "platelets": {
        "unit": "x10^3/uL",                                    # 단위: 천/마이크로리터
        "display_name": "Platelets",
        "category": "cbc",
        "ranges": {"default": (150.0, 400.0)},
        "critical_low": 50.0,                                   # 위급 저하: 자발 출혈 위험
        "critical_high": 1000.0,                                # 위급 상승: 혈전 위험
    },

    # MCV (평균적혈구용적) — 적혈구 크기 지표
    # < 80: 소적혈구(철결핍빈혈 등) / > 100: 대적혈구(B12/엽산 결핍 등)
    "mcv": {
        "unit": "fL",                                           # 단위: 펨토리터
        "display_name": "MCV (Mean Corpuscular Volume)",
        "category": "cbc",
        "ranges": {"default": (80.0, 100.0)},
        "critical_low": None,
        "critical_high": None,
    },

    # MCH (평균적혈구혈색소량) — 적혈구당 헤모글로빈 양
    "mch": {
        "unit": "pg",                                           # 단위: 피코그램
        "display_name": "MCH (Mean Corpuscular Hemoglobin)",
        "category": "cbc",
        "ranges": {"default": (27.0, 33.0)},
        "critical_low": None,
        "critical_high": None,
    },

    # MCHC (평균적혈구혈색소농도) — 적혈구 내 헤모글로빈 농도
    "mchc": {
        "unit": "g/dL",                                         # 단위: 그램/데시리터
        "display_name": "MCHC",
        "category": "cbc",
        "ranges": {"default": (32.0, 36.0)},
        "critical_low": None,
        "critical_high": None,
    },

    # ══════════════════════════════════════════════════════════════════
    # BMP (Basic Metabolic Panel, 기초대사패널)
    # ──────────────────────────────────────────────────────────────────
    # 전해질, 신기능, 혈당 등 기초 대사 상태를 평가합니다.

    # Sodium (나트륨) — 체내 수분 균형 및 신경/근육 기능 지표
    # 저나트륨혈증: 의식변화, 경련 / 고나트륨혈증: 탈수, 갈증
    "sodium": {
        "unit": "mEq/L",                                       # 단위: 밀리당량/리터
        "display_name": "Sodium (Na)",
        "category": "bmp",
        "ranges": {"default": (136.0, 145.0)},
        "critical_low": 120.0,                                  # 위급 저하: 중증 저나트륨혈증
        "critical_high": 160.0,                                 # 위급 상승: 중증 고나트륨혈증
    },

    # Potassium (칼륨) — 심장 리듬, 근육 기능 지표
    # 저칼륨혈증: 부정맥, 근육약화 / 고칼륨혈증: 심장마비 위험
    "potassium": {
        "unit": "mEq/L",                                       # 단위: 밀리당량/리터
        "display_name": "Potassium (K)",
        "category": "bmp",
        "ranges": {"default": (3.5, 5.0)},
        "critical_low": 2.5,                                    # 위급 저하: 치명적 부정맥 위험
        "critical_high": 6.5,                                   # 위급 상승: 심장마비 위험
    },

    # Chloride (염소) — 산-염기 균형 지표
    "chloride": {
        "unit": "mEq/L",                                       # 단위: 밀리당량/리터
        "display_name": "Chloride (Cl)",
        "category": "bmp",
        "ranges": {"default": (98.0, 106.0)},
        "critical_low": 80.0,
        "critical_high": 120.0,
    },

    # CO2/Bicarbonate (이산화탄소/중탄산) — 산-염기 균형 지표
    # 저하: 대사성 산증 / 상승: 대사성 알칼리증
    "co2": {
        "unit": "mEq/L",                                       # 단위: 밀리당량/리터
        "display_name": "CO2 (Bicarbonate)",
        "category": "bmp",
        "ranges": {"default": (23.0, 29.0)},
        "critical_low": 10.0,                                   # 위급 저하: 심한 대사성 산증
        "critical_high": 40.0,                                  # 위급 상승: 심한 대사성 알칼리증
    },

    # BUN (혈중요소질소) — 신기능 지표
    # 상승: 신부전, 탈수, 고단백 식이 / BUN/Cr 비율 > 20: 신전성 원인 시사
    "bun": {
        "unit": "mg/dL",                                       # 단위: 밀리그램/데시리터
        "display_name": "BUN (Blood Urea Nitrogen)",
        "category": "bmp",
        "ranges": {"default": (7.0, 20.0)},
        "critical_low": None,
        "critical_high": 100.0,                                 # 위급 상승: 심한 신부전
    },

    # Creatinine (크레아티닌) — 신기능의 가장 중요한 지표
    # 상승: 신기능 저하 (GFR 감소와 반비례)
    "creatinine": {
        "unit": "mg/dL",                                       # 단위: 밀리그램/데시리터
        "display_name": "Creatinine",
        "category": "bmp",
        "ranges": {
            "M": (0.7, 1.3),                                   # 남성 정상범위
            "F": (0.6, 1.1),                                   # 여성 정상범위 (근육량 차이)
            "default": (0.6, 1.3),
        },
        "critical_low": None,
        "critical_high": 10.0,                                  # 위급 상승: 투석 고려 수준
    },

    # Glucose (혈당, 공복) — 당뇨병 진단/관리 지표
    # 저혈당: 의식변화, 경련 / 고혈당: 당뇨성 케톤산증(DKA) 위험
    "glucose": {
        "unit": "mg/dL",                                       # 단위: 밀리그램/데시리터
        "display_name": "Glucose (Fasting)",
        "category": "bmp",
        "ranges": {"default": (70.0, 100.0)},                  # 공복 정상범위
        "critical_low": 40.0,                                   # 위급 저하: 심한 저혈당
        "critical_high": 500.0,                                 # 위급 상승: DKA/고삼투압 상태
    },

    # Calcium (칼슘) — 뼈, 신경, 근육, 심장 기능 지표
    # 저칼슘혈증: 경련, 부정맥 / 고칼슘혈증: 의식변화, 신석
    "calcium": {
        "unit": "mg/dL",                                       # 단위: 밀리그램/데시리터
        "display_name": "Calcium (Ca)",
        "category": "bmp",
        "ranges": {"default": (8.5, 10.5)},
        "critical_low": 6.0,                                    # 위급 저하: 경련/부정맥 위험
        "critical_high": 13.0,                                  # 위급 상승: 고칼슘혈증 위기
    },

    # ══════════════════════════════════════════════════════════════════
    # Cardiac Markers (심장 표지자)
    # ──────────────────────────────────────────────────────────────────
    # 심부전 및 심근 손상을 평가하는 혈액 표지자입니다.

    # BNP (B형 나트륨이뇨펩티드) — 심부전 진단/추적 지표
    # 심실 벽 스트레스에 의해 분비. 상승: 심부전, 폐색전, 폐고혈압
    "bnp": {
        "unit": "pg/mL",                                       # 단위: 피코그램/밀리리터
        "display_name": "BNP (B-type Natriuretic Peptide)",
        "category": "cardiac",
        "ranges": {"default": (0.0, 100.0)},                   # 100 미만: 심부전 배제
        "critical_low": None,
        "critical_high": None,
        "tiers": {                                              # 단계별 분류
            "normal": (0, 100),                                 # 정상: 심부전 가능성 낮음
            "elevated": (100, 400),                             # 상승: 심부전 가능
            "high": (400, float("inf")),                        # 높음: 심부전 가능성 높음
        },
    },

    # NT-proBNP — BNP의 비활성 전구체, 심부전 진단 (나이별 기준 다름)
    "nt_probnp": {
        "unit": "pg/mL",                                       # 단위: 피코그램/밀리리터
        "display_name": "NT-proBNP",
        "category": "cardiac",
        "ranges": {"default": (0.0, 125.0)},                   # 기본값; 나이별 조정은 analyzer에서
        "critical_low": None,
        "critical_high": None,
        "age_ranges": {                                         # 나이별 심부전 배제 기준값
            "lt50": 450,                                        # 50세 미만: 450 pg/mL
            "50_75": 900,                                       # 50~75세: 900 pg/mL
            "gt75": 1800,                                       # 75세 초과: 1800 pg/mL
        },
    },

    # Troponin I — 심근 손상의 고감도 표지자
    # 상승: 급성 심근경색, 심근염, 폐색전 등
    "troponin_i": {
        "unit": "ng/mL",                                       # 단위: 나노그램/밀리리터
        "display_name": "Troponin I",
        "category": "cardiac",
        "ranges": {"default": (0.0, 0.04)},                    # 정상 상한: 0.04 ng/mL
        "critical_low": None,
        "critical_high": 0.4,                                   # 위급 상승: 심근경색 강력 시사
    },

    # Troponin T — 심근 손상 표지자 (Troponin I와 함께 사용)
    "troponin_t": {
        "unit": "ng/mL",                                       # 단위: 나노그램/밀리리터
        "display_name": "Troponin T",
        "category": "cardiac",
        "ranges": {"default": (0.0, 0.01)},                    # 정상 상한: 0.01 ng/mL
        "critical_low": None,
        "critical_high": 0.1,                                   # 위급 상승: 심근 손상 확인
    },

    # CK-MB — 심근 효소 (Troponin보다 특이도 낮지만 경과 추적에 유용)
    "ck_mb": {
        "unit": "ng/mL",                                       # 단위: 나노그램/밀리리터
        "display_name": "CK-MB",
        "category": "cardiac",
        "ranges": {"default": (0.0, 5.0)},                     # 정상 상한: 5.0 ng/mL
        "critical_low": None,
        "critical_high": None,
    },

    # ══════════════════════════════════════════════════════════════════
    # Liver Function (간기능 검사)
    # ──────────────────────────────────────────────────────────────────
    # 간 손상, 담즙 정체, 간 합성 기능을 평가합니다.

    # AST (SGOT) — 간세포 손상 지표 (간, 심장, 근육에도 존재)
    "ast": {
        "unit": "U/L",                                         # 단위: 국제단위/리터
        "display_name": "AST (SGOT)",
        "category": "liver",
        "ranges": {"default": (10.0, 40.0)},
        "critical_low": None,
        "critical_high": 1000.0,                                # 위급 상승: 급성 간괴사 시사
    },

    # ALT (SGPT) — 간 특이적 손상 지표 (AST보다 간에 더 특이적)
    "alt": {
        "unit": "U/L",                                         # 단위: 국제단위/리터
        "display_name": "ALT (SGPT)",
        "category": "liver",
        "ranges": {"default": (7.0, 56.0)},
        "critical_low": None,
        "critical_high": 1000.0,                                # 위급 상승: 급성 간괴사 시사
    },

    # ALP (알칼리인산분해효소) — 담즙 정체, 골질환 지표
    "alp": {
        "unit": "U/L",                                         # 단위: 국제단위/리터
        "display_name": "ALP (Alkaline Phosphatase)",
        "category": "liver",
        "ranges": {"default": (44.0, 147.0)},
        "critical_low": None,
        "critical_high": None,
    },

    # Total Bilirubin (총 빌리루빈) — 황달 지표
    # 상승: 간질환, 용혈, 담도 폐쇄
    "bilirubin_total": {
        "unit": "mg/dL",                                       # 단위: 밀리그램/데시리터
        "display_name": "Total Bilirubin",
        "category": "liver",
        "ranges": {"default": (0.1, 1.2)},
        "critical_low": None,
        "critical_high": 15.0,                                  # 위급 상승: 심한 황달
    },

    # Direct Bilirubin (직접 빌리루빈) — 포합(conjugated) 빌리루빈
    # 상승: 담즙 정체, 간내/간외 폐쇄
    "bilirubin_direct": {
        "unit": "mg/dL",                                       # 단위: 밀리그램/데시리터
        "display_name": "Direct Bilirubin",
        "category": "liver",
        "ranges": {"default": (0.0, 0.3)},
        "critical_low": None,
        "critical_high": None,
    },

    # Albumin (알부민) — 간 합성 기능 지표
    # 저하: 간경변, 영양실조, 만성질환, 신증후군
    "albumin": {
        "unit": "g/dL",                                        # 단위: 그램/데시리터
        "display_name": "Albumin",
        "category": "liver",
        "ranges": {"default": (3.5, 5.5)},
        "critical_low": 1.5,                                    # 위급 저하: 심한 저알부민혈증
        "critical_high": None,
    },

    # ══════════════════════════════════════════════════════════════════
    # Coagulation (응고 검사)
    # ──────────────────────────────────────────────────────────────────
    # 출혈 및 혈전 위험을 평가합니다.

    # D-Dimer — 혈전 형성/분해 지표
    # 상승: 심부정맥혈전증(DVT), 폐색전(PE), DIC 등
    "d_dimer": {
        "unit": "ug/mL",                                       # 단위: 마이크로그램/밀리리터
        "display_name": "D-Dimer",
        "category": "coag",
        "ranges": {"default": (0.0, 0.5)},                     # 0.5 미만: DVT/PE 배제에 유용
        "critical_low": None,
        "critical_high": None,
    },

    # PT/INR — 외인성 응고 경로 지표, 와파린 모니터링
    # 상승: 출혈 위험 증가 / INR > 5.0: 심한 출혈 위험
    "pt_inr": {
        "unit": "",                                            # 단위 없음 (비율)
        "display_name": "PT/INR",
        "category": "coag",
        "ranges": {"default": (0.8, 1.2)},                     # 정상: 0.8~1.2
        "critical_low": None,
        "critical_high": 5.0,                                   # 위급 상승: 심각한 출혈 위험
    },

    # ══════════════════════════════════════════════════════════════════
    # Inflammatory (염증 표지자)
    # ──────────────────────────────────────────────────────────────────
    # 감염 및 염증 상태를 평가합니다.

    # CRP (C-반응 단백) — 비특이적 염증 지표
    # 상승: 감염, 자가면역, 조직 손상, 악성 종양 등
    "crp": {
        "unit": "mg/L",                                        # 단위: 밀리그램/리터
        "display_name": "CRP (C-Reactive Protein)",
        "category": "inflammatory",
        "ranges": {"default": (0.0, 10.0)},                    # 10 미만: 정상
        "critical_low": None,
        "critical_high": None,
    },

    # Procalcitonin (프로칼시토닌) — 세균 감염 특이적 표지자
    # 바이러스 감염에서는 잘 상승하지 않아 세균 감염과 감별에 유용
    "procalcitonin": {
        "unit": "ng/mL",                                       # 단위: 나노그램/밀리리터
        "display_name": "Procalcitonin",
        "category": "inflammatory",
        "ranges": {"default": (0.0, 0.1)},
        "critical_low": None,
        "critical_high": None,
        "tiers": {                                              # 단계별 세균 감염 위험도
            "normal": (0, 0.1),                                 # 정상: 세균 감염 가능성 낮음
            "low_risk": (0.1, 0.25),                            # 저위험: 국소 감염 가능
            "moderate": (0.25, 0.5),                            # 중등도: 항생제 고려
            "high": (0.5, 2.0),                                 # 고위험: 세균 감염 가능성 높음
            "severe": (2.0, float("inf")),                      # 중증: 패혈증 가능성
        },
    },

    # ESR (적혈구침강속도) — 비특이적 염증 지표
    # 만성 염증, 자가면역, 감염에서 상승. 나이, 성별에 따라 다름
    "esr": {
        "unit": "mm/hr",                                       # 단위: 밀리미터/시간
        "display_name": "ESR (Erythrocyte Sedimentation Rate)",
        "category": "inflammatory",
        "ranges": {
            "M": (0.0, 15.0),                                  # 남성 정상범위
            "F": (0.0, 20.0),                                  # 여성 정상범위
            "default": (0.0, 20.0),
        },
        "critical_low": None,
        "critical_high": None,
    },
}


# ══════════════════════════════════════════════════════════════════════
# Helper 함수 (조회용)
# ──────────────────────────────────────────────────────────────────────
# analyzer.py에서 이 함수들을 import하여 사용합니다.

def get_range(test_name: str, sex: str = "M", age: int = 50) -> tuple[float, float]:
    """검사항목의 성별/나이별 정상범위 (하한, 상한)을 반환합니다."""
    spec = RANGES.get(test_name)
    if spec is None:
        return (0.0, float("inf"))

    ranges = spec["ranges"]
    sex_upper = sex.upper()

    # NT-proBNP는 나이별로 기준이 다름 → 별도 처리
    if test_name == "nt_probnp" and "age_ranges" in spec:
        if age < 50:
            high = spec["age_ranges"]["lt50"]
        elif age <= 75:
            high = spec["age_ranges"]["50_75"]
        else:
            high = spec["age_ranges"]["gt75"]
        return (0.0, float(high))

    # 성별 범위가 있으면 성별 범위 사용, 없으면 기본값
    if sex_upper in ranges:
        return ranges[sex_upper]
    return ranges.get("default", (0.0, float("inf")))


def get_critical_range(test_name: str) -> tuple[float | None, float | None]:
    """위급값 (critical_low, critical_high)을 반환합니다. 없으면 (None, None)."""
    spec = RANGES.get(test_name)
    if spec is None:
        return (None, None)
    return (spec.get("critical_low"), spec.get("critical_high"))


def get_unit(test_name: str) -> str:
    """검사항목의 단위 문자열을 반환합니다. (예: "mg/dL", "mEq/L")"""
    spec = RANGES.get(test_name)
    return spec["unit"] if spec else ""


def get_display_name(test_name: str) -> str:
    """검사항목의 표시용 이름을 반환합니다. (예: "Potassium (K)")"""
    spec = RANGES.get(test_name)
    return spec["display_name"] if spec else test_name


def get_category(test_name: str) -> str:
    """검사항목의 패널 카테고리를 반환합니다. (예: "cbc", "bmp", "cardiac")"""
    spec = RANGES.get(test_name)
    return spec.get("category", "unknown") if spec else "unknown"


def get_tiers(test_name: str) -> dict | None:
    """단계별 분류(tiers)가 있는 항목은 tier 딕셔너리를, 없으면 None을 반환합니다."""
    spec = RANGES.get(test_name)
    if spec is None:
        return None
    return spec.get("tiers")
