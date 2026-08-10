FROM public.ecr.aws/lambda/python:3.11

COPY pyproject.toml README.md LICENSE /var/task/
COPY src /var/task/src
RUN python -m pip install --no-cache-dir /var/task

COPY config/sources.json /var/task/config/sources.json
COPY lambdas/schema_identity_gate/handler.py /var/task/handler.py

CMD ["handler.handler"]
