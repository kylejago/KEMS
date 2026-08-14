"""Persistent completed Power Down event history for KEMS."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core import (
    ControlState,
    PowerDownAuditState,
    PowerDownResult,
    SimulationState,
    Snapshot,
    finalise_power_down_audit,
)

STORAGE_VERSION = 1


class PowerDownHistoryRecorder:
    """Retain the last completed event after Octopus removes the live entity."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.power_down",
        )
        self._last = PowerDownResult()
        self._pending: dict[str, Any] | None = None

    @property
    def last_result(self) -> PowerDownResult:
        """Return the retained completed event."""
        return self._last

    async def async_load(self) -> None:
        """Restore the retained result and any in-progress session."""
        data = await self._store.async_load()
        if not data:
            return
        self._last = self._normalise_legacy_result(
            PowerDownResult.from_dict(data.get("last_result", {}))
        )
        pending = data.get("pending")
        if isinstance(pending, dict):
            self._pending = dict(pending)

    @staticmethod
    def _normalise_legacy_result(result: PowerDownResult) -> PowerDownResult:
        """Upgrade old zero-sample failures to an evidence-safe result.

        Earlier Alpha 7 builds could persist a failed Power Down result even
        when KEMS had not observed a single active-session controller sample.
        Keep the useful session/financial history, but make the safety outcome
        explicitly inconclusive on load.
        """
        if not result.available or result.active_samples_observed > 0:
            return result
        if result.completion_reason not in {
            "session_activity_not_observed",
            "plan_or_ev_safety_check_failed",
            "insufficient_active_samples",
        }:
            return result
        values = result.to_dict()
        values.update(
            {
                "ev_successfully_blocked": None,
                "plan_safe_throughout": None,
                "island_override_observed": None,
                "completed_successfully": None,
                "completion_reason": "insufficient_active_samples",
            }
        )
        return PowerDownResult.from_dict(values)

    async def async_update(
        self,
        snapshot: Snapshot,
        simulation: SimulationState,
        control: ControlState,
        now: datetime,
    ) -> PowerDownResult:
        """Capture an active event and finalise it exactly once after its end."""
        session_start = simulation.saving_session_start or snapshot.saving_session_start
        session_end = simulation.saving_session_end or snapshot.saving_session_end
        session_id = snapshot.saving_session_id or (
            session_start.isoformat() if session_start is not None else None
        )
        session_known = bool(
            session_id
            and session_start is not None
            and session_end is not None
            and (snapshot.saving_session_joined or simulation.saving_session_joined)
            and (
                now >= session_start
                or snapshot.saving_session_active
                or simulation.saving_session_active
            )
        )
        already_completed = bool(
            self._last.available and self._last.session_id == session_id
        )

        if session_known and not already_completed:
            if self._pending is None or self._pending.get("session_id") != session_id:
                duration_hours = max(
                    (session_end - session_start).total_seconds() / 3600,
                    0.0,
                )
                self._pending = {
                    "session_id": session_id,
                    "session_start": session_start.isoformat(),
                    "session_end": session_end.isoformat(),
                    "starting_simulated_soc_percent": simulation.simulated_battery_soc,
                    "finishing_simulated_soc_percent": simulation.simulated_battery_soc,
                    "planned_battery_to_home_kwh": round(
                        control.desired_battery_to_home_power_kw * duration_hours,
                        3,
                    ),
                    "planned_export_kwh": (
                        simulation.estimated_saving_session_export_kwh
                    ),
                    "maximum_inverter_output_kw": control.total_kh7_ac_output_kw,
                    "rewardable_reduction_kwh": (
                        simulation.estimated_saving_session_rewardable_reduction_kwh
                    ),
                    "bonus_pence": simulation.estimated_saving_session_bonus_pence,
                    "fixed_export_income_pence": (
                        simulation.estimated_saving_session_export_income_pence
                    ),
                    "combined_income_pence": (
                        simulation.estimated_saving_session_total_income_pence
                    ),
                    "active_samples_observed": 0,
                    "ev_successfully_blocked": True,
                    "plan_safe_throughout": True,
                    "island_override_observed": False,
                }
            else:
                self._pending["finishing_simulated_soc_percent"] = (
                    simulation.simulated_battery_soc
                )
                self._pending["maximum_inverter_output_kw"] = max(
                    float(self._pending.get("maximum_inverter_output_kw") or 0.0),
                    control.total_kh7_ac_output_kw,
                )
                for pending_key, value in (
                    (
                        "planned_export_kwh",
                        simulation.estimated_saving_session_export_kwh,
                    ),
                    (
                        "rewardable_reduction_kwh",
                        simulation.estimated_saving_session_rewardable_reduction_kwh,
                    ),
                    ("bonus_pence", simulation.estimated_saving_session_bonus_pence),
                    (
                        "fixed_export_income_pence",
                        simulation.estimated_saving_session_export_income_pence,
                    ),
                    (
                        "combined_income_pence",
                        simulation.estimated_saving_session_total_income_pence,
                    ),
                ):
                    if value is not None:
                        self._pending[pending_key] = value

            active_now = bool(
                session_start <= now < session_end
                and (snapshot.saving_session_active or simulation.saving_session_active)
            )
            audit = PowerDownAuditState(
                active_samples_observed=int(
                    self._pending.get("active_samples_observed", 0) or 0
                ),
                ev_successfully_blocked=bool(
                    self._pending.get("ev_successfully_blocked", True)
                ),
                plan_safe_throughout=bool(
                    self._pending.get(
                        "plan_safe_throughout",
                        self._pending.get("plan_safe", True),
                    )
                ),
                island_override_observed=bool(
                    self._pending.get(
                        "island_override_observed",
                        self._pending.get("island_override", False),
                    )
                ),
            ).observe(
                session_active=active_now,
                desired_ev_charging_allowed=control.desired_ev_charging_allowed,
                plan_safe=control.plan_safe,
                island_mode_active=control.island_mode_active,
            )
            self._pending.update(
                {
                    "active_samples_observed": audit.active_samples_observed,
                    "ev_successfully_blocked": audit.ev_successfully_blocked,
                    "plan_safe_throughout": audit.plan_safe_throughout,
                    "island_override_observed": audit.island_override_observed,
                }
            )

        if self._pending is not None:
            pending_end = datetime.fromisoformat(str(self._pending["session_end"]))
            if now >= pending_end:
                audit = PowerDownAuditState(
                    active_samples_observed=int(
                        self._pending.get("active_samples_observed", 0) or 0
                    ),
                    ev_successfully_blocked=bool(
                        self._pending.get("ev_successfully_blocked", False)
                    ),
                    plan_safe_throughout=bool(
                        self._pending.get("plan_safe_throughout", False)
                    ),
                    island_override_observed=bool(
                        self._pending.get("island_override_observed", False)
                    ),
                )
                completed, reason = finalise_power_down_audit(audit)
                evidence_available = completed is not None
                self._last = PowerDownResult.from_dict(
                    {
                        **self._pending,
                        "available": True,
                        "active_samples_observed": audit.active_samples_observed,
                        "ev_successfully_blocked": (
                            audit.ev_successfully_blocked
                            if evidence_available
                            else None
                        ),
                        "plan_safe_throughout": (
                            audit.plan_safe_throughout if evidence_available else None
                        ),
                        "island_override_observed": (
                            audit.island_override_observed
                            if evidence_available
                            else None
                        ),
                        "completed_successfully": completed,
                        "completion_reason": reason,
                    }
                )
                self._pending = None

        await self.async_save()
        return self._last

    async def async_save(self) -> None:
        """Persist the completed result and an in-progress session."""
        await self._store.async_save(
            {
                "last_result": self._last.to_dict(),
                "pending": self._pending,
            }
        )
