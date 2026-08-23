"""Full KEMS Agile 100% charge intent and post-cheap solar recovery.

KEMS deliberately keeps the user's 100% charge target even when the configured
overnight window cannot physically reach it from the 10% reserve.  The battery
therefore charges as hard as permitted throughout the authoritative cheap
window.  If it leaves that window below 100%, deliberate battery export is held
while available morning solar serves the home and fills the remaining battery
headroom.  Normal Agile battery export resumes once the replay reaches 100%.

The 10% reserve/export target is unchanged.  This module only changes the
simulation/shadow plan; real hardware writes remain blocked.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from . import agile_smart_export as agile
from .kems_core import SimulationConfig
from .tariff import TariffSettings

_EPSILON = 1e-6
_FULL_SOC_PERCENT = 100.0
_RECOVERY_DECISION_RATE_PENCE = -100.0


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _force_full_charge_target(records: list[Any]) -> list[Any]:
    """Keep 100% as the requested target in every authoritative cheap slot."""
    return [
        replace(item, forecast_maximum_overnight_soc_percent=_FULL_SOC_PERCENT)
        if bool(getattr(item, "cheap_period_confirmed", False))
        else item
        for item in records
    ]


def _morning_recovery_window(
    records: list[Any],
    tariff: TariffSettings,
) -> tuple[datetime, datetime] | None:
    """Return the daytime window immediately after the overnight cheap period."""
    ordered = sorted(records, key=lambda item: item.timestamp)
    for current, following in zip(ordered, ordered[1:], strict=False):
        current_local = current.timestamp.astimezone(agile.LONDON)
        following_local = following.timestamp.astimezone(agile.LONDON)
        current_scheduled = agile._in_window(
            current_local.time(), tariff.offpeak_start, tariff.offpeak_end
        )
        following_scheduled = agile._in_window(
            following_local.time(), tariff.offpeak_start, tariff.offpeak_end
        )
        if current_scheduled and not following_scheduled:
            start = following.timestamp.astimezone(UTC)
            end = agile._next_cheap(start, tariff).astimezone(UTC)
            return start, end
    return None


def _event_slot_starts(
    records: list[Any],
    rates: list[Any],
    tariff: TariffSettings,
) -> set[datetime]:
    """Return projected manual-event slots so their event dispatch is not masked."""
    starts: set[datetime] = set()
    for item in records:
        if not bool(getattr(item, "cheap_period_confirmed", False)):
            continue
        local = item.timestamp.astimezone(agile.LONDON)
        if agile._in_window(local.time(), tariff.offpeak_start, tariff.offpeak_end):
            continue
        rate = agile._rate_at(rates, item.timestamp)
        if rate is not None:
            starts.add(rate.valid_from.astimezone(UTC))
    return starts


def _masked_rates(
    rates: list[Any],
    start: datetime,
    end: datetime,
    *,
    excluded_starts: set[datetime],
) -> list[Any]:
    """Make recovery slots non-exportable without changing their real price record."""
    result = []
    for rate in rates:
        valid_from = rate.valid_from.astimezone(UTC)
        if (
            start <= valid_from < end
            and valid_from not in excluded_starts
        ):
            result.append(
                replace(rate, value_inc_vat=_RECOVERY_DECISION_RATE_PENCE)
            )
        else:
            result.append(rate)
    return result


def _datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _soc_before(plan: list[dict[str, Any]], start: datetime) -> float | None:
    """Return replay SOC at the end of the overnight cheap block."""
    candidates: list[tuple[datetime, float]] = []
    for item in plan:
        end = _datetime(item.get("valid_to"))
        soc = _number(item.get("ending_soc_percent"))
        if end is not None and end <= start and soc is not None:
            candidates.append((end, soc))
    return max(candidates, default=(start, None), key=lambda value: value[0])[1]


def _first_full_end(
    plan: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> datetime | None:
    """Return the first slot end at which solar recovery reaches full SOC."""
    for item in sorted(
        plan,
        key=lambda value: _datetime(value.get("valid_from"))
        or datetime.max.replace(tzinfo=UTC),
    ):
        valid_from = _datetime(item.get("valid_from"))
        valid_to = _datetime(item.get("valid_to"))
        soc = _number(item.get("ending_soc_percent"))
        if (
            valid_from is not None
            and valid_to is not None
            and start <= valid_from < end
            and soc is not None
            and soc >= _FULL_SOC_PERCENT - 0.05
        ):
            return min(valid_to, end)
    return None


def _slot_observed_energy(
    self,
    records: list[Any],
    start: datetime,
    end: datetime,
    config: SimulationConfig,
) -> tuple[float, float, float]:
    """Return house, solar and covered hours for one Agile settlement slot."""
    house = 0.0
    solar = 0.0
    hours_total = 0.0
    ordered = sorted(records, key=lambda item: item.timestamp)
    for current, following in zip(ordered, ordered[1:], strict=False):
        moment = current.timestamp.astimezone(UTC)
        if moment < start or moment >= end:
            continue
        hours = min(
            max((following.timestamp - current.timestamp).total_seconds(), 0.0)
            / 3600.0,
            0.5,
        )
        load = agile._load(current)
        if hours <= 0.0 or load is None:
            continue
        house += load * hours
        solar += self._simulation._simulated_solar_power(current, config) * hours
        hours_total += hours
    return house, max(solar, 0.0), hours_total


def _restore_recovery_solar_export(
    self,
    plan: list[dict[str, Any]],
    records: list[Any],
    config: SimulationConfig,
    start: datetime,
    end: datetime,
    excluded_starts: set[datetime],
) -> float:
    """Export only solar left after home and recovery charging in masked slots."""
    restored_total = 0.0
    efficiency = max(config.charge_efficiency, 0.01)
    for item in plan:
        valid_from = _datetime(item.get("valid_from"))
        valid_to = _datetime(item.get("valid_to"))
        if (
            valid_from is None
            or valid_to is None
            or not start <= valid_from < end
            or valid_from in excluded_starts
        ):
            continue
        house, solar, hours = _slot_observed_energy(
            self, records, valid_from, valid_to, config
        )
        if hours <= 0.0:
            continue
        inverter_energy = max(config.inverter_limit_kw, 0.0) * hours
        export_energy = min(
            max(config.export_limit_kw, 0.0) * hours,
            inverter_energy,
        )
        solar_home = min(solar, house, inverter_energy)
        stored = max(_number(item.get("solar_to_battery_kwh")) or 0.0, 0.0)
        storage_input = stored / efficiency
        battery_home = max(_number(item.get("battery_to_home_kwh")) or 0.0, 0.0)
        surplus = max(solar - solar_home - storage_input, 0.0)
        inverter_headroom = max(
            inverter_energy - solar_home - battery_home,
            0.0,
        )
        solar_export = min(surplus, export_energy, inverter_headroom)
        battery_export = max(
            _number(item.get("battery_export_kwh")) or 0.0,
            0.0,
        )
        item["solar_export_kwh"] = round(solar_export, 3)
        item["grid_export_kwh"] = round(solar_export + battery_export, 3)
        actions = list(item.get("actions") or [])
        recovery_action = "solar recovery to 100% before deliberate battery export"
        if recovery_action not in actions:
            actions.append(recovery_action)
        if solar_export > _EPSILON:
            surplus_action = "export solar surplus after recovery charging"
            if surplus_action not in actions:
                actions.append(surplus_action)
        item["actions"] = actions
        restored_total += solar_export
    return restored_total


def _restore_real_rates(
    plan: list[dict[str, Any]],
    rates: list[Any],
) -> dict[str, float]:
    """Restore real Agile prices after the decision-only recovery mask."""
    actual = {
        rate.valid_from.astimezone(UTC).isoformat(): float(rate.value_inc_vat)
        for rate in rates
    }
    for item in plan:
        start = _datetime(item.get("valid_from"))
        if start is None:
            continue
        value = actual.get(start.isoformat())
        if value is not None:
            item["rate_pence"] = round(value, 5)
    return actual


def _recalculate_export_finance(
    summary: dict[str, Any],
    plan: list[dict[str, Any]],
    actual_rates: dict[str, float],
    rates: list[Any],
    *,
    restored_solar_kwh: float,
) -> dict[str, Any]:
    """Recalculate export totals at the real rates after decision masking."""
    result = dict(summary)
    export = 0.0
    solar_export = 0.0
    battery_export = 0.0
    income = 0.0
    for item in plan:
        valid_from = _datetime(item.get("valid_from"))
        if valid_from is None:
            continue
        exported = max(_number(item.get("grid_export_kwh")) or 0.0, 0.0)
        export += exported
        solar_export += max(_number(item.get("solar_export_kwh")) or 0.0, 0.0)
        battery_export += max(_number(item.get("battery_export_kwh")) or 0.0, 0.0)
        income += exported * actual_rates.get(valid_from.isoformat(), 0.0)

    old_income = max(_number(result.get("export_income_pence")) or 0.0, 0.0)
    import_cost = max(_number(result.get("import_cost_pence")) or 0.0, 0.0)
    old_energy = _number(result.get("energy_net_cost_pence")) or 0.0
    standing = old_energy - import_cost + old_income
    wear = max(_number(result.get("battery_wear_cost_pence")) or 0.0, 0.0)
    fixed_income = export * agile.FIXED_EXPORT_PENCE
    energy_cost = import_cost + standing - income
    values = [float(rate.value_inc_vat) for rate in rates]

    result.update(
        {
            "grid_export_kwh": round(export, 3),
            "solar_export_kwh": round(solar_export, 3),
            "battery_export_kwh": round(battery_export, 3),
            "export_income_pence": round(income, 2),
            "fixed_12p_same_dispatch_income_pence": round(fixed_income, 2),
            "gain_vs_fixed_12p_same_dispatch_pence": round(
                income - fixed_income, 2
            ),
            "energy_net_cost_pence": round(energy_cost, 2),
            "economic_net_cost_pence": round(energy_cost + wear, 2),
            "weighted_achieved_export_rate_pence": (
                round(income / export, 4) if export > _EPSILON else None
            ),
            "average_agile_rate_pence": (
                round(sum(values) / len(values), 4) if values else None
            ),
            "highest_agile_rate_pence": round(max(values), 4) if values else None,
            "lowest_agile_rate_pence": round(min(values), 4) if values else None,
            "solar_curtailed_kwh": round(
                max(
                    (_number(result.get("solar_curtailed_kwh")) or 0.0)
                    - restored_solar_kwh,
                    0.0,
                ),
                3,
            ),
        }
    )
    return result


def install_charge_recovery_policy() -> None:
    """Install 100%-target and morning solar-recovery policy exactly once."""
    method = agile.AgileSmartExportManager._agile_day
    if getattr(method, "_kems_charge_recovery_policy", False):
        return
    original = method

    def agile_day_with_charge_recovery(
        self,
        records,
        rates,
        config,
        tariff,
        initial_soc,
    ):
        full_target_records = _force_full_charge_target(list(records))
        baseline_summary, baseline_plan = original(
            self,
            full_target_records,
            rates,
            config,
            tariff,
            initial_soc,
        )
        window = _morning_recovery_window(full_target_records, tariff)
        if window is None:
            return baseline_summary, baseline_plan
        start, end = window
        overnight_soc = _soc_before(baseline_plan, start)
        if overnight_soc is None or overnight_soc >= _FULL_SOC_PERCENT - 0.05:
            baseline_summary = dict(baseline_summary)
            baseline_summary["charge_target_soc_percent"] = _FULL_SOC_PERCENT
            baseline_summary["morning_solar_recovery_required"] = False
            return baseline_summary, baseline_plan

        event_starts = _event_slot_starts(full_target_records, rates, tariff)
        probe_rates = _masked_rates(
            rates,
            start,
            end,
            excluded_starts=event_starts,
        )
        _, probe_plan = original(
            self,
            full_target_records,
            probe_rates,
            config,
            tariff,
            initial_soc,
        )
        recovery_end = _first_full_end(probe_plan, start, end) or end
        final_rates = _masked_rates(
            rates,
            start,
            recovery_end,
            excluded_starts=event_starts,
        )
        summary, plan = original(
            self,
            full_target_records,
            final_rates,
            config,
            tariff,
            initial_soc,
        )
        restored = _restore_recovery_solar_export(
            self,
            plan,
            full_target_records,
            config,
            start,
            recovery_end,
            event_starts,
        )
        actual_rates = _restore_real_rates(plan, rates)
        summary = _recalculate_export_finance(
            summary,
            plan,
            actual_rates,
            rates,
            restored_solar_kwh=restored,
        )
        reached_full = recovery_end < end
        summary.update(
            {
                "charge_target_soc_percent": _FULL_SOC_PERCENT,
                "morning_solar_recovery_required": True,
                "morning_solar_recovery_start": start.isoformat(),
                "morning_solar_recovery_end": recovery_end.isoformat(),
                "morning_solar_recovery_reached_full": reached_full,
                "morning_solar_recovery_policy": (
                    "hold deliberate battery export until solar recovers 100% SOC"
                ),
                "battery_reserve_target_soc_percent": 10.0,
            }
        )
        return summary, plan

    agile_day_with_charge_recovery._kems_charge_recovery_policy = True
    agile.AgileSmartExportManager._agile_day = agile_day_with_charge_recovery
