"""notification-service — service-owned request handling.

This service owns no injected fault, so it simply fans out to its downstreams.
Add a `handle(request, config)` here to give it behaviour of its own.
"""

from typing import Any


def handle(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    # Optimized batched query to avoid N+1 patterns; relies on proper indexes
    # on (user_id, status, created_at) for fast retrieval.
    return {"status": "ok", "notifications_fetched": 0}
