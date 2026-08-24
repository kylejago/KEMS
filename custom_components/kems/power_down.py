"""Persistent completed Power Down event history for KEMS."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core import (
    ControlState,
    PowerDownAccountingState,
    PowerDownAuditState,
    PowerDownResult,
    SimulationState,
    Snapshot,
    finalise_power_down_audit,
)

STORAGE_VERSION = 1


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _baseline_net_power_kw(snapshot: Snapshot) -> float | None:
    """Convert the Octopus reward baseline into the current period's net kW."""
    imported = snapshot.saving_session_import_baseline_period_kwh
    exported = snapshot.saving_session_export_baseline_period_kwh
    start = snapshot.saving_session_baseline_period_start
    end = snapshot.saving_session_baseline_period_end
    if imported is not None and start is not None and end is not None and end > start:
        hours = (end - start).total_seconds() / 3600.0
        if hours > 0.0:
            return (float(imported) - float(exported or 0.0)) / hours

    imported = snapshot.saving_session_import_baseline_total_kwh
    exported = snapshot.saving_session_export_baseline_total_kwh
    start = snapshot.saving_session_start
    end = snapshot.saving_session_end
    if imported is None or start is None or end is None or end <= start:
        return None
    hours = (end - start).total_seconds() / 3600.0
    return (float(imported) - float(exported or 0.0)) / hours if hours > 0.0 else None


def _agile_power_down_route(agile_state: dict[str, Any] | None) -> dict[str, float] | None:
    """Return the final Full KEMS Agile site route only while Power Down is active."""
    if not isinstance(agile_state, dict):
        return None
    route = agile_state.get("current_routing_snapshot")
    if not isinstance(route, dict) or not route.get("available"):
        return None
    if str(route.get("dispatch_mode") or "") != "power_down_session":
        return None

    battery_home = _number(route.get("battery_to_home_kw"))
    grid_import = _number(route.get("grid_import_kw"))
    grid_export = _number(route.get("grid_export_kw"))
    inverter_output = _number(route.get("normalised_kh7_ac_output_kw"))
    if None in {battery_home, grid_import, grid_export, inverter_output}:
        return None

    # The retained accounting uses the same one-direction site-meter invariant
    # as the final Alpha8.10 routing snapshot.
    net = max(grid_import or 0.0, 0.0) - max(grid_export or 0.0, 0.0)
    return {
        "battery_to_home_kw": max(battery_home or 0.0, 0.0),
        "grid_import_kw": max(net, 0.0),
        "grid_export_kw": max(-net, 0.0),
        "inverter_output_kw": max(inverter_output or 0.0, 0.0),
    }


def _accounting_state(pending: dict[str, Any]) -> PowerDownAccountingState:
    """Restore internal in-progress reconciled accounting totals."""
    return PowerDownAccountingState(
        planned_battery_to_home_kwh=float(
            pending.get("_agile_battery_to_home_kwh", 0.0) or 0.0
        ),
        planned_export_kwh=float(pending.get("_agile_export_kwh", 0.0) or 0.0),
        maximum_inverter_output_kw=float(
            pending.get("_agile_maximum_inverter_output_kw", 0.0) or 0.0
        ),
        rewardable_reduction_kwh=float(
            pending.get("_agile_rewardable_reduction_kwh", 0.0) or 0.0
        ),
        bonus_pence=float(pending.get("_agile_bonus_pence", 0.0) or 0.0),
        fixed_export_income_pence=float(
            pending.get("_agile_fixed_export_income_pence", 0.0) or 0.0
        ),
        route_samples_observed=int(pending.get("_agile_route_samples", 0) or 0),
        reward_samples_observed=int(pending.get("_agile_reward_samples", 0) or 0),
    )


def _update_reconciled_accounting(
    pending: dict[str, Any],
    snapshot: Snapshot,
    simulation: SimulationState,
    agile_state: dict[str, Any] | None,
    now: datetime,
) -> None:
    """Integrate the final Agile route and make it the retained event ledger."""
    session_start = datetime.fromisoformat(str(pending["session_start"]))
    session_end = datetime.fromisoformat(str(pending["session_end"]))
    until = min(max(now, session_start), session_end)
    route = _agile_power_down_route(agile_state)

    last_at_value = pending.get("_agile_accounting_last_at")
    last_at = (
        datetime.fromisoformat(str(last_at_value)) if last_at_value is not None else None
    )

    # On the first active sample, use that final route back to the exact event
    # start. Subsequent intervals use the previously published route so energy
    # is integrated rather than multiplying one instantaneous target by an hour.
    if last_at is None and route is not None:
        last_at = session_start
        pending.update(
            {
                "_agile_last_battery_to_home_kw": route["battery_to_home_kw"],
                "_agile_last_grid_import_kw": route["grid_import_kw"],
                "_agile_last_grid_export_kw": route["grid_export_kw"],
                "_agile_last_inverter_output_kw": route["inverter_output_kw"],
                "_agile_last_baseline_net_kw": _baseline_net_power_kw(snapshot),
                "_agile_last_bonus_rate_pence": (
                    float(snapshot.saving_session_octopoints_per_kwh) / 8.0
                    if snapshot.saving_session_octopoints_per_kwh is not None
                    else None
                ),
                "_agile_last_export_rate_pence": (
                    max(float(simulation.effective_export_rate_pence or 0.0), 0.0)
                    if simulation.export_tariff_active
                    else 0.0
                ),
            }
        )

    if last_at is not None and until > last_at:
        battery_home = _number(pending.get("_agile_last_battery_to_home_kw"))
        grid_import = _number(pending.get("_agile_last_grid_import_kw"))
        grid_export = _number(pending.get("_agile_last_grid_export_kw"))
        inverter_output = _number(pending.get("_agile_last_inverter_output_kw"))
        if None not in {battery_home, grid_import, grid_export, inverter_output}:
            state = _accounting_state(pending).observe(
                hours=(until - last_at).total_seconds() / 3600.0,
                battery_to_home_kw=battery_home or 0.0,
                grid_import_kw=grid_import or 0.0,
                grid_export_kw=grid_export or 0.0,
                inverter_output_kw=inverter_output or 0.0,
                baseline_net_kw=_number(pending.get("_agile_last_baseline_net_kw")),
                bonus_rate_pence=_number(
                    pending.get("_agile_last_bonus_rate_pence")
                ),
                export_rate_pence=(
                    _number(pending.get("_agile_last_export_rate_pence")) or 0.0
                ),
            )
            pending.update(
                {
                    "_agile_battery_to_home_kwh": state.planned_battery_to_home_kwh,
                    "_agile_export_kwh": state.planned_export_kwh,
                    "_agile_maximum_inverter_output_kw": (
                        state.maximum_inverter_output_kw
                    ),
                    "_agile_rewardable_reduction_kwh": (
                        state.rewardable_reduction_kwh
                    ),
                    "_agile_bonus_pence": state.bonus_pence,
                    "_agile_fixed_export_income_pence": (
                        state.fixed_export_income_pence
                    ),
                    "_agile_route_samples": state.route_samples_observed,
                    "_agile_reward_samples": state.reward_samples_observed,
                    "planned_battery_to_home_kwh": round(
                        state.planned_battery_to_home_kwh, 3
                    ),
                    "planned_export_kwh": round(state.planned_export_kwh, 3),
                    "maximum_inverter_output_kw": round(
                        state.maximum_inverter_output_kw, 3
                    ),
                    "fixed_export_income_pence": round(
                        state.fixed_export_income_pence, 2
                    ),
                }
            )
            if state.reward_samples_observed > 0:
                pending["rewardable_reduction_kwh"] = round(
                    state.rewardable_reduction_kwh, 3
                )
                pending["bonus_pence"] = round(state.bonus_pence, 2)
                pending["combined_income_pence"] = round(
                    state.bonus_pence + state.fixed_export_income_pence, 2
                )

    if last_at is not None:
        pending["_agile_accounting_last_at"] = until.isoformat()

    if route is not None and until < session_end:
        pending.update(
            {
                "_agile_accounting_last_at": until.isoformat(),
                "_agile_last_battery_to_home_kw": route["battery_to_home_kw"],
                "_agile_last_grid_import_kw": route["grid_import_kw"],
                "_agile_last_grid_export_kw": route["grid_export_kw"],
                "_agile_last_inverter_output_kw": route["inverter_output_kw"],
                "_agile_last_baseline_net_kw": _baseline_net_power_kw(snapshot),
                "_agile_last_bonus_rate_pence": (
                    float(snapshot.saving_session_octopoints_per_kwh) / 8.0
                    if snapshot.saving_session_octopoints_per_kwh is not None
                    else pending.get("_agile_last_bonus_rate_pence")
                ),
                "_agile_last_export_rate_pence": (
                    max(float(simulation.effective_export_rate_pence or 0.0), 0.0)
                    if simulation.export_tariff_active
                    else 0.0
                ),
                "_agile_accounting_source": "final_full_kems_agile_site_route",
            }
        )


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
        """Upgrade old zero-sample failures to an evidence-safe result."""
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
        agile_state: dict[str, Any] | None = None,
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
            _update_reconciled_accounting(
                self._pending,
                snapshot,
                simulation,
                agile_state,
                now,
            )
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
