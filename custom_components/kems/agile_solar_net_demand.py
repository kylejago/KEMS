"""Solar-aware net-house protection and current solar-first routing.

The retained rolling optimiser historically reserved battery for gross predicted
house demand even when a high-confidence hourly solar forecast would cover part
of that demand. This canonical Alpha8 layer credits only temporally overlapping
solar, with a confidence haircut, while preserving the normal reserve and the
forecast pre-cheap SOC floor applied by the existing arbitrage layer.

The same layer reconciles the reporting-only current routing snapshot when the
battery is idle outside a confirmed cheap period: solar serves the house before
surplus PV is charged/exported, preventing simultaneous simulated house import
and solar export. Real hardware writes remain blocked.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_rolling_planning, agile_routing
from . import agile_smart_export as agile
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    SolarForecastState,
)
from .kems_core.solar_net_demand import project_solar_net_house_demand
from .tariff import TariffSettings

rolling = agile_rolling_planning.rolling_runtime
current_runtime = agile_routing.current_runtime
_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _forecast_aware_predicted_house_until_deadline(self) -> float:
    """Protect forecast net house demand rather than gross demand when safe."""
    gross = max(float(_original_predicted_house(self)), 0.0)
    now = getattr(self, "_rolling_now", None)
    tariff = getattr(self, "_rolling_tariff", None)
    forecast = getattr(self, "_kems_forecast_arbitrage_forecast", None)
    forecast_plan = getattr(self, "_kems_forecast_arbitrage_plan", None)
    learned = getattr(self, "_kems_forecast_arbitrage_learned", None)

    if not isinstance(now, datetime) or not isinstance(tariff, TariffSettings):
        self._kems_solar_net_house_protection = {
            "active": False,
            "gross_house_kwh": round(gross, 3),
            "solar_to_house_credit_kwh": 0.0,
            "net_house_kwh": round(gross, 3),
            "reason": "rolling planning context unavailable",
        }
        return gross

    projection = project_solar_net_house_demand(
        now=now,
        deadline=agile._next_cheap(now, tariff).astimezone(UTC),
        gross_house_kwh=gross,
        forecast=forecast if isinstance(forecast, SolarForecastState) else None,
        forecast_plan=(
            forecast_plan if isinstance(forecast_plan, ForecastPlanState) else None
        ),
        learned=learned if isinstance(learned, LearnedState) else None,
    )
    self._kems_solar_net_house_protection = projection.to_dict()
    return projection.net_house_kwh


def _rolling_plan_with_solar_net_evidence(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Expose the solar credit used by the final rolling allocation."""
    plan = _original_rolling_plan(
        self,
        state,
        now=now,
        config=config,
        tariff=tariff,
    )
    if not isinstance(plan, dict):
        return plan
    evidence = getattr(self, "_kems_solar_net_house_protection", None)
    if isinstance(evidence, dict):
        plan["solar_net_house_protection"] = dict(evidence)
        plan["solar_aware_house_protection"] = bool(evidence.get("active"))
        plan["gross_protected_house_energy_kwh"] = evidence.get("gross_house_kwh")
        plan["forecast_solar_to_house_credit_kwh"] = evidence.get(
            "solar_to_house_credit_kwh"
        )
        plan["net_protected_house_energy_kwh"] = evidence.get("net_house_kwh")
    return plan


def _cheap_period_confirmed(self) -> bool:
    """Return whether the current coordinator record intentionally uses grid."""
    records = list(getattr(self, "_panel_today_records", []) or [])
    if not records:
        return False
    return bool(getattr(records[-1], "cheap_period_confirmed", False))


def _snapshot_with_idle_solar_first(
    self,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Route current solar to house first while battery discharge is idle."""
    snapshot = _original_current_snapshot(self, state)
    if not isinstance(snapshot, dict) or not snapshot.get("available"):
        return snapshot

    total_discharge = max(_number(snapshot.get("total_discharge_kw")) or 0.0, 0.0)
    if total_discharge > _EPSILON or _cheap_period_confirmed(self):
        snapshot["solar_first_idle_routing"] = False
        return snapshot

    config = getattr(self, "_rolling_config", None)
    if not isinstance(config, SimulationConfig):
        return snapshot

    house = max(_number(snapshot.get("simulated_house_load_kw")) or 0.0, 0.0)
    solar = max(_number(snapshot.get("solar_power_kw")) or 0.0, 0.0)
    if house <= _EPSILON or solar <= _EPSILON:
        snapshot["solar_first_idle_routing"] = False
        return snapshot

    solar_to_home = min(house, solar)
    solar_remaining = max(solar - solar_to_home, 0.0)
    existing_solar_charge = max(
        _number(snapshot.get("solar_to_battery_kw")) or 0.0,
        0.0,
    )
    solar_to_battery = min(existing_solar_charge, solar_remaining)
    solar_remaining = max(solar_remaining - solar_to_battery, 0.0)

    grid_to_battery = max(_number(snapshot.get("grid_to_battery_kw")) or 0.0, 0.0)
    battery_export = max(_number(snapshot.get("battery_export_kw")) or 0.0, 0.0)
    inverter_limit = max(config.inverter_limit_kw, 0.0)
    export_limit = min(max(config.export_limit_kw, 0.0), inverter_limit)
    export_allowed = config.export_tariff_status == "active"
    export_headroom = max(export_limit - battery_export, 0.0)
    inverter_headroom = max(inverter_limit - solar_to_home, 0.0)
    solar_export = (
        min(solar_remaining, export_headroom, inverter_headroom)
        if export_allowed
        else 0.0
    )
    solar_curtailment = max(solar_remaining - solar_export, 0.0)
    grid_import = max(house - solar_to_home, 0.0) + grid_to_battery
    grid_export = solar_export + battery_export
    kh7_ac_output = solar_to_home + solar_export + battery_export

    snapshot.update(
        {
            "routing_basis": (
                "current coordinator routing snapshot — idle solar-to-house first"
            ),
            "solar_to_home_kw": round(solar_to_home, 3),
            "solar_to_battery_kw": round(solar_to_battery, 3),
            "solar_export_kw": round(solar_export, 3),
            "grid_import_kw": round(grid_import, 3),
            "grid_export_kw": round(grid_export, 3),
            "solar_curtailment_kw": round(solar_curtailment, 3),
            "normalised_kh7_ac_output_kw": round(kh7_ac_output, 3),
            "solar_routing_basis": (
                "outside cheap period: solar serves house first; preserve planned "
                "solar charging, then export paid surplus within limits"
            ),
            "solar_first_idle_routing": True,
            "hardware_writes": "blocked",
        }
    )
    return snapshot


def install_solar_net_demand() -> None:
    """Install final solar-aware rolling protection and routing reconciliation."""
    predicted_house = rolling._predicted_house_until_deadline
    if not getattr(predicted_house, "_kems_solar_net_demand", False):
        global _original_predicted_house
        _original_predicted_house = predicted_house
        _forecast_aware_predicted_house_until_deadline._kems_solar_net_demand = True
        rolling._predicted_house_until_deadline = (
            _forecast_aware_predicted_house_until_deadline
        )

    rolling_plan = rolling._rolling_plan
    if not getattr(rolling_plan, "_kems_solar_net_demand", False):
        global _original_rolling_plan
        _original_rolling_plan = rolling_plan
        _rolling_plan_with_solar_net_evidence._kems_solar_net_demand = True
        rolling._rolling_plan = _rolling_plan_with_solar_net_evidence

    current_snapshot = current_runtime._snapshot
    if not getattr(current_snapshot, "_kems_solar_net_demand", False):
        global _original_current_snapshot
        _original_current_snapshot = current_snapshot
        _snapshot_with_idle_solar_first._kems_solar_net_demand = True
        current_runtime._snapshot = _snapshot_with_idle_solar_first
