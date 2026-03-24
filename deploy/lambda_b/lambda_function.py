"""
Lambda B — Analysis & Report Handler (No S3 Write).

parallel_results에서 직접 추론 데이터를 받아 처리.
S3 Claim-Check 로드/저장 없음. 모든 데이터가 HTTP 본문으로 전달.
"""

import json
import traceback

from clinical_logic.clinical_engine import ClinicalEngine
from rag.rag_service import RAGService
from rag.config import Config as RAGConfig
from bedrock_report.report_generator import BedrockReportGenerator


def lambda_handler(event, context):
    """
    Expected event:
    {
        "run_id": "abc-123",
        "patient_info": { ... },
        "parallel_results": {
            "seg": { ... 추론 결과 직접 ... },
            "densenet": { ... },
            "yolo": { ... }
        }
    }
    """
    # Function URL 이벤트 지원
    if "body" in event and isinstance(event.get("body"), str):
        event = json.loads(event["body"])

    try:
        run_id = event["run_id"]
        patient_info = event.get("patient_info", {})
        parallel_results = event["parallel_results"]

        print(f"[LambdaB] 시작: run_id={run_id}")

        # ── 1. 추론 결과 추출 (직접 전달됨, S3 로드 없음) ──
        segmentation = parallel_results.get("seg", {})
        detection = parallel_results.get("densenet", {})
        yolo = parallel_results.get("yolo", {"detections": [], "processing_time": 0})

        # seg/densenet 필수 확인
        if segmentation.get("status") == "failed":
            return _error(500, f"Critical model failed: seg - {segmentation.get('message')}", run_id)
        if detection.get("status") == "failed":
            return _error(500, f"Critical model failed: densenet - {detection.get('message')}", run_id)

        # yolo 실패 시 graceful degradation
        if yolo.get("status") == "failed":
            print(f"[LambdaB] YOLO Graceful Degradation")
            yolo = {"detections": [], "processing_time": 0}

        # ── 2. L3: Clinical Logic ──
        print("[LambdaB] L3 Clinical Logic")
        engine = ClinicalEngine()
        densenet_preds = {}
        for pred in detection.get("predictions", []):
            densenet_preds[pred["disease"]] = pred["probability"]

        clinical_result = engine.analyze(
            anatomy_result=segmentation,
            densenet_preds=densenet_preds,
            yolo_detections=yolo.get("detections", []),
            patient_info=patient_info,
        )
        print(f"[LambdaB] L3 완료")

        # ── 3. L5: RAG Search ──
        print("[LambdaB] L5 RAG Search")
        rag_config = RAGConfig()
        rag = RAGService(rag_config)
        rag_evidence = rag.search(clinical_logic_result=clinical_result, top_k=3)
        print(f"[LambdaB] L5 완료")

        # ── 4. L6: Bedrock Report ──
        print("[LambdaB] L6 Bedrock Report")
        generator = BedrockReportGenerator()
        report_event = {
            "layer1_segmentation": segmentation,
            "layer2_detection": detection,
            "layer2b_yolo": yolo,
            "layer3_clinical_logic": clinical_result,
            "layer5_rag": rag_evidence,
            "patient_info": patient_info,
            "run_id": run_id,
        }
        report = generator.generate_report(report_event)
        print(f"[LambdaB] L6 완료: {len(str(report))} chars")

        # ── 결과 직접 반환 (S3 저장 없음) ──
        # Function URL 호환: statusCode 대신 status 사용
        # (Function URL은 statusCode 필드를 HTTP 상태로 해석하여 body가 비워짐)
        return {
            "status": "ok",
            "run_id": run_id,
            "clinical_logic": clinical_result,
            "rag_evidence": rag_evidence,
            "report": report,
        }

    except Exception as e:
        print(f"[LambdaB] 오류:\n{traceback.format_exc()}")
        return _error(500, str(e), event.get("run_id", "unknown"))


def _error(code, msg, run_id):
    return {
        "status": "failed",
        "error": msg,
        "run_id": run_id,
    }
