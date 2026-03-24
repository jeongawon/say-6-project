"""
Clinical Logic Engine — 후방 호환 래퍼
기존 ChestModal에서 호출하는 인터페이스를 유지하면서 새 engine.py로 위임

사용법 (레거시):
    engine = ClinicalEngine()
    findings = engine.analyze(anatomy_result, densenet_preds, yolo_detections)

사용법 (신규 — 권장):
    from layer3_clinical_logic.engine import run_clinical_logic
    from layer3_clinical_logic.models import ClinicalLogicInput
    result = run_clinical_logic(input)
"""

from .models import (
    AnatomyMeasurements,
    DenseNetPredictions,
    YoloDetection,
    PatientInfo,
    PriorResult,
    ClinicalLogicInput,
)
from .engine import run_clinical_logic


class ClinicalEngine:
    """전체 Clinical Logic 실행 엔진 (래퍼)"""

    def analyze(self, anatomy_result: dict, densenet_preds: dict = None,
                yolo_detections: list = None, patient_info: dict = None,
                prior_results: list = None) -> dict:
        """
        Layer 1/2 결과를 받아 Clinical Logic 실행

        Args:
            anatomy_result: Layer 1 출력 dict (measurements, view, age_pred, sex_pred)
            densenet_preds: {질환명: 확률} dict
            yolo_detections: [{class_name, bbox, confidence, lobe}, ...]
            patient_info: {age, sex, chief_complaint, temperature, ...}
            prior_results: [{modal, summary, findings}, ...]

        Returns:
            run_clinical_logic() 결과 dict
        """
        # Layer 1 결과 → AnatomyMeasurements 변환
        m = anatomy_result.get("measurements", {})
        anatomy = AnatomyMeasurements(
            ctr=m.get("ctr", 0.0),
            ctr_status=m.get("ctr_status", "normal"),
            heart_width_px=m.get("heart_width_px", 0),
            thorax_width_px=m.get("thorax_width_px", 0),
            heart_area_px2=m.get("heart_area_px", 0),
            right_lung_area_px2=m.get("right_lung_area_px", 0),
            left_lung_area_px2=m.get("left_lung_area_px", 0),
            lung_area_ratio=m.get("lung_area_ratio", 0.9),
            total_lung_area_px2=m.get("total_lung_area_px", 0),
            view=anatomy_result.get("view", "PA"),
            predicted_age=anatomy_result.get("age_pred"),
            predicted_sex=anatomy_result.get("sex_pred"),
        )

        # DenseNet 결과 → DenseNetPredictions 변환
        densenet = DenseNetPredictions()
        if densenet_preds:
            for key, val in densenet_preds.items():
                attr_name = key.replace(" ", "_")
                if hasattr(densenet, attr_name):
                    setattr(densenet, attr_name, val)

        # YOLO 결과 변환
        yolo_list = []
        if yolo_detections:
            for det in yolo_detections:
                yolo_list.append(YoloDetection(
                    class_name=det.get("class_name", det.get("class", "")),
                    bbox=det.get("bbox", [0, 0, 0, 0]),
                    confidence=det.get("confidence", 0.0),
                    lobe=det.get("lobe"),
                ))

        # PatientInfo 변환
        pi = None
        if patient_info:
            pi = PatientInfo(**{k: v for k, v in patient_info.items()
                                if k in PatientInfo.__dataclass_fields__})

        # PriorResult 변환
        pr_list = []
        if prior_results:
            for pr in prior_results:
                pr_list.append(PriorResult(
                    modal=pr.get("modal", ""),
                    summary=pr.get("summary", ""),
                    findings=pr.get("findings", {}),
                ))

        # 통합 입력 생성 + 실행
        cli_input = ClinicalLogicInput(
            anatomy=anatomy,
            densenet=densenet,
            yolo_detections=yolo_list,
            patient_info=pi,
            prior_results=pr_list,
        )

        return run_clinical_logic(cli_input)
