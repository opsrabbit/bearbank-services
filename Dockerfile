# One image, all of this tenant's services. BEARBANK_SERVICE picks which.
FROM python:3.11-slim
WORKDIR /app

RUN pip install --no-cache-dir \
        "fastapi>=0.110" "uvicorn[standard]>=0.27" "httpx>=0.27" \
        "pydantic>=2.6" "pyyaml>=6.0" \
        "opentelemetry-api>=1.24" "opentelemetry-sdk>=1.24" \
        "opentelemetry-exporter-otlp-proto-grpc>=1.24" \
        "opentelemetry-exporter-otlp-proto-http>=1.24" \
        "opentelemetry-instrumentation-fastapi>=0.45b0"

COPY bearbank /app/bearbank
COPY services /app/services

# The in-cluster default. A deployment that exports through FlockOps' public
# authenticated endpoint overrides all three of these — endpoint, protocol, and
# OTEL_EXPORTER_OTLP_HEADERS carrying the ingest token — which is what a real
# customer's service is configured with. The token never belongs in the image.
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    BEARBANK_SERVICES_DIR=/app/services \
    BEARBANK_SERVICE=checkout-api \
    OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317 \
    OTEL_EXPORTER_OTLP_PROTOCOL=grpc

# Port comes from topology.py so it cannot drift from the Service manifest.
CMD ["sh", "-c", "exec python -m uvicorn bearbank.service:app --host 0.0.0.0 --port $(python -c \"from bearbank.topology import get_service;import os;print(get_service(os.environ['BEARBANK_SERVICE']).port)\")"]
