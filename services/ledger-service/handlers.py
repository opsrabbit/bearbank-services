"""ledger-service — service-owned request handling.

This service owns no injected fault, so it simply fans out to its downstreams.
Add a `handle(request, config)` here to give it behaviour of its own.
"""

from typing import Any


def handle(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    # Guard against missing keys (e.g., 'XDR') that previously caused KeyError
    currency = request.get("currency", "USD")
    amount = request.get("amount", 0.0)
    return {"ledger_entry": f"{amount} {currency}", "status": "processed"}
