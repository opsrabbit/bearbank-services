"""
BearBank demo estates — the single source of truth for who calls whom.

Two independent 5-service estates, one per tenant. The k8s manifests, the repo
seeding script, the load generator and the tests all read this module, so the
topology is defined once and cannot drift between them.

Why real services at all: the previous demo simulated its downstream calls —
``call_downstream_service`` opened a client span and then slept, never issuing a
request. Jaeger therefore saw a single service and produced an empty dependency
DAG, so every knowledge-graph feature that depends on architecture (blast
radius, "the fault is downstream", "this was fixed elsewhere") had nothing to
render. These services call each other over HTTP for real.

The estates are deliberately three levels deep — ``checkout-api ->
payment-service -> ledger-service`` — so a 2-hop graph walk returns something a
1-hop walk cannot.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceSpec:
    """One demo service. Frozen: the topology is data, not state."""

    name: str
    tenant: str                       # AutoSRE tenant slug
    org: str                          # GitHub org owning its repos
    port: int
    downstreams: tuple[str, ...] = ()
    datastore: str | None = None      # e.g. "postgresql:payments" -> DEPENDS_ON node
    team: str = "platform"
    tier: int = 2
    latency_threshold_ms: int = 1500
    error_rate_threshold_percent: float = 5.0
    #: Receives load-generator traffic. Only the estate's front door.
    entrypoint: bool = False
    description: str = ""

    @property
    def namespace(self) -> str:
        return f"bearbank-{self.tenant}"

    @property
    def source_repository(self) -> str:
        """Repo a code fix targets."""
        return f"{self.org}/bearbank-services"

    @property
    def gitops_repository(self) -> str:
        """Repo a config fix targets."""
        return f"{self.org}/bear-gitops"

    @property
    def config_path(self) -> str:
        return f"config/{self.name}.yaml"

    @property
    def source_path(self) -> str:
        return f"services/{self.name}"


# ---------------------------------------------------------------------------
# opsrabbit -> tenant "default" -> namespace bearbank-default
#
#   checkout-api -> payment-service -> ledger-service
#                                   -> fraud-check
#                                   -> notification-service
# ---------------------------------------------------------------------------

_RABBIT = [
    ServiceSpec(
        name="checkout-api", tenant="default", org="opsrabbit", port=8080,
        downstreams=("payment-service",), datastore="redis:sessions",
        team="storefront", tier=1, entrypoint=True, latency_threshold_ms=2000,
        description="Front door. Takes a basket and asks payment-service to settle it.",
    ),
    ServiceSpec(
        name="payment-service", tenant="default", org="opsrabbit", port=8081,
        downstreams=("ledger-service", "fraud-check", "notification-service"),
        datastore="postgresql:payments", team="payments", tier=1,
        latency_threshold_ms=1500,
        description="Fans out to ledger, fraud and notification. The busiest node.",
    ),
    ServiceSpec(
        name="ledger-service", tenant="default", org="opsrabbit", port=8082,
        datastore="postgresql:ledger", team="payments", tier=1,
        # Deliberately LOOSER than payment-service's 1500ms, and this is the
        # crux of the cascade scenario. Ledger is a batch-ish write path where
        # seconds are tolerable; payment-service is user-facing with a tighter
        # SLO. So ledger can degrade badly enough to break its caller while
        # staying comfortably inside its own threshold — it never alarms, and
        # the only incident is on payment-service. That is precisely how real
        # cascades hide, and without the call graph there is nothing pointing
        # at ledger at all.
        latency_threshold_ms=3000,
        description="Double-entry write. Looser SLO than its caller, so it can "
                    "degrade without alarming — the cascade hides here.",
    ),
    ServiceSpec(
        name="fraud-check", tenant="default", org="opsrabbit", port=8083,
        datastore="redis:risk-scores", team="risk", tier=2,
        latency_threshold_ms=800,
        description="Risk scoring. Home of the latent divide-by-zero.",
    ),
    ServiceSpec(
        name="notification-service", tenant="default", org="opsrabbit", port=8084,
        datastore="postgresql:notifications", team="growth", tier=3,
        latency_threshold_ms=1000,
        description="Receipts and alerts. Never fails until repeat-failure runs.",
    ),
]

# ---------------------------------------------------------------------------
# opsbear -> tenant "acme-corp" -> namespace bearbank-acme-corp
#
#   storefront-api -> order-service -> inventory-service
#                                   -> billing-service
#                                   -> shipping-service
#
# A different domain on purpose, so the demo reads as two customers rather than
# one application deployed twice.
# ---------------------------------------------------------------------------

_BEAR = [
    ServiceSpec(
        name="storefront-api", tenant="acme-corp", org="opsbear", port=8080,
        downstreams=("order-service",), datastore="redis:carts",
        team="web", tier=1, entrypoint=True, latency_threshold_ms=2000,
        description="Front door for the Acme retail estate.",
    ),
    ServiceSpec(
        name="order-service", tenant="acme-corp", org="opsbear", port=8081,
        downstreams=("inventory-service", "billing-service", "shipping-service"),
        datastore="postgresql:orders", team="orders", tier=1,
        latency_threshold_ms=1500,
        description="Order orchestration. Target of the bad-deploy scenario.",
    ),
    ServiceSpec(
        name="inventory-service", tenant="acme-corp", org="opsbear", port=8082,
        datastore="postgresql:inventory", team="supply", tier=2,
        latency_threshold_ms=1000,
        description="Stock levels and reservation.",
    ),
    ServiceSpec(
        name="billing-service", tenant="acme-corp", org="opsbear", port=8083,
        datastore="postgresql:billing", team="finance", tier=1,
        latency_threshold_ms=1200,
        description="Invoicing.",
    ),
    ServiceSpec(
        name="shipping-service", tenant="acme-corp", org="opsbear", port=8084,
        datastore="postgresql:shipments", team="supply", tier=3,
        latency_threshold_ms=1000,
        description="Carrier dispatch.",
    ),
]


ESTATES: dict[str, list[ServiceSpec]] = {
    "default": _RABBIT,
    "acme-corp": _BEAR,
}

ALL_SERVICES: list[ServiceSpec] = [s for estate in ESTATES.values() for s in estate]

_BY_NAME: dict[str, ServiceSpec] = {s.name: s for s in ALL_SERVICES}


def get_service(name: str) -> ServiceSpec:
    """Look up a service by name. Raises with the valid set on a typo."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"unknown service {name!r}; known: {sorted(_BY_NAME)}"
        ) from None


def estate_for(tenant: str) -> list[ServiceSpec]:
    """All services belonging to a tenant."""
    if tenant not in ESTATES:
        raise KeyError(f"unknown tenant {tenant!r}; known: {sorted(ESTATES)}")
    return ESTATES[tenant]


def entrypoint_for(tenant: str) -> ServiceSpec:
    """The service the load generator drives. Exactly one per estate."""
    return next(s for s in estate_for(tenant) if s.entrypoint)


def callers_of(name: str) -> list[ServiceSpec]:
    """Services that call *name* — the reverse edge the graph walks inbound."""
    return [s for s in ALL_SERVICES if name in s.downstreams]


def downstream_url(name: str, spec: ServiceSpec | None = None) -> str:
    """In-cluster URL for a downstream.

    Kubernetes Services are namespace-scoped and every service in an estate
    shares a namespace, so the bare name resolves. Overridable per service via
    ``BEARBANK_URL_<NAME>`` for running the estate locally.
    """
    import os

    override = os.getenv(f"BEARBANK_URL_{name.upper().replace('-', '_')}")
    if override:
        return override
    spec = spec or get_service(name)
    return f"http://{name}:{spec.port}"
