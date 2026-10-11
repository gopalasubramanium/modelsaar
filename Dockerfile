# Local build only; no published image is claimed. The container runs the gateway;
# model execution stays with your inference runtime on the host or another container.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODELSAAR_IN_CONTAINER=1 \
    MODELSAAR_HOME=/data
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install --no-cache-dir . && adduser --disabled-password --gecos "" modelsaar \
    && mkdir -p /data && chown modelsaar /data
USER modelsaar
VOLUME ["/data"]
EXPOSE 8484
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8484/healthz').status==200 else 1)"
# Provide /data/config.yaml (see examples/config.docker.yaml) or run `modelsaar init` once.
CMD ["modelsaar", "serve"]
