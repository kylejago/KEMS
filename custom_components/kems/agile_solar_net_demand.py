"""Solar-aware net-house protection and physical rolling export capacity.

The retained rolling optimiser historically reserved battery for gross predicted
house demand even when a high-confidence hourly solar forecast would cover part
of that demand. This canonical Alpha8 layer credits only temporally overlapping
solar, with a confidence haircut, while preserving the normal reserve and the
forecast pre-cheap SOC floor applied by the existing arbitrage layer.

The same final layer reconciles every remaining Agile export slot against the
same five-minute solar-aware shared-inverter capacity used by the deadline
guard. House demand is served before deliberate battery export, so a nominal
3.5 kWh half-hour is no longer published when the battery cannot physically
export that much while respecting the 7 kW shared AC envelope.

Current idle routing remains solar-first. Real hardware writes remain blocked.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_deadline_guard, agile_rolling_planning, agile_routing
from . import agile_smart_export as agile
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    SolarForecastState,
)
from .kems_core.physical_slot_capacity import allocate_physical_export_slots
from .kems_core.solar_net_demand import (
    project_solar_net_house_demand,
    route_idle_solar_first,
)
from .tariff import TariffSettings

rolling = agile_rolling_planning.rolling_runtime
current_runtime = agile_routing.current_runtime
deadline_runtime = agile_deadline_guard.deadline_runtime
_EPSILON = 1e-6
HARD_FLOOR_GUARD_MINUTES = 5.0


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dt(value: Any) -> datetime | None:
    """Return one aware timestamp normalised to UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


def _physical_house_kw(self) -> float:
    """Return the conservative house power used for future export capacity."""
    evidence = getattr(self, "_kems_solar_net_house_protection", None)
    if isinstance(evidence, dict):
        value = _number(evidence.get("conservative_house_kw"))
        if value is not None and value > _EPSILON:
            return value

    records = list(getattr(self, "_panel_today_records", []) or [])
    if records:
        value = _number(getattr(records[-1], "house_load_kw", None))
        if value is not None:
            return max(value, 0.0)
    return 0.0


def _current_house_kw(self, *, fallback: float) -> float:
    """Return the latest coordinator house power for instantaneous routing."""
    records = list(getattr(self, "_panel_today_records", []) or [])
    if records:
        value = _number(getattr(records[-1], "house_load_kw", None))
        if value is not None:
            return max(value, 0.0)
    return max(float(fallback), 0.0)


def _power_down_windows(plan: dict[str, Any]) -> tuple[tuple[datetime, datetime], ...]:
    """Return absolute-priority Power Down windows already reserved by the plan."""
    context = plan.get("power_down_priority")
    if not isinstance(context, dict) or not context.get("available"):
        return ()
    start = _dt(context.get("start"))
    end = _dt(context.get("end"))
    if start is None or end is None or end <= start:
        return ()
    return ((start, end),)


def _slot_map(state: dict[str, Any]) -> dict[datetime, dict[str, Any]]:
    """Return remaining Today rows keyed by settlement start."""
    output: dict[datetime, dict[str, Any]] = {}
    for item in state.get("today_slots", []) or []:
        if not isinstance(item, dict):
            continue
        start = _dt(item.get("valid_from"))
        if start is not None:
            output[start] = item
    return output


def _current_physical_targets(
    *,
    allocations,
    capacity_segments: list[dict[str, Any]],
    now: datetime,
    house_kw: float,
    export_limit_kw: float,
    current_soc_percent: float | None = None,
    target_soc_percent: float | None = None,
    battery_capacity_kwh: float | None = None,
    discharge_efficiency: float | None = None,
    hard_floor_guard_minutes: float = HARD_FLOOR_GUARD_MINUTES,
) -> tuple[float, float, float]:
    """Return house/export targets while never planning through reserve SOC."""
    now_utc = now.astimezone(UTC)
    current = next(
        (item for item in allocations if item.valid_from <= now_utc < item.valid_to),
        None,
    )

    segment = next(
        (
            item
            for item in capacity_segments
            if (_dt(item.get("start")) or now_utc)
            <= now_utc
            < (_dt(item.get("end")) or now_utc)
        ),
        capacity_segments[0] if capacity_segments else None,
    )
    if not isinstance(segment, dict):
        return 0.0, 0.0, 0.0

    solar_kw = max(_number(segment.get("solar_kw")) or 0.0, 0.0)
    battery_kw = max(_number(segment.get("battery_kw")) or 0.0, 0.0)

    # The rolling arrival reserve handles the long-horizon 10%-at-cheap-start
    # trajectory. This local guard is deliberately narrow: it prevents the
    # instantaneous battery target from crossing the absolute reserve between
    # coordinator scans. Five minutes matches KEMS' persisted cadence and only
    # begins tapering house discharge very close to the hard floor.
    discharge_ceiling_kw = battery_kw
    soc = _number(current_soc_percent)
    target = _number(target_soc_percent)
    capacity = _number(battery_capacity_kwh)
    efficiency = _number(discharge_efficiency)
    if (
        soc is not None
        and target is not None
        and capacity is not None
        and capacity > _EPSILON
        and efficiency is not None
        and efficiency > _EPSILON
    ):
        if soc <= target + _EPSILON:
            discharge_ceiling_kw = 0.0
        else:
            usable_stored_kwh = max(soc - target, 0.0) / 100.0 * capacity
            usable_ac_kwh = usable_stored_kwh * min(max(efficiency, 0.01), 1.0)
            guard_hours = max(float(hard_floor_guard_minutes) / 60.0, _EPSILON)
            discharge_ceiling_kw = min(
                battery_kw,
                usable_ac_kwh / guard_hours,
            )

    solar_to_home = min(house_kw, solar_kw)
    house_battery = min(
        max(house_kw - solar_to_home, 0.0),
        discharge_ceiling_kw,
    )
    physical_export = min(
        max(discharge_ceiling_kw - house_battery, 0.0),
        max(export_limit_kw, 0.0),
    )

    # A price-optimised hold applies only to deliberate battery export. The
    # household battery target remains independent so a zero-allocation slot
    # cannot turn an otherwise avoidable house deficit into premium grid import.
    # The exception is the absolute reserve guard above: once 10% is reached,
    # preserving battery health is physically mandatory and grid supplies the
    # residual house load until cheap charging starts.
    paced_export = 0.0
    if current is not None and current.allocated_kwh > _EPSILON:
        remaining_hours = max(
            (current.valid_to - now_utc).total_seconds() / 3600.0,
            _EPSILON,
        )
        paced_export = min(
            current.allocated_kwh / remaining_hours,
            physical_export,
        )
    total = house_battery + paced_export
    return (
        round(house_battery, 3),
        round(paced_export, 3),
        round(total, 3),
    )


def _apply_physical_slot_allocations(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Reallocate final rolling export over physically achievable slot capacity."""
    if not plan.get("available"):
        return plan
    mode = str(plan.get("dispatch_mode") or "price_optimised")
    if mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}:
        return plan

    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    segments = deadline_runtime._capacity_segments(
        self,
        now=now,
        deadline=deadline,
        config=config,
    )
    desired = max(_number(plan.get("planned_battery_export_kwh")) or 0.0, 0.0)
    future_house_kw = _physical_house_kw(self)
    current_house_kw = _current_house_kw(self, fallback=future_house_kw)
    slots = list(state.get("today_slots", []) or [])
    physical = allocate_physical_export_slots(
        slots=slots,
        capacity_segments=segments,
        now=now,
        deadline=deadline,
        desired_export_kwh=desired,
        house_kw=future_house_kw,
        export_limit_kw=config.export_limit_kw,
        excluded_windows=_power_down_windows(plan),
    )

    by_start = _slot_map(state)
    selected: list[dict[str, Any]] = []
    for allocation in physical.allocations:
        slot = by_start.get(allocation.valid_from)
        if slot is None:
            continue
        slot["physical_battery_export_capacity_kwh"] = allocation.capacity_kwh
        slot["rolling_planned_battery_export_kwh"] = allocation.allocated_kwh
        slot["rolling_replan_generated_at"] = now.isoformat()
        is_current = allocation.valid_from <= now.astimezone(UTC) < allocation.valid_to
        if allocation.allocated_kwh > _EPSILON:
            slot["rolling_action"] = "planned battery export — physical capacity"
            if not is_current:
                slot["battery_export_kwh"] = allocation.allocated_kwh
                slot["actions"] = ["planned battery export — physical capacity"]
            selected.append(
                {
                    "valid_from": allocation.valid_from.isoformat(),
                    "valid_to": allocation.valid_to.isoformat(),
                    "label": slot.get("label"),
                    "rate_pence": allocation.rate_pence,
                    "planned_battery_export_kwh": allocation.allocated_kwh,
                    "physical_export_capacity_kwh": allocation.capacity_kwh,
                    "physical_capacity_reconciled": True,
                }
            )
        elif not is_current:
            slot["rolling_action"] = "hold — physical capacity / price replan"
            slot["actions"] = ["hold — physical capacity / price replan"]

    selected.sort(key=lambda item: _dt(item.get("valid_from")) or deadline)
    next_slot = next(
        (
            item
            for item in selected
            if (_dt(item.get("valid_to")) or deadline) > now.astimezone(UTC)
        ),
        None,
    )

    plan.update(
        {
            "planned_battery_export_kwh": physical.allocated_kwh,
            "selected_slots": selected,
            "next_export_slot": dict(next_slot) if next_slot is not None else None,
            "remaining_slot_capacity_kwh": physical.total_capacity_kwh,
            "physical_slot_capacity_reconciled": True,
            "physical_slot_capacity_model": (
                "5-minute solar-aware shared-inverter headroom; house first"
            ),
            "physical_slot_capacity_house_kw": physical.house_kw,
            "current_routing_house_kw": round(current_house_kw, 3),
            "current_routing_house_source": "latest coordinator house_load_kw",
            "physical_slot_capacity_kwh": physical.total_capacity_kwh,
            "physical_slot_unallocated_required_export_kwh": physical.unallocated_kwh,
            "physical_slot_capacity": physical.to_dict(),
            "hardware_writes": "blocked",
        }
    )

    soc = _number(plan.get("simulated_soc_percent"))
    target_soc = _number(plan.get("target_soc_percent"))
    if target_soc is None:
        target_soc = max(float(config.battery_reserve_percent), 10.0)
    reserve_headroom_ac = None
    reserve_guard_limit_kw = None
    if soc is not None:
        reserve_headroom_ac = (
            max(soc - target_soc, 0.0)
            / 100.0
            * max(float(config.battery_capacity_kwh), 0.0)
            * min(max(float(config.discharge_efficiency), 0.01), 1.0)
        )
        reserve_guard_limit_kw = reserve_headroom_ac / (HARD_FLOOR_GUARD_MINUTES / 60.0)
    floor_active = soc is not None and soc <= target_soc + _EPSILON
    plan.update(
        {
            "hard_reserve_soc_percent": round(target_soc, 3),
            "hard_reserve_floor_active": floor_active,
            "hard_reserve_guard_minutes": HARD_FLOOR_GUARD_MINUTES,
            "hard_reserve_headroom_ac_kwh": (
                round(reserve_headroom_ac, 3)
                if reserve_headroom_ac is not None
                else None
            ),
            "hard_reserve_guard_limit_kw": (
                round(reserve_guard_limit_kw, 3)
                if reserve_guard_limit_kw is not None
                else None
            ),
            "hard_reserve_policy": (
                "never plan battery discharge below reserve; taper only within "
                "the final five-minute reserve guard"
            ),
        }
    )

    # Deadline modes keep ownership of their normal command calculation. The
    # absolute floor below is a final safety clamp only; it never changes Power
    # Down, cheap-charge or Happy Hour ownership because those returned above.
    if mode not in {"deadline_following", "maximum_discharge"}:
        house_target, export_target, total_target = _current_physical_targets(
            allocations=physical.allocations,
            capacity_segments=segments,
            now=now,
            house_kw=current_house_kw,
            export_limit_kw=config.export_limit_kw,
            current_soc_percent=soc,
            target_soc_percent=target_soc,
            battery_capacity_kwh=config.battery_capacity_kwh,
            discharge_efficiency=config.discharge_efficiency,
        )
        plan["current_house_battery_kw"] = house_target
        plan["current_battery_export_target_kw"] = export_target
        plan["current_battery_discharge_target_kw"] = total_target
        if floor_active:
            plan["dispatch_action"] = (
                "10% reserve floor — no battery discharge/export; grid covers "
                "residual house load until cheap charge"
            )
        elif export_target > _EPSILON:
            plan["dispatch_action"] = "price-optimised physical export; house first"
    elif soc is not None and reserve_guard_limit_kw is not None:
        house_target = max(_number(plan.get("current_house_battery_kw")) or 0.0, 0.0)
        export_target = max(
            _number(plan.get("current_battery_export_target_kw")) or 0.0,
            0.0,
        )
        allowed_kw = max(reserve_guard_limit_kw, 0.0)
        clamped_house = min(house_target, allowed_kw)
        clamped_export = min(export_target, max(allowed_kw - clamped_house, 0.0))
        plan["current_house_battery_kw"] = round(clamped_house, 3)
        plan["current_battery_export_target_kw"] = round(clamped_export, 3)
        plan["current_battery_discharge_target_kw"] = round(
            clamped_house + clamped_export,
            3,
        )
        if floor_active:
            plan["dispatch_action"] = (
                "10% reserve floor — no battery discharge/export; grid covers "
                "residual house load until cheap charge"
            )

    return plan


def _rolling_plan_with_solar_net_evidence(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Expose solar credit and enforce final physical rolling slot capacity."""
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
    return _apply_physical_slot_allocations(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )


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

    routing = route_idle_solar_first(
        house_kw=house,
        solar_kw=solar,
        requested_solar_to_battery_kw=(
            _number(snapshot.get("solar_to_battery_kw")) or 0.0
        ),
        grid_to_battery_kw=_number(snapshot.get("grid_to_battery_kw")) or 0.0,
        battery_export_kw=_number(snapshot.get("battery_export_kw")) or 0.0,
        inverter_limit_kw=config.inverter_limit_kw,
        export_limit_kw=config.export_limit_kw,
        export_allowed=config.export_tariff_status == "active",
    )
    snapshot.update(
        {
            "routing_basis": (
                "current coordinator routing snapshot — idle solar-to-house first"
            ),
            "solar_to_home_kw": routing.solar_to_home_kw,
            "solar_to_battery_kw": routing.solar_to_battery_kw,
            "solar_export_kw": routing.solar_export_kw,
            "grid_import_kw": routing.grid_import_kw,
            "grid_export_kw": routing.grid_export_kw,
            "solar_curtailment_kw": routing.solar_curtailment_kw,
            "normalised_kh7_ac_output_kw": routing.kh7_ac_output_kw,
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
