"""각 Layer HTTP 호출 클라이언트"""
import time
import requests

import config


class LayerClient:
    def __init__(self):
        self.session = requests.Session()

    def _call(self, url: str, payload: dict, timeout: int) -> dict:
        """공통 HTTP 호출 + 응답 시간 측정"""
        start = time.time()
        resp = self.session.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        data["_processing_time_ms"] = int((time.time() - start) * 1000)
        return data

    def call_layer1(self, image_payload: dict) -> dict:
        """Layer 1 Segmentation 호출"""
        return self._call(config.LAYER1_URL, image_payload,
                          config.LAYER_TIMEOUTS["layer1"])

    def call_layer2(self, image_payload: dict) -> dict:
        """Layer 2a DenseNet 호출"""
        return self._call(config.LAYER2_URL, image_payload,
                          config.LAYER_TIMEOUTS["layer2"])

    def call_layer2b(self, image_payload: dict) -> dict:
        """Layer 2b YOLOv8 호출"""
        return self._call(config.LAYER2B_URL, image_payload,
                          config.LAYER_TIMEOUTS["layer2b"])

    def call_layer3(self, payload: dict) -> dict:
        """Layer 3 Clinical Logic 호출"""
        return self._call(config.LAYER3_URL, payload,
                          config.LAYER_TIMEOUTS["layer3"])

    def call_layer5(self, clinical_logic: dict, top_k: int = 3) -> dict:
        """Layer 5 RAG 호출"""
        payload = {
            "action": "custom",
            "clinical_logic": clinical_logic,
            "top_k": top_k,
        }
        return self._call(config.LAYER5_URL, payload,
                          config.LAYER_TIMEOUTS["layer5"])

    def call_layer6(self, payload: dict) -> dict:
        """Layer 6 Bedrock Report 호출"""
        return self._call(config.LAYER6_URL, payload,
                          config.LAYER_TIMEOUTS["layer6"])
