"""폐부종 (Edema) — 양측 대칭성 + butterfly 패턴 + CTR 교차"""

from ..models import ClinicalLogicInput
from thresholds import get_threshold, EDEMA_SYMMETRY, EDEMA_BILATERAL_DENSENET


def analyze(input: ClinicalLogicInput, other_results: dict = None) -> dict:
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Edema")

    detected = False
    evidence = []
    severity = None
    location = None
    alert = False
    recommendation = None

    # DenseNet 확률 기반 1차 의심
    if d.Edema > threshold:
        detected = True
        evidence.append(f"DenseNet Edema: {d.Edema:.2f}")

    if not detected:
        evidence.append("폐부종 소견 없음")
        return {
            "finding": "Edema",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": None,
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    # ── Atelectasis 동반 시 대칭성 보정 ──
    # 무기폐가 존재하면 한쪽 폐 면적이 줄어들어
    # lung_area_ratio 기반 대칭성 판단이 부정확해진다.
    # 이 경우 DenseNet 확률만으로 양측/편측을 추정한다.
    atelectasis_present = False
    if other_results:
        atelectasis_present = other_results.get(
            "Atelectasis", {}
        ).get("detected", False)

    if atelectasis_present:
        # 무기폐 동반 → 폐 면적 비율 대칭성 판단 불가
        symmetry_score = None
        if d.Edema > EDEMA_BILATERAL_DENSENET:
            # 심인성 폐부종은 대부분 양측성이므로, 고확률이면 bilateral 가정
            bilateral_symmetric = True
            location = "bilateral"
            evidence.append(
                "무기폐(Atelectasis) 동반 → 면적 기반 대칭성 판단 불가, "
                f"DenseNet {d.Edema:.2f} > {EDEMA_BILATERAL_DENSENET} → 양측(bilateral) 추정"
            )
        else:
            # DenseNet 확률이 낮으면 위치를 특정할 수 없음
            bilateral_symmetric = False
            location = "indeterminate"
            evidence.append(
                "무기폐(Atelectasis) 동반 → 면적 기반 대칭성 판단 불가, "
                f"DenseNet {d.Edema:.2f} ≤ {EDEMA_BILATERAL_DENSENET} → 위치 미확정(indeterminate)"
            )
    else:
        # 무기폐 없음 → 기존 대칭성 로직 유지
        ratio = a.lung_area_ratio
        symmetry_score = 1.0 - abs(1.0 - ratio) if ratio > 0 else 0.0
        bilateral_symmetric = symmetry_score > EDEMA_SYMMETRY

        if bilateral_symmetric:
            evidence.append(f"양측 대칭 (symmetry score {symmetry_score:.2f})")
            location = "bilateral"
        else:
            evidence.append(f"비대칭 (symmetry score {symmetry_score:.2f})")
            location = "unilateral"

    # Butterfly 패턴
    butterfly = d.Edema > 0.75
    if butterfly:
        evidence.append("Butterfly 패턴 의심 (DenseNet 고확률)")

    # SpO2 교차 검증 — 폐부종이면 SpO2 저하 동반 가능
    if input.patient_info and input.patient_info.spo2:
        spo2 = input.patient_info.spo2
        if spo2 < 92:
            evidence.append(f"SpO2 {spo2}% → 저산소증 동반 (폐부종 부합)")
            if severity == "mild":
                severity = "moderate"
        elif spo2 < 95:
            evidence.append(f"SpO2 {spo2}% → 경미한 저산소증")

    # 동반 소견 교차
    confidence = "medium"
    if bilateral_symmetric and a.ctr > 0.50:
        cp_blunted = (a.right_cp_status == "blunted") or (a.left_cp_status == "blunted")
        if cp_blunted:
            confidence = "high"
            evidence.append(f"양측 대칭 + CTR {a.ctr:.4f} + 흉수 -> CHF 폐부종")
            recommendation = "이뇨제 + 심초음파 권장"
        else:
            confidence = "high"
            evidence.append(f"양측 대칭 + CTR {a.ctr:.4f} -> CHF 폐부종 의심")
            recommendation = "BNP + 심초음파 권장"
    elif bilateral_symmetric and a.ctr <= 0.50:
        confidence = "medium"
        evidence.append(f"양측 대칭 + 정상 심장 -> 비심인성 부종(ARDS 등) 가능")
        recommendation = "임상 상관 필요, ARDS 감별"

    # severity
    if d.Edema > 0.80:
        severity = "severe"
    elif d.Edema > 0.60:
        severity = "moderate"
    else:
        severity = "mild"

    return {
        "finding": "Edema",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "symmetry_score": round(symmetry_score, 2) if symmetry_score is not None else None,
            "butterfly": butterfly,
            "ctr": round(a.ctr, 4),
            "bilateral_symmetric": bilateral_symmetric,
        },
        "location": location,
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
