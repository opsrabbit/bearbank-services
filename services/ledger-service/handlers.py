"""ledger-service — service-owned request handling.

This service owns no injected fault, so it simply fans out to its downstreams.
Add a `handle(request, config)` here to give it behaviour of its own.
"""

import time
from typing import Any


def handle(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    # Simulate database query with timeout handling per recommendation
    timeout_s = float(config.get("database", {}).get("query_timeout_ms", 15000) / 1000.0)
    start = time.perf_counter()
    time.sleep(0.045)
    elapsed_ms = (time.perf_counter() - start) * 1000
    if elapsed_ms > timeout_s * 1000:
        return {"status": "timeout"}
    return {"ledger_entry": "processed", "query_time_ms": round(elapsed_ms, 1)}
