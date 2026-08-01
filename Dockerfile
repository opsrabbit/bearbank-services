# One image, ten services. Which one a container becomes is decided at runtime
# by BEARBANK_SERVICE; topology.py supplies the rest. Ten bespoke images would
# be ten build pipelines to keep in step for no benefit.
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
        "fastapi>=0.110" \
        "uvicorn[standard]>=0.27" \
        "httpx>=0.27" \
        "pydantic>=2.6" \
        "pyyaml>=6.0" \
        "opentelemetry-api>=1.24" \
        "opentelemetry-sdk>=1.24" \
        "opentelemetry-exporter-otlp-proto-grpc>=1.24" \
        "opentelemetry-instrumentation-fastapi>=0.45b0"

COPY demo/bearbank /app/demo/bearbank
COPY demo/__init__.py /app/demo/__init__.py

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    BEARBANK_SERVICE=checkout-api \
    OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317

# The port comes from topology.py, so the entrypoint resolves it rather than
# hard-coding one and drifting from the Service manifest.
CMD ["sh", "-c", "exec python -m uvicorn demo.bearbank.service:app --host 0.0.0.0 --port $(python -c \"from demo.bearbank.topology import get_service;import os;print(get_service(os.environ['BEARBANK_SERVICE']).port)\")"]
