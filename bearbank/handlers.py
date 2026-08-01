"""
Per-service handler loading.

Each service owns its business logic in ``services/<name>/handlers.py``. The
directories are named after the service, hyphens and all, so a repo path
matches a service name exactly — which is what lets the remediation agent's
discovery mode land on the right file. Hyphens are not importable as module
names, so handlers are loaded by path rather than by ``import``.

Only services that own a fault need a handler; the rest fall through to a
no-op. That is deliberate: it keeps exactly one copy of each defect in the
repo, so a code fix cannot be applied to the wrong service.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import Any

#: Where per-service handlers live.
#:
#: Overridable because the same runtime is deployed in two layouts: inside this
#: repo as ``demo/bearbank/services/``, and in each tenant's own
#: ``bearbank-services`` repo as a top-level ``services/`` next to the runtime
#: package. The org repo puts them at the root deliberately — a fix PR targeting
#: ``services/fraud-check/handlers.py`` reads like a normal service repo, which
#: is what the remediation agent's discovery mode has to navigate.
SERVICES_DIR = Path(
    os.getenv("BEARBANK_SERVICES_DIR")
    or Path(__file__).resolve().parent / "services"
)


def load_handler(service_name: str) -> ModuleType | None:
    """Load ``services/<service_name>/handlers.py``, or None if absent."""
    path = SERVICES_DIR / service_name / "handlers.py"
    if not path.exists():
        return None

    spec = importlib.util.spec_from_file_location(
        f"bearbank_handlers_{service_name.replace('-', '_')}", path
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_handler(
    handler: ModuleType | None, request: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    """Invoke a handler's ``handle``. Exceptions propagate on purpose.

    A fault must reach the span so triage can classify on it; swallowing it
    here would leave AutoSRE with a slow trace and no root cause.
    """
    if handler is None or not hasattr(handler, "handle"):
        return {}
    return handler.handle(request, config)
