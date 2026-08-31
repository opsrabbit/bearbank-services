"""
Fault mechanics for the BearBank demo.

Three primitives, composed into five scenarios by applying them to different
services. Fewer mechanics than scenarios on purpose: the "a fix proven on
another service" demo *requires* the same failure mode to recur somewhere new,
so reusing a mechanic is the point rather than a shortcut.

Every fault is **activated by config** so a scenario can be triggered without a
redeploy, but they are **fixed differently** — that distinction is what
exercises AutoSRE's config-vs-code remediation split:

    pool_exhaustion      -> fixed in bear-gitops        (config)
    divide_by_zero       -> fixed in bearbank-services  (code; config merely exposes it)
    pricing_engine_5xx   -> fixed in bearbank-services  (code)

The code faults are written to look like ordinary defects — a subtraction that
can reach zero, a lookup with no fallback — so the generated pull request reads
like a plausible code review rather than a puzzle.

Only pool exhaustion lives here. It is an infrastructure-level concern that
every service shares and that is fixed in config, so a shared implementation is
correct. The two code-fixed defects live in ``services/<name>/handlers.py``
instead: exactly one copy each, so a fix cannot land on the wrong service.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FaultSpec:
    """What a fault does and how AutoSRE is expected to respond to it."""

    name: str
    category: str        # triage category we expect
    fix_kind: str        # "config" | "code"
    fix_hint: str        # where the fix lands
    description: str


FAULTS: dict[str, FaultSpec] = {
    "pool_exhaustion": FaultSpec(
        name="pool_exhaustion",
        category="latency",
        fix_kind="config",
        fix_hint="database.connection_pool_size in bear-gitops",
        description=(
            "Connection pool starved. Latency climbs steeply as the pool shrinks "
            "and a fraction of requests start timing out."
        ),
    ),
    "divide_by_zero_guarded": FaultSpec(
        name="divide_by_zero_guarded",
        category="code_bug",
        fix_kind="code",
        fix_hint="compute_risk_weight in services/fraud-check/handlers.py",
        description=(
            "Excluding every band would once have divided by zero here. It is "
            "GUARDED now and the guard is deployed, so this reports a nonsensical "
            "config rather than a raising one — nothing can be scored when every "
            "band is excluded. Kept as the worked example of a code fix."
        ),
    ),
    "unknown_base_currency": FaultSpec(
        name="unknown_base_currency",
        category="code_bug",
        fix_kind="code",
        fix_hint="price_multiplier in services/fraud-check/handlers.py",
        description=(
            "Scores are normalised against a base currency read straight out of "
            "the multiplier table, so a base that is not configured raises "
            "KeyError on every request. Deliberately not keyed on "
            "features.new_pricing_engine, which already means pricing_engine_5xx "
            "and classifies as error_rate rather than code_bug."
        ),
    ),
    "pricing_engine_5xx": FaultSpec(
        name="pricing_engine_5xx",
        category="error_rate",
        fix_kind="code",
        fix_hint="apply_pricing in services/order-service/handlers.py",
        description=(
            "A new pricing path returns 503 when it meets an order shape it does "
            "not handle. Raises no Python exception, so it reads as an error-rate "
            "incident rather than a code bug."
        ),
    ),
}


# ---------------------------------------------------------------------------
# 1. Pool exhaustion — config-fixed
# ---------------------------------------------------------------------------

def latency_multiplier(config: dict[str, Any]) -> float:
    """Latency scale factor from the connection pool size.

    A starved pool makes every request queue behind a free connection, so
    latency rises sharply rather than linearly once the pool is too small for
    the offered load. Healthy pools return 1.0 and cost nothing.
    """
    pool_size = int(_dig(config, "database", "connection_pool_size", default=25) or 25)
    if pool_size >= 25:
        return 1.0
    if pool_size >= 10:
        return 2.0 + (25 - pool_size) * 0.2      # 2-5x
    if pool_size >= 1:
        return 8.0 + (10 - pool_size) * 4.0      # 8-44x
    return 50.0


def pool_is_starved(config: dict[str, Any]) -> bool:
    """True when the pool is small enough to also shed a few requests.

    Real pool exhaustion times out as well as slowing down, so the edge shows
    both signals. Latency alone is now enough — the graph flags a neighbour far
    slower than its siblings as ELEVATED LATENCY even at 0% errors — but shedding
    a few requests keeps this faithful to how pool exhaustion actually behaves.
    """
    pool_size = int(_dig(config, "database", "connection_pool_size", default=25) or 25)
    return pool_size < 5


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

def active_faults(config: dict[str, Any]) -> list[str]:
    """Which faults the current config would trigger. Drives /debug/faults."""
    active = []
    if int(_dig(config, "database", "connection_pool_size", default=25) or 25) < 25:
        active.append("pool_exhaustion")
    # `divide_by_zero` is GUARDED and the guard is deployed, so this reports a
    # config that WOULD have reached the old defect rather than one that raises.
    # Kept because the config is still worth flagging as nonsensical — excluding
    # every band means nothing can be scored — and because it documents what the
    # worked code-fix example was.
    risk = config.get("risk") or {}
    if int(risk.get("excluded_bands", 0) or 0) >= int(risk.get("bands", 10) or 10):
        active.append("divide_by_zero_guarded")
    if (config.get("features") or {}).get("new_pricing_engine"):
        active.append("pricing_engine_5xx")

    # The live code defect: price_multiplier reads its base straight out of the
    # multiplier table. A base currency that is not configured raises KeyError on
    # every request. Deliberately NOT keyed on new_pricing_engine, which already
    # means pricing_engine_5xx — two scenarios injecting one fault would make
    # them indistinguishable.
    pricing = config.get("pricing") or {}
    multipliers = pricing.get("multipliers") or {}
    base_currency = str(pricing.get("base_currency") or "USD")
    if base_currency not in multipliers:
        active.append("unknown_base_currency")

    return active


def should_shed(rate: float, rng: random.Random | None = None) -> bool:
    """Sample a failure at *rate*. Injectable RNG so tests are deterministic."""
    if rate <= 0:
        return False
    return (rng or random).random() < min(rate, 1.0)


def _dig(config: dict[str, Any], *path: str, default: Any = None) -> Any:
    """Read a nested config key, tolerating missing intermediate sections."""
    node: Any = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node if node is not None else default
