FROM public.ecr.aws/lambda/python:3.12
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && rm -rf /root/.cache /tmp/*
COPY *.py ./
COPY index.html ./
CMD ["lambda_function.handler"]
