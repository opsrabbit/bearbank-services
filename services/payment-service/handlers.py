"""payment-service — service-owned request handling.

This service owns no injected fault, so it simply fans out to its downstreams.
Add a `handle(request, config)` here to give it behaviour of its own.
"""

from typing import Any


def handle(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    # Ensure consistent response structure for latency tracking and downstream fan-out
    return {"status": "ok"}
