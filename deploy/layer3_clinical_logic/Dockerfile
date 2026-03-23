# Layer 3 Clinical Logic — 순수 Python (GPU/PyTorch 불필요)
# 외부 패키지 의존성 없음 (dataclasses + 표준 라이브러리만 사용)
FROM public.ecr.aws/lambda/python:3.12

# 캐시 정리
RUN rm -rf /root/.cache/pip /tmp/*

# Layer 3 소스 코드 복사
COPY layer3_clinical_logic/ ${LAMBDA_TASK_ROOT}/layer3_clinical_logic/
COPY pipeline/ ${LAMBDA_TASK_ROOT}/pipeline/

# Lambda 핸들러 + 테스트 페이지
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
COPY index.html ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.handler"]
