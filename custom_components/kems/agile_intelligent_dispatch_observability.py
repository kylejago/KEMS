"""Retain Intelligent-dispatch replan evidence for later diagnostics.

Alpha8.64 owns the proven confirmed Intelligent start/end dispatch behaviour.
This successor adds observability only: transition evidence is retained on the
long-lived manager after subsequent coordinator scans so a later diagnostic can
prove the last confirmed start/end replan without changing routing or control.

This remains simulation/shadow only. It does not enable hardware writes.
"""

from __future__ import annotations

from typing import Any

from .agile_intelligent_dispatch_replan import (
    IntelligentDispatchReplanAgileSmartExportManager,
)

_REPLAN_SENSOR = "sensor.kems_intelligent_dispatch_replan"
_TRANSITIONS = {"confirmed_start", "confirmed_end"}
_HISTORY_LIMIT = 8


def _transition_evidence(diagnostic: dict[str, Any]) -> dict[str, Any]:
    """Copy the immutable proof fields for one confirmed transition."""
    return {
        "transition": diagnostic.get("transition"),
        "occurred_at": diagnostic.get("generated_at"),
        "previous_confirmed": diagnostic.get("previous_confirmed"),
        "confirmed": diagnostic.get("confirmed"),
        "previous_plan_soc_percent": diagnostic.get("previous_plan_soc_percent"),
        "replanned_soc_percent": diagnostic.get("replanned_soc_percent"),
        "plan_invalidated": diagnostic.get("plan_invalidated"),
        "replan_completed": diagnostic.get("replan_completed"),
        "current_slot_export_blocked": diagnostic.get("current_slot_export_blocked"),
        "hardware_writes": "blocked",
    }


def _retained_copy(value: Any) -> dict[str, Any] | None:
    """Return a defensive copy of retained transition evidence."""
    return dict(value) if isinstance(value, dict) else None


class IntelligentDispatchObservabilityAgileSmartExportManager(
    IntelligentDispatchReplanAgileSmartExportManager
):
    """Retain confirmed Intelligent transition proof without altering dispatch."""

    def _publish(self, state: dict[str, Any]) -> None:
        super()._publish(state)

        diagnostic = state.get("intelligent_dispatch_replan")
        if not isinstance(diagnostic, dict):
            return

        transition = str(diagnostic.get("transition") or "inactive")
        if transition in _TRANSITIONS:
            evidence = _transition_evidence(diagnostic)
            self._alpha865_last_transition_evidence = evidence
            if transition == "confirmed_start":
                self._alpha865_last_confirmed_start = evidence
            else:
                self._alpha865_last_confirmed_end = evidence

            history = list(getattr(self, "_alpha865_transition_history", ()) or ())
            history.append(evidence)
            self._alpha865_transition_history = history[-_HISTORY_LIMIT:]

        last_transition = _retained_copy(
            getattr(self, "_alpha865_last_transition_evidence", None)
        )
        last_start = _retained_copy(
            getattr(self, "_alpha865_last_confirmed_start", None)
        )
        last_end = _retained_copy(getattr(self, "_alpha865_last_confirmed_end", None))
        history = [
            dict(item)
            for item in list(getattr(self, "_alpha865_transition_history", ()) or ())[
                -_HISTORY_LIMIT:
            ]
            if isinstance(item, dict)
        ]

        diagnostic.update(
            {
                "last_transition": (
                    last_transition.get("transition") if last_transition else None
                ),
                "last_transition_at": (
                    last_transition.get("occurred_at") if last_transition else None
                ),
                "last_transition_evidence": last_transition,
                "last_confirmed_start": last_start,
                "last_confirmed_end": last_end,
                "transition_history": history,
                "transition_history_limit": _HISTORY_LIMIT,
                "retention_scope": "manager lifetime",
                "observability_owner": (
                    "IntelligentDispatchObservabilityAgileSmartExportManager"
                ),
                "hardware_writes": "blocked",
            }
        )
        state["intelligent_dispatch_replan"] = diagnostic

        self._set(
            _REPLAN_SENSOR,
            transition,
            {
                "friendly_name": "Intelligent dispatch rolling replan",
                **diagnostic,
            },
        )
