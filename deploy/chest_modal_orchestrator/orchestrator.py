"""파이프라인 오케스트레이션 — 5단계 순차/병렬 실행 + 결과 취합"""
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from layer_client import LayerClient


KST = timezone(timedelta(hours=9))


class ChestModalOrchestrator:
    def __init__(self):
        self.client = LayerClient()

    def run(self, parsed_input: dict) -> dict:
        """전체 파이프라인 실행"""
        start = time.time()
        options = parsed_input.get("options", {})
        skip = options.get("skip_layers", [])

        result = {
            "modal": "chest_xray",
            "request_id": f"req_{int(time.time())}",
            "timestamp": datetime.now(KST).isoformat(),
            "status": "success",
            "layer_results": {},
            "pipeline_metadata": {
                "layers_executed": [],
                "layers_skipped": list(skip),
                "layers_failed": [],
            },
        }

        image_payload = self._build_image_payload(parsed_input)
        patient_info = parsed_input.get("patient_info", {})
        prior_results = parsed_input.get("prior_results", [])

        # ============================================================
        # Step 1+2: Layer 1 + Layer 2a + Layer 2b 병렬
        # ============================================================
        layer1_ok = False
        layer2_ok = False

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            if "layer1" not in skip:
                futures[executor.submit(self.client.call_layer1, image_payload)] = "layer1"
            if "layer2" not in skip:
                futures[executor.submit(self.client.call_layer2, image_payload)] = "layer2"
            if "layer2b" not in skip:
                futures[executor.submit(self.client.call_layer2b, image_payload)] = "layer2b"

            for future in as_completed(futures):
                layer_name = futures[future]
                try:
                    layer_result = future.result()
                    pt = layer_result.pop("_processing_time_ms", 0)
                    result["layer_results"][layer_name] = {
                        "status": "success",
                        "processing_time_ms": pt,
                        **layer_result,
                    }
                    result["pipeline_metadata"]["layers_executed"].append(layer_name)
                    if layer_name == "layer1":
                        layer1_ok = True
                    elif layer_name == "layer2":
                        layer2_ok = True
                except Exception as e:
                    result["layer_results"][layer_name] = {
                        "status": "error", "error": str(e),
                    }
                    result["pipeline_metadata"]["layers_failed"].append(layer_name)

        # ============================================================
        # Step 3: Layer 3 (Layer 1 + 2 필수)
        # ============================================================
        layer3_ok = False
        if layer1_ok and layer2_ok and "layer3" not in skip:
            try:
                payload = self._build_layer3_payload(
                    result["layer_results"]["layer1"],
                    result["layer_results"]["layer2"],
                    patient_info, prior_results,
                )
                layer3_result = self.client.call_layer3(payload)
                pt = layer3_result.pop("_processing_time_ms", 0)
                result["layer_results"]["layer3"] = {
                    "status": "success",
                    "processing_time_ms": pt,
                    **layer3_result,
                }
                result["pipeline_metadata"]["layers_executed"].append("layer3")
                layer3_ok = True
            except Exception as e:
                result["layer_results"]["layer3"] = {
                    "status": "error", "error": str(e),
                }
                result["pipeline_metadata"]["layers_failed"].append("layer3")

        # ============================================================
        # Step 4: Layer 5 RAG (Layer 3 필수, include_rag 옵션)
        # ============================================================
        if layer3_ok and options.get("include_rag", True) and "layer5" not in skip:
            try:
                layer3_result_data = result["layer_results"]["layer3"].get("result", {})
                layer5_result = self.client.call_layer5(
                    layer3_result_data,
                    top_k=options.get("top_k", 3),
                )
                pt = layer5_result.pop("_processing_time_ms", 0)
                result["layer_results"]["layer5"] = {
                    "status": "success",
                    "processing_time_ms": pt,
                    **layer5_result,
                }
                result["pipeline_metadata"]["layers_executed"].append("layer5")
            except Exception as e:
                result["layer_results"]["layer5"] = {
                    "status": "error", "error": str(e),
                }
                result["pipeline_metadata"]["layers_failed"].append("layer5")

        # ============================================================
        # Step 5: Layer 6 Bedrock (Layer 3 필수, Layer 5는 선택)
        # ============================================================
        if layer3_ok and "layer6" not in skip:
            try:
                payload = self._build_layer6_payload(
                    result["layer_results"], patient_info, prior_results, options,
                )
                layer6_result = self.client.call_layer6(payload)
                pt = layer6_result.pop("_processing_time_ms", 0)
                result["layer_results"]["layer6"] = {
                    "status": "success",
                    "processing_time_ms": pt,
                    **layer6_result,
                }
                result["pipeline_metadata"]["layers_executed"].append("layer6")
            except Exception as e:
                result["layer_results"]["layer6"] = {
                    "status": "error", "error": str(e),
                }
                result["pipeline_metadata"]["layers_failed"].append("layer6")

        # ============================================================
        # 결과 취합
        # ============================================================
        result["pipeline_metadata"]["total_processing_time_ms"] = int(
            (time.time() - start) * 1000
        )
        result["summary"] = self._build_summary(result)
        result["suggested_next_actions"] = self._extract_next_actions(result)
        result["report"] = self._extract_report(result)

        if result["pipeline_metadata"]["layers_failed"]:
            result["status"] = "partial"

        return result

    # ================================================================
    # 내부 헬퍼
    # ================================================================

    def _build_image_payload(self, parsed_input: dict) -> dict:
        """이미지 payload 생성 (base64 또는 s3_key)"""
        if parsed_input.get("image_base64"):
            return {"image_base64": parsed_input["image_base64"]}
        return {"s3_key": parsed_input["s3_key"]}

    def _flatten_layer1_for_layer3(self, layer1: dict) -> dict:
        """Layer 1 measurements 중첩 → Layer 3 anatomy 평탄"""
        m = layer1.get("measurements", {})
        return {
            "ctr": m.get("ctr"),
            "ctr_status": m.get("ctr_status"),
            "heart_width_px": m.get("heart_width_px"),
            "thorax_width_px": m.get("thorax_width_px"),
            "right_lung_area_px2": m.get("right_lung_area_px"),
            "left_lung_area_px2": m.get("left_lung_area_px"),
            "heart_area_px2": m.get("heart_area_px"),
            "lung_area_ratio": m.get("lung_area_ratio"),
            "total_lung_area_px2": m.get("total_lung_area_px"),
            # mediastinum
            "mediastinum_status": m.get("mediastinum", {}).get("status"),
            "mediastinum_width_px": m.get("mediastinum", {}).get("width_px"),
            # trachea
            "trachea_midline": m.get("trachea", {}).get("midline"),
            "trachea_deviation_direction": m.get("trachea", {}).get("deviation_direction"),
            "trachea_deviation_ratio": m.get("trachea", {}).get("deviation_ratio"),
            # cp_angle
            "right_cp_status": m.get("cp_angle", {}).get("right", {}).get("status"),
            "right_cp_angle_degrees": m.get("cp_angle", {}).get("right", {}).get("angle_degrees"),
            "left_cp_status": m.get("cp_angle", {}).get("left", {}).get("status"),
            "left_cp_angle_degrees": m.get("cp_angle", {}).get("left", {}).get("angle_degrees"),
            # diaphragm
            "diaphragm_status": m.get("diaphragm", {}).get("status"),
            # meta
            "view": layer1.get("view"),
            "predicted_age": layer1.get("age_pred"),
            "predicted_sex": layer1.get("sex_pred"),
        }

    def _normalize_layer2_for_layer3(self, layer2: dict) -> dict:
        """Layer 2a probabilities 키 변환: 공백 → 언더스코어"""
        densenet = {}
        for disease, prob in layer2.get("probabilities", {}).items():
            densenet[disease.replace(" ", "_")] = prob
        return densenet

    def _build_layer3_payload(self, layer1: dict, layer2: dict,
                              patient_info: dict, prior_results: list) -> dict:
        return {
            "action": "custom",
            "anatomy": self._flatten_layer1_for_layer3(layer1),
            "densenet": self._normalize_layer2_for_layer3(layer2),
            "patient_info": patient_info,
            "prior_results": prior_results,
        }

    def _build_layer6_payload(self, layer_results: dict, patient_info: dict,
                              prior_results: list, options: dict) -> dict:
        layer3 = layer_results.get("layer3", {})
        layer3_result = layer3.get("result", {})
        layer5 = layer_results.get("layer5", {})

        # Layer 5: live모드 → results, mock모드 → rag_evidence
        rag_evidence = layer5.get("results", layer5.get("rag_evidence", []))

        return {
            "action": "generate",
            "report_language": options.get("report_language", "ko"),
            "patient_info": patient_info,
            "anatomy_measurements": layer_results.get("layer1", {}).get("measurements", {}),
            "densenet_predictions": layer_results.get("layer2", {}).get("probabilities", {}),
            "yolo_detections": layer_results.get("layer2b", {}).get("detections", []),
            "clinical_logic": layer3_result,
            "cross_validation_summary": layer3_result.get("cross_validation", {}),
            "prior_results": prior_results,
            "rag_evidence": rag_evidence,
        }

    def _build_summary(self, result: dict) -> dict:
        """Layer 3 결과에서 요약 생성"""
        layer3 = result["layer_results"].get("layer3", {})
        r = layer3.get("result", {})

        detected = []
        for name, finding in r.get("findings", {}).items():
            if finding.get("detected") and name != "No_Finding":
                detected.append(name)

        diff = r.get("differential_diagnosis", [])
        primary = diff[0]["diagnosis"] if diff else None

        return {
            "risk_level": r.get("risk_level", "UNKNOWN"),
            "detected_diseases": detected,
            "detected_count": len(detected),
            "primary_diagnosis": primary,
            "one_line": (
                f"{', '.join(detected)} -> {primary}. {r.get('risk_level', '')}."
                if detected else "No significant findings."
            ),
            "alert_flags": r.get("alert_flags", []),
        }

    def _extract_report(self, result: dict) -> dict:
        """Layer 6 결과에서 소견서 추출"""
        layer6 = result["layer_results"].get("layer6", {})
        return layer6.get("report", {}).get("report", {})

    def _extract_next_actions(self, result: dict) -> list:
        """Layer 6 결과에서 권고 조치 추출"""
        layer6 = result["layer_results"].get("layer6", {})
        return layer6.get("report", {}).get("suggested_next_actions", [])
