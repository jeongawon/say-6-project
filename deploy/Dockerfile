# Lambda Container Image for Chest X-Ray Modal v2
# PyTorch CPU + U-Net + DenseNet-121 + YOLOv8

FROM public.ecr.aws/lambda/python:3.12

# 시스템 의존성
RUN dnf install -y gcc gcc-c++ && dnf clean all

# Python 패키지 설치
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# 추론 코드 복사
COPY handler.py ${LAMBDA_TASK_ROOT}/
COPY pipeline/ ${LAMBDA_TASK_ROOT}/pipeline/
COPY layer1_segmentation/ ${LAMBDA_TASK_ROOT}/layer1_segmentation/
COPY layer2_detection/ ${LAMBDA_TASK_ROOT}/layer2_detection/
COPY layer3_clinical_logic/ ${LAMBDA_TASK_ROOT}/layer3_clinical_logic/
COPY layer4_cross_validation/ ${LAMBDA_TASK_ROOT}/layer4_cross_validation/
COPY layer5_rag/ ${LAMBDA_TASK_ROOT}/layer5_rag/
COPY layer6_report/ ${LAMBDA_TASK_ROOT}/layer6_report/

# Lambda 핸들러 지정
CMD ["handler.lambda_handler"]
