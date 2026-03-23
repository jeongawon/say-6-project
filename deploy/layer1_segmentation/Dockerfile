# Layer 1 Segmentation — Lambda Container
FROM public.ecr.aws/lambda/python:3.12

# PyTorch CPU + transformers (AutoModel 사용) + Pillow + numpy
# albumentations, timm: transformers 모델 로딩 시 필요
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch torchvision \
    && pip install --no-cache-dir "transformers>=4.40,<5.0" Pillow numpy timm albumentations \
    && rm -rf /root/.cache /tmp/*

# Lambda 핸들러 + 테스트 페이지 복사
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
COPY index.html ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.handler"]
