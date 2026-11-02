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

    NOTE: this is the demo's deliberate latent defect. ``excluded_bands`` is
    subtracted without checking it leaves anything behind, so excluding every
    band divides by zero. The fix belongs here, in code — a config change that
    merely stops reaching it would leave the defect in place.
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

    NOTE: this is the demo's latent defect, and it replaced the divide-by-zero
    above once that was fixed AND deployed — a scenario whose defect is guarded
    in production tests nothing, and fails quietly, because no incident fires
    and it reads as "the agent did nothing".

    Scores are normalised against a base currency, but the base is read straight
    out of the multiplier table without checking it is there. Point
    ``pricing.base_currency`` at a currency that is not configured and every
    request raises KeyError.

    The fix belongs here, in code: the per-request lookup below already defaults
    a missing currency, and the base should do the same. Pointing the config back
    at a configured currency would merely stop reaching the defect, which is the
    wrong answer for the same reason it was wrong for the divide-by-zero.
    """
    pricing = config.get("pricing") or {}
    multipliers = pricing.get("multipliers") or {}
    currency = str(request.get("currency") or "USD")

    base_currency = str(pricing.get("base_currency") or "USD")
    base = multipliers[base_currency]
    return multipliers.get(currency, 1.0) / base


def handle(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Score one request. Raises KeyError when the latent defect is reached."""
    return {
        "risk_weight": compute_risk_weight(config),
        "price_multiplier": price_multiplier(request, config),
    }
