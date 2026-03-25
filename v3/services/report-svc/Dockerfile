# ── report-svc Docker 이미지 ─────────────────────────────────
# 의료 보고서 생성 서비스
# 분석 결과를 종합하여 Bedrock Claude로 의료 보고서 생성
# 모델 로딩 없이 API 호출 기반이므로 경량 서비스
# 빌드: docker build -t report-svc .
# ──────────────────────────────────────────────────────────────

# 베이스 이미지 — Python 3.11 경량 이미지
FROM python:3.11-slim

WORKDIR /app

# ── Docker 캐시 최적화 전략 ──────────────────────────────────
# requirements.txt를 먼저 복사하여 의존성 레이어를 캐시
# 소스코드만 변경 시 pip install 단계를 재실행하지 않아 빌드 속도 향상
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 서비스 소스코드 복사
COPY . .

# 공유 스키마 복사 — 서비스 간 공통 데이터 모델 (빌드 컨텍스트에서)
COPY shared/ /app/shared/

# 서비스 포트 — 모든 마이크로서비스가 내부적으로 8000번 포트 사용
EXPOSE 8000

# K8s 리소스 힌트 (실제 제한은 K8s manifest에서 적용)
# readinessProbe initialDelaySeconds: 2 — 모델 로딩이 없어 즉시 준비 완료
# CPU: 250m, Memory: 512Mi — API 호출 기반이라 리소스 적게 필요

# ── 서버 실행 ────────────────────────────────────────────────
# uvicorn ASGI 서버로 FastAPI 앱 실행
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
