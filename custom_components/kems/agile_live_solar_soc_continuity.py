"""Alpha8.50 canonical elapsed-solar and displayed-SOC continuity.

Alpha8.49 made the active Grid/Solar/Battery row mirror the canonical current
routing snapshot, but live field evidence exposed two remaining reporting gaps:

* Today's solar export still preserved a replay value that could itself be zero
  while the current routing snapshot was exporting solar; and
* the active row retained Alpha8.48's older SOC projection even after its flow
  components had been replaced by canonical current routing.

This successor is reporting/accounting only. It integrates consecutive
canonical current-routing solar-export samples into a small persisted daily
ledger, combines that elapsed solar with completed/settled battery export, and
rebases displayed SOC from the canonical current SOC through the already
published flow deltas. It does not re-run the optimiser or alter dispatch,
Power Down, cheap charging, midnight rollover, safety, or hardware writes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from . import agile_smart_export as agile
from .agile_canonical_flow_accounting import (
    CanonicalFlowAccountingAgileSmartExportManager,
    _settled_battery_income,
    _today_agile,
)
from .agile_current_day_settlement import _reconcile_comparison
from .agile_flow_presentation import _dt, _number
from .const import DOMAIN
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    Snapshot,
    SolarForecastState,
)
from .tariff import TariffSettings

LIVE_SOLAR_STORE_VERSION = 1
MAX_CANONICAL_SAMPLE_GAP = timedelta(minutes=5)
_EPSILON = 1e-6


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _route_sample(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return one finite canonical solar-export sample for integration."""
    routing = state.get("current_routing_snapshot")
    if not isinstance(routing, dict) or not routing.get("available"):
        return None
    generated = _dt(routing.get("generated_at"))
    valid_from = _dt(routing.get("routing_valid_from"))
    valid_to = _dt(routing.get("routing_valid_to"))
    export_kw = _number(routing.get("solar_export_kw"))
    rate = _number(routing.get("current_agile_rate_pence"))
    if (
        generated is None
        or valid_from is None
        or valid_to is None
        or export_kw is None
        or valid_to <= valid_from
        or not (valid_from <= generated <= valid_to)
    ):
        return None
    return {
        "timestamp": generated.isoformat(),
        "local_date": generated.astimezone(agile.LONDON).date().isoformat(),
        "slot_start": valid_from.isoformat(),
        "slot_end": valid_to.isoformat(),
        "solar_export_kw": max(export_kw, 0.0),
        "rate_pence": max(rate or 0.0, 0.0),
    }


def _valid_tracker(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if not isinstance(value.get("local_date"), str):
        return False
    for key in ("solar_export_kwh", "solar_export_income_pence"):
        if _number(value.get(key)) is None:
            return False
    return True


def _new_tracker(
    state: dict[str, Any],
    *,
    now: datetime,
    sample: dict[str, Any] | None,
) -> dict[str, Any]:
    """Seed the tracker only from accounting KEMS already owns at activation."""
    today = _today_agile(state)
    parent_solar = (
        max(_number(today.get("solar_export_kwh")) or 0.0, 0.0) if today else 0.0
    )
    parent_income = (
        max(_number(today.get("export_income_pence")) or 0.0, 0.0) if today else 0.0
    )
    settled_income = _settled_battery_income(state, now=now)
    solar_income = max(parent_income - settled_income, 0.0)
    local_date = now.astimezone(agile.LONDON).date().isoformat()
    return {
        "local_date": local_date,
        "tracking_started_at": now.isoformat(),
        "baseline_solar_export_kwh": round(parent_solar, 6),
        "baseline_solar_export_income_pence": round(solar_income, 6),
        "solar_export_kwh": round(parent_solar, 6),
        "solar_export_income_pence": round(solar_income, 6),
        "tracked_increment_kwh": 0.0,
        "tracked_increment_income_pence": 0.0,
        "sample_count": 1 if sample is not None else 0,
        "skipped_gap_count": 0,
        "last_sample": dict(sample) if sample is not None else None,
        "source": "canonical current-routing sample accumulator",
        "hardware_writes": "blocked",
    }


def _sample_times(sample: dict[str, Any]) -> tuple[datetime, datetime, datetime] | None:
    timestamp = _dt(sample.get("timestamp"))
    start = _dt(sample.get("slot_start"))
    end = _dt(sample.get("slot_end"))
    if timestamp is None or start is None or end is None:
        return None
    return timestamp, start, end


def _integrated_increment(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> tuple[float, float] | None:
    """Integrate two bounded canonical samples without spanning unknown gaps."""
    previous_times = _sample_times(previous)
    current_times = _sample_times(current)
    if previous_times is None or current_times is None:
        return None
    previous_ts, previous_start, previous_end = previous_times
    current_ts, current_start, current_end = current_times
    if current_ts <= previous_ts:
        return None
    if current_ts - previous_ts > MAX_CANONICAL_SAMPLE_GAP:
        return None
    if previous.get("local_date") != current.get("local_date"):
        return None

    previous_kw = max(_number(previous.get("solar_export_kw")) or 0.0, 0.0)
    current_kw = max(_number(current.get("solar_export_kw")) or 0.0, 0.0)
    previous_rate = max(_number(previous.get("rate_pence")) or 0.0, 0.0)
    current_rate = max(_number(current.get("rate_pence")) or 0.0, 0.0)

    energy = 0.0
    income = 0.0
    if previous_start == current_start and previous_end == current_end:
        left = max(previous_ts, previous_start)
        right = min(current_ts, current_end)
        if right <= left:
            return None
        hours = (right - left).total_seconds() / 3600.0
        energy = ((previous_kw + current_kw) / 2.0) * hours
        average_rate = (previous_rate + current_rate) / 2.0
        income = energy * average_rate
    elif previous_end == current_start:
        previous_left = max(previous_ts, previous_start)
        previous_right = previous_end
        current_left = current_start
        current_right = min(current_ts, current_end)
        if previous_right > previous_left:
            previous_hours = (previous_right - previous_left).total_seconds() / 3600.0
            previous_energy = previous_kw * previous_hours
            energy += previous_energy
            income += previous_energy * previous_rate
        if current_right > current_left:
            current_hours = (current_right - current_left).total_seconds() / 3600.0
            current_energy = current_kw * current_hours
            energy += current_energy
            income += current_energy * current_rate
    else:
        return None

    return max(energy, 0.0), max(income, 0.0)


def _advance_tracker(
    tracker: dict[str, Any] | None,
    state: dict[str, Any],
    *,
    now: datetime,
) -> tuple[dict[str, Any], bool]:
    """Advance the persisted elapsed-solar ledger by one canonical sample."""
    sample = _route_sample(state)
    local_date = now.astimezone(agile.LONDON).date().isoformat()
    if not _valid_tracker(tracker) or tracker.get("local_date") != local_date:
        return _new_tracker(state, now=now, sample=sample), True

    updated = dict(tracker)
    previous = updated.get("last_sample")
    if sample is None:
        return updated, False
    if isinstance(previous, dict):
        increment = _integrated_increment(previous, sample)
        if increment is None:
            previous_ts = _dt(previous.get("timestamp"))
            current_ts = _dt(sample.get("timestamp"))
            if (
                previous_ts is not None
                and current_ts is not None
                and current_ts > previous_ts
            ):
                updated["skipped_gap_count"] = (
                    int(updated.get("skipped_gap_count", 0)) + 1
                )
        else:
            energy, income = increment
            updated["solar_export_kwh"] = round(
                max(_number(updated.get("solar_export_kwh")) or 0.0, 0.0) + energy,
                6,
            )
            updated["solar_export_income_pence"] = round(
                max(_number(updated.get("solar_export_income_pence")) or 0.0, 0.0)
                + income,
                6,
            )
            updated["tracked_increment_kwh"] = round(
                max(_number(updated.get("tracked_increment_kwh")) or 0.0, 0.0) + energy,
                6,
            )
            updated["tracked_increment_income_pence"] = round(
                max(_number(updated.get("tracked_increment_income_pence")) or 0.0, 0.0)
                + income,
                6,
            )
    updated["last_sample"] = dict(sample)
    updated["sample_count"] = int(updated.get("sample_count", 0)) + 1
    updated["hardware_writes"] = "blocked"
    return updated, True


def _apply_elapsed_solar_accounting(
    state: dict[str, Any],
    *,
    tracker: dict[str, Any],
    now: datetime,
) -> None:
    """Publish tracked elapsed solar + completed settled battery export."""
    today = _today_agile(state)
    diagnostic = state.get("current_day_settlement_reconciliation")
    if today is None or not isinstance(diagnostic, dict):
        return

    solar_export = round(max(_number(tracker.get("solar_export_kwh")) or 0.0, 0.0), 3)
    solar_income = max(_number(tracker.get("solar_export_income_pence")) or 0.0, 0.0)
    settled_battery_export = round(
        max(_number(diagnostic.get("battery_export_kwh")) or 0.0, 0.0),
        3,
    )
    settled_battery_income = _settled_battery_income(state, now=now)
    grid_export = round(solar_export + settled_battery_export, 3)
    export_income = round(solar_income + settled_battery_income, 2)

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
                export_income - fixed_income, 2
            ),
            "weighted_achieved_export_rate_pence": (
                round(export_income / grid_export, 4)
                if grid_export > _EPSILON
                else None
            ),
            "solar_export_accounting_source": (
                "parent baseline + elapsed canonical current-routing samples"
            ),
            "battery_export_accounting_source": (
                "completed digital-twin half-hour settlement only"
            ),
            "grid_export_accounting_source": (
                "elapsed canonical solar + completed settled battery export"
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
                "elapsed canonical solar + completed settled battery export"
            ),
            "live_solar_replay_applied": False,
            "live_solar_capture_preserved": False,
            "elapsed_live_solar_accounting_applied": True,
            "elapsed_live_solar_export_kwh": solar_export,
            "elapsed_live_solar_export_income_pence": round(solar_income, 2),
            "elapsed_live_solar_tracking_started_at": tracker.get(
                "tracking_started_at"
            ),
            "elapsed_live_solar_baseline_kwh": round(
                max(_number(tracker.get("baseline_solar_export_kwh")) or 0.0, 0.0), 3
            ),
            "elapsed_live_solar_increment_kwh": round(
                max(_number(tracker.get("tracked_increment_kwh")) or 0.0, 0.0), 3
            ),
            "elapsed_live_solar_sample_count": int(tracker.get("sample_count", 0)),
            "elapsed_live_solar_skipped_gap_count": int(
                tracker.get("skipped_gap_count", 0)
            ),
            "elapsed_live_solar_source": tracker.get("source"),
            "hardware_writes": "blocked",
        }
    )


def _battery_delta_kwh(slot: dict[str, Any], config: SimulationConfig) -> float:
    charge = max(_number(slot.get("flow_battery_charge_kwh")) or 0.0, 0.0)
    discharge = max(_number(slot.get("flow_battery_to_home_kwh")) or 0.0, 0.0)
    discharge += max(_number(slot.get("flow_battery_export_kwh")) or 0.0, 0.0)
    efficiency = max(float(config.discharge_efficiency), _EPSILON)
    return charge - (discharge / efficiency)


def _rebase_display_soc(
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
) -> None:
    """Make displayed SOC continuous with canonical current SOC and shown flows."""
    routing = state.get("current_routing_snapshot")
    if not isinstance(routing, dict) or not routing.get("available"):
        return
    current_soc = _number(routing.get("simulated_soc_percent"))
    start = _dt(routing.get("routing_valid_from"))
    end = _dt(routing.get("routing_valid_to"))
    now_utc = now.astimezone(UTC)
    if (
        current_soc is None
        or start is None
        or end is None
        or not (start <= now_utc < end)
        or config.battery_capacity_kwh <= _EPSILON
    ):
        return

    slots = [
        slot for slot in state.get("today_slots", []) or [] if isinstance(slot, dict)
    ]
    slots.sort(
        key=lambda slot: _dt(slot.get("valid_from")) or datetime.max.replace(tzinfo=UTC)
    )
    active_index = next(
        (
            index
            for index, slot in enumerate(slots)
            if _dt(slot.get("valid_from")) == start
        ),
        None,
    )
    if active_index is None:
        return

    active = slots[active_index]
    old_active_soc = _number(active.get("flow_estimated_soc_percent"))
    capacity = float(config.battery_capacity_kwh)
    battery_kwh = _clamp(current_soc, 0.0, 100.0) * capacity / 100.0
    battery_kwh = _clamp(
        battery_kwh + _battery_delta_kwh(active, config), 0.0, capacity
    )
    corrected_active_soc = 100.0 * battery_kwh / capacity
    active["flow_estimated_soc_percent"] = round(corrected_active_soc, 1)
    active["flow_soc_basis"] = (
        "canonical current SOC + remaining displayed battery flow"
    )
    active["flow_soc_current_percent"] = round(current_soc, 3)
    active["flow_soc_pre_rebase_estimate_percent"] = old_active_soc
    active["flow_soc_hardware_writes"] = "blocked"

    rebased_rows = 1
    for slot in slots[active_index + 1 :]:
        slot_start = _dt(slot.get("valid_from"))
        if slot_start is None or slot_start < end:
            continue
        if _number(slot.get("flow_estimated_soc_percent")) is None:
            continue
        battery_kwh = _clamp(
            battery_kwh + _battery_delta_kwh(slot, config),
            0.0,
            capacity,
        )
        old_soc = _number(slot.get("flow_estimated_soc_percent"))
        slot["flow_estimated_soc_percent"] = round(100.0 * battery_kwh / capacity, 1)
        slot["flow_soc_basis"] = (
            "rebased from canonical active SOC through displayed flow deltas"
        )
        slot["flow_soc_pre_rebase_estimate_percent"] = old_soc
        slot["flow_soc_hardware_writes"] = "blocked"
        rebased_rows += 1

    state["flow_soc_continuity"] = {
        "active": True,
        "generated_at": now.isoformat(),
        "current_soc_percent": round(current_soc, 3),
        "active_pre_rebase_soc_percent": old_active_soc,
        "active_rebased_soc_percent": round(corrected_active_soc, 3),
        "rebased_rows": rebased_rows,
        "basis": "canonical SOC + displayed battery-flow deltas",
        "reporting_only": True,
        "hardware_writes": "blocked",
    }


class LiveSolarSocContinuityAgileSmartExportManager(
    CanonicalFlowAccountingAgileSmartExportManager
):
    """Own canonical elapsed-solar accounting and displayed SOC continuity."""

    def __init__(self, hass: HomeAssistant, entry_id: str, history_days: int) -> None:
        super().__init__(hass, entry_id, history_days)
        self._alpha850_live_solar_store: Store[dict[str, Any]] = Store(
            hass,
            LIVE_SOLAR_STORE_VERSION,
            f"{DOMAIN}.{entry_id}.agile_live_solar_accounting",
        )
        self._alpha850_live_solar_tracker: dict[str, Any] | None = None
        self._alpha850_live_solar_dirty = False

    async def async_load(self) -> None:
        await super().async_load()
        data = await self._alpha850_live_solar_store.async_load() or {}
        tracker = data.get("tracker") if isinstance(data, dict) else None
        if _valid_tracker(tracker):
            self._alpha850_live_solar_tracker = dict(tracker)

    async def _save_alpha850_live_solar_tracker(self) -> None:
        if not self._alpha850_live_solar_dirty:
            return
        await self._alpha850_live_solar_store.async_save(
            {
                "tracker": (
                    dict(self._alpha850_live_solar_tracker)
                    if isinstance(self._alpha850_live_solar_tracker, dict)
                    else None
                )
            }
        )
        self._alpha850_live_solar_dirty = False

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
        tracker, changed = _advance_tracker(
            self._alpha850_live_solar_tracker,
            self._state,
            now=now,
        )
        self._alpha850_live_solar_tracker = tracker
        self._alpha850_live_solar_dirty = self._alpha850_live_solar_dirty or changed
        _apply_elapsed_solar_accounting(self._state, tracker=tracker, now=now)
        _rebase_display_soc(self._state, now=now, config=config)
        self._publish(self._state)
        if self._alpha850_live_solar_dirty:
            await self._save_alpha850_live_solar_tracker()
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
        tracker = self._alpha850_live_solar_tracker
        if isinstance(tracker, dict):
            _apply_elapsed_solar_accounting(self._state, tracker=tracker, now=now)
        config = getattr(self, "_rolling_config", None)
        if isinstance(config, SimulationConfig):
            _rebase_display_soc(self._state, now=now, config=config)
        self._publish(self._state)
        return self.state
