"""Hard 10%-by-cheap-window deadline for Agile Smart Export.

The Agile price optimiser may move battery export between half-hour slots, but it
must never wait so long that the configured battery can no longer reach the
10% pre-cheap target through the real inverter/export path. This module replaces
only the Agile day dispatch method; the rest of the comparison engine remains
unchanged and simulation-only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import agile_smart_export as agile
from .kems_core import SimulationConfig, Snapshot
from .tariff import TariffSettings

AGILE_TARGET_SOC_PERCENT = 10.0
_EPSILON = 1e-6


def _effective_deadline_kw(config: SimulationConfig) -> float:
    """Return the conservative AC battery-discharge path available to the grid."""
    return max(
        min(
            max(config.max_discharge_kw, 0.0),
            max(config.inverter_limit_kw, 0.0),
            max(config.export_limit_kw, 0.0),
        ),
        0.0,
    )


def _remaining_capacity_kwh(
    start: datetime,
    deadline: datetime,
    effective_kw: float,
) -> float:
    """Return best-case AC discharge energy available between two instants."""
    hours = max((deadline - start).total_seconds() / 3600.0, 0.0)
    return hours * max(effective_kw, 0.0)


def _target_percent(config: SimulationConfig) -> float:
    """Never plan below either the KEMS reserve or the explicit Agile target."""
    return min(
        max(AGILE_TARGET_SOC_PERCENT, config.battery_reserve_percent, 0.0),
        100.0,
    )


def _deadline_metrics(
    *,
    battery_kwh: float,
    timestamp: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Describe whether the 10%-by-cheap-window target is still reachable."""
    capacity = max(config.battery_capacity_kwh, 0.1)
    efficiency = max(config.discharge_efficiency, 0.01)
    target_percent = _target_percent(config)
    target_kwh = capacity * target_percent / 100.0
    deadline = agile._next_cheap(timestamp, tariff)
    effective_kw = _effective_deadline_kw(config)
    required_ac = max(battery_kwh - target_kwh, 0.0) * efficiency
    remaining_ac = _remaining_capacity_kwh(timestamp, deadline, effective_kw)
    margin = remaining_ac - required_ac
    hours = max((deadline - timestamp).total_seconds() / 3600.0, 0.0)
    required_average_kw = required_ac / hours if hours > _EPSILON else None
    minimum_battery_kwh = max(
        battery_kwh - remaining_ac / efficiency,
        capacity * max(config.battery_reserve_percent, 0.0) / 100.0,
    )
    minimum_soc = min(max(100.0 * minimum_battery_kwh / capacity, 0.0), 100.0)

    if required_ac <= 0.01:
        status = "Target reached"
    elif effective_kw <= _EPSILON or hours <= _EPSILON or margin < -0.05:
        status = "Physically unreachable"
    elif margin <= max(effective_kw * 0.5, 0.25):
        status = "At risk"
    else:
        status = "On track"

    return {
        "deadline_target_soc_percent": round(target_percent, 1),
        "deadline_time": deadline.isoformat(),
        "deadline_status": status,
        "deadline_effective_discharge_kw": round(effective_kw, 3),
        "deadline_required_discharge_kwh": round(required_ac, 3),
        "deadline_max_remaining_discharge_kwh": round(remaining_ac, 3),
        "deadline_margin_kwh": round(margin, 3),
        "deadline_required_average_kw": (
            round(required_average_kw, 3)
            if required_average_kw is not None
            else None
        ),
        "deadline_minimum_reachable_soc_percent": round(minimum_soc, 1),
    }


def agile_day_with_deadline(
    self,
    records: list[Snapshot],
    rates: list[agile.AgileRate],
    config: SimulationConfig,
    tariff: TariffSettings,
    initial_soc: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Optimise Agile prices without ever sacrificing the 10% deadline."""
    capacity = max(config.battery_capacity_kwh, 0.1)
    reserve = capacity * max(config.battery_reserve_percent, 0.0) / 100.0
    target_kwh = capacity * _target_percent(config) / 100.0
    efficiency = max(config.discharge_efficiency, 0.01)
    effective_deadline_kw = _effective_deadline_kw(config)
    battery = min(max(capacity * initial_soc / 100.0, reserve), capacity)
    totals = {
        key: 0.0
        for key in (
            "import_cost",
            "income",
            "fixed_income",
            "grid_import",
            "grid_export",
            "solar",
            "solar_home",
            "solar_battery",
            "solar_export",
            "grid_battery",
            "battery_home",
            "battery_export",
            "curtailed",
        )
    }
    intervals = covered = 0
    plans: dict[str, dict[str, Any]] = {}
    last_timestamp = records[0].timestamp if records else datetime.now(agile.UTC)

    for index, (current, following) in enumerate(
        zip(records, records[1:], strict=False)
    ):
        hours = min(
            max((following.timestamp - current.timestamp).total_seconds(), 0.0)
            / 3600.0,
            0.5,
        )
        if hours <= 0:
            continue
        intervals += 1
        slot = agile._rate_at(rates, current.timestamp)
        load = agile._load(current)
        if (
            current.stale_fields
            or following.stale_fields
            or slot is None
            or load is None
            or agile._load(following) is None
            or current.current_import_rate is None
        ):
            continue

        covered += 1
        last_timestamp = following.timestamp
        rate = slot.value_inc_vat
        import_rate = float(current.current_import_rate)
        load_kwh = load * hours
        solar_kwh = self._simulation._simulated_solar_power(current, config) * hours
        inverter = max(config.inverter_limit_kw, 0.0) * hours
        export_limit = min(max(config.export_limit_kw, 0.0) * hours, inverter)
        charge_limit = max(config.max_charge_kw, 0.0) * hours
        discharge_limit = max(config.max_discharge_kw, 0.0) * hours
        grid_import = solar_home = solar_battery = solar_export = 0.0
        grid_battery = battery_home = battery_export = curtailed = 0.0
        actions: list[str] = []

        if current.cheap_period_confirmed:
            grid_import = load_kwh
            target = capacity * agile._overnight_target(current, config) / 100.0
            solar_left = solar_kwh
            if rate <= 0:
                charge = min(
                    solar_left,
                    charge_limit,
                    max(target - battery, 0.0)
                    / max(config.charge_efficiency, 0.01),
                )
                solar_battery = charge * config.charge_efficiency
                battery += solar_battery
                solar_left -= charge
                if charge:
                    actions.append("store solar")
            grid_charge = min(
                max(
                    charge_limit
                    - solar_battery / max(config.charge_efficiency, 0.01),
                    0.0,
                ),
                max(target - battery, 0.0)
                / max(config.charge_efficiency, 0.01),
            )
            if config.site_import_limit_kw is not None:
                grid_charge = min(
                    grid_charge,
                    max(config.site_import_limit_kw * hours - grid_import, 0.0),
                )
            grid_battery = grid_charge * config.charge_efficiency
            battery += grid_battery
            grid_import += grid_charge
            if grid_charge:
                actions.append("cheap charge")
            if rate > 0:
                solar_export = min(solar_left, export_limit)
                curtailed = max(solar_left - solar_export, 0.0)
                if solar_export:
                    actions.append("export solar")
            else:
                curtailed += solar_left
        else:
            solar_home = min(solar_kwh, load_kwh, inverter)
            remaining_load = max(load_kwh - solar_home, 0.0)
            floor = self._floor(
                records,
                index,
                current,
                config,
                reserve,
                capacity,
            )
            available = max(battery - floor, 0.0) * efficiency
            battery_home = min(
                remaining_load,
                discharge_limit,
                available,
                max(inverter - solar_home, 0.0),
            )
            battery -= battery_home / efficiency
            grid_import = max(remaining_load - battery_home, 0.0)
            if battery_home:
                actions.append("battery to home")
            if grid_import:
                actions.append("protected import")

            solar_left = max(solar_kwh - solar_home, 0.0)
            next_cheap = agile._next_cheap(current.timestamp, tariff)
            future_after_current = _remaining_capacity_kwh(
                following.timestamp,
                next_cheap,
                effective_deadline_kw,
            )
            pre_export_inverter_used = solar_home + battery_home
            current_battery_export_cap = min(
                export_limit,
                max(inverter - pre_export_inverter_used, 0.0),
                max(discharge_limit - battery_home, 0.0),
            )
            required_before_store = max(battery - target_kwh, 0.0) * efficiency
            deadline_margin_before_store = (
                current_battery_export_cap
                + future_after_current
                - required_before_store
            )

            best_future = agile._best_rate(
                rates,
                current.timestamp + agile.timedelta(seconds=1),
                next_cheap,
            )
            stored_value = (
                best_future * config.charge_efficiency * config.discharge_efficiency
                - agile.BATTERY_WEAR_PENCE_PER_KWH
            )
            wants_storage = (
                solar_left
                and battery < capacity
                and (battery < floor or stored_value > rate + 0.001)
            )
            if wants_storage:
                charge = min(
                    solar_left,
                    charge_limit,
                    max(capacity - battery, 0.0)
                    / max(config.charge_efficiency, 0.01),
                )
                if battery >= floor:
                    max_input_by_deadline = max(deadline_margin_before_store, 0.0) / max(
                        config.charge_efficiency * efficiency,
                        0.01,
                    )
                    charge = min(charge, max_input_by_deadline)
                solar_battery = charge * config.charge_efficiency
                battery += solar_battery
                solar_left -= charge
                if charge:
                    actions.append("store solar for higher Agile slot")
                elif solar_left:
                    actions.append("deadline blocks extra solar storage")

            inverter_used = solar_home + battery_home
            required_after_store = max(battery - target_kwh, 0.0) * efficiency
            mandatory_now = max(required_after_store - future_after_current, 0.0)
            deadline_reserve_ac = min(
                mandatory_now,
                max(export_limit, 0.0),
                max(inverter - inverter_used, 0.0),
                max(discharge_limit - battery_home, 0.0),
            )

            if rate > 0:
                solar_export = min(
                    solar_left,
                    max(export_limit - deadline_reserve_ac, 0.0),
                    max(inverter - inverter_used - deadline_reserve_ac, 0.0),
                )
                if solar_export:
                    actions.append("export solar")
            curtailed = max(solar_left - solar_export, 0.0)
            inverter_used += solar_export

            floor = self._floor(
                records,
                index,
                current,
                config,
                reserve,
                capacity,
            )
            exportable = max(battery - floor, 0.0) * efficiency
            threshold = agile._threshold(
                rates,
                current.timestamp,
                next_cheap,
                exportable,
                effective_deadline_kw,
            )
            available_export = min(
                exportable,
                max(export_limit - solar_export, 0.0),
                max(inverter - inverter_used, 0.0),
                max(discharge_limit - battery_home, 0.0),
            )
            price_export = bool(
                rate > 0
                and threshold is not None
                and rate + _EPSILON >= threshold
            )
            requested_export = available_export if price_export else 0.0
            if mandatory_now > requested_export:
                requested_export = min(mandatory_now, available_export)
            battery_export = min(requested_export, available_export)
            battery -= battery_export / efficiency
            if battery_export:
                if mandatory_now > _EPSILON:
                    actions.append("deadline export to protect 10% target")
                elif price_export:
                    actions.append("export battery at high Agile price")

        battery = min(max(battery, reserve), capacity)
        exported = solar_export + battery_export
        totals["import_cost"] += grid_import * import_rate
        totals["income"] += exported * rate
        totals["fixed_income"] += exported * agile.FIXED_EXPORT_PENCE
        for key, value in (
            ("grid_import", grid_import),
            ("grid_export", exported),
            ("solar", solar_kwh),
            ("solar_home", solar_home),
            ("solar_battery", solar_battery),
            ("solar_export", solar_export),
            ("grid_battery", grid_battery),
            ("battery_home", battery_home),
            ("battery_export", battery_export),
            ("curtailed", curtailed),
        ):
            totals[key] += value

        key = slot.valid_from.isoformat()
        plan = plans.setdefault(
            key,
            {
                "valid_from": slot.valid_from.isoformat(),
                "valid_to": slot.valid_to.isoformat(),
                "rate_pence": round(rate, 5),
                "grid_import_kwh": 0.0,
                "grid_export_kwh": 0.0,
                "solar_export_kwh": 0.0,
                "solar_to_battery_kwh": 0.0,
                "battery_to_home_kwh": 0.0,
                "battery_export_kwh": 0.0,
                "ending_soc_percent": None,
                "actions": [],
            },
        )
        for name, value in (
            ("grid_import_kwh", grid_import),
            ("grid_export_kwh", exported),
            ("solar_export_kwh", solar_export),
            ("solar_to_battery_kwh", solar_battery),
            ("battery_to_home_kwh", battery_home),
            ("battery_export_kwh", battery_export),
        ):
            plan[name] += value
        plan["ending_soc_percent"] = round(100.0 * battery / capacity, 1)
        plan["actions"].extend(
            action for action in actions if action not in plan["actions"]
        )

    coverage = covered / intervals if intervals else 0.0
    wear = (
        totals["battery_home"] + totals["battery_export"]
    ) * agile.BATTERY_WEAR_PENCE_PER_KWH
    standing = agile._standing(records)
    energy_cost = totals["import_cost"] + standing - totals["income"]
    fixed_cost = (
        totals["import_cost"] + standing - totals["fixed_income"] + wear
    )
    weighted = (
        totals["income"] / totals["grid_export"]
        if totals["grid_export"] > _EPSILON
        else None
    )
    values = [item.value_inc_vat for item in rates]
    summary = {
        "ready": bool(covered >= 3 and coverage >= agile.MIN_COVERAGE and rates),
        "data_coverage": round(coverage, 4),
        "energy_net_cost_pence": round(energy_cost, 2),
        "economic_net_cost_pence": round(energy_cost + wear, 2),
        "import_cost_pence": round(totals["import_cost"], 2),
        "export_income_pence": round(totals["income"], 2),
        "fixed_12p_same_dispatch_income_pence": round(totals["fixed_income"], 2),
        "gain_vs_fixed_12p_same_dispatch_pence": round(
            fixed_cost - (energy_cost + wear),
            2,
        ),
        "grid_import_kwh": round(totals["grid_import"], 3),
        "grid_export_kwh": round(totals["grid_export"], 3),
        "solar_generation_kwh": round(totals["solar"], 3),
        "solar_to_home_kwh": round(totals["solar_home"], 3),
        "solar_to_battery_kwh": round(totals["solar_battery"], 3),
        "solar_export_kwh": round(totals["solar_export"], 3),
        "grid_to_battery_kwh": round(totals["grid_battery"], 3),
        "battery_to_home_kwh": round(totals["battery_home"], 3),
        "battery_export_kwh": round(totals["battery_export"], 3),
        "solar_curtailed_kwh": round(totals["curtailed"], 3),
        "battery_wear_cost_pence": round(wear, 2),
        "weighted_achieved_export_rate_pence": (
            round(weighted, 4) if weighted is not None else None
        ),
        "average_agile_rate_pence": (
            round(sum(values) / len(values), 4) if values else None
        ),
        "highest_agile_rate_pence": round(max(values), 4) if values else None,
        "lowest_agile_rate_pence": round(min(values), 4) if values else None,
        "ending_soc_percent": round(100.0 * battery / capacity, 1),
        **_deadline_metrics(
            battery_kwh=battery,
            timestamp=last_timestamp,
            config=config,
            tariff=tariff,
        ),
    }

    payload = []
    for slot in rates:
        item = plans.get(slot.valid_from.isoformat())
        if item:
            item = dict(item)
            for name in (
                "grid_import_kwh",
                "grid_export_kwh",
                "solar_export_kwh",
                "solar_to_battery_kwh",
                "battery_to_home_kwh",
                "battery_export_kwh",
            ):
                item[name] = round(float(item[name]), 3)
        else:
            item = {
                "valid_from": slot.valid_from.isoformat(),
                "valid_to": slot.valid_to.isoformat(),
                "rate_pence": round(slot.value_inc_vat, 5),
                "grid_import_kwh": None,
                "grid_export_kwh": None,
                "solar_export_kwh": None,
                "solar_to_battery_kwh": None,
                "battery_to_home_kwh": None,
                "battery_export_kwh": None,
                "ending_soc_percent": None,
                "actions": ["future slot"],
            }
        payload.append(item)
    return summary, payload


def aggregate_with_deadline(
    days: list[dict[str, Any]],
    key: str,
    label: str,
) -> dict[str, Any]:
    """Preserve current-day deadline metrics through the reporting aggregate."""
    period = _ORIGINAL_AGGREGATE(days, key, label)
    ready = [item for item in days if item and item.get("ready")]
    if len(ready) != 1:
        return period
    source = ready[0].get("agile_smart_export", {})
    target = period.get("agile_smart_export", {})
    for name in (
        "deadline_target_soc_percent",
        "deadline_time",
        "deadline_status",
        "deadline_effective_discharge_kw",
        "deadline_required_discharge_kwh",
        "deadline_max_remaining_discharge_kwh",
        "deadline_margin_kwh",
        "deadline_required_average_kw",
        "deadline_minimum_reachable_soc_percent",
    ):
        target[name] = source.get(name)
    return period


def publish_with_deadline(self, state: dict[str, Any]) -> None:
    """Publish deadline status as first-class simulation entities."""
    _ORIGINAL_PUBLISH(self, state)
    periods = state.get("periods", {})
    today = periods.get("today", {}) if isinstance(periods, dict) else {}
    data = (
        today.get("agile_smart_export", {})
        if isinstance(today, dict)
        else {}
    )
    values = (
        (
            "sensor.kems_agile_deadline_target_soc",
            data.get("deadline_target_soc_percent"),
            "Agile Smart Export target SOC at cheap-window start",
            "%",
        ),
        (
            "sensor.kems_agile_deadline_required_average_kw",
            data.get("deadline_required_average_kw"),
            "Agile required average discharge to target",
            "kW",
        ),
        (
            "sensor.kems_agile_deadline_effective_discharge_kw",
            data.get("deadline_effective_discharge_kw"),
            "Agile effective deadline discharge limit",
            "kW",
        ),
        (
            "sensor.kems_agile_deadline_required_discharge_kwh",
            data.get("deadline_required_discharge_kwh"),
            "Agile energy still required to reach target",
            "kWh",
        ),
        (
            "sensor.kems_agile_deadline_remaining_capacity_kwh",
            data.get("deadline_max_remaining_discharge_kwh"),
            "Agile maximum remaining discharge capacity",
            "kWh",
        ),
        (
            "sensor.kems_agile_deadline_margin_kwh",
            data.get("deadline_margin_kwh"),
            "Agile deadline energy margin",
            "kWh",
        ),
        (
            "sensor.kems_agile_deadline_minimum_reachable_soc",
            data.get("deadline_minimum_reachable_soc_percent"),
            "Agile minimum physically reachable SOC at deadline",
            "%",
        ),
    )
    common = {
        "mode": "simulation_only",
        "deadline": data.get("deadline_time"),
        "target_soc_percent": data.get("deadline_target_soc_percent"),
    }
    for entity_id, value, friendly_name, unit in values:
        self._set(
            entity_id,
            agile._state(value),
            {
                "friendly_name": friendly_name,
                "unit_of_measurement": unit,
                **common,
            },
        )
    self._set(
        "sensor.kems_agile_deadline_status",
        data.get("deadline_status") or "Unavailable",
        {
            "friendly_name": "Agile 10% deadline status",
            **common,
            "required_average_kw": data.get("deadline_required_average_kw"),
            "effective_discharge_kw": data.get("deadline_effective_discharge_kw"),
            "required_discharge_kwh": data.get("deadline_required_discharge_kwh"),
            "remaining_capacity_kwh": data.get(
                "deadline_max_remaining_discharge_kwh"
            ),
            "margin_kwh": data.get("deadline_margin_kwh"),
            "minimum_reachable_soc_percent": data.get(
                "deadline_minimum_reachable_soc_percent"
            ),
        },
    )


_ORIGINAL_AGGREGATE = agile._aggregate
_ORIGINAL_PUBLISH = agile.AgileSmartExportManager._publish


def install_deadline_patch() -> None:
    """Install the hard Agile deadline exactly once."""
    method = agile.AgileSmartExportManager._agile_day
    if not getattr(method, "_kems_agile_deadline", False):
        agile_day_with_deadline._kems_agile_deadline = True
        agile.AgileSmartExportManager._agile_day = agile_day_with_deadline

    aggregate = agile._aggregate
    if not getattr(aggregate, "_kems_agile_deadline", False):
        aggregate_with_deadline._kems_agile_deadline = True
        agile._aggregate = aggregate_with_deadline

    publish = agile.AgileSmartExportManager._publish
    if not getattr(publish, "_kems_agile_deadline", False):
        publish_with_deadline._kems_agile_deadline = True
        agile.AgileSmartExportManager._publish = publish_with_deadline
