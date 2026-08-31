"""
fraud-check — risk scoring.

Service-owned logic. Lives here rather than in the shared runtime so a fix
targets exactly one service: a guard added to this file changes fraud-check and
nothing else, which is what a real code review of a single service's defect
looks like.
"""

from typing import Any


def compute_risk_weight(config: dict[str, Any]) -> float:
    """Weight a risk score across the active scoring bands.

    Scores are spread evenly over whichever bands remain after exclusions, so
    the weight of any one band is 1/active.

    This carried the demo's original latent defect: ``excluded_bands`` was
    subtracted without checking it left anything behind, so excluding every band
    divided by zero. Fixed by the guard below, and the fix is deployed — kept
    here as the worked example of what a code fix looks like.
    """
    risk = config.get("risk") or {}
    bands = int(risk.get("bands", 10) or 10)
    excluded = int(risk.get("excluded_bands", 0) or 0)

    active_bands = bands - excluded
    if active_bands <= 0:
        return 0.0
    return 1.0 / active_bands


def price_multiplier(request: dict[str, Any], config: dict[str, Any]) -> float:
    """Currency multiplier applied to a scored request.

    NOTE: this is the demo's deliberate latent defect, and it is reached only
    when ``features.new_pricing_engine`` is enabled — a half-finished engine
    behind a flag, which is how this kind of bug usually ships.

    The new path normalises every currency against a base rate, but reads that
    base straight out of the multiplier table without checking it is there. Turn
    the flag on without also configuring ``pricing.base_currency`` and every
    request raises KeyError.

    The fix belongs here, in code: the old path already defaults a missing
    currency, and the new one should do the same for its base. Turning the flag
    back off would merely stop reaching the defect, which is the wrong answer
    for the same reason it was wrong for the divide-by-zero above.
    """
    pricing = config.get("pricing") or {}
    multipliers = pricing.get("multipliers") or {}
    currency = str(request.get("currency") or "USD")

    if (config.get("features") or {}).get("new_pricing_engine"):
        base = multipliers[str(pricing.get("base_currency") or "XDR")]
        return multipliers.get(currency, 1.0) / base

    return multipliers.get(currency, 1.0)


def handle(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Score one request. Raises KeyError when the latent defect is reached."""
    return {
        "risk_weight": compute_risk_weight(config),
        "price_multiplier": price_multiplier(request, config),
    }
