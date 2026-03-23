# Layer 6 Bedrock Report — Lambda 컨테이너
# 순수 Python + boto3(Lambda 내장)만 사용. 외부 패키지 불필요.
FROM public.ecr.aws/lambda/python:3.12

# boto3는 Lambda 런타임에 내장 — 별도 설치 불필요
# 캐시 정리
RUN rm -rf /root/.cache/pip /tmp/*

# 소스 코드 복사
COPY lambda_function.py ./
COPY index.html ./

# layer6_bedrock_report 패키지 복사 (deploy 스크립트가 준비)
COPY layer6_bedrock_report/ ./layer6_bedrock_report/

CMD ["lambda_function.handler"]
