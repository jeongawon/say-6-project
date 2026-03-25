"""
6-stage sequential pipeline: seg -> densenet -> yolo -> clinical -> rag -> report.

입력: PredictRequest (image base64 + patient info)
출력: PredictResponse (findings + summary + report)

이 파일이 chest-svc의 핵심 오케스트레이터입니다.
6단계 파이프라인의 실행 순서와 데이터 흐름을 제어합니다.
"""

import io
import base64
import logging
import time

from PIL import Image

# ── 각 Layer 모듈 임포트 ──────────────────────────────────────
from layer1_segmentation.model import run_segmentation      # Stage 1: UNet 세그멘테이션
from layer2_detection.densenet import run_densenet           # Stage 2a: DenseNet 14-질환 분류
from layer2_detection.yolo import run_yolov8                 # Stage 2b: YOLOv8 병변 탐지
from layer3_clinical_logic.engine import run_clinical_logic  # Stage 3: 임상 로직 엔진

# ── 데이터 모델 임포트 (Layer 간 데이터 전달용) ────────────────
from layer3_clinical_logic.models import (
    AnatomyMeasurements,                    # Layer 1 출력 구조체
    DenseNetPredictions,                    # Layer 2a 출력 구조체
    YoloDetection,                          # Layer 2b 개별 탐지 결과
    PatientInfo as ClinicalPatientInfo,     # 환자 정보 (임상 로직용)
    PriorResult,                            # 이전 검사 결과 (ECG, 혈액 등)
    ClinicalLogicInput,                     # Layer 3 전체 입력 구조체
)
from report.chest_report_generator import ChestReportGenerator  # Stage 5+6: 소견서 생성기

logger = logging.getLogger(__name__)


# ── 유틸리티 함수: 이미지 디코딩 ───────────────────────────────
def _decode_image(image_b64: str) -> Image.Image:
    """base64 -> RGB PIL Image. 오케스트레이터가 보낸 base64 이미지를 PIL로 변환."""
    image_bytes = base64.b64decode(image_b64)
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


# ── 유틸리티 함수: Layer 간 데이터 변환 ────────────────────────
# 아래 _build_* 함수들은 각 Layer의 dict 출력을 Layer 3 입력 데이터클래스로 변환합니다.
# Layer 1/2의 출력 형식이 바뀌면 이 함수들도 함께 수정해야 합니다.

def _build_anatomy(seg_result: dict) -> AnatomyMeasurements:
    """Layer 1 결과 -> AnatomyMeasurements dataclass."""
    m = seg_result.get("measurements", {})
    return AnatomyMeasurements(
        ctr=m.get("ctr", 0.0),
        ctr_status=m.get("ctr_status", "normal"),
        heart_width_px=m.get("heart_width_px", 0),
        thorax_width_px=m.get("thorax_width_px", 0),
        heart_area_px2=m.get("heart_area_px", 0),
        right_lung_area_px2=m.get("right_lung_area_px", 0),
        left_lung_area_px2=m.get("left_lung_area_px", 0),
        lung_area_ratio=m.get("lung_area_ratio", 0.9),
        total_lung_area_px2=m.get("right_lung_area_px", 0) + m.get("left_lung_area_px", 0),
        view=seg_result.get("view", "PA"),
        predicted_age=seg_result.get("age_pred"),
        predicted_sex=seg_result.get("sex_pred"),
    )


def _build_densenet_preds(densenet_result: dict) -> DenseNetPredictions:
    """Layer 2a 결과 -> DenseNetPredictions dataclass."""
    preds = DenseNetPredictions()
    for pred in densenet_result.get("predictions", []):
        disease = pred["disease"]
        prob = pred["probability"]
        attr_name = disease.replace(" ", "_")
        if hasattr(preds, attr_name):
            setattr(preds, attr_name, prob)
    return preds


def _build_yolo_detections(yolo_result: dict) -> list[YoloDetection]:
    """Layer 2b 결과 -> YoloDetection list."""
    detections = []
    for det in yolo_result.get("detections", []):
        bbox_raw = det.get("bbox", [0, 0, 0, 0])
        # bbox가 배열이면 그대로, dict면 변환
        if isinstance(bbox_raw, list):
            bbox_list = [int(v) for v in bbox_raw]
        else:
            bbox_list = [int(bbox_raw.get("x1",0)), int(bbox_raw.get("y1",0)),
                         int(bbox_raw.get("x2",0)), int(bbox_raw.get("y2",0))]
        detections.append(YoloDetection(
            class_name=det.get("class_name", det.get("class", "")),
            bbox=bbox_list,
            confidence=det.get("confidence", 0.0),
            lobe=det.get("lobe"),
        ))
    return detections


def _build_clinical_patient_info(patient_info: dict) -> ClinicalPatientInfo:
    """PredictRequest.patient_info -> ClinicalPatientInfo."""
    return ClinicalPatientInfo(
        age=patient_info.get("age"),
        sex=patient_info.get("sex"),
        chief_complaint=patient_info.get("chief_complaint"),
        temperature=patient_info.get("temperature"),
        heart_rate=patient_info.get("heart_rate"),
        blood_pressure=patient_info.get("blood_pressure"),
        spo2=patient_info.get("spo2"),
        respiratory_rate=patient_info.get("respiratory_rate"),
    )


def _build_prior_results(context: dict) -> list[PriorResult]:
    """PredictRequest.context -> PriorResult list."""
    prior = []
    for pr in context.get("prior_results", []):
        prior.append(PriorResult(
            modal=pr.get("modal", ""),
            summary=pr.get("summary", ""),
            findings=pr.get("findings", {}),
        ))
    return prior


# ── Stage 4 유틸리티: 교차검증 결과 요약 ───────────────────────
def _build_cross_validation_summary(cross_val: dict) -> dict:
    """
    교차 검증 결과를 요약 형태로 변환.
    DenseNet, YOLO, Clinical Logic 3개 소스의 일치도를 기준으로
    high/medium/low 그룹으로 분류합니다.
    """
    high = []
    medium = []
    low = []
    flags = []
    for name, cv in cross_val.items():
        conf = cv.get("confidence", "none")
        if conf == "high":
            high.append(name)
        elif conf == "medium":
            medium.append(name)
        elif conf == "low":
            low.append(name)
        if cv.get("flag"):
            flags.append(f"{name}: {cv['flag']}")
    return {
        "high_agreement": high,
        "medium_agreement": medium,
        "low_agreement": low,
        "flags": flags,
    }


# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [박현우] 파이프라인 순서/단계 조정이 필요하면       ║
# ║  이 함수를 수정하세요. 현재는 v2에서 마이그레이션된         ║
# ║  6-stage 순차 실행 구조입니다.                             ║
# ║  - 단계 추가: 새 Stage를 적절한 위치에 삽입                ║
# ║  - 단계 제거: 해당 Stage 코드를 주석 처리 또는 삭제        ║
# ║  - 병렬 실행: Stage 2a/2b는 독립적이므로 asyncio로 병렬화  ║
# ║    가능 (성능 최적화 시 고려)                               ║
# ╚══════════════════════════════════════════════════════════╝
async def run_pipeline(
    models: dict,
    image_b64: str,
    patient_info: dict,
    context: dict,
    report_generator: ChestReportGenerator,
) -> dict:
    """
    6-stage 순차 파이프라인 실행.

    Args:
        models: {"unet": ort session, "densenet": ort session, "yolo": ort session}
        image_b64: base64 encoded chest X-ray image
        patient_info: dict with age, sex, chief_complaint, history, etc.
        context: dict with prior_results, etc.
        report_generator: ChestReportGenerator instance

    Returns:
        dict: {findings, summary, report, metadata}
    """
    t_start = time.time()
    timings = {}

    # ══════════════════════════════════════════════════════════
    # Stage 1: 세그멘테이션 (UNet ONNX)
    # ──────────────────────────────────────────────────────────
    # base64 이미지 디코딩 -> UNet 추론 -> 마스크 생성
    # 출력: CTR(심흉비), CP angle, 폐면적비, 촬영 뷰, 나이/성별 예측
    # TODO: [박현우] UNet 모델 교체 시 layer1_segmentation/model.py 수정
    # ══════════════════════════════════════════════════════════
    t0 = time.time()
    pil_image = _decode_image(image_b64)
    seg_result = run_segmentation(models["unet"], pil_image)
    timings["segmentation"] = round(time.time() - t0, 4)
    logger.info(f"Stage 1 (seg): CTR={seg_result['measurements']['ctr']:.4f}, "
                f"view={seg_result['view']}, {timings['segmentation']}s")

    # ══════════════════════════════════════════════════════════
    # Stage 2a: DenseNet-121 14-질환 분류
    # ──────────────────────────────────────────────────────────
    # CheXpert 표준 14개 질환에 대한 확률 출력
    # 0.5 이상이면 양성(pos), 미만이면 음성(neg)
    # TODO: [박현우] DenseNet 모델 교체 시 layer2_detection/densenet.py 수정
    # ══════════════════════════════════════════════════════════
    t0 = time.time()
    densenet_result = run_densenet(models["densenet"], pil_image)
    timings["densenet"] = round(time.time() - t0, 4)
    pos_count = sum(1 for p in densenet_result["predictions"] if p["status"] == "pos")
    logger.info(f"Stage 2a (densenet): {pos_count} positive findings, {timings['densenet']}s")

    # ══════════════════════════════════════════════════════════
    # Stage 2b: YOLOv8 병변 바운딩박스 탐지
    # ──────────────────────────────────────────────────────────
    # VinDr-CXR 19 클래스 물체 탐지 (위치 + 신뢰도)
    # NMS 적용 후 confidence > 0.25인 탐지만 반환
    # TODO: [박현우] YOLOv8 모델 교체 시 layer2_detection/yolo.py 수정
    # ══════════════════════════════════════════════════════════
    t0 = time.time()
    yolo_result = run_yolov8(models["yolo"], pil_image)
    timings["yolo"] = round(time.time() - t0, 4)
    logger.info(f"Stage 2b (yolo): {len(yolo_result['detections'])} detections, {timings['yolo']}s")

    # ══════════════════════════════════════════════════════════
    # Stage 3: 임상 로직 엔진
    # ──────────────────────────────────────────────────────────
    # Layer 1/2 결과를 종합하여 14개 질환별 규칙 기반 판정 수행
    # 교차검증(DenseNet vs YOLO vs Logic) + 감별진단 + 위험도 분류
    # TODO: [박현우] 임상 로직 수정 시 layer3_clinical_logic/rules/*.py
    # TODO: [박현우] 감별진단 패턴 추가 시 layer3_clinical_logic/differential.py
    # ══════════════════════════════════════════════════════════
    t0 = time.time()

    # Layer 1/2 결과를 Layer 3 입력 데이터클래스로 변환
    anatomy = _build_anatomy(seg_result)
    densenet_preds = _build_densenet_preds(densenet_result)
    yolo_dets = _build_yolo_detections(yolo_result)
    clinical_pi = _build_clinical_patient_info(patient_info)
    prior_results = _build_prior_results(context)

    # 임상 로직 엔진에 전달할 통합 입력 구성
    clinical_input = ClinicalLogicInput(
        anatomy=anatomy,
        densenet=densenet_preds,
        yolo_detections=yolo_dets,
        patient_info=clinical_pi,
        prior_results=prior_results,
    )
    clinical_result = run_clinical_logic(clinical_input)
    timings["clinical_logic"] = round(time.time() - t0, 4)
    logger.info(f"Stage 3 (clinical): {clinical_result['detected_count']} detected, "
                f"risk={clinical_result['risk_level']}, {timings['clinical_logic']}s")

    # ══════════════════════════════════════════════════════════
    # Stage 4: 교차검증 요약
    # ──────────────────────────────────────────────────────────
    # 3개 소스(DenseNet, YOLO, Clinical Logic)의 일치도를
    # high/medium/low로 그룹화하여 소견서 생성에 활용
    # ══════════════════════════════════════════════════════════
    cv_summary = _build_cross_validation_summary(clinical_result.get("cross_validation", {}))

    # ══════════════════════════════════════════════════════════
    # Stage 5+6: RAG 유사 케이스 검색 + Bedrock 소견서 생성
    # ──────────────────────────────────────────────────────────
    # 1) rag-svc에서 유사 판독문 Top-3 검색 (미연결 시 skip)
    # 2) 전체 분석 결과를 프롬프트로 조립
    # 3) Bedrock Claude 호출 -> 전문 소견서 생성
    # TODO: [박현우] 소견서 프롬프트 수정 시 report/prompt_templates.py
    # ══════════════════════════════════════════════════════════
    t0 = time.time()

    # DenseNet 결과를 소견서 생성기용 dict로 변환
    densenet_dict = {}
    for pred in densenet_result["predictions"]:
        densenet_dict[pred["disease"]] = pred["probability"]

    # YOLO 결과를 소견서 생성기용 dict list로 변환
    yolo_dets_for_report = []
    for det in yolo_result["detections"]:
        bbox = det.get("bbox", [0, 0, 0, 0])
        bbox_list = bbox if isinstance(bbox, list) else [bbox.get("x1",0), bbox.get("y1",0), bbox.get("x2",0), bbox.get("y2",0)]
        yolo_dets_for_report.append({
            "class_name": det.get("class_name", det.get("class", "")),
            "confidence": det.get("confidence", 0),
            "bbox": bbox_list,
            "lobe": det.get("lobe", ""),
        })

    # 소견서 생성기에 전달할 전체 이벤트 데이터 조립
    report_event = {
        "patient_info": patient_info,
        "prior_results": context.get("prior_results", []),
        "anatomy_measurements": seg_result.get("measurements", {}),
        "densenet_predictions": densenet_dict,
        "yolo_detections": yolo_dets_for_report,
        "clinical_logic": clinical_result,
        "cross_validation_summary": cv_summary,
        "pertinent_negatives": clinical_result.get("pertinent_negatives", []),
        "report_language": context.get("report_language", "ko"),
    }

    # Bedrock Claude 소견서 생성 (실패 시 빈 문자열 반환)
    try:
        report_result = await report_generator.generate_report(report_event)
        report_text = report_result.get("report", {}).get("narrative", "")
        report_summary = report_result.get("report", {}).get("summary", "")
        report_metadata = report_result.get("metadata", {})
    except Exception as e:
        logger.warning(f"Report generation failed: {e}")
        report_result = {}
        report_text = ""
        report_summary = ""
        report_metadata = {"error": str(e)}

    timings["report"] = round(time.time() - t0, 4)

    # ══════════════════════════════════════════════════════════
    # 최종 응답 구성
    # ──────────────────────────────────────────────────────────
    # Clinical Logic 결과를 PredictResponse 형식으로 변환하여 반환
    # ══════════════════════════════════════════════════════════

    # 14개 질환별 판정 결과 — detected=True인 소견만 findings에 포함
    findings_list = []
    for name, result in clinical_result.get("findings", {}).items():
        if result.get("detected", False):
            findings_list.append({
                "name": name,
                "detected": True,
                "confidence": _confidence_to_float(result.get("confidence", "medium")),
                "detail": "; ".join(result.get("evidence", [])),
            })

    # pertinent negatives (임상적으로 의미 있는 음성 소견)
    pertinent_negatives = clinical_result.get("pertinent_negatives", [])

    # suggested next actions (Bedrock 응답에서 추출, 없으면 빈 리스트)
    next_actions = (
        report_result.get("report", {}).get("suggested_next_actions", [])
        or report_result.get("suggested_next_actions", [])
    )

    total_time = round(time.time() - t_start, 4)

    # 요약 문자열 생성 (Bedrock 요약이 있으면 그것을 사용)
    summary_parts = []
    detected_names = [
        f["name"] for f in findings_list
        if f["name"] != "No_Finding"
    ]
    if detected_names:
        summary_parts.append(f"Detected: {', '.join(detected_names)}")
    else:
        summary_parts.append("No significant findings")
    summary_parts.append(f"Risk: {clinical_result['risk_level']}")
    if clinical_result.get("alert_flags"):
        summary_parts.append(f"ALERT: {', '.join(clinical_result['alert_flags'])}")

    # impression (Bedrock 소견서의 인상 부분, 없으면 narrative 전체)
    impression_text = report_result.get("report", {}).get("impression", "")
    if not impression_text:
        impression_text = report_text  # fallback to full narrative

    # summary: Bedrock concise summary 우선, 없으면 clinical logic 요약
    summary_text = report_summary or " | ".join(summary_parts)

    return {
        "status": "success",
        "modal": "chest",
        "findings": findings_list,                  # detected=True인 소견만
        "pertinent_negatives": pertinent_negatives,  # 임상적 음성 소견
        "summary": summary_text,
        "report": impression_text,                   # Bedrock impression (concise)
        "risk_level": clinical_result["risk_level"],           # top-level로 이동
        "suggested_next_actions": next_actions,                # top-level 추가
        "metadata": {
            "timings": timings,                    # 각 Stage별 소요 시간
            "total_time": total_time,              # 전체 파이프라인 소요 시간
            "detected_count": clinical_result["detected_count"],    # 탐지된 질환 수
            "all_findings_count": 14,              # 전체 14개 질환 (참고용)
            "alert_flags": clinical_result.get("alert_flags", []),  # 긴급 알림 질환
            "differential_diagnosis": clinical_result.get("differential_diagnosis", []),
            "cross_validation_summary": cv_summary,
            "segmentation_view": seg_result.get("view", "unknown"),  # PA/AP/Lateral
            "mask_base64": seg_result.get("mask_base64"),          # 세그멘테이션 마스크 PNG (테스트 UI 오버레이)
            "measurements": seg_result.get("measurements", {}),    # 해부학 측정값 (CTR, CP각 등)
            "yolo_detections": yolo_result.get("detections", []),   # YOLO bbox 목록
            "image_size": yolo_result.get("image_size"),            # 원본 이미지 크기
            "original_size": seg_result.get("original_size"),       # 세그멘테이션 원본 크기
            "report_metadata": report_metadata,    # Bedrock 호출 메타데이터
        },
    }


# ── 유틸리티 함수: 신뢰도 문자열 -> 숫자 변환 ─────────────────
def _confidence_to_float(confidence: str) -> float:
    """
    Confidence string -> float (0.0~1.0).
    Clinical Logic 엔진이 반환하는 문자열 신뢰도를 숫자로 변환.
    API 응답의 Finding.confidence 필드에 사용됩니다.
    """
    mapping = {
        "high": 0.9,
        "medium": 0.7,
        "low": 0.4,
        "none": 0.1,
    }
    return mapping.get(confidence, 0.5)
