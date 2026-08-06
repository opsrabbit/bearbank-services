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


def handle(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Score one request. Raises ZeroDivisionError when the defect is reached."""
    return {"risk_weight": compute_risk_weight(config)}
