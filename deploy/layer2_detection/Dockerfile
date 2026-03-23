# Layer 2 Detection — DenseNet-121 Lambda Container
FROM public.ecr.aws/lambda/python:3.12

# PyTorch CPU + Pillow + numpy 설치 후 불필요 패키지 즉시 제거 (단일 레이어)
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch torchvision Pillow numpy \
    && rm -rf /root/.cache /tmp/*

# Lambda 핸들러 + 테스트 페이지 복사
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
COPY index.html ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.handler"]
