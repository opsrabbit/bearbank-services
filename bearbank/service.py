"""
BearBank demo service — one implementation, ten deployments.

Which service this process *is* comes from ``BEARBANK_SERVICE``; everything else
(who it calls, which datastore it touches, what port it listens on) is looked up
in ``topology.py``. Ten bespoke services would be ten times the code and would
drift; this way the topology is declared once.

The important part is ``call_downstream``: it issues a **real HTTP request** with
trace context propagated. That is what produces genuine parent/child spans across
processes, which is what Jaeger's dependency DAG and the knowledge graph are
built from. The previous demo simulated this and the graph saw nothing.

Config arrives as a mounted file. ArgoCD syncs the tenant's GitOps repo into a
ConfigMap, Kubernetes mounts it, and this process re-reads it on an interval —
so a merged config PR takes effect without a redeploy, which is what lets an
incident auto-resolve during a live demo. Nothing here talks to GitHub.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode
from pydantic import BaseModel

from bearbank import faults
from bearbank.handlers import load_handler, run_handler
from bearbank.topology import ServiceSpec, downstream_url, get_service

SERVICE_NAME = os.getenv("BEARBANK_SERVICE", "checkout-api")
SPEC: ServiceSpec = get_service(SERVICE_NAME)

#: This service's own logic, from services/<name>/handlers.py. None for the
#: services that own no fault — they just fan out.
HANDLER = load_handler(SERVICE_NAME)

CONFIG_RELOAD_SECONDS = int(os.getenv("CONFIG_RELOAD_SECONDS", "30"))
DOWNSTREAM_TIMEOUT_S = float(os.getenv("DOWNSTREAM_TIMEOUT_S", "10"))

# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

def _span_exporter():
    """Build the span exporter the way a customer's service would.

    A real customer does not hand-roll this: they set the standard
    ``OTEL_EXPORTER_OTLP_*`` variables and let the SDK read them. BearBank exists
    to mirror a customer estate, so on the HTTP path it constructs the exporter
    with **no arguments at all** and lets the SDK do exactly that. That is not
    only more faithful, it dodges a real trap — an explicit ``endpoint=`` is used
    VERBATIM by the HTTP exporter, while an endpoint the SDK reads from the
    environment gets ``/v1/traces`` appended. Passing it in means remembering the
    signal path; not passing it means the SDK is right by construction.

    ⚠️ gRPC (4317) and HTTP (4318) are different endpoints, not a preference, and
    the wrong one fails on the BatchSpanProcessor thread: no exception, no failed
    request, no log line, just spans that never arrive. ``insecure=`` exists only
    on the gRPC exporter — passing it to the HTTP one is a TypeError at import
    time, which is at least loud.
    """
    protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")

    if protocol.startswith("http"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HTTPSpanExporter,
        )

        # A misconfiguration that otherwise presents as silence: 4317 is the gRPC
        # port, so an HTTP exporter aimed at it delivers nothing and says nothing.
        if ":4317" in endpoint:
            print(
                f"[otel] WARNING {SERVICE_NAME}: protocol is {protocol} but the "
                f"endpoint is {endpoint} — :4317 is the gRPC port, so no spans "
                "will arrive. Use the OTLP/HTTP endpoint.",
                flush=True,
            )
        # No arguments: endpoint (plus /v1/traces) and OTEL_EXPORTER_OTLP_HEADERS
        # both come from the environment, which is where a customer puts them and
        # where the ingest token belongs — never in the image.
        print(f"[otel] {SERVICE_NAME}: http/protobuf -> {endpoint}", flush=True)
        return HTTPSpanExporter()

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter as GRPCSpanExporter,
    )

    print(f"[otel] {SERVICE_NAME}: grpc -> {endpoint}", flush=True)
    return GRPCSpanExporter(endpoint=endpoint, insecure=True)


_provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
_provider.add_span_processor(BatchSpanProcessor(_span_exporter()))
trace.set_tracer_provider(_provider)
tracer = trace.get_tracer(__name__)

# ---------------------------------------------------------------------------
# Config — served from the tenant's GitOps repo
# ---------------------------------------------------------------------------

#: Healthy defaults. A scenario makes the estate ill by changing the repo copy,
#: never by changing these.
DEFAULT_CONFIG: dict[str, Any] = {
    "database": {"connection_pool_size": 25, "query_timeout_ms": 15000},
    "risk": {"bands": 10, "excluded_bands": 0},
    "features": {"new_pricing_engine": False},
    "pricing": {"multipliers": {"USD": 1.0, "GBP": 1.27, "EUR": 1.08},
                "base_currency": "USD"},
    "service": {"artificial_latency_ms": 0},
}

_config: dict[str, Any] = dict(DEFAULT_CONFIG)
_config_source = "defaults"


def current_config() -> dict[str, Any]:
    return _config


async def _load_config() -> None:
    """Refresh config from the mounted file.

    The file is the ONLY mechanism, deliberately. ArgoCD watches the tenant's
    GitOps repo, generates a ConfigMap from it, and Kubernetes mounts that at
    /config; the kubelet refreshes the mounted file within about a minute of
    the ConfigMap changing. So a merged config-fix PR reaches a running pod
    without this process ever talking to GitHub.

    An earlier version also fetched from raw.githubusercontent as a fallback.
    That was dead weight — the GitOps repos are private, so it always failed —
    and worse, it was a second config path that could disagree with the one
    ArgoCD manages. Removed rather than fixed.

    A read failure leaves the previous config in place. Falling back to healthy
    defaults mid-scenario would make a fault appear to fix itself.
    """
    global _config, _config_source

    path = os.getenv("CONFIG_FILE_PATH", f"/config/{SERVICE_NAME}.yaml")
    if not os.path.exists(path):
        return                       # keep defaults until ArgoCD lands the mount
    try:
        with open(path) as fh:
            loaded = yaml.safe_load(fh) or {}
        _config = {**DEFAULT_CONFIG, **loaded}
        _config_source = f"file:{path}"
    except Exception as exc:  # noqa: BLE001 — demo service, never crash on config
        print(f"config read failed ({path}): {exc}")


async def _config_reload_loop() -> None:
    while True:
        await asyncio.sleep(CONFIG_RELOAD_SECONDS)
        await _load_config()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class WorkRequest(BaseModel):
    order_id: str = "demo-order"
    amount: float = 42.0
    currency: str = "USD"
    depth: int = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _load_config()
    task = asyncio.create_task(_config_reload_loop())
    print(f"{SERVICE_NAME} up — downstreams={list(SPEC.downstreams)} config={_config_source}")
    yield
    task.cancel()


app = FastAPI(title=f"BearBank — {SERVICE_NAME}", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "healthy", "service": SERVICE_NAME}


@app.get("/ready")
async def ready() -> dict[str, Any]:
    return {"status": "ready", "service": SERVICE_NAME}


@app.get("/debug/config")
async def debug_config() -> dict[str, Any]:
    """What this pod believes, and which faults that belief activates."""
    return {
        "service": SERVICE_NAME,
        "tenant": SPEC.tenant,
        "source": _config_source,
        "config": _config,
        "active_faults": faults.active_faults(_config),
        "downstreams": list(SPEC.downstreams),
    }


async def _simulate_datastore() -> None:
    """Emit a client span for the service's datastore.

    Carries the OTEL ``db.system`` attributes the graph's span-topology parser
    reads to create DEPENDS_ON dependency nodes. This one is genuinely
    simulated — the demo has no real Postgres per service, and a dependency
    node only needs the attributes.
    """
    if not SPEC.datastore:
        return
    system, _, instance = SPEC.datastore.partition(":")
    with tracer.start_as_current_span(f"{system} query", kind=SpanKind.CLIENT) as span:
        span.set_attribute("db.system", system)
        span.set_attribute("db.name", instance)
        span.set_attribute("peer.service", SPEC.datastore)
        await asyncio.sleep(random.uniform(0.004, 0.02))


async def call_downstream(name: str, payload: WorkRequest) -> dict[str, Any]:
    """Issue a REAL HTTP call to a downstream service.

    This is the difference between this demo and the previous one. A simulated
    span with a ``peer.service`` attribute never becomes an edge in Jaeger's
    dependency DAG, because there is no second process reporting the other half
    of the call. Trace context is injected into the headers so the child span
    lands in the same trace and the parent/child relationship survives.
    """
    url = f"{downstream_url(name)}/work"
    headers: dict[str, str] = {}
    inject(headers)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json=payload.model_dump() | {"depth": payload.depth + 1},
            headers=headers,
            timeout=DOWNSTREAM_TIMEOUT_S,
        )
    if resp.status_code >= 500:
        raise HTTPException(
            status_code=502,
            detail=f"downstream {name} returned {resp.status_code}",
        )
    return resp.json()


@app.post("/work")
async def work(request: WorkRequest) -> dict[str, Any]:
    """The estate's single unit of work.

    Applies whatever faults the current config activates, touches its datastore,
    then fans out to its downstreams. Every service runs the same shape, so the
    trace depth mirrors the topology.
    """
    started = time.perf_counter()
    span = trace.get_current_span()
    span.set_attribute("bearbank.service", SERVICE_NAME)
    span.set_attribute("bearbank.tenant", SPEC.tenant)

    config = current_config()

    # --- service-owned logic, and the faults it may raise ------------------
    #
    # Whatever services/<name>/handlers.py does. Exceptions are recorded on the
    # span and re-raised: the exception type must reach the span logs, because
    # that is what summarize_trace_exceptions classifies on. A Python builtin
    # (ZeroDivisionError from fraud-check) becomes category=code_bug; anything
    # else (PricingUnavailable from order-service) stays an error-rate signal.
    try:
        for key, value in run_handler(HANDLER, request.model_dump(), config).items():
            span.set_attribute(f"bearbank.{key}", value)
    except Exception as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        status = 500 if isinstance(exc, ArithmeticError) else 503
        span.set_attribute("http.status_code", status)
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    # --- fault: pool exhaustion (latency, and errors when severe) ----------
    multiplier = faults.latency_multiplier(config)
    base_ms = 20 + random.uniform(0, 30)
    extra_ms = float((config.get("service") or {}).get("artificial_latency_ms", 0) or 0)
    delay_s = (base_ms * multiplier + extra_ms) / 1000.0
    span.set_attribute("bearbank.latency_multiplier", multiplier)
    await asyncio.sleep(delay_s)

    if faults.pool_is_starved(config) and faults.should_shed(0.25):
        span.set_status(Status(StatusCode.ERROR, "connection pool exhausted"))
        span.set_attribute("http.status_code", 503)
        raise HTTPException(status_code=503, detail="connection pool exhausted")

    await _simulate_datastore()

    # --- fan out ----------------------------------------------------------
    results = {}
    for name in SPEC.downstreams:
        results[name] = await call_downstream(name, request)

    return {
        "service": SERVICE_NAME,
        "order_id": request.order_id,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "downstream": results,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=SPEC.port)
