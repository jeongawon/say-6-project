"""
Layer 6 Bedrock Report Generator
Bedrock Claude Sonnet 호출 + 프롬프트 조립 + 응답 파싱
"""
import json
import time
import boto3

from .config import Config
from .prompt_templates import (
    SYSTEM_PROMPT, SYSTEM_PROMPT_EN,
    USER_PROMPT_TEMPLATE, USER_PROMPT_TEMPLATE_EN,
    RAG_SECTION_PLACEHOLDER, RAG_SECTION_PLACEHOLDER_EN,
    RAG_SECTION_TEMPLATE,
)
from .rag_placeholder import RAGPlaceholder


class BedrockReportGenerator:
    def __init__(self, config=None):
        self.config = config or Config()
        self.bedrock = boto3.client(
            "bedrock-runtime",
            region_name=self.config.REGION,
        )
        self.model_id = self.config.MODEL_ID
        self.rag = RAGPlaceholder()

    def generate_report(self, event: dict) -> dict:
        """
        Layer 1~5 결과 + 환자정보 -> Bedrock Sonnet -> 소견서

        Args:
            event: Lambda event (Layer 1~5 결과 종합 JSON)

        Returns:
            dict: 소견서 + 메타데이터
        """
        start_time = time.time()
        lang = event.get("report_language", "ko")

        # RAG 검색 (현재 placeholder)
        clinical_logic = event.get("clinical_logic", {})
        rag_results = self.rag.search_similar_cases(clinical_logic)
        if rag_results:
            event["rag_evidence"] = rag_results

        # 1. 프롬프트 조립
        system_prompt = self._build_system_prompt(event, lang)
        user_prompt = self._build_user_prompt(event, lang)

        # 2. Bedrock 호출
        response = self._invoke_bedrock(
            system_prompt, user_prompt,
            self.config.TEMPERATURE, self.config.MAX_TOKENS
        )

        # 3. 응답 파싱 (실패 시 재시도)
        try:
            report = self._parse_response(response)
        except (ValueError, json.JSONDecodeError):
            # temperature 0.0으로 재시도
            response = self._invoke_bedrock(
                system_prompt, user_prompt,
                self.config.RETRY_TEMPERATURE, self.config.MAX_TOKENS
            )
            report = self._parse_response(response)

        # 4. 위험도 + 알림 플래그
        risk_level = clinical_logic.get("risk_level", "ROUTINE")
        alert_flags = clinical_logic.get("alert_flags", [])

        # 5. 결과 조립
        result = {
            "request_id": event.get("request_id", ""),
            "report": {
                "structured": report.get("structured", {}),
                "narrative": report.get("narrative", ""),
                "summary": report.get("summary", ""),
                "risk_level": risk_level,
                "alert_flags": alert_flags,
            },
            "suggested_next_actions": report.get("suggested_next_actions", []),
            "metadata": {
                "model_used": self.model_id,
                "input_tokens": response.get("usage", {}).get("input_tokens", 0),
                "output_tokens": response.get("usage", {}).get("output_tokens", 0),
                "latency_ms": int((time.time() - start_time) * 1000),
                "rag_used": bool(event.get("rag_evidence")),
                "report_language": lang,
            },
        }

        return result

    def _invoke_bedrock(self, system_prompt, user_prompt, temperature, max_tokens):
        """Bedrock API 호출"""
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
        }

        response = self.bedrock.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        return json.loads(response["body"].read())

    def _build_system_prompt(self, event, lang="ko"):
        """시스템 프롬프트 조립 - RAG 섹션 포함"""
        rag_evidence = event.get("rag_evidence", [])

        if rag_evidence:
            rag_section = RAG_SECTION_TEMPLATE.format(
                rag_cases="\n\n".join([
                    f"[유사 케이스 {i+1}] (유사도: {r.get('similarity', 'N/A')})\n{r.get('impression', '')}"
                    for i, r in enumerate(rag_evidence[:3])
                ])
            )
        else:
            rag_section = RAG_SECTION_PLACEHOLDER if lang == "ko" else RAG_SECTION_PLACEHOLDER_EN

        template = SYSTEM_PROMPT if lang == "ko" else SYSTEM_PROMPT_EN
        return template.format(rag_section=rag_section)

    def _build_user_prompt(self, event, lang="ko"):
        """유저 프롬프트 조립 - 각 Layer 결과를 섹션별로 포맷"""
        patient_info_section = self._format_patient_info(event.get("patient_info", {}))
        prior_results_section = self._format_prior_results(event.get("prior_results", []))
        anatomy_section = self._format_anatomy(event.get("anatomy_measurements", {}))
        detection_section = self._format_detection(
            event.get("densenet_predictions", {}),
            event.get("yolo_detections", [])
        )
        clinical_logic = event.get("clinical_logic", {})
        clinical_logic_section = self._format_clinical_logic(clinical_logic)
        cross_validation_section = self._format_cross_validation(
            event.get("cross_validation_summary", {})
        )
        differential_section = self._format_differential(
            clinical_logic.get("differential_diagnosis", [])
        )
        risk_level = clinical_logic.get("risk_level", "ROUTINE")

        template = USER_PROMPT_TEMPLATE if lang == "ko" else USER_PROMPT_TEMPLATE_EN
        return template.format(
            patient_info_section=patient_info_section,
            prior_results_section=prior_results_section,
            anatomy_section=anatomy_section,
            detection_section=detection_section,
            clinical_logic_section=clinical_logic_section,
            cross_validation_section=cross_validation_section,
            differential_section=differential_section,
            risk_level=risk_level,
        )

    def _parse_response(self, response):
        """Bedrock 응답에서 JSON 추출"""
        text = response["content"][0]["text"]

        # ```json ... ``` 블록 추출
        if "```json" in text:
            json_str = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text and "{" in text:
            parts = text.split("```")
            json_str = None
            for part in parts:
                stripped = part.strip()
                if stripped.startswith("{"):
                    json_str = stripped
                    break
            if json_str is None:
                json_str = self._extract_json_braces(text)
        elif "{" in text:
            json_str = self._extract_json_braces(text)
        else:
            raise ValueError("Bedrock 응답에서 JSON을 찾을 수 없습니다")

        # 파싱 시도
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # JSON 문자열 값 내부의 리터럴 개행을 이스케이프
            fixed = self._fix_json_newlines(json_str)
            return json.loads(fixed)

    def _fix_json_newlines(self, text):
        """JSON 문자열 값 내부의 리터럴 개행을 \\n으로 변환"""
        result = []
        in_string = False
        escape_next = False
        i = 0
        while i < len(text):
            ch = text[i]
            if escape_next:
                result.append(ch)
                escape_next = False
            elif ch == '\\':
                result.append(ch)
                escape_next = True
            elif ch == '"':
                result.append(ch)
                in_string = not in_string
            elif ch == '\n' and in_string:
                result.append('\\n')
            elif ch == '\r' and in_string:
                pass  # skip CR
            else:
                result.append(ch)
            i += 1
        return ''.join(result)

    def _extract_json_braces(self, text):
        """중괄호 매칭으로 JSON 추출"""
        start = text.index("{")
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i+1]
        # fallback
        end = text.rindex("}") + 1
        return text[start:end]

    # ============================================================
    # 섹션 포맷팅
    # ============================================================
    def _format_patient_info(self, info):
        if not info:
            return "정보 없음"
        lines = []
        if info.get("age"):
            lines.append(f"나이: {info['age']}세")
        if info.get("sex"):
            sex_kr = "남성" if info["sex"] == "M" else "여성"
            lines.append(f"성별: {sex_kr}")
        if info.get("chief_complaint"):
            lines.append(f"주소: {info['chief_complaint']}")
        if info.get("temperature"):
            lines.append(f"체온: {info['temperature']}C")
        if info.get("heart_rate"):
            lines.append(f"심박수: {info['heart_rate']}bpm")
        if info.get("blood_pressure"):
            lines.append(f"혈압: {info['blood_pressure']}mmHg")
        if info.get("spo2"):
            lines.append(f"SpO2: {info['spo2']}%")
        if info.get("respiratory_rate"):
            lines.append(f"호흡수: {info['respiratory_rate']}회/분")
        return "\n".join(lines) if lines else "정보 없음"

    def _format_prior_results(self, results):
        if not results:
            return "이전 검사 없음"
        lines = []
        for r in results:
            modal = r.get("modal", "")
            summary = r.get("summary", "")
            lines.append(f"- {modal.upper()}: {summary}")
        return "\n".join(lines)

    def _format_anatomy(self, anat):
        if not anat:
            return "측정값 없음"
        lines = []
        if "ctr" in anat:
            lines.append(f"CTR: {anat['ctr']:.4f} ({anat.get('ctr_status', '')})")
        if "heart_width_px" in anat:
            lines.append(f"심장폭: {anat['heart_width_px']}px, 흉곽폭: {anat.get('thorax_width_px', '')}px")
        if "lung_area_ratio" in anat:
            lines.append(f"좌/우 폐 면적비: {anat['lung_area_ratio']:.3f}")
        if "mediastinum_status" in anat:
            lines.append(f"종격동: {anat.get('mediastinum_status', 'N/A')} (폭 {anat.get('mediastinum_width_px', 'N/A')}px)")
        if "trachea_midline" in anat:
            if anat["trachea_midline"]:
                lines.append("기관: 중심선 유지")
            else:
                direction = anat.get("trachea_deviation_direction", "")
                lines.append(f"기관: {direction}측 편위")
        if "right_cp_status" in anat:
            r_angle = anat.get("right_cp_angle_degrees", "")
            l_angle = anat.get("left_cp_angle_degrees", "")
            lines.append(f"우측 CP angle: {r_angle}deg ({anat.get('right_cp_status', '')})")
            lines.append(f"좌측 CP angle: {l_angle}deg ({anat.get('left_cp_status', '')})")
        if "diaphragm_status" in anat:
            lines.append(f"횡격막: {anat.get('diaphragm_status', 'N/A')}")
        if "view" in anat:
            lines.append(f"촬영 뷰: {anat['view']}")
        if "predicted_age" in anat:
            lines.append(f"예측 나이/성별: {anat.get('predicted_age')}세 {anat.get('predicted_sex', '')}")
        return "\n".join(lines) if lines else "측정값 없음"

    def _format_detection(self, densenet, yolo):
        lines = []

        # DenseNet 확률 (높은 순 정렬)
        if densenet:
            sorted_preds = sorted(densenet.items(), key=lambda x: x[1], reverse=True)
            lines.append("[DenseNet-121 14-label 확률]")
            for disease, prob in sorted_preds:
                marker = "!!!" if prob >= 0.7 else "!" if prob >= 0.5 else ""
                lines.append(f"  {disease}: {prob:.4f} {marker}")

        # YOLO 탐지
        if yolo:
            lines.append("\n[YOLOv8 Object Detection]")
            for det in yolo:
                name = det.get("class_name", "")
                conf = det.get("confidence", 0)
                lobe = det.get("lobe", "")
                bbox = det.get("bbox", [])
                lines.append(f"  {name}: conf={conf:.2f}, lobe={lobe}, bbox={bbox}")

        return "\n".join(lines) if lines else "탐지 결과 없음"

    def _format_clinical_logic(self, logic):
        if not logic:
            return "임상 로직 결과 없음"

        findings = logic.get("findings", {})
        if not findings:
            return "판정 결과 없음"

        lines = [f"감지 질환 수: {logic.get('detected_count', 0)}"]

        for disease, info in findings.items():
            if isinstance(info, dict) and info.get("detected"):
                severity = info.get("severity", "")
                confidence = info.get("confidence", "")
                location = info.get("location", "")
                evidence = info.get("evidence", [])
                recommendation = info.get("recommendation", "")

                lines.append(f"\n[{disease}] 양성")
                lines.append(f"  신뢰도: {confidence}, 심각도: {severity}")
                if location:
                    lines.append(f"  위치: {location}")
                if evidence:
                    lines.append(f"  근거: {', '.join(str(e) for e in evidence)}")
                if info.get("quantitative"):
                    lines.append(f"  정량: {json.dumps(info['quantitative'], ensure_ascii=False)}")
                if recommendation:
                    lines.append(f"  권고: {recommendation}")

        return "\n".join(lines)

    def _format_cross_validation(self, cv):
        if not cv:
            return "교차 검증 미실행"
        lines = []
        if cv.get("high_agreement"):
            lines.append(f"높은 일치: {', '.join(cv['high_agreement'])}")
        if cv.get("medium_agreement"):
            lines.append(f"중간 일치: {', '.join(cv['medium_agreement'])}")
        if cv.get("low_agreement"):
            lines.append(f"낮은 일치: {', '.join(cv['low_agreement'])}")
        if cv.get("flags"):
            lines.append(f"주의 필요: {', '.join(cv['flags'])}")
        return "\n".join(lines) if lines else "교차 검증 데이터 없음"

    def _format_differential(self, diff_list):
        if not diff_list:
            return "감별 진단 없음"
        lines = []
        for i, d in enumerate(diff_list, 1):
            diagnosis = d.get("diagnosis", "")
            probability = d.get("probability", "")
            reasoning = d.get("reasoning", "")
            lines.append(f"{i}. {diagnosis} (가능성: {probability})")
            if reasoning:
                lines.append(f"   근거: {reasoning}")
        return "\n".join(lines)
