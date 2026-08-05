"""ledger-service — service-owned request handling.

This service owns no injected fault, so it simply fans out to its downstreams.
Add a `handle(request, config)` here to give it behaviour of its own.
"""

from typing import Any


def handle(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    # Guard against missing or malformed request data to prevent unhandled exceptions
    if not isinstance(request, dict) or "order_id" not in request:
        return {"status": "skipped", "reason": "missing_order_id"}
    return {"status": "processed"}
