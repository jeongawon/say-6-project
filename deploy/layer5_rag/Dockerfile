# Layer 5 RAG — FAISS + FastEmbed (bge-small-en-v1.5)
# Live 모드: S3에서 FAISS 인덱스(183MB) + 메타데이터(176MB) 다운로드
FROM public.ecr.aws/lambda/python:3.12

# fastembed(ONNX) + faiss-cpu + numpy 설치 + 불필요 패키지 정리 (단일 레이어)
RUN pip install --no-cache-dir faiss-cpu numpy fastembed \
    && pip uninstall -y sympy mpmath -y 2>/dev/null || true \
    && rm -rf /var/lang/lib/python3.12/site-packages/setuptools* \
    && rm -rf /var/lang/lib/python3.12/site-packages/pkg_resources \
    && rm -rf /var/lang/lib/python3.12/site-packages/pip* \
    && rm -rf /var/lang/lib/python3.12/site-packages/pygments \
    && rm -rf /root/.cache /tmp/*

# FastEmbed 모델 사전 다운로드 (cold start 단축)
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

# Layer 5 소스 코드 복사
COPY layer5_rag/ ${LAMBDA_TASK_ROOT}/layer5_rag/

# Lambda 핸들러 + 테스트 페이지
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
COPY index.html ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.handler"]
