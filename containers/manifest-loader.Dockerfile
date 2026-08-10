FROM public.ecr.aws/lambda/python:3.11

COPY pyproject.toml README.md LICENSE /var/task/
COPY src /var/task/src
RUN python -m pip install --no-cache-dir /var/task

COPY lambdas/manifest_loader/handler.py /var/task/handler.py

CMD ["handler.handler"]
