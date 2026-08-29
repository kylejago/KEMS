"""Alpha8.49 canonical-current flow presentation/accounting reconciliation.

Alpha8.48 introduced the stable Grid/Solar/Battery slot contract. Alpha8.49 keeps
that contract and all dispatch/control owners unchanged, but corrects two
presentation authority leaks found in live diagnostics:

* the active slot is rendered from ``current_routing_snapshot`` rather than a
  second solar optimisation inside the presentation forecast; and
* Today's solar export preserves the live Agile replay total captured before
  completed-slot settlement replaces the headline export ledger.

Battery export remains settlement-only in Today's accounting. Real hardware
writes remain blocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import agile_smart_export as agile
from .agile_current_day_settlement import _reconcile_comparison
from .agile_flow_presentation import (
    FlowPresentationAgileSmartExportManager,
    _dt,
    _number,
)
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    Snapshot,
    SolarForecastState,
)
from .kems_core.slot_flow import build_slot_flow
from .tariff import TariffSettings

_EPSILON = 1e-6


def _today_agile(state: dict[str, Any]) -> dict[str, Any] | None:
    periods = state.get("periods")
    if not isinstance(periods, dict):
        return None
    today = periods.get("today")
    if not isinstance(today, dict):
        return None
    result = today.get("agile_smart_export")
    return result if isinstance(result, dict) and result.get("ready") else None


def _completed_replay_battery_income(
    state: dict[str, Any],
    *,
    now: datetime,
) -> float:
    """Return replay battery-export income already represented in elapsed slots."""
    now_utc = now.astimezone(UTC)
    income = 0.0
    for slot in state.get("today_slots", []) or []:
        if not isinstance(slot, dict):
            continue
        end = _dt(slot.get("valid_to"))
        if end is None or end > now_utc:
            continue
        exported = _number(
            slot.get("replay_battery_export_kwh", slot.get("battery_export_kwh"))
        )
        rate = _number(slot.get("rate_pence"))
        if exported is not None and rate is not None:
            income += max(exported, 0.0) * rate
    return income


def _capture_live_replay_accounting(
    state: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, float] | None:
    """Capture replay-owned solar/export economics before settlement truncation."""
    today = _today_agile(state)
    if today is None:
        return None
    solar_export = _number(today.get("solar_export_kwh"))
    export_income = _number(today.get("export_income_pence"))
    if solar_export is None or export_income is None:
        return None
    return {
        "solar_export_kwh": max(solar_export, 0.0),
        "export_income_pence": max(export_income, 0.0),
        "completed_replay_battery_income_pence": (
            _completed_replay_battery_income(state, now=now)
        ),
    }


def _settled_battery_income(
    state: dict[str, Any],
    *,
    now: datetime,
) -> float:
    """Return income only from completed digital-twin battery-export settlements."""
    now_utc = now.astimezone(UTC)
    income = 0.0
    for slot in state.get("today_slots", []) or []:
        if not isinstance(slot, dict) or not slot.get("settlement_source"):
            continue
        end = _dt(slot.get("valid_to"))
        if end is None or end > now_utc:
            continue
        exported = _number(slot.get("battery_export_kwh"))
        rate = _number(slot.get("rate_pence"))
        if exported is not None and rate is not None:
            income += max(exported, 0.0) * rate
    return income


def _apply_captured_live_solar_accounting(
    state: dict[str, Any],
    *,
    now: datetime,
    capture: dict[str, float] | None,
) -> None:
    """Restore replay-live solar while preserving settled-only battery export."""
    if not capture:
        return
    today = _today_agile(state)
    diagnostic = state.get("current_day_settlement_reconciliation")
    if today is None or not isinstance(diagnostic, dict):
        return

    solar_export = round(max(capture["solar_export_kwh"], 0.0), 3)
    settled_battery_export = round(
        max(_number(diagnostic.get("battery_export_kwh")) or 0.0, 0.0),
        3,
    )
    grid_export = round(solar_export + settled_battery_export, 3)

    settled_battery_income = _settled_battery_income(state, now=now)
    export_income = round(
        max(
            capture["export_income_pence"]
            - capture["completed_replay_battery_income_pence"]
            + settled_battery_income,
            0.0,
        ),
        2,
    )

    import_cost = _number(today.get("import_cost_pence")) or 0.0
    old_export_income = _number(today.get("export_income_pence")) or 0.0
    old_energy_net = _number(today.get("energy_net_cost_pence"))
    standing_component = (
        old_energy_net - import_cost + old_export_income
        if old_energy_net is not None
        else 0.0
    )
    battery_home = max(_number(today.get("battery_to_home_kwh")) or 0.0, 0.0)
    wear_rate = _number(state.get("battery_wear_assumption_pence_per_discharged_kwh"))
    if wear_rate is None:
        wear_rate = agile.BATTERY_WEAR_PENCE_PER_KWH
    wear_cost = round((battery_home + settled_battery_export) * wear_rate, 2)
    energy_net = round(import_cost + standing_component - export_income, 2)
    economic_net = round(energy_net + wear_cost, 2)
    fixed_income = round(grid_export * agile.FIXED_EXPORT_PENCE, 2)

    today.update(
        {
            "grid_export_kwh": grid_export,
            "solar_export_kwh": solar_export,
            "battery_export_kwh": settled_battery_export,
            "export_income_pence": export_income,
            "battery_wear_cost_pence": wear_cost,
            "energy_net_cost_pence": energy_net,
            "economic_net_cost_pence": economic_net,
            "fixed_12p_same_dispatch_income_pence": fixed_income,
            "gain_vs_fixed_12p_same_dispatch_pence": round(
                export_income - fixed_income,
                2,
            ),
            "weighted_achieved_export_rate_pence": (
                round(export_income / grid_export, 4)
                if grid_export > _EPSILON
                else None
            ),
            "solar_export_accounting_source": (
                "live Agile replay captured before settlement"
            ),
            "battery_export_accounting_source": (
                "completed digital-twin half-hour settlement only"
            ),
            "grid_export_accounting_source": (
                "captured live replay solar + completed settled battery export"
            ),
        }
    )

    periods = state.get("periods")
    period_today = periods.get("today") if isinstance(periods, dict) else None
    if isinstance(period_today, dict):
        _reconcile_comparison(period_today)

    checks = diagnostic.get("accounting_checks")
    checks = dict(checks) if isinstance(checks, dict) else {}
    checks["grid_export_balance"] = (
        abs(grid_export - (solar_export + settled_battery_export)) <= 0.002
    )
    checks["future_planned_battery_export_excluded"] = True
    diagnostic.update(
        {
            "grid_export_kwh": grid_export,
            "solar_export_kwh": solar_export,
            "battery_export_kwh": settled_battery_export,
            "export_income_pence": export_income,
            "accounting_checks": checks,
            "all_accounting_checks_passed": all(checks.values()) if checks else True,
            "export_accounting_source": (
                "captured live replay solar + completed settled battery export"
            ),
            "live_solar_replay_applied": True,
            "live_solar_capture_preserved": True,
            "hardware_writes": "blocked",
        }
    )


def _active_slot_from_routing(
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
) -> None:
    """Overwrite only the active row from the canonical current routing snapshot."""
    routing = state.get("current_routing_snapshot")
    if not isinstance(routing, dict) or not routing.get("available"):
        return
    start = _dt(routing.get("routing_valid_from"))
    end = _dt(routing.get("routing_valid_to"))
    now_utc = now.astimezone(UTC)
    if start is None or end is None or not (start <= now_utc < end):
        return

    active = next(
        (
            slot
            for slot in state.get("today_slots", []) or []
            if isinstance(slot, dict) and _dt(slot.get("valid_from")) == start
        ),
        None,
    )
    if active is None:
        return

    hours = max((end - now_utc).total_seconds() / 3600.0, 0.0)
    if hours <= _EPSILON:
        return

    def energy(field: str) -> float:
        return max(_number(routing.get(field)) or 0.0, 0.0) * hours

    # Keep Alpha8.48's end-SOC estimate; Alpha8.49 changes the routing authority,
    # not the rolling SOC forecast authority.
    estimated_soc = _number(active.get("flow_estimated_soc_percent"))
    if estimated_soc is None:
        estimated_soc = _number(routing.get("simulated_soc_percent"))

    active.update(
        build_slot_flow(
            grid_import_kwh=energy("grid_import_kw"),
            solar_generation_kwh=energy("solar_power_kw"),
            solar_to_home_kwh=energy("solar_to_home_kw"),
            solar_to_battery_kwh=energy("solar_to_battery_kw"),
            solar_export_kwh=energy("solar_export_kw"),
            grid_to_battery_kwh=energy("grid_to_battery_kw"),
            battery_to_home_kwh=energy("battery_to_home_kw"),
            battery_export_kwh=energy("battery_export_kw"),
            estimated_soc_percent=estimated_soc,
            basis="canonical current routing snapshot",
            scope="remaining slot",
        )
    )
    active["flow_routing_authority"] = "current_routing_snapshot"
    active["flow_routing_generated_at"] = routing.get("generated_at")
    active["flow_hardware_writes"] = "blocked"


class CanonicalFlowAccountingAgileSmartExportManager(
    FlowPresentationAgileSmartExportManager
):
    """Make current routing and captured replay accounting authoritative to display."""

    async def async_update(
        self,
        *,
        records: list[Snapshot],
        now: datetime,
        config: SimulationConfig,
        learned: LearnedState,
        forecast: SolarForecastState,
        forecast_plan: ForecastPlanState,
        tariff: TariffSettings,
    ) -> dict[str, Any]:
        await super().async_update(
            records=records,
            now=now,
            config=config,
            learned=learned,
            forecast=forecast,
            forecast_plan=forecast_plan,
            tariff=tariff,
        )
        self._alpha849_live_replay_capture = _capture_live_replay_accounting(
            self._state,
            now=now,
        )
        _active_slot_from_routing(self._state, now=now, config=config)
        self._publish(self._state)
        return self.state

    def reconcile_current_day_settlements(
        self,
        *,
        settled_half_hours: list[dict[str, Any]],
        now: datetime,
    ) -> dict[str, Any]:
        super().reconcile_current_day_settlements(
            settled_half_hours=settled_half_hours,
            now=now,
        )
        capture = getattr(self, "_alpha849_live_replay_capture", None)
        _apply_captured_live_solar_accounting(
            self._state,
            now=now,
            capture=capture if isinstance(capture, dict) else None,
        )
        config = getattr(self, "_rolling_config", None)
        if isinstance(config, SimulationConfig):
            _active_slot_from_routing(self._state, now=now, config=config)
        self._publish(self._state)
        return self.state
