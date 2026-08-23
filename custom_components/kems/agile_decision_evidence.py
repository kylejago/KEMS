"""Truthful evidence provenance for Full KEMS Agile settlement-slot reporting.

The underlying Agile optimiser remains untouched.  This reporting layer makes
an explicit distinction between a recorded historical simulation outcome, a
live rolling plan, deterministic tariff/event policy and a slot for which KEMS
has no retained decision evidence.  A historical replay placeholder such as
``future slot`` must never be presented as a deliberate battery hold.

Real hardware writes remain blocked.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from . import agile_dashboard_parity as parity

_MISSING_DECISION = "No KEMS decision recorded — runtime/data gap"
_NO_LIVE_PLAN = "Waiting for live rolling plan — no decision published"
_TABLE_HEADER = """          | Slot | Price | KEMS decision |
          |---|---:|---|
"""
_TABLE_HEADER_WITH_EVIDENCE = """          | Slot | Price | KEMS decision | Evidence |
          |---|---:|---|---|
"""
_TABLE_ROW = """          {% for slot in slots %}| {{ '▶ ' if slot.get('status') == 'current' else '' }}{{ slot.get('label') }} | {{ (slot.get('rate_pence') | round(2)) if slot.get('rate_pence') is not none else '—' }}{% if slot.get('rate_pence') is not none %}p{% endif %} | {{ slot.get('decision') }} |
"""
_TABLE_ROW_WITH_EVIDENCE = """          {% for slot in slots %}| {{ '▶ ' if slot.get('status') == 'current' else '' }}{{ slot.get('label') }} | {{ (slot.get('rate_pence') | round(2)) if slot.get('rate_pence') is not none else '—' }}{% if slot.get('rate_pence') is not none %}p{% endif %} | {{ slot.get('decision') }} | {{ slot.get('evidence_label', '—') }} |
"""


def _actions(value: Any) -> list[str]:
    """Return the raw historical action labels without inventing a decision."""
    return [str(item) for item in value or []]


def _classify_slot(
    slot: dict[str, Any],
    raw: dict[str, Any] | None,
    *,
    rolling_available: bool,
) -> dict[str, Any]:
    """Attach provenance and correct any unsupported decision presentation."""
    result = dict(slot)
    status = str(result.get("status") or "")
    decision = str(result.get("decision") or "")
    actions = _actions(raw.get("actions")) if isinstance(raw, dict) else []

    # A past slot that the replay still marks as future has no retained KEMS
    # sample.  This is exactly the restart/data-gap case that previously became
    # the misleading phrase "Hold battery / normal solar".
    if status == "past" and actions == ["future slot"]:
        result.update(
            {
                "decision": _MISSING_DECISION,
                "decision_source": "missing_historical_evidence",
                "evidence_available": False,
                "evidence_label": "No retained KEMS sample",
            }
        )
        return result

    if decision.startswith("Power Down —") or decision.startswith("Happy Hour —"):
        source = "event_priority"
        label = "Event priority"
        available = True
    elif (
        decision.startswith("Happy Hour prep —")
        or decision.startswith("Deadline guard —")
        or decision.startswith("Planned battery export")
    ):
        source = "rolling_plan"
        label = "Live rolling plan"
        available = True
    elif decision.startswith("Cheap period —"):
        source = "tariff_policy"
        label = "Tariff policy"
        available = True
    elif status == "past" and isinstance(raw, dict):
        source = "historical_simulation"
        label = "Recorded simulation"
        available = True
    elif raw is None:
        source = "price_publication"
        label = "No retained slot" if status == "past" else "Price publication"
        available = False
    elif status in {"current", "future"} and rolling_available:
        source = "rolling_plan"
        label = "Live rolling plan"
        available = True
    elif status in {"current", "future"}:
        result["decision"] = _NO_LIVE_PLAN
        source = "rolling_plan_unavailable"
        label = "No live plan"
        available = False
    else:
        source = "unknown"
        label = "Evidence unavailable"
        available = False

    result.update(
        {
            "decision_source": source,
            "evidence_available": available,
            "evidence_label": label,
        }
    )
    return result


def _slot_decisions_with_evidence(
    original,
    self,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Post-process the canonical slot table without changing dispatch."""
    slots = original(self, state)
    published = {
        str(item.get("valid_from")): item
        for item in state.get("today_slots", [])
        if isinstance(item, dict) and item.get("valid_from")
    }
    rolling_state = self._hass.states.get("sensor.kems_agile_rolling_export_plan")
    rolling_attrs = dict(rolling_state.attributes) if rolling_state is not None else {}
    rolling_available = bool(rolling_attrs.get("available"))

    return [
        _classify_slot(
            slot,
            published.get(str(slot.get("valid_from"))),
            rolling_available=rolling_available,
        )
        for slot in slots
    ]


def _dashboard_with_evidence(content: str) -> str:
    """Add decision provenance to the existing compact settlement table."""
    if _TABLE_HEADER not in content or _TABLE_ROW not in content:
        return content
    return content.replace(_TABLE_HEADER, _TABLE_HEADER_WITH_EVIDENCE, 1).replace(
        _TABLE_ROW,
        _TABLE_ROW_WITH_EVIDENCE,
        1,
    )


def install_decision_evidence() -> None:
    """Install reporting-only decision provenance after dashboard parity."""
    slot_decisions = parity._slot_decisions
    if not getattr(slot_decisions, "_kems_decision_evidence", False):
        original = slot_decisions

        def slot_decisions_with_evidence(self, state: dict[str, Any]):
            return _slot_decisions_with_evidence(original, self, state)

        slot_decisions_with_evidence._kems_decision_evidence = True
        parity._slot_decisions = slot_decisions_with_evidence

    if "| Evidence |" not in parity._REPLACEMENT_CARDS:
        parity._REPLACEMENT_CARDS = _dashboard_with_evidence(parity._REPLACEMENT_CARDS)
