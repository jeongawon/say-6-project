"""출력 형태 변환 — 내부 전체 결과를 외부 반환 형태로"""


class OutputFormatter:
    @staticmethod
    def default(full_result: dict) -> dict:
        """전체 결과 반환 — API 기본"""
        return full_result

    @staticmethod
    def summary_only(full_result: dict) -> dict:
        """요약만 — 다른 모달이 참고할 때"""
        return {
            "modal": "chest_xray",
            "summary": full_result.get("summary", {}),
            "suggested_next_actions": full_result.get("suggested_next_actions", []),
            "timestamp": full_result.get("timestamp", ""),
        }

    @staticmethod
    def orchestrator_format(full_result: dict) -> dict:
        """오케스트레이터용 — 팀에서 형태 정하면 여기만 수정"""
        return full_result
