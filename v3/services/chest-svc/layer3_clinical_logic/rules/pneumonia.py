"""폐렴 (Pneumonia) — 5단계 임상정보 교차 감별.
영상 단독 판단 불가. 반드시 임상 정보와 교차하여 판정.
Consolidation + 다른 Rule 결과에 의존 → 가장 마지막에 실행.
"""

from ..models import ClinicalLogicInput
from thresholds import get_threshold


def analyze(input: ClinicalLogicInput, other_results: dict = None) -> dict:
    # ── confidence 판정 기준 (14개 Rule 공통) ──────────────────
    # "high"   — 2개 이상 독립 소스 일치 (CTR+DenseNet+YOLO 등)
    # "medium" — 1개 소스 양성 + 합리적 근거
    # "low"    — 1개 소스만 양성 + 근거 약함 (의사 확인 필요)
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Pneumonia")
    pi = input.patient_info

    detected = False
    evidence = []
    severity = None
    location = None
    alert = False
    recommendation = None
    probability = "low"

    # === Step 1: Consolidation Logic 결과 확인 ===
    consolidation_detected = False
    consolidation_lobe = None
    if other_results:
        consol = other_results.get("Consolidation", {})
        consolidation_detected = consol.get("detected", False)
        consolidation_lobe = consol.get("quantitative", {}).get("lobe")
        if consolidation_detected:
            evidence.append("경화 소견 확인")
            location = consol.get("location")

    # === Step 2: 환자 정보 파싱 ===
    fever = None
    cough = None
    tachypnea = None

    if pi:
        if pi.temperature is not None:
            fever = pi.temperature > 38.0
            if fever:
                evidence.append(f"체온 {pi.temperature}C (발열)")

        if pi.chief_complaint:
            cc = pi.chief_complaint.lower()
            cough = ("기침" in cc or "cough" in cc)
            if cough:
                evidence.append("기침 (+)")

        if pi.respiratory_rate is not None:
            tachypnea = pi.respiratory_rate > 20
            if tachypnea:
                evidence.append(f"호흡수 {pi.respiratory_rate}/min (빈호흡)")

    # === Step 3: 이전 검사 결과 반영 ===
    wbc_elevated = None
    crp_elevated = None

    for pr in input.prior_results:
        if pr.modal == "lab":
            wbc = pr.findings.get("WBC")
            crp = pr.findings.get("CRP")
            if wbc is not None:
                wbc_elevated = wbc > 11000
                if wbc_elevated:
                    evidence.append(f"WBC {wbc} (상승)")
            if crp is not None:
                crp_elevated = crp > 5.0
                if crp_elevated:
                    evidence.append(f"CRP {crp} (상승)")

    # === Step 4: 감별 Rule ===
    if consolidation_detected and fever and cough:
        detected = True
        probability = "high"
        evidence.append("경화 + 발열 + 기침 → 감염성 폐렴 의심")
        severity = "moderate"

    elif consolidation_detected and fever and wbc_elevated:
        detected = True
        probability = "high"
        evidence.append("경화 + 발열 + WBC 상승 → 세균성 폐렴 가능성 높음")
        severity = "moderate"

    elif consolidation_detected and (fever is None or not fever) and a.ctr > 0.50:
        detected = False
        probability = "low"
        evidence.append(f"경화 + 정상 체온 + CTR {a.ctr:.4f} → 심인성 폐부종 가능 (폐렴 아닐 수 있음)")

    elif consolidation_detected:
        detected = True
        probability = "low"
        evidence.append("경화 확인, 폐렴 감별 위해 CBC/CRP 권장")
        recommendation = "CBC/CRP/Blood Culture 시행"
        severity = "mild"

    elif d.Pneumonia > threshold:
        detected = True
        probability = "low"
        evidence.append(f"DenseNet Pneumonia: {d.Pneumonia:.2f}, 경미한 폐렴 가능, 임상 상관 필요")
        severity = "mild"

    # === Step 5: ECG 결과 교차 ===
    ecg_normal = None
    for pr in input.prior_results:
        if pr.modal == "ecg":
            summary = pr.summary.lower()
            ecg_normal = ("정상" in summary or "normal" in summary or
                          "stemi 아님" in summary or "nsr" in summary)
            if ecg_normal and consolidation_detected and detected:
                evidence.append("ECG 정상 → 심인성 배제 → 감염성 폐렴 가능성 상향")
                if probability == "low":
                    probability = "medium"

    if not detected:
        evidence.append("폐렴 소견 없음" if not evidence else evidence[-1])
        return {
            "finding": "Pneumonia",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": None,
            "severity": None,
            "recommendation": recommendation,
            "alert": False,
        }

    confidence = probability  # high/medium/low 그대로 매핑

    return {
        "finding": "Pneumonia",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "consolidation_lobe": consolidation_lobe,
            "fever": fever,
            "cough": cough,
            "tachypnea": tachypnea,
            "wbc_elevated": wbc_elevated,
            "crp_elevated": crp_elevated,
            "ecg_normal": ecg_normal,
            "probability": probability,
        },
        "location": location,
        "severity": severity,
        "recommendation": recommendation or ("항생제 치료 시작 고려" if probability == "high" else None),
        "alert": alert,
    }
