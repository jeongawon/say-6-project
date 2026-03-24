"""폐부종 (Edema) — 양측 대칭성 + butterfly 패턴 + CTR 교차"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold


def analyze(input: ClinicalLogicInput) -> dict:
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

    # 양측 대칭성 분석 (폐 면적비로 대체 — 실제로는 intensity 필요)
    ratio = a.lung_area_ratio
    # 대칭 점수: 1에 가까울수록 대칭
    symmetry_score = 1.0 - abs(1.0 - ratio) if ratio > 0 else 0.0
    bilateral_symmetric = symmetry_score > 0.85

    if bilateral_symmetric:
        evidence.append(f"양측 대칭 (symmetry score {symmetry_score:.2f})")
        location = "bilateral"
    else:
        evidence.append(f"비대칭 (symmetry score {symmetry_score:.2f})")
        location = "unilateral"

    # Butterfly 패턴은 폐 마스크 내 intensity 분석이 필요 — 현재 미구현
    # DenseNet 확률이 높으면 butterfly 양성으로 간주
    butterfly = d.Edema > 0.75
    if butterfly:
        evidence.append("Butterfly 패턴 의심 (DenseNet 고확률)")

    # 동반 소견 교차
    confidence = "medium"
    if bilateral_symmetric and a.ctr > 0.50:
        # 양측 대칭 + 심비대 → CHF 폐부종
        cp_blunted = (a.right_cp_status == "blunted") or (a.left_cp_status == "blunted")
        if cp_blunted:
            confidence = "high"
            evidence.append(f"양측 대칭 + CTR {a.ctr:.4f} + 흉수 → CHF 폐부종")
            recommendation = "이뇨제 + 심초음파 권장"
        else:
            confidence = "high"
            evidence.append(f"양측 대칭 + CTR {a.ctr:.4f} → CHF 폐부종 의심")
            recommendation = "BNP + 심초음파 권장"
    elif bilateral_symmetric and a.ctr <= 0.50:
        confidence = "medium"
        evidence.append(f"양측 대칭 + 정상 심장 → 비심인성 부종(ARDS 등) 가능")
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
            "symmetry_score": round(symmetry_score, 2),
            "butterfly": butterfly,
            "ctr": round(a.ctr, 4),
            "bilateral_symmetric": bilateral_symmetric,
        },
        "location": location,
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
