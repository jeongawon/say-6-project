FROM public.ecr.aws/lambda/python:3.12
ENV FASTEMBED_CACHE_PATH=/var/task/fastembed_cache
ENV HF_HOME=/tmp/hf_cache
COPY shared/result_store.py ${LAMBDA_TASK_ROOT}/
COPY shared/config.py ${LAMBDA_TASK_ROOT}/
COPY lambda_b/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# FastEmbed 모델 사전 다운로드 (v1과 동일 — 콜드 스타트 60초→5초)
RUN FASTEMBED_CACHE_PATH=/var/task/fastembed_cache \
    python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"
COPY lambda_b/*.py ${LAMBDA_TASK_ROOT}/
COPY lambda_b/clinical_logic/ ${LAMBDA_TASK_ROOT}/clinical_logic/
COPY lambda_b/rag/ ${LAMBDA_TASK_ROOT}/rag/
COPY lambda_b/bedrock_report/ ${LAMBDA_TASK_ROOT}/bedrock_report/
CMD ["lambda_function.lambda_handler"]
