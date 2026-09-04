"""Session-scoped physical telemetry evidence for KEMS commissioning.

Commissioning proof is deliberately not persisted. A Home Assistant restart,
physical source remap, unit change, or loss of the FoxESS mapping gate must
start a fresh evidence window so pre-install history cannot satisfy physical
commissioning checks.
"""

from __future__ import annotations

from typing import Any

SESSION_ATTR = "_foxess_commissioning_session"
DEFAULT_MAX_RECORDS = 360


def _timestamp_text(value: Any) -> str | None:
    """Return one diagnostic-safe timestamp string."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def collect_foxess_session_records(
    owner: Any,
    *,
    source_signature: tuple[tuple[str, str | None], ...],
    snapshot: Any,
    ready: bool,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Return fresh-session FoxESS evidence and its commissioning metadata.

    The caller supplies a deterministic signature containing the authoritative
    physical source identities and raw units. Any signature change invalidates
    the previous window. Evidence is also cleared whenever the physical mapping
    gate is not ready. Only strictly newer snapshot timestamps are retained, so
    repeated sensor-property reads cannot duplicate one coordinator sample.
    """
    session = getattr(owner, SESSION_ATTR, None)
    reset_reason: str | None = None

    if not ready:
        reset_reason = "physical_sources_not_ready"
        session = {
            "signature": source_signature,
            "records": [],
            "started_at": None,
            "reset_reason": reset_reason,
        }
        setattr(owner, SESSION_ATTR, session)
    elif not isinstance(session, dict):
        reset_reason = "session_started"
        session = {
            "signature": source_signature,
            "records": [],
            "started_at": None,
            "reset_reason": reset_reason,
        }
        setattr(owner, SESSION_ATTR, session)
    elif session.get("signature") != source_signature:
        reset_reason = "source_signature_changed"
        session = {
            "signature": source_signature,
            "records": [],
            "started_at": None,
            "reset_reason": reset_reason,
        }
        setattr(owner, SESSION_ATTR, session)

    records = session["records"]
    if ready:
        timestamp = getattr(snapshot, "timestamp", None)
        previous_timestamp = (
            getattr(records[-1], "timestamp", None) if records else None
        )
        if timestamp is not None and (
            previous_timestamp is None or timestamp > previous_timestamp
        ):
            records.append(snapshot)
            if session["started_at"] is None:
                session["started_at"] = timestamp
            limit = max(int(max_records), 1)
            if len(records) > limit:
                del records[:-limit]

    metadata = {
        "scope": "current coordinator session only",
        "persistent": False,
        "sample_count": len(records),
        "started_at": _timestamp_text(session.get("started_at")),
        "reset_reason": reset_reason or session.get("reset_reason"),
        "source_signature": [
            {"role": role, "identity": identity}
            for role, identity in source_signature
        ],
    }
    return tuple(records), metadata
