"""Read-only metadata for explicitly requested Home Assistant Core restarts.

The call_service event proves a restart was requested through a Home Assistant
service, but its context does not prove which integration, automation or person
was responsible. Do not persist or print user identifiers or service arguments.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def classify_restart_service_call(event: Any, *, now: datetime) -> dict[str, Any] | None:
    """Return bounded, non-identifying evidence for a Core restart request."""
    data = getattr(event, "data", None)
    if not isinstance(data, dict):
        return None
    if data.get("domain") != "homeassistant" or data.get("service") != "restart":
        return None

    context = getattr(event, "context", None)
    return {
        "status": "restart_service_called",
        "observed_at": now.isoformat(),
        "user_context_present": getattr(context, "user_id", None) is not None,
        "parent_context_present": getattr(context, "parent_id", None) is not None,
        "source": "homeassistant_call_service_event",
        "attribution": (
            "Request confirmed; context flags alone do not establish an "
            "actor or distinguish an update, automation, integration or UI action"
        ),
        "hardware_writes": "none",
    }
