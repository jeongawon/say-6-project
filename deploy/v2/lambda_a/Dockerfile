FROM public.ecr.aws/lambda/python:3.12
COPY shared/result_store.py ${LAMBDA_TASK_ROOT}/
COPY shared/config.py ${LAMBDA_TASK_ROOT}/
COPY lambda_a/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lambda_a/*.py ${LAMBDA_TASK_ROOT}/
CMD ["lambda_function.lambda_handler"]
