# Layer 2b YOLOv8 Detection — VinDr-CXR 14-Class Lambda Container
FROM public.ecr.aws/lambda/python:3.12

# PyTorch CPU 2.5.1 고정 + ultralytics 설치 후 불필요 패키지 즉시 제거 (단일 레이어)
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.5.1+cpu torchvision==0.20.1+cpu \
    && pip install --no-cache-dir ultralytics==8.3.52 Pillow numpy \
    && pip uninstall -y opencv-python 2>/dev/null || true \
    && pip install --no-cache-dir opencv-python-headless \
    && rm -rf /var/lang/lib/python3.12/site-packages/pip* \
    && rm -rf /root/.cache /tmp/*

# Lambda 핸들러 + 테스트 페이지 복사
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
COPY index.html ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.handler"]
