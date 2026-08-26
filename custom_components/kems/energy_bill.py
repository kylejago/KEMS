"""Canonical Live Data vs KEMS bill-equivalent energy-cost contract."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from .kems_core import KEMSData, ScenarioSummary, Snapshot
from .product_types import (
    EXPORT_TARIFF_TYPE_AGILE,
    EXPORT_TARIFF_TYPE_FIXED,
    EXPORT_TARIFF_TYPE_NONE,
    kems_strategy_label,
)

PERIODS = {
    "today": (0, "Today"),
    "yesterday": (1, "Yesterday"),
    "this_week": (0, "This Week"),
    "last_week": (0, "Last Week"),
    "7_days": (7, "Last 7 days"),
    "this_month": (0, "This Month"),
    "last_month": (0, "Last Month"),
    "30_days": (30, "Last 30 days"),
    "year": (-1, "This Year"),
    "365_days": (365, "Rolling 365 evidence"),
    "all_time": (0, "All tracked evidence"),
}


def _f(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _daily(
    closed: Mapping[str, Mapping[str, Any]],
    tracking_date: date | None,
    tracking: Mapping[str, Any] | None,
) -> dict[date, dict[str, float]]:
    output: dict[date, dict[str, float]] = {}
    for key, values in closed.items():
        try:
            day = date.fromisoformat(str(key))
        except ValueError:
            continue
        output[day] = {
            str(name): float(value)
            for name, value in values.items()
            if isinstance(value, (int, float))
        }
    if tracking_date is not None and tracking:
        output[tracking_date] = {
            str(name): float(value)
            for name, value in tracking.items()
            if isinstance(value, (int, float))
        }
    return output


def _bounds(key: str, today: date, days: set[date]) -> tuple[date, date]:
    if key == "today":
        return today, today
    if key == "yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    if key == "this_week":
        return week_start, today
    if key == "last_week":
        end = week_start - timedelta(days=1)
        return end - timedelta(days=6), end
    if key == "7_days":
        return today - timedelta(days=6), today
    if key == "this_month":
        return today.replace(day=1), today
    if key == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if key == "30_days":
        return today - timedelta(days=29), today
    if key == "year":
        return today.replace(month=1, day=1), today
    if key == "365_days":
        return today - timedelta(days=364), today
    return (min(days), today) if days else (today, today)


def _standing_maps(
    records: list[Snapshot],
) -> tuple[dict[date, float], dict[date, float]]:
    electricity: dict[date, float] = {}
    gas: dict[date, float] = {}
    for item in sorted(records, key=lambda row: row.timestamp):
        day = item.timestamp.date()
        if item.electricity_standing_charge is not None:
            electricity[day] = max(float(item.electricity_standing_charge), 0.0)
        if item.gas_standing_charge is not None:
            gas[day] = max(float(item.gas_standing_charge), 0.0)
    return electricity, gas


def _standing(
    days: set[date], known: Mapping[date, float], fallback: float | None
) -> tuple[float, int]:
    default = max(_f(fallback), 0.0)
    total = 0.0
    estimated = 0
    for day in days:
        if day in known:
            total += known[day]
        else:
            total += default
            estimated += 1
    return round(total, 2), estimated


def _sum(rows: list[Mapping[str, Any]], field: str) -> float:
    return sum(_f(row.get(field)) for row in rows)


def _gas(
    rows: list[Mapping[str, Any]],
    days: set[date],
    standing_by_day: Mapping[date, float],
    fallback: float | None,
    available: bool,
) -> dict[str, Any]:
    if not available:
        return {
            "gas_available": False,
            "gas_usage_cost_pence": None,
            "gas_standing_charge_pence": None,
            "gas_total_cost_pence": None,
            "gas_usage_kwh": None,
        }
    total = round(_sum(rows, "gas_cost_pence"), 2)
    standing, estimated = _standing(days, standing_by_day, fallback)
    return {
        "gas_available": True,
        "gas_usage_cost_pence": round(total - standing, 2),
        "gas_standing_charge_pence": standing,
        "gas_total_cost_pence": total,
        "gas_usage_kwh": round(_sum(rows, "gas_consumption_kwh"), 3),
        "gas_standing_estimated_days": estimated,
    }


def _settled_power_down_reward(
    data: KEMSData,
    start: date,
    end: date,
    now: datetime,
) -> float | None:
    """Return the retained completed Power Down reward for this bill period."""
    result = data.last_power_down
    if (
        not result.available
        or result.completed_successfully is not True
        or result.session_start is None
        or result.bonus_pence is None
    ):
        return None

    event_at = result.session_start
    if event_at.tzinfo is not None and now.tzinfo is not None:
        event_at = event_at.astimezone(now.tzinfo)
    if not start <= event_at.date() <= end:
        return None
    return round(max(_f(result.bonus_pence), 0.0), 2)


def _live(
    rows: list[Mapping[str, Any]],
    days: set[date],
    elec_standing: Mapping[date, float],
    gas_standing: Mapping[date, float],
    data: KEMSData,
    gas_available: bool,
) -> dict[str, Any]:
    if not rows:
        return {"ready": False, "total_energy_cost_pence": None}
    imported = round(_sum(rows, "import_cost_pence"), 2)
    exported = round(_sum(rows, "export_income_pence"), 2)
    standing, estimated = _standing(
        days,
        elec_standing,
        data.snapshot.electricity_standing_charge,
    )
    gas = _gas(rows, days, gas_standing, data.gas.standing_charge_pence, gas_available)
    electricity_total = round(imported + standing - exported, 2)
    gas_total = gas["gas_total_cost_pence"]
    total = round(electricity_total + gas_total, 2) if gas_total is not None else None
    return {
        "ready": total is not None,
        "electricity_import_cost_pence": imported,
        "electricity_standing_charge_pence": standing,
        "electricity_export_income_pence": exported,
        "power_down_reward_pence": 0.0,
        "supplier_energy_credit_pence": 0.0,
        "electricity_total_cost_pence": electricity_total,
        **gas,
        "total_energy_cost_pence": total,
        "home_energy_kwh": round(_sum(rows, "house_consumption_kwh"), 3),
        "grid_import_kwh": round(_sum(rows, "grid_import_kwh"), 3),
        "grid_export_kwh": round(_sum(rows, "grid_export_kwh"), 3),
        "battery_wear_included": False,
        "electricity_standing_estimated_days": estimated,
        "evidence": "Measured KEMS daily billing ledger",
    }


def _scenario(
    scenario: ScenarioSummary | None,
    gas: Mapping[str, Any],
    settled_power_down_reward_pence: float | None = None,
) -> dict[str, Any]:
    if scenario is None or not scenario.ready:
        return {"ready": False, "total_energy_cost_pence": None}

    reward = (
        round(max(settled_power_down_reward_pence, 0.0), 2)
        if settled_power_down_reward_pence is not None
        else round(scenario.power_down_income_pence, 2)
    )
    if settled_power_down_reward_pence is None:
        electric = round(scenario.total_cost_pence, 2)
        reward_source = "scenario_estimate"
    else:
        electric = round(
            scenario.import_cost_pence
            + scenario.standing_charge_pence
            - scenario.export_income_pence
            - reward,
            2,
        )
        reward_source = "settled_power_down_event"

    gas_total = gas.get("gas_total_cost_pence")
    return {
        "ready": gas_total is not None,
        "electricity_import_cost_pence": round(scenario.import_cost_pence, 2),
        "electricity_standing_charge_pence": round(scenario.standing_charge_pence, 2),
        "electricity_export_income_pence": round(scenario.export_income_pence, 2),
        "power_down_reward_pence": reward,
        "power_down_reward_source": reward_source,
        "supplier_energy_credit_pence": reward,
        "electricity_total_cost_pence": electric,
        **gas,
        "total_energy_cost_pence": (
            round(electric + gas_total, 2) if gas_total is not None else None
        ),
        "home_energy_kwh": round(scenario.house_consumption_kwh, 3),
        "grid_import_kwh": round(scenario.grid_import_kwh, 3),
        "grid_export_kwh": round(scenario.grid_export_kwh, 3),
        "battery_wear_included": False,
        "evidence": "Canonical KEMS scenario replay",
    }


def _strategy_days(
    closed: Mapping[str, Mapping[str, Any]],
    state: Mapping[str, Any],
    strategy: str,
    today: date,
) -> dict[date, Mapping[str, Any]]:
    output: dict[date, Mapping[str, Any]] = {}
    for key, value in closed.items():
        try:
            day = date.fromisoformat(str(key))
        except ValueError:
            continue
        row = value.get(strategy) if isinstance(value, Mapping) else None
        if isinstance(row, Mapping) and row.get("ready") is not False:
            output[day] = row
    current = ((state.get("periods") or {}).get("today") or {}).get(strategy)
    if isinstance(current, Mapping) and current.get("ready") is not False:
        output[today] = current
    return output


def _strategy(
    rows: list[Mapping[str, Any]],
    days: set[date],
    gas: Mapping[str, Any],
    standing_by_day: Mapping[date, float],
    fallback_standing: float | None,
    label: str,
    settled_power_down_reward_pence: float | None = None,
) -> dict[str, Any]:
    if not rows:
        return {"ready": False, "total_energy_cost_pence": None}
    imported = round(_sum(rows, "import_cost_pence"), 2)
    exported = round(_sum(rows, "export_income_pence"), 2)
    produced = round(_sum(rows, "energy_net_cost_pence"), 2)
    standing, estimated = _standing(days, standing_by_day, fallback_standing)

    # Older retained producers can have a reward folded into their net result.
    # Prefer the explicit completed Power Down settlement when it is available,
    # replacing (rather than adding to) that legacy reconciliation.
    inferred_reward = round(max(imported + standing - exported - produced, 0.0), 2)
    reward = (
        round(max(settled_power_down_reward_pence, 0.0), 2)
        if settled_power_down_reward_pence is not None
        else inferred_reward
    )
    electric = round(imported + standing - exported - reward, 2)
    gas_total = gas.get("gas_total_cost_pence")
    return {
        "ready": gas_total is not None,
        "electricity_import_cost_pence": imported,
        "electricity_standing_charge_pence": standing,
        "electricity_export_income_pence": exported,
        "power_down_reward_pence": reward,
        "power_down_reward_source": (
            "settled_power_down_event"
            if settled_power_down_reward_pence is not None
            else "legacy_reconciliation"
        ),
        "supplier_energy_credit_pence": reward,
        "electricity_total_cost_pence": electric,
        **gas,
        "total_energy_cost_pence": (
            round(electric + gas_total, 2) if gas_total is not None else None
        ),
        "home_energy_kwh": round(_sum(rows, "house_load_kwh"), 3),
        "grid_import_kwh": round(_sum(rows, "grid_import_kwh"), 3),
        "grid_export_kwh": round(_sum(rows, "grid_export_kwh"), 3),
        "battery_wear_included": False,
        "electricity_standing_estimated_days": estimated,
        "evidence": f"{label} retained replay",
    }


def build_energy_cost_comparison(
    *,
    data: KEMSData,
    agile_state: Mapping[str, Any],
    agile_daily: Mapping[str, Mapping[str, Any]],
    daily_records: Mapping[str, Mapping[str, Any]],
    tracking_date: date | None,
    tracking_values: Mapping[str, Any] | None,
    history_records: list[Snapshot],
    export_tariff_type: str,
    now: datetime,
) -> dict[str, Any]:
    """Return the one financial payload used by Home Assistant and KEMS Web."""
    actual = _daily(daily_records, tracking_date, tracking_values)
    actual_days = set(actual)
    elec_standing, gas_standing = _standing_maps(history_records)
    gas_available = bool(
        data.gas.available
        or any(_f(row.get("gas_cost_pence")) for row in actual.values())
    )
    strategy_label = kems_strategy_label(export_tariff_type)
    retained_key = (
        "agile_smart_export"
        if export_tariff_type == EXPORT_TARIFF_TYPE_AGILE
        else "full_kems_forecast"
    )
    retained = _strategy_days(agile_daily, agile_state, retained_key, now.date())

    periods: dict[str, Any] = {}
    for key, (_, label) in PERIODS.items():
        start, end = _bounds(key, now.date(), actual_days)
        dates = {day for day in actual_days if start <= day <= end}
        rows = [actual[day] for day in sorted(dates)]
        live = _live(rows, dates, elec_standing, gas_standing, data, gas_available)
        gas = {name: value for name, value in live.items() if name.startswith("gas_")}
        settled_reward = _settled_power_down_reward(data, start, end, now)

        if export_tariff_type == EXPORT_TARIFF_TYPE_NONE and key in {
            "today",
            "yesterday",
            "7_days",
            "30_days",
        }:
            period = data.scenarios.period(key)
            kems = _scenario(
                period.scenario("kems_no_export") if period else None,
                gas,
                settled_reward,
            )
        elif export_tariff_type in {
            EXPORT_TARIFF_TYPE_FIXED,
            EXPORT_TARIFF_TYPE_AGILE,
        }:
            strategy_dates = {
                day
                for day in retained
                if start <= day <= end and (not dates or day in dates)
            }
            strategy_rows = [retained[day] for day in sorted(strategy_dates)]
            if (
                not strategy_rows
                and export_tariff_type == EXPORT_TARIFF_TYPE_FIXED
                and key in {"today", "yesterday", "7_days", "30_days"}
            ):
                period = data.scenarios.period(key)
                kems = _scenario(
                    period.scenario("kems_forecast") if period else None,
                    gas,
                    settled_reward,
                )
            else:
                kems = _strategy(
                    strategy_rows,
                    strategy_dates,
                    gas,
                    elec_standing,
                    data.snapshot.electricity_standing_charge,
                    strategy_label,
                    settled_reward,
                )
        else:
            kems = {
                "ready": False,
                "total_energy_cost_pence": None,
                "evidence": "Matching long-range no-export replay is still building",
            }

        kems["strategy"] = export_tariff_type
        kems["strategy_label"] = strategy_label
        live_total = live.get("total_energy_cost_pence")
        kems_total = kems.get("total_energy_cost_pence")
        saving = (
            round(float(live_total) - float(kems_total), 2)
            if live_total is not None and kems_total is not None
            else None
        )
        periods[key] = {
            "label": label,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days_included": len(dates),
            "live_data": live,
            "kems": kems,
            "saving_pence": saving,
            "comparable": bool(live.get("ready") and kems.get("ready")),
        }

    today = periods["today"]
    return {
        "contract_version": 2,
        "headline": "Total energy cost",
        "basis": "bill_equivalent",
        "formula": (
            "electricity import + electricity standing charge - electricity export "
            "income - settled Power Down rewards + gas usage + gas standing charge"
        ),
        "battery_wear_included": False,
        "gas_included": True,
        "standing_charges_included": True,
        "selected_kems_strategy": export_tariff_type,
        "selected_kems_strategy_label": strategy_label,
        "products": ["live_data", "kems"],
        "periods": periods,
        "today_live_total_energy_cost_pence": today["live_data"].get(
            "total_energy_cost_pence"
        ),
        "today_kems_total_energy_cost_pence": today["kems"].get(
            "total_energy_cost_pence"
        ),
        "today_saving_pence": today.get("saving_pence"),
        "generated_at": now.isoformat(),
        "reporting_only": True,
        "hardware_writes": "blocked",
    }
