"""
ecg-svc analyzer — 규칙 기반 12-리드 ECG 분석 모듈.

8가지 임상 기준에 따라 ECG 데이터를 분석합니다:
  1. 심박수 분류 (서맥 < 60 bpm, 정상 60-100 bpm, 빈맥 > 100 bpm)
  2. 리듬/부정맥 검출 (심방세동 AF, 심실빈맥 VT, 상심실성빈맥 SVT)
  3. PR 간격 분석 (1도 방실차단, WPW 증후군)
  4. QRS / 각차단 (우각차단 RBBB, 좌각차단 LBBB)
  5. 심실비대 (좌심실비대 LVH — Sokolow-Lyon/Cornell, 우심실비대 RVH)
  6. ST 분절 분석 (상승/하강, 관상동맥 영역 매핑)
  7. QT/QTc 간격 (Bazett 공식으로 보정)
  8. 전기축 편위 (정상, 좌축편위, 우축편위, 극단축편위)

입력 데이터 형식 (req.data):
  {
    "heart_rate": 78,                     # 심박수 (bpm)
    "rhythm_regular": true,               # 리듬 규칙성
    "p_wave_present": true,               # P파 존재 여부
    "pr_interval": 160,                   # PR 간격 (ms)
    "qrs_duration": 90,                   # QRS 폭 (ms)
    "qt_interval": 400,                   # QT 간격 (ms)
    "rr_intervals": [780, 790, 785, ...], # RR 간격 목록 (ms, 선택사항)
    "leads": {
      "I":   {"r_amp": 0.8, "s_amp": -0.2, "st_dev": 0.0},
      "II":  {"r_amp": 1.2, "s_amp": -0.3, "st_dev": 0.0},
      ...12개 리드 데이터...
    }
  }

r_amp / s_amp: 밀리볼트(mV) 단위. R파는 양수, S파는 음수.
st_dev: ST 편위(mV). 양수 = 상승(elevation), 음수 = 하강(depression).
"""

from __future__ import annotations

import logging
import math
import sys
from typing import Any

sys.path.insert(0, "/app/shared")
from schemas import Finding, PatientInfo

logger = logging.getLogger("ecg-svc.analyzer")

# ── 리드 그룹 분류 (관상동맥 영역별) ─────────────────────────────────
ANTERIOR_LEADS = ["V1", "V2", "V3", "V4"]   # 전벽 (좌전하행지 LAD 영역)
LATERAL_LEADS = ["I", "aVL", "V5", "V6"]    # 측벽 (좌회선지 LCx 영역)
INFERIOR_LEADS = ["II", "III", "aVF"]        # 하벽 (우관상동맥 RCA 영역)
ALL_LEADS = [
    "I", "II", "III", "aVR", "aVL", "aVF",
    "V1", "V2", "V3", "V4", "V5", "V6",
]


# ── Helper: 리드 데이터 안전 접근 ────────────────────────────────────
def _lead(leads: dict, name: str) -> dict:
    """리드 데이터를 기본값과 병합하여 반환. 누락된 리드는 0으로 채움."""
    default = {"r_amp": 0.0, "s_amp": 0.0, "st_dev": 0.0}
    raw = leads.get(name, default)
    return {**default, **raw}


def _abs_s(leads: dict, name: str) -> float:
    """특정 리드의 S파 절대값(mV)을 반환."""
    return abs(_lead(leads, name).get("s_amp", 0.0))


def _r(leads: dict, name: str) -> float:
    """특정 리드의 R파 진폭(mV)을 반환."""
    return _lead(leads, name).get("r_amp", 0.0)


# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [원정아] 실제 ECG 분석 로직으로 교체               ║
# ║  현재는 규칙 기반 템플릿입니다.                            ║
# ║  ML 모델을 추가하려면 이 함수를 수정하세요.                ║
# ╚══════════════════════════════════════════════════════════╝

# ── 분석 진입점 ──────────────────────────────────────────────────────
def analyze_ecg(data: dict, patient_info: PatientInfo) -> list[Finding]:
    """
    8개 규칙 기반 ECG 분석 모듈을 순차 실행하고 결과를 취합합니다.

    ML 모델 도입 시: 이 함수에서 모델 추론을 호출하고,
    결과를 Finding 객체로 변환하여 반환하면 됩니다.
    """
    findings: list[Finding] = []

    # 입력 데이터 추출
    heart_rate = data.get("heart_rate")               # 심박수 (bpm)
    rhythm_regular = data.get("rhythm_regular", True)  # 리듬 규칙성
    p_wave_present = data.get("p_wave_present", True)  # P파 존재 여부
    pr_interval = data.get("pr_interval")              # PR 간격 (ms)
    qrs_duration = data.get("qrs_duration")            # QRS 폭 (ms)
    qt_interval = data.get("qt_interval")              # QT 간격 (ms)
    rr_intervals = data.get("rr_intervals", [])        # RR 간격 목록 (ms)
    leads = data.get("leads", {})                      # 12-리드 데이터

    age = patient_info.age          # 환자 나이
    sex = patient_info.sex.upper()  # 환자 성별 (M/F)

    # 1) 심박수 분류 (서맥/정상/빈맥)
    findings.extend(_rate_analysis(heart_rate))

    # 2) 리듬/부정맥 분석 (AF, SVT, VT)
    findings.extend(
        _rhythm_analysis(heart_rate, rhythm_regular, p_wave_present, rr_intervals, qrs_duration)
    )

    # 3) PR 간격 분석 (방실차단, WPW)
    if pr_interval is not None:
        findings.extend(_pr_analysis(pr_interval))

    # 4) QRS 폭 / 각차단 분석 (RBBB, LBBB)
    if qrs_duration is not None:
        findings.extend(_qrs_analysis(qrs_duration, leads))

    # 5) 심실비대 분석 (LVH — Sokolow-Lyon/Cornell, RVH)
    findings.extend(_ventricular_hypertrophy(leads, age, sex))

    # 6) ST 분절 분석 (상승/하강, 영역 매핑)
    findings.extend(_st_analysis(leads))

    # 7) QT/QTc 간격 분석 (Bazett 공식)
    if qt_interval is not None and heart_rate is not None and heart_rate > 0:
        findings.extend(_qt_analysis(qt_interval, heart_rate, sex))

    # 8) 전기축 편위 분석
    findings.extend(_axis_analysis(leads))

    return findings


# ══════════════════════════════════════════════════════════════════════
# 모듈 1. 심박수 분류 (Heart Rate Classification)
# ──────────────────────────────────────────────────────────────────────
# 서맥(< 60 bpm), 정상(60-100 bpm), 빈맥(> 100 bpm)을 판별합니다.
# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [원정아] 실제 ECG 분석 로직으로 교체               ║
# ║  현재는 규칙 기반 템플릿입니다.                            ║
# ║  ML 모델을 추가하려면 이 함수를 수정하세요.                ║
# ╚══════════════════════════════════════════════════════════╝
def _rate_analysis(hr: float | None) -> list[Finding]:
    """심박수를 기준으로 서맥/정상/빈맥을 분류합니다."""
    if hr is None:
        return []

    findings = []
    if hr < 60:
        # 서맥 (Bradycardia): 심박수 60 bpm 미만
        findings.append(Finding(
            name="bradycardia",
            detected=True,
            confidence=0.95,
            detail=f"Heart rate {hr} bpm (< 60 bpm)",
        ))
    elif hr > 100:
        # 빈맥 (Tachycardia): 심박수 100 bpm 초과
        findings.append(Finding(
            name="tachycardia",
            detected=True,
            confidence=0.95,
            detail=f"Heart rate {hr} bpm (> 100 bpm)",
        ))
    else:
        # 정상 동성 리듬 (Normal Sinus Rate)
        findings.append(Finding(
            name="normal_sinus_rate",
            detected=True,
            confidence=0.95,
            detail=f"Heart rate {hr} bpm (normal range 60-100)",
        ))
    return findings


# ══════════════════════════════════════════════════════════════════════
# 모듈 2. 리듬/부정맥 분석 (Rhythm / Arrhythmia Detection)
# ──────────────────────────────────────────────────────────────────────
# 심방세동(AF), 상심실성빈맥(SVT), 심실빈맥(VT)을 점수 기반으로 검출합니다.
# - AF: 불규칙 리듬 + P파 부재 + 높은 RR 변동성
# - SVT: HR > 150 + 좁은 QRS + 규칙적 리듬
# - VT: HR > 100 + 넓은 QRS (>= 120ms)
# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [원정아] 실제 ECG 분석 로직으로 교체               ║
# ║  현재는 규칙 기반 템플릿입니다.                            ║
# ║  ML 모델을 추가하려면 이 함수를 수정하세요.                ║
# ╚══════════════════════════════════════════════════════════╝
def _rhythm_analysis(
    hr: float | None,
    rhythm_regular: bool,
    p_wave_present: bool,
    rr_intervals: list[float],
    qrs_duration: float | None,
) -> list[Finding]:
    """리듬 규칙성, P파 유무, RR 변동성 등을 종합하여 부정맥을 판별합니다."""
    findings = []

    # RR 간격 변동성 계산 (3개 이상의 RR 간격 필요)
    rr_variability = 0.0
    if len(rr_intervals) >= 3:
        mean_rr = sum(rr_intervals) / len(rr_intervals)
        if mean_rr > 0:
            diffs = [abs(rr_intervals[i] - rr_intervals[i - 1]) for i in range(1, len(rr_intervals))]
            rr_variability = (sum(diffs) / len(diffs)) / mean_rr

    # ── 심방세동 (Atrial Fibrillation) 판별 ──
    # 불규칙 리듬 + P파 부재 + 높은 RR 변동성 → 점수 합산
    af_score = 0.0
    af_reasons = []
    if not rhythm_regular:
        af_score += 0.3                                  # 불규칙 리듬 (+0.3점)
        af_reasons.append("irregular rhythm")
    if not p_wave_present:
        af_score += 0.35                                 # P파 부재 (+0.35점)
        af_reasons.append("absent P waves")
    if rr_variability > 0.12:
        af_score += 0.25                                 # 높은 RR 변동성 (+0.25점)
        af_reasons.append(f"high RR variability ({rr_variability:.2f})")

    af_detected = af_score >= 0.55  # 0.55점 이상이면 AF로 판정
    findings.append(Finding(
        name="atrial_fibrillation",
        detected=af_detected,
        confidence=round(min(af_score + 0.1, 0.98) if af_detected else max(1.0 - af_score, 0.5), 2),
        detail=", ".join(af_reasons) if af_detected else "No AF criteria met",
    ))

    # ── 상심실성빈맥 (SVT) 판별 ──
    # 조건: HR > 150 bpm + 좁은 QRS (< 120ms) + 규칙적 리듬
    qrs_narrow = (qrs_duration is not None and qrs_duration < 120)
    if hr is not None and hr > 150 and qrs_narrow and rhythm_regular:
        findings.append(Finding(
            name="supraventricular_tachycardia",
            detected=True,
            confidence=0.80,
            detail=f"HR {hr} bpm, narrow QRS ({qrs_duration} ms), regular rhythm",
        ))

    # ── 심실빈맥 (VT) 판별 ──
    # 조건: HR > 100 bpm + 넓은 QRS (>= 120ms)
    qrs_wide = (qrs_duration is not None and qrs_duration >= 120)
    if hr is not None and hr > 100 and qrs_wide:
        vt_conf = 0.70
        if hr > 150:                    # 빠른 심박 → 신뢰도 상향
            vt_conf = 0.85
        if qrs_duration and qrs_duration > 160:  # 매우 넓은 QRS → 추가 가중
            vt_conf = min(vt_conf + 0.10, 0.95)
        findings.append(Finding(
            name="ventricular_tachycardia",
            detected=True,
            confidence=round(vt_conf, 2),
            detail=f"HR {hr} bpm, wide QRS ({qrs_duration} ms)",
        ))

    return findings


# ══════════════════════════════════════════════════════════════════════
# 모듈 3. PR 간격 분석 (PR Interval Analysis)
# ──────────────────────────────────────────────────────────────────────
# - PR > 200ms: 1도 방실차단 (First Degree AV Block)
# - PR < 120ms: 짧은 PR — WPW 증후군(조기 흥분) 가능성
# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [원정아] 실제 ECG 분석 로직으로 교체               ║
# ║  현재는 규칙 기반 템플릿입니다.                            ║
# ║  ML 모델을 추가하려면 이 함수를 수정하세요.                ║
# ╚══════════════════════════════════════════════════════════╝
def _pr_analysis(pr: float) -> list[Finding]:
    """PR 간격을 기준으로 방실전도 이상을 판별합니다."""
    findings = []
    if pr > 200:
        # 1도 방실차단: PR 간격이 200ms를 초과
        findings.append(Finding(
            name="first_degree_av_block",
            detected=True,
            confidence=0.90,
            detail=f"PR interval {pr} ms (> 200 ms)",
        ))
    elif pr < 120:
        # 짧은 PR 간격: WPW 증후군(조기 흥분 증후군) 가능성
        findings.append(Finding(
            name="short_pr_interval",
            detected=True,
            confidence=0.85,
            detail=f"PR interval {pr} ms (< 120 ms) — consider pre-excitation (WPW)",
        ))
    return findings


# ══════════════════════════════════════════════════════════════════════
# 모듈 4. QRS / 각차단 분석 (Bundle Branch Block)
# ──────────────────────────────────────────────────────────────────────
# - QRS >= 120ms인 경우 각차단 의심
# - RBBB (우각차단): V1에서 rsR' 패턴, I/V6에서 넓은 S파
# - LBBB (좌각차단): I, aVL, V5-V6에서 넓은 R파, V1에서 깊은 S파
# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [원정아] 실제 ECG 분석 로직으로 교체               ║
# ║  현재는 규칙 기반 템플릿입니다.                            ║
# ║  ML 모델을 추가하려면 이 함수를 수정하세요.                ║
# ╚══════════════════════════════════════════════════════════╝
def _qrs_analysis(qrs: float, leads: dict) -> list[Finding]:
    """QRS 폭을 기준으로 각차단(RBBB/LBBB)을 판별합니다."""
    findings = []
    if qrs < 120:
        return findings  # QRS < 120ms → 정상, 각차단 아님

    # ── RBBB (우각차단) 점수 판정 ──
    # 기준: QRS >= 120ms, V1에서 R > S (rsR' 패턴), I/V6에서 넓은 S파
    v1 = _lead(leads, "V1")
    lead_i = _lead(leads, "I")
    v6 = _lead(leads, "V6")

    rbbb_score = 0.0
    rbbb_reasons = []
    if qrs >= 120:
        rbbb_score += 0.3                                      # 넓은 QRS (+0.3)
        rbbb_reasons.append(f"QRS {qrs} ms")
    if v1.get("r_amp", 0) > abs(v1.get("s_amp", 0)):
        rbbb_score += 0.3                                      # V1에서 R 우세 (+0.3)
        rbbb_reasons.append("dominant R in V1")
    if abs(lead_i.get("s_amp", 0)) > lead_i.get("r_amp", 0):
        rbbb_score += 0.2                                      # I에서 넓은 S (+0.2)
        rbbb_reasons.append("wide S in lead I")
    if abs(v6.get("s_amp", 0)) > 0.3:
        rbbb_score += 0.1                                      # V6에서 넓은 S (+0.1)
        rbbb_reasons.append("wide S in V6")

    if rbbb_score >= 0.6:  # 0.6점 이상이면 RBBB로 판정
        findings.append(Finding(
            name="right_bundle_branch_block",
            detected=True,
            confidence=round(min(rbbb_score, 0.95), 2),
            detail="; ".join(rbbb_reasons),
        ))

    # ── LBBB (좌각차단) 점수 판정 ──
    # 기준: QRS >= 120ms, I/aVL/V5-V6에서 넓은 R파, V1에서 깊은 S파
    lbbb_score = 0.0
    lbbb_reasons = []
    if qrs >= 120:
        lbbb_score += 0.3                                      # 넓은 QRS (+0.3)
        lbbb_reasons.append(f"QRS {qrs} ms")
    if _r(leads, "I") > 0.5 and _r(leads, "V6") > 0.5:
        lbbb_score += 0.3                                      # I, V6에서 넓은 R (+0.3)
        lbbb_reasons.append("broad R in I and V6")
    if v1.get("r_amp", 0) < abs(v1.get("s_amp", 0)):
        lbbb_score += 0.2                                      # V1에서 깊은 S (+0.2)
        lbbb_reasons.append("deep S in V1")
    if _r(leads, "aVL") > 0.5:
        lbbb_score += 0.1                                      # aVL에서 넓은 R (+0.1)
        lbbb_reasons.append("broad R in aVL")

    # RBBB와 LBBB가 동시에 검출되는 것을 방지 — 더 높은 점수 쪽만 채택
    if lbbb_score >= 0.6 and lbbb_score > rbbb_score:
        findings.append(Finding(
            name="left_bundle_branch_block",
            detected=True,
            confidence=round(min(lbbb_score, 0.95), 2),
            detail="; ".join(lbbb_reasons),
        ))

    return findings


# ══════════════════════════════════════════════════════════════════════
# 모듈 5. 심실비대 분석 (Ventricular Hypertrophy)
# ──────────────────────────────────────────────────────────────────────
# LVH (좌심실비대):
#   - Sokolow-Lyon 기준: S(V1) + R(V5 또는 V6) > 3.5 mV
#   - Cornell 기준: R(aVL) + S(V3) > 2.8 mV(남) 또는 > 2.0 mV(여)
#   - 35세 미만은 전압 기준 특이도가 낮아 신뢰도 보정
# RVH (우심실비대):
#   - R(V1) > 0.7 mV, R/S ratio V1 > 1.0, V5/V6에서 깊은 S파
# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [원정아] 실제 ECG 분석 로직으로 교체               ║
# ║  현재는 규칙 기반 템플릿입니다.                            ║
# ║  ML 모델을 추가하려면 이 함수를 수정하세요.                ║
# ╚══════════════════════════════════════════════════════════╝
def _ventricular_hypertrophy(leads: dict, age: int, sex: str) -> list[Finding]:
    """Sokolow-Lyon / Cornell 기준으로 LVH, R/S ratio 등으로 RVH를 판별합니다."""
    findings = []

    # ── LVH (좌심실비대) 판별 ──
    # Sokolow-Lyon 기준: S(V1) + R(V5 또는 V6) > 3.5 mV
    s_v1 = _abs_s(leads, "V1")       # V1의 S파 절대값
    r_v5 = _r(leads, "V5")           # V5의 R파 진폭
    r_v6 = _r(leads, "V6")           # V6의 R파 진폭
    sokolow = s_v1 + max(r_v5, r_v6)  # Sokolow-Lyon 지수

    # Cornell 기준: R(aVL) + S(V3) > 2.8 mV(남) 또는 > 2.0 mV(여)
    r_avl = _r(leads, "aVL")         # aVL의 R파 진폭
    s_v3 = _abs_s(leads, "V3")       # V3의 S파 절대값
    cornell = r_avl + s_v3            # Cornell 전압 지수
    cornell_threshold = 2.8 if sex == "M" else 2.0  # 성별에 따른 기준값

    lvh_detected = False
    lvh_reasons = []
    lvh_conf = 0.5

    if sokolow > 3.5:
        lvh_detected = True
        lvh_reasons.append(f"Sokolow-Lyon {sokolow:.1f} mV (> 3.5)")
        lvh_conf = max(lvh_conf, 0.80)
    if cornell > cornell_threshold:
        lvh_detected = True
        lvh_reasons.append(f"Cornell {cornell:.1f} mV (> {cornell_threshold})")
        lvh_conf = max(lvh_conf, 0.82)
    if sokolow > 3.5 and cornell > cornell_threshold:
        lvh_conf = 0.92  # 두 기준 모두 충족 시 높은 신뢰도

    # 나이 보정: 35세 미만 젊은 성인은 전압 기준의 특이도가 낮음
    if age < 35 and lvh_detected:
        lvh_conf = max(lvh_conf - 0.15, 0.50)
        lvh_reasons.append("age < 35 — reduced specificity")

    findings.append(Finding(
        name="left_ventricular_hypertrophy",
        detected=lvh_detected,
        confidence=round(lvh_conf, 2),
        detail="; ".join(lvh_reasons) if lvh_reasons else "Voltage criteria not met",
    ))

    # ── RVH (우심실비대) 판별 ──
    # 기준: R(V1) > 0.7 mV, V1 R/S ratio > 1.0, V5/V6에서 깊은 S파
    r_v1 = _r(leads, "V1")
    s_v1_val = abs(_lead(leads, "V1").get("s_amp", 0.01))
    rs_ratio_v1 = r_v1 / max(s_v1_val, 0.01)  # 0으로 나누기 방지

    rvh_detected = False
    rvh_reasons = []
    rvh_conf = 0.5

    if r_v1 > 0.7:
        rvh_detected = True
        rvh_reasons.append(f"R(V1) = {r_v1:.1f} mV (> 0.7)")
        rvh_conf = max(rvh_conf, 0.75)
    if rs_ratio_v1 > 1.0:
        rvh_detected = True
        rvh_reasons.append(f"R/S ratio V1 = {rs_ratio_v1:.1f} (> 1.0)")
        rvh_conf = max(rvh_conf, 0.78)
    # V5/V6에서 깊은 S파 → 우심실 과부하 시사
    if _abs_s(leads, "V5") > 0.7 or _abs_s(leads, "V6") > 0.7:
        if rvh_detected:
            rvh_conf = min(rvh_conf + 0.10, 0.95)
            rvh_reasons.append("deep S in V5/V6")

    findings.append(Finding(
        name="right_ventricular_hypertrophy",
        detected=rvh_detected,
        confidence=round(rvh_conf if rvh_detected else 0.90, 2),
        detail="; ".join(rvh_reasons) if rvh_reasons else "No RVH criteria met",
    ))

    return findings


# ══════════════════════════════════════════════════════════════════════
# 모듈 6. ST 분절 분석 (ST Segment Analysis)
# ──────────────────────────────────────────────────────────────────────
# ST 상승(elevation): >= 0.1 mV (1mm) → 급성 심근경색 가능성
# ST 하강(depression): <= -0.1 mV → 심근 허혈 가능성
# 관상동맥 영역별 매핑: 전벽(LAD), 측벽(LCx), 하벽(RCA)
# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [원정아] 실제 ECG 분석 로직으로 교체               ║
# ║  현재는 규칙 기반 템플릿입니다.                            ║
# ║  ML 모델을 추가하려면 이 함수를 수정하세요.                ║
# ╚══════════════════════════════════════════════════════════╝
_ST_ELEVATION_THRESHOLD = 0.1     # ST 상승 기준값: 0.1 mV (ECG 용지 1mm)
_ST_DEPRESSION_THRESHOLD = -0.1   # ST 하강 기준값: -0.1 mV

def _st_analysis(leads: dict) -> list[Finding]:
    """12개 리드의 ST 편위를 분석하여 상승/하강을 판별하고 관상동맥 영역을 매핑합니다."""
    findings = []

    elevation_leads: list[str] = []     # ST 상승이 관찰된 리드들
    depression_leads: list[str] = []    # ST 하강이 관찰된 리드들

    # 각 리드의 ST 편위를 기준값과 비교
    for name in ALL_LEADS:
        st = _lead(leads, name).get("st_dev", 0.0)
        if st >= _ST_ELEVATION_THRESHOLD:
            elevation_leads.append(f"{name}(+{st:.2f} mV)")
        elif st <= _ST_DEPRESSION_THRESHOLD:
            depression_leads.append(f"{name}({st:.2f} mV)")

    # ── ST 상승 판정 ──
    if elevation_leads:
        # 어떤 관상동맥 영역에 해당하는지 분류 (전벽/측벽/하벽)
        territory = _classify_territory(
            [l.split("(")[0] for l in elevation_leads]
        )
        # 영향받는 리드 수가 많을수록 신뢰도 상승
        conf = min(0.70 + len(elevation_leads) * 0.05, 0.95)
        findings.append(Finding(
            name="st_elevation",
            detected=True,
            confidence=round(conf, 2),
            detail=f"Leads: {', '.join(elevation_leads)}. Territory: {territory}",
        ))
    else:
        findings.append(Finding(
            name="st_elevation",
            detected=False,
            confidence=0.92,
            detail="No significant ST elevation",
        ))

    # ── ST 하강 판정 ──
    if depression_leads:
        conf = min(0.70 + len(depression_leads) * 0.05, 0.95)
        findings.append(Finding(
            name="st_depression",
            detected=True,
            confidence=round(conf, 2),
            detail=f"Leads: {', '.join(depression_leads)}",
        ))

    return findings


def _classify_territory(lead_names: list[str]) -> str:
    """ST 변화가 관찰된 리드들을 관상동맥 영역(전벽/측벽/하벽)으로 분류합니다."""
    anterior = set(lead_names) & set(ANTERIOR_LEADS)   # 전벽 (LAD)
    lateral = set(lead_names) & set(LATERAL_LEADS)     # 측벽 (LCx)
    inferior = set(lead_names) & set(INFERIOR_LEADS)   # 하벽 (RCA)

    parts = []
    if anterior:
        parts.append("anterior")
    if lateral:
        parts.append("lateral")
    if inferior:
        parts.append("inferior")
    return ", ".join(parts) if parts else "non-specific"


# ══════════════════════════════════════════════════════════════════════
# 모듈 7. QT/QTc 간격 분석 (QT Interval Analysis)
# ──────────────────────────────────────────────────────────────────────
# Bazett 공식: QTc = QT / sqrt(RR초)
# - 남성 QTc > 450ms: QT 연장
# - 여성 QTc > 460ms: QT 연장
# - QTc > 500ms: 위험한 QT 연장 (Torsades de Pointes 위험)
# - QTc < 340ms: 짧은 QT 증후군
# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [원정아] 실제 ECG 분석 로직으로 교체               ║
# ║  현재는 규칙 기반 템플릿입니다.                            ║
# ║  ML 모델을 추가하려면 이 함수를 수정하세요.                ║
# ╚══════════════════════════════════════════════════════════╝
def _qt_analysis(qt: float, hr: float, sex: str) -> list[Finding]:
    """Bazett 공식으로 QTc를 계산하고 연장/단축 여부를 판별합니다."""
    findings = []
    rr_sec = 60.0 / hr                # RR 간격을 초 단위로 변환
    qtc = qt / math.sqrt(rr_sec)       # Bazett 공식: QTc = QT / sqrt(RR초)

    # 기준값: 남성 > 450ms, 여성 > 460ms이면 QT 연장
    # 500ms 초과: 위험한 QT 연장 (Torsades de Pointes 부정맥 위험)
    threshold = 450 if sex == "M" else 460
    short_threshold = 340  # 짧은 QT 증후군 기준값

    if qtc > 500:
        # 위험한 QT 연장 — TdP (Torsades de Pointes) 위험
        findings.append(Finding(
            name="qt_prolongation",
            detected=True,
            confidence=0.93,
            detail=f"QTc = {qtc:.0f} ms (> 500 ms) — critically prolonged, TdP risk",
        ))
    elif qtc > threshold:
        # QT 연장 (성별 기준 초과)
        findings.append(Finding(
            name="qt_prolongation",
            detected=True,
            confidence=0.85,
            detail=f"QTc = {qtc:.0f} ms (> {threshold} ms for {'male' if sex == 'M' else 'female'})",
        ))
    elif qtc < short_threshold:
        # 짧은 QT 증후군 — 돌연사 위험과 관련
        findings.append(Finding(
            name="short_qt",
            detected=True,
            confidence=0.80,
            detail=f"QTc = {qtc:.0f} ms (< 340 ms) — short QT syndrome concern",
        ))
    else:
        # QTc 정상 범위
        findings.append(Finding(
            name="qt_interval_normal",
            detected=True,
            confidence=0.90,
            detail=f"QTc = {qtc:.0f} ms (normal)",
        ))

    return findings


# ══════════════════════════════════════════════════════════════════════
# 모듈 8. 전기축 편위 분석 (Axis Deviation)
# ──────────────────────────────────────────────────────────────────────
# I 유도와 aVF 유도의 순 진폭(R + S)으로 전기축 방향을 추정합니다.
# - I(+) aVF(+): 정상축 (0 ~ +90도)
# - I(+) aVF(-): 좌축편위 (-30 ~ -90도) → 좌전속지차단 등
# - I(-) aVF(+): 우축편위 (+90 ~ +180도) → 우심실비대, 폐질환 등
# - I(-) aVF(-): 극단축편위 (northwest axis) → 심실 기원 리듬 등
# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [원정아] 실제 ECG 분석 로직으로 교체               ║
# ║  현재는 규칙 기반 템플릿입니다.                            ║
# ║  ML 모델을 추가하려면 이 함수를 수정하세요.                ║
# ╚══════════════════════════════════════════════════════════╝
def _axis_analysis(leads: dict) -> list[Finding]:
    """I 유도와 aVF 유도의 순 진폭으로 전기축 방향을 추정합니다."""
    findings = []
    # I 유도와 aVF 유도의 순 진폭(net amplitude) 계산: R파 + S파
    net_i = _r(leads, "I") + _lead(leads, "I").get("s_amp", 0.0)
    net_avf = _r(leads, "aVF") + _lead(leads, "aVF").get("s_amp", 0.0)

    if net_i > 0 and net_avf > 0:
        # 정상축: 0 ~ +90도
        axis_range = "normal (0 to +90)"
    elif net_i > 0 and net_avf < 0:
        # 좌축편위: -30 ~ -90도 (좌전속지차단, 하벽 심근경색 등)
        axis_range = "left axis deviation (-30 to -90)"
        findings.append(Finding(
            name="left_axis_deviation",
            detected=True,
            confidence=0.82,
            detail=f"Net I = {net_i:.2f}, Net aVF = {net_avf:.2f}",
        ))
        return findings
    elif net_i < 0 and net_avf > 0:
        # 우축편위: +90 ~ +180도 (우심실비대, 폐질환 등)
        axis_range = "right axis deviation (+90 to +180)"
        findings.append(Finding(
            name="right_axis_deviation",
            detected=True,
            confidence=0.82,
            detail=f"Net I = {net_i:.2f}, Net aVF = {net_avf:.2f}",
        ))
        return findings
    else:
        # 극단축편위 (northwest axis): 심실 기원 리듬, 인공심박동기 등
        axis_range = "extreme/northwest axis"
        findings.append(Finding(
            name="extreme_axis_deviation",
            detected=True,
            confidence=0.78,
            detail=f"Net I = {net_i:.2f}, Net aVF = {net_avf:.2f}",
        ))
        return findings

    findings.append(Finding(
        name="axis_normal",
        detected=True,
        confidence=0.88,
        detail=axis_range,
    ))
    return findings
