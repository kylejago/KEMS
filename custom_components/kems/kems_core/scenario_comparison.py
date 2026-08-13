"""Parallel what-if scenario comparison for KEMS.

This module deliberately keeps comparison replay separate from the live/control
simulation.  Every scenario is evaluated from the same retained observations so
users can compare system choices without changing the active KEMS operating
strategy.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

from .models import (
    ScenarioComparisonState,
    ScenarioPeriodComparison,
    ScenarioSummary,
    ScenarioTimelinePoint,
    SimulationConfig,
    SimulationState,
    Snapshot,
)
from .simulation import SimulationEngine, _interval_hours, _load_kw

SCENARIO_NO_SYSTEM = "no_system"
SCENARIO_SOLAR_ONLY = "solar_only"
SCENARIO_SOLAR_BATTERY = "solar_battery"
SCENARIO_KEMS_NO_EXPORT = "kems_no_export"
SCENARIO_KEMS_FULL = "kems_full"
SCENARIO_FULL_ISLAND = "full_island"
FINANCIAL_SCENARIO_KEYS = (
    SCENARIO_NO_SYSTEM,
    SCENARIO_SOLAR_ONLY,
    SCENARIO_SOLAR_BATTERY,
    SCENARIO_KEMS_NO_EXPORT,
    SCENARIO_KEMS_FULL,
)
SCENARIO_KEYS = (*FINANCIAL_SCENARIO_KEYS, SCENARIO_FULL_ISLAND)

SCENARIO_LABELS = {
    SCENARIO_NO_SYSTEM: "No system",
    SCENARIO_SOLAR_ONLY: "Solar only",
    SCENARIO_SOLAR_BATTERY: "Solar + battery",
    SCENARIO_KEMS_NO_EXPORT: "KEMS no-export",
    SCENARIO_KEMS_FULL: "Full KEMS smart control",
    SCENARIO_FULL_ISLAND: "Full island mode — grid down",
}

SCENARIO_DESCRIPTIONS = {
    SCENARIO_NO_SYSTEM: "Grid supplies the whole home; no solar or battery.",
    SCENARIO_SOLAR_ONLY: (
        "Proposal/live solar supplies the home first; surplus is exported at the "
        "configured paid export rate; no battery."
    ),
    SCENARIO_SOLAR_BATTERY: (
        "Conventional self-use: solar supplies the home then battery, battery "
        "supplies the home, surplus solar is exported; no tariff-aware grid charging."
    ),
    SCENARIO_KEMS_NO_EXPORT: (
        "KEMS solar-aware self-use while export is unpaid: cheap charging only to "
        "the calculated target, no deliberate export."
    ),
    SCENARIO_KEMS_FULL: (
        "Full KEMS tariff-aware control with cheap charging, home reserve, solar "
        "export, paced battery export and Power Down optimisation."
    ),
    SCENARIO_FULL_ISLAND: (
        "Grid unavailable for the whole replay period. EV charging is deliberately "
        "shed, then solar and battery serve the remaining house demand through the "
        "EPS limit with no import or export possible."
    ),
}

PERIOD_SPECS: tuple[tuple[str, int], ...] = (
    ("today", 1),
    ("yesterday", 1),
    ("7_days", 7),
    ("30_days", 30),
)

TIMELINE_STEP_MINUTES = 30
MAX_TIMELINE_POINTS = 49
PREPARED_SOC_MARGIN_PERCENT = 5.0
ISLAND_ENERGY_TOLERANCE_KWH = 0.001
REQUIRED_SOC_SEARCH_STEPS = 10


def _standing_charge(day_records: list[Snapshot]) -> float:
    """Return one daily electricity standing charge in pence."""
    for item in day_records:
        if item.electricity_standing_charge is not None:
            return max(float(item.electricity_standing_charge), 0.0)
    return 0.0


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _island_load_components(snapshot: Snapshot) -> tuple[float | None, float]:
    """Return EPS-backed demand and EV power intentionally shed in island mode."""
    recorded_load = _load_kw(snapshot)
    if recorded_load is None:
        return None, 0.0
    recorded_load = max(recorded_load, 0.0)
    ev_power = max(snapshot.ev_power_kw or 0.0, 0.0)
    ev_shed = min(ev_power, recorded_load)
    return max(recorded_load - ev_shed, 0.0), ev_shed


class ScenarioComparisonEngine:
    """Replay retained observations through several independent system designs."""

    def __init__(self) -> None:
        self._simulation = SimulationEngine()

    def compare(
        self,
        records: list[Snapshot],
        now: datetime,
        config: SimulationConfig,
        forecast_energy_until_offpeak_kwh: float | None = None,
        current_snapshot: Snapshot | None = None,
    ) -> ScenarioComparisonState:
        """Build today, yesterday, 7-day and 30-day scenario comparisons."""
        ordered = sorted(records, key=lambda item: item.timestamp)
        grouped: dict[date, list[Snapshot]] = {}
        # The longest public comparison is 30 days. Keep one earlier seed day
        # so battery scenarios can carry an independent end-SOC into that window
        # without replaying the integration's full retained-history depth each minute.
        replay_start = now.date() - timedelta(days=30)
        for record in ordered:
            record_day = record.timestamp.date()
            if record_day < replay_start or record_day > now.date():
                continue
            grouped.setdefault(record_day, []).append(record)

        if not grouped:
            empty = ScenarioPeriodComparison(
                key="today",
                label="Today",
                start_date=now.date(),
                end_date=now.date(),
                days_included=0,
                scenarios=(),
            )
            return ScenarioComparisonState(
                generated_at=now,
                periods={"today": empty},
                timeline=(),
            )

        dates = sorted(grouped)
        # Carry each hypothetical battery independently across retained days.
        basic_soc = min(max(config.battery_initial_percent, 0.0), 100.0)
        no_export_soc = basic_soc
        full_soc = basic_soc
        day_summaries: dict[date, dict[str, ScenarioSummary]] = {}

        for day in dates:
            day_records = grouped[day]
            is_current_day = day == now.date()
            day_now = now if is_current_day else day_records[-1].timestamp
            learned_forecast = (
                forecast_energy_until_offpeak_kwh if is_current_day else None
            )

            display_snapshot = (
                current_snapshot
                if is_current_day and current_snapshot is not None
                else day_records[-1]
            )
            simple, basic_soc = self._simple_day_scenarios(
                day_records,
                config,
                initial_basic_soc_percent=basic_soc,
                current_snapshot=display_snapshot,
            )
            no_export_state = self._simulation.simulate_today(
                day_records,
                day_now,
                replace(
                    config,
                    battery_initial_percent=no_export_soc,
                    export_tariff_status="awaiting",
                    battery_export_enabled=False,
                    strategy="self_use",
                ),
                learned_forecast,
                current_snapshot=display_snapshot,
            )
            full_state = self._simulation.simulate_today(
                day_records,
                day_now,
                replace(
                    config,
                    battery_initial_percent=full_soc,
                    export_tariff_status="active",
                    battery_export_enabled=True,
                    strategy="paced_export",
                ),
                learned_forecast,
                current_snapshot=display_snapshot,
            )
            no_export_summary = self._summary_from_simulation(
                SCENARIO_KEMS_NO_EXPORT,
                no_export_state,
                day_records,
            )
            full_summary = self._summary_from_simulation(
                SCENARIO_KEMS_FULL,
                full_state,
                day_records,
            )
            no_export_soc = no_export_summary.ending_soc_percent or no_export_soc
            full_soc = full_summary.ending_soc_percent or full_soc

            summaries = {
                **simple,
                SCENARIO_KEMS_NO_EXPORT: no_export_summary,
                SCENARIO_KEMS_FULL: full_summary,
            }
            baseline = summaries[SCENARIO_NO_SYSTEM]
            day_summaries[day] = {
                key: self._with_savings(summary, baseline)
                for key, summary in summaries.items()
            }

        periods = self._build_periods(day_summaries, now.date())
        periods = self._add_island_periods(
            periods,
            grouped,
            day_summaries,
            config,
            current_snapshot=current_snapshot,
        )
        current_day = grouped.get(now.date(), [])
        timeline: tuple[ScenarioTimelinePoint, ...] = ()
        if len(current_day) >= 2:
            previous_day = now.date() - timedelta(days=1)
            previous = day_summaries.get(previous_day, {})
            timeline = self._today_timeline(
                current_day,
                now,
                config,
                forecast_energy_until_offpeak_kwh,
                previous_basic_soc=(
                    previous.get(SCENARIO_SOLAR_BATTERY).ending_soc_percent
                    if previous.get(SCENARIO_SOLAR_BATTERY)
                    else config.battery_initial_percent
                ),
                previous_no_export_soc=(
                    previous.get(SCENARIO_KEMS_NO_EXPORT).ending_soc_percent
                    if previous.get(SCENARIO_KEMS_NO_EXPORT)
                    else config.battery_initial_percent
                ),
                previous_full_soc=(
                    previous.get(SCENARIO_KEMS_FULL).ending_soc_percent
                    if previous.get(SCENARIO_KEMS_FULL)
                    else config.battery_initial_percent
                ),
            )

        return ScenarioComparisonState(
            generated_at=now,
            periods=periods,
            timeline=timeline,
        )

    def _simple_day_scenarios(
        self,
        day_records: list[Snapshot],
        config: SimulationConfig,
        *,
        initial_basic_soc_percent: float,
        current_snapshot: Snapshot | None = None,
    ) -> tuple[dict[str, ScenarioSummary], float]:
        """Replay no-system, solar-only and conventional self-use together."""
        day_records = sorted(day_records, key=lambda item: item.timestamp)
        standing = _standing_charge(day_records)
        capacity = max(config.battery_capacity_kwh, 0.1)
        reserve_kwh = capacity * max(config.battery_reserve_percent, 0.0) / 100
        battery_kwh = min(
            max(capacity * initial_basic_soc_percent / 100, reserve_kwh),
            capacity,
        )

        names = (SCENARIO_NO_SYSTEM, SCENARIO_SOLAR_ONLY, SCENARIO_SOLAR_BATTERY)
        acc = {
            key: {
                "house": 0.0,
                "import": 0.0,
                "cheap_import": 0.0,
                "day_import": 0.0,
                "import_cost": 0.0,
                "cheap_import_cost": 0.0,
                "day_import_cost": 0.0,
                "export": 0.0,
                "export_income": 0.0,
                "solar": 0.0,
                "solar_to_home": 0.0,
                "solar_to_battery": 0.0,
                "solar_export": 0.0,
                "curtailed": 0.0,
                "battery_charge": 0.0,
                "battery_to_home": 0.0,
                "battery_export": 0.0,
                "covered": 0,
                "intervals": 0,
            }
            for key in names
        }
        export_rate = max(config.export_rate_pence, 0.0)

        for current, following in zip(day_records, day_records[1:], strict=False):
            hours = _interval_hours(current.timestamp, following.timestamp)
            if hours <= 0:
                continue
            for key in names:
                acc[key]["intervals"] += 1
            if current.stale_fields or following.stale_fields:
                continue
            load_kw = _load_kw(current)
            if load_kw is None or _load_kw(following) is None:
                continue
            rate = current.current_import_rate
            if rate is None:
                continue
            for key in names:
                acc[key]["covered"] += 1

            load_kwh = load_kw * hours
            inverter_kwh = max(config.inverter_limit_kw, 0.0) * hours
            export_limit_kwh = min(
                max(config.export_limit_kw, 0.0) * hours,
                inverter_kwh,
            )
            solar_kwh = self._simulation._simulated_solar_power(current, config) * hours
            cheap = current.cheap_period_confirmed

            # No system.
            self._add_import(acc[SCENARIO_NO_SYSTEM], load_kwh, rate, cheap)
            acc[SCENARIO_NO_SYSTEM]["house"] += load_kwh

            # Solar only: direct self-consumption first, paid export for surplus.
            solar_to_home = min(solar_kwh, load_kwh, inverter_kwh)
            solar_only_import = max(load_kwh - solar_to_home, 0.0)
            solar_surplus = max(solar_kwh - solar_to_home, 0.0)
            solar_export = min(solar_surplus, export_limit_kwh)
            solar_curtail = max(solar_surplus - solar_export, 0.0)
            solar_acc = acc[SCENARIO_SOLAR_ONLY]
            self._add_import(solar_acc, solar_only_import, rate, cheap)
            solar_acc["house"] += load_kwh
            solar_acc["solar"] += solar_kwh
            solar_acc["solar_to_home"] += solar_to_home
            solar_acc["solar_export"] += solar_export
            solar_acc["export"] += solar_export
            solar_acc["export_income"] += solar_export * export_rate
            solar_acc["curtailed"] += solar_curtail

            # Conventional solar + battery self-use.  It never grid-charges and
            # is deliberately tariff-unaware; that is the reference point KEMS
            # should beat through scheduling rather than extra hardware.
            basic = acc[SCENARIO_SOLAR_BATTERY]
            basic_solar_to_home = min(solar_kwh, load_kwh, inverter_kwh)
            net_load = max(load_kwh - basic_solar_to_home, 0.0)
            solar_surplus = max(solar_kwh - basic_solar_to_home, 0.0)
            available_ac = max(battery_kwh - reserve_kwh, 0.0) * max(
                config.discharge_efficiency,
                0.01,
            )
            battery_to_home = min(
                net_load,
                max(config.max_discharge_kw, 0.0) * hours,
                available_ac,
                max(inverter_kwh - basic_solar_to_home, 0.0),
            )
            battery_kwh -= battery_to_home / max(config.discharge_efficiency, 0.01)
            grid_import = max(net_load - battery_to_home, 0.0)

            charge_input = min(
                solar_surplus,
                max(config.max_charge_kw, 0.0) * hours,
                max(capacity - battery_kwh, 0.0) / max(config.charge_efficiency, 0.01),
            )
            stored_from_solar = charge_input * max(config.charge_efficiency, 0.01)
            battery_kwh += stored_from_solar
            remaining_solar = max(solar_surplus - charge_input, 0.0)
            inverter_used = basic_solar_to_home + battery_to_home
            basic_export = min(
                remaining_solar,
                export_limit_kwh,
                max(inverter_kwh - inverter_used, 0.0),
            )
            basic_curtail = max(remaining_solar - basic_export, 0.0)
            battery_kwh = min(max(battery_kwh, reserve_kwh), capacity)

            self._add_import(basic, grid_import, rate, cheap)
            basic["house"] += load_kwh
            basic["solar"] += solar_kwh
            basic["solar_to_home"] += basic_solar_to_home
            basic["solar_to_battery"] += stored_from_solar
            basic["solar_export"] += basic_export
            basic["export"] += basic_export
            basic["export_income"] += basic_export * export_rate
            basic["curtailed"] += basic_curtail
            basic["battery_charge"] += stored_from_solar
            basic["battery_to_home"] += battery_to_home

        # Build an instantaneous/recent power plan from the newest retained
        # snapshot using each scenario's current replay state. This is separate
        # from the cumulative kWh totals above and is intended for live displays.
        current_plans = self._simple_current_plans(
            current_snapshot or (day_records[-1] if day_records else None),
            config,
            battery_kwh=battery_kwh,
            reserve_kwh=reserve_kwh,
            capacity=capacity,
        )

        summaries: dict[str, ScenarioSummary] = {}
        for key in names:
            item = acc[key]
            intervals = int(item["intervals"])
            covered = int(item["covered"])
            coverage = covered / intervals if intervals else 0.0
            energy_net = item["import_cost"] - item["export_income"]
            summaries[key] = ScenarioSummary(
                key=key,
                label=SCENARIO_LABELS[key],
                description=SCENARIO_DESCRIPTIONS[key],
                ready=covered >= 3,
                samples=len(day_records),
                data_coverage=round(coverage * 100, 1),
                import_cost_pence=round(item["import_cost"], 2),
                cheap_import_cost_pence=round(item["cheap_import_cost"], 2),
                day_import_cost_pence=round(item["day_import_cost"], 2),
                export_income_pence=round(item["export_income"], 2),
                power_down_income_pence=0.0,
                standing_charge_pence=round(standing, 2),
                energy_net_cost_pence=round(energy_net, 2),
                total_cost_pence=round(energy_net + standing, 2),
                house_consumption_kwh=round(item["house"], 3),
                grid_import_kwh=round(item["import"], 3),
                cheap_grid_import_kwh=round(item["cheap_import"], 3),
                day_grid_import_kwh=round(item["day_import"], 3),
                grid_export_kwh=round(item["export"], 3),
                solar_generation_kwh=round(item["solar"], 3),
                solar_to_home_kwh=round(item["solar_to_home"], 3),
                solar_to_battery_kwh=round(item["solar_to_battery"], 3),
                solar_export_kwh=round(item["solar_export"], 3),
                solar_curtailed_kwh=round(item["curtailed"], 3),
                battery_charge_kwh=round(item["battery_charge"], 3),
                battery_grid_charge_kwh=0.0,
                battery_solar_charge_kwh=round(item["solar_to_battery"], 3),
                battery_to_home_kwh=round(item["battery_to_home"], 3),
                battery_export_kwh=round(item["battery_export"], 3),
                current_house_load_kw=current_plans[key]["house"],
                current_solar_power_kw=current_plans[key]["solar"],
                current_grid_import_kw=current_plans[key]["grid_import"],
                current_grid_export_kw=current_plans[key]["grid_export"],
                current_solar_to_home_kw=current_plans[key]["solar_to_home"],
                current_solar_to_battery_kw=current_plans[key]["solar_to_battery"],
                current_solar_export_kw=current_plans[key]["solar_export"],
                current_grid_to_battery_kw=current_plans[key]["grid_to_battery"],
                current_battery_to_home_kw=current_plans[key]["battery_to_home"],
                current_battery_export_kw=current_plans[key]["battery_export"],
                current_battery_soc_percent=(
                    round(100 * battery_kwh / capacity, 1)
                    if key == SCENARIO_SOLAR_BATTERY
                    else None
                ),
                ending_soc_percent=(
                    round(100 * battery_kwh / capacity, 1)
                    if key == SCENARIO_SOLAR_BATTERY
                    else None
                ),
            )

        return summaries, round(100 * battery_kwh / capacity, 1)

    def _simple_current_plans(
        self,
        snapshot: Snapshot | None,
        config: SimulationConfig,
        *,
        battery_kwh: float,
        reserve_kwh: float,
        capacity: float,
    ) -> dict[str, dict[str, float | None]]:
        """Return latest-snapshot power routing for the three simple scenarios."""
        empty = {
            "house": None,
            "solar": None,
            "grid_import": None,
            "grid_export": None,
            "solar_to_home": None,
            "solar_to_battery": None,
            "solar_export": None,
            "grid_to_battery": None,
            "battery_to_home": None,
            "battery_export": None,
        }
        if snapshot is None or snapshot.stale_fields:
            return {
                SCENARIO_NO_SYSTEM: dict(empty),
                SCENARIO_SOLAR_ONLY: dict(empty),
                SCENARIO_SOLAR_BATTERY: dict(empty),
            }

        load = _load_kw(snapshot)
        if load is None:
            return {
                SCENARIO_NO_SYSTEM: dict(empty),
                SCENARIO_SOLAR_ONLY: dict(empty),
                SCENARIO_SOLAR_BATTERY: dict(empty),
            }

        load = max(load, 0.0)
        solar = max(self._simulation._simulated_solar_power(snapshot, config), 0.0)
        inverter_limit = max(config.inverter_limit_kw, 0.0)
        export_limit = min(max(config.export_limit_kw, 0.0), inverter_limit)

        no_system = {
            "house": round(load, 3),
            "solar": 0.0,
            "grid_import": round(load, 3),
            "grid_export": 0.0,
            "solar_to_home": 0.0,
            "solar_to_battery": 0.0,
            "solar_export": 0.0,
            "grid_to_battery": 0.0,
            "battery_to_home": 0.0,
            "battery_export": 0.0,
        }

        solar_to_home = min(solar, load, inverter_limit)
        solar_only_import = max(load - solar_to_home, 0.0)
        solar_surplus = max(solar - solar_to_home, 0.0)
        solar_export = min(solar_surplus, export_limit)
        solar_only = {
            "house": round(load, 3),
            "solar": round(solar, 3),
            "grid_import": round(solar_only_import, 3),
            "grid_export": round(solar_export, 3),
            "solar_to_home": round(solar_to_home, 3),
            "solar_to_battery": 0.0,
            "solar_export": round(solar_export, 3),
            "grid_to_battery": 0.0,
            "battery_to_home": 0.0,
            "battery_export": 0.0,
        }

        basic_solar_to_home = min(solar, load, inverter_limit)
        net_load = max(load - basic_solar_to_home, 0.0)
        available_ac = max(battery_kwh - reserve_kwh, 0.0) * max(
            config.discharge_efficiency, 0.01
        )
        battery_to_home = min(
            net_load,
            max(config.max_discharge_kw, 0.0),
            available_ac,
            max(inverter_limit - basic_solar_to_home, 0.0),
        )
        grid_import = max(net_load - battery_to_home, 0.0)
        solar_surplus = max(solar - basic_solar_to_home, 0.0)
        solar_to_battery = min(
            solar_surplus,
            max(config.max_charge_kw, 0.0),
            max(capacity - battery_kwh, 0.0) / max(config.charge_efficiency, 0.01),
        )
        remaining_solar = max(solar_surplus - solar_to_battery, 0.0)
        inverter_used = basic_solar_to_home + battery_to_home
        basic_export = min(
            remaining_solar,
            export_limit,
            max(inverter_limit - inverter_used, 0.0),
        )
        solar_battery = {
            "house": round(load, 3),
            "solar": round(solar, 3),
            "grid_import": round(grid_import, 3),
            "grid_export": round(basic_export, 3),
            "solar_to_home": round(basic_solar_to_home, 3),
            "solar_to_battery": round(solar_to_battery, 3),
            "solar_export": round(basic_export, 3),
            "grid_to_battery": 0.0,
            "battery_to_home": round(battery_to_home, 3),
            "battery_export": 0.0,
        }

        return {
            SCENARIO_NO_SYSTEM: no_system,
            SCENARIO_SOLAR_ONLY: solar_only,
            SCENARIO_SOLAR_BATTERY: solar_battery,
        }

    def _add_island_periods(
        self,
        periods: dict[str, ScenarioPeriodComparison],
        grouped: dict[date, list[Snapshot]],
        daily: dict[date, dict[str, ScenarioSummary]],
        config: SimulationConfig,
        *,
        current_snapshot: Snapshot | None = None,
    ) -> dict[str, ScenarioPeriodComparison]:
        """Append a non-financial full-grid-outage replay to every period."""
        result: dict[str, ScenarioPeriodComparison] = {}
        for key, period in periods.items():
            records = sorted(
                (
                    record
                    for day, day_records in grouped.items()
                    if period.start_date <= day <= period.end_date
                    for record in day_records
                ),
                key=lambda item: item.timestamp,
            )
            previous_day = period.start_date - timedelta(days=1)
            previous_full = daily.get(previous_day, {}).get(SCENARIO_KEMS_FULL)
            initial_soc = (
                previous_full.ending_soc_percent
                if previous_full is not None
                and previous_full.ending_soc_percent is not None
                else config.battery_initial_percent
            )
            island = self._island_period_scenario(
                records,
                config,
                initial_soc_percent=initial_soc,
                current_snapshot=(current_snapshot if key == "today" else None),
            )
            result[key] = replace(
                period,
                scenarios=(*period.scenarios, island),
            )
        return result

    def _island_period_scenario(
        self,
        records: list[Snapshot],
        config: SimulationConfig,
        *,
        initial_soc_percent: float,
        current_snapshot: Snapshot | None = None,
    ) -> ScenarioSummary:
        """Add advance-preparation resilience to the sudden-outage replay."""
        sudden = self._island_replay(
            records,
            config,
            initial_soc_percent=initial_soc_percent,
            current_snapshot=current_snapshot,
        )
        if not sudden.ready:
            return replace(
                sudden,
                required_starting_soc_status="unavailable",
                prepared_outage_status="unavailable",
            )

        maximum = self._island_replay(
            records,
            config,
            initial_soc_percent=100.0,
        )
        if not maximum.ready:
            return replace(
                sudden,
                required_starting_soc_status="unavailable",
                prepared_outage_status="unavailable",
            )

        floor = sudden.emergency_floor_percent or 0.0
        required_soc: float | None
        required_status: str
        if maximum.energy_limited_unserved_kwh > ISLAND_ENERGY_TOLERANCE_KWH:
            required_soc = None
            required_status = "insufficient_energy_even_at_100"
            recommended_target = 100.0
        else:
            low = min(max(floor, 0.0), 100.0)
            low_result = self._island_replay(
                records,
                config,
                initial_soc_percent=low,
            )
            if low_result.energy_limited_unserved_kwh <= ISLAND_ENERGY_TOLERANCE_KWH:
                required_soc = low
            else:
                high = 100.0
                for _ in range(REQUIRED_SOC_SEARCH_STEPS):
                    midpoint = (low + high) / 2
                    midpoint_result = self._island_replay(
                        records,
                        config,
                        initial_soc_percent=midpoint,
                    )
                    if (
                        midpoint_result.energy_limited_unserved_kwh
                        <= ISLAND_ENERGY_TOLERANCE_KWH
                    ):
                        high = midpoint
                    else:
                        low = midpoint
                required_soc = high
            required_soc = round(required_soc, 1)
            recommended_target = min(
                required_soc + PREPARED_SOC_MARGIN_PERCENT,
                100.0,
            )
            required_status = (
                "ready"
                if maximum.eps_limited_unserved_kwh <= ISLAND_ENERGY_TOLERANCE_KWH
                else "eps_limit_only"
            )

        prepared_start = max(
            sudden.starting_soc_percent or floor,
            recommended_target,
        )
        prepared = self._island_replay(
            records,
            config,
            initial_soc_percent=prepared_start,
        )
        if not prepared.ready:
            prepared_status = "unavailable"
        elif prepared.outage_survived:
            prepared_status = "survived"
        elif (
            prepared.energy_limited_unserved_kwh <= ISLAND_ENERGY_TOLERANCE_KWH
            and prepared.eps_limited_unserved_kwh > ISLAND_ENERGY_TOLERANCE_KWH
        ):
            prepared_status = "eps_limited"
        else:
            prepared_status = "shortfall"

        return replace(
            sudden,
            required_starting_soc_percent=required_soc,
            required_starting_soc_status=required_status,
            recommended_prepared_soc_percent=round(recommended_target, 1),
            prepared_starting_soc_percent=round(prepared_start, 1),
            prepared_soc_margin_percent=PREPARED_SOC_MARGIN_PERCENT,
            prepared_outage_survived=prepared.outage_survived,
            prepared_outage_status=prepared_status,
            prepared_load_served_kwh=prepared.load_served_kwh,
            prepared_unserved_load_kwh=prepared.unserved_load_kwh,
            prepared_load_served_percent=prepared.load_served_percent,
            prepared_ending_soc_percent=prepared.ending_soc_percent,
            prepared_minimum_soc_percent=prepared.minimum_soc_percent,
            prepared_eps_limited_unserved_kwh=(prepared.eps_limited_unserved_kwh),
            prepared_energy_limited_unserved_kwh=(prepared.energy_limited_unserved_kwh),
            prepared_first_shortfall_at=prepared.first_shortfall_at,
        )

    def _island_replay(
        self,
        records: list[Snapshot],
        config: SimulationConfig,
        *,
        initial_soc_percent: float,
        current_snapshot: Snapshot | None = None,
    ) -> ScenarioSummary:
        """Replay a complete grid outage using only proposal/live solar and battery."""
        ordered = sorted(records, key=lambda item: item.timestamp)
        capacity = max(config.battery_capacity_kwh, 0.1)
        normal_reserve_percent = min(
            max(config.battery_reserve_percent, 0.0),
            100.0,
        )
        island_reserve_percent = min(
            max(config.island_reserve_percent, 0.0),
            100.0,
        )
        emergency_floor_percent = min(
            normal_reserve_percent,
            island_reserve_percent,
        )
        conservation_threshold_percent = max(
            island_reserve_percent,
            emergency_floor_percent,
        )
        floor_kwh = capacity * emergency_floor_percent / 100
        starting_soc_percent = min(
            max(initial_soc_percent, emergency_floor_percent),
            100.0,
        )
        battery_kwh = min(
            max(capacity * starting_soc_percent / 100, floor_kwh),
            capacity,
        )
        min_battery_kwh = battery_kwh

        house = 0.0
        island_demand = 0.0
        ev_energy_shed = 0.0
        served = 0.0
        unserved = 0.0
        solar = 0.0
        solar_to_home = 0.0
        solar_to_battery = 0.0
        curtailed = 0.0
        battery_charge = 0.0
        battery_to_home = 0.0
        eps_limited = 0.0
        post_solar_demand = 0.0
        covered = 0
        intervals = 0
        outage_hours = 0.0
        first_shortfall_at: str | None = None

        for current, following in zip(ordered, ordered[1:], strict=False):
            hours = _interval_hours(current.timestamp, following.timestamp)
            if hours <= 0:
                continue
            intervals += 1
            if current.stale_fields or following.stale_fields:
                continue
            recorded_load_kw = _load_kw(current)
            load_kw, ev_shed_kw = _island_load_components(current)
            following_load_kw, _ = _island_load_components(following)
            if recorded_load_kw is None or load_kw is None or following_load_kw is None:
                continue
            covered += 1
            outage_hours += hours

            recorded_load_kwh = max(recorded_load_kw, 0.0) * hours
            load_kwh = load_kw * hours
            ev_shed_kwh = ev_shed_kw * hours
            solar_kwh = self._simulation._simulated_solar_power(current, config) * hours
            eps_limit_kwh = max(config.eps_output_limit_kw, 0.0) * hours
            discharge_limit_kwh = max(config.max_discharge_kw, 0.0) * hours
            charge_limit_kwh = max(config.max_charge_kw, 0.0) * hours

            direct_solar = min(solar_kwh, load_kwh, eps_limit_kwh)
            remaining_load = max(load_kwh - direct_solar, 0.0)
            available_battery_ac = max(battery_kwh - floor_kwh, 0.0) * max(
                config.discharge_efficiency,
                0.01,
            )
            available_eps = max(eps_limit_kwh - direct_solar, 0.0)
            discharge = min(
                remaining_load,
                discharge_limit_kwh,
                available_battery_ac,
                available_eps,
            )
            battery_kwh -= discharge / max(config.discharge_efficiency, 0.01)

            interval_served = direct_solar + discharge
            interval_unserved = max(load_kwh - interval_served, 0.0)
            if interval_unserved > 1e-6 and first_shortfall_at is None:
                first_shortfall_at = current.timestamp.isoformat()

            surplus_solar = max(solar_kwh - direct_solar, 0.0)
            charge_input = min(
                surplus_solar,
                charge_limit_kwh,
                max(capacity - battery_kwh, 0.0) / max(config.charge_efficiency, 0.01),
            )
            stored = charge_input * max(config.charge_efficiency, 0.01)
            battery_kwh += stored
            interval_curtailed = max(surplus_solar - charge_input, 0.0)

            battery_kwh = min(max(battery_kwh, floor_kwh), capacity)
            min_battery_kwh = min(min_battery_kwh, battery_kwh)
            house += recorded_load_kwh
            island_demand += load_kwh
            ev_energy_shed += ev_shed_kwh
            served += interval_served
            unserved += interval_unserved
            solar += solar_kwh
            solar_to_home += direct_solar
            solar_to_battery += stored
            curtailed += interval_curtailed
            battery_charge += stored
            battery_to_home += discharge
            eps_limited += min(
                interval_unserved,
                max(load_kwh - eps_limit_kwh, 0.0),
            )
            post_solar_demand += max(load_kwh - min(solar_kwh, load_kwh), 0.0)

        current_house: float | None = None
        current_ev_shed: float | None = None
        current_solar: float | None = None
        current_solar_to_home: float | None = None
        current_solar_to_battery: float | None = None
        current_battery_to_home: float | None = None
        latest = current_snapshot or (ordered[-1] if ordered else None)
        if latest is not None:
            latest_load, latest_ev_shed = _island_load_components(latest)
            if not latest.stale_fields and latest_load is not None:
                current_house = latest_load
                current_ev_shed = latest_ev_shed
                current_solar = max(
                    self._simulation._simulated_solar_power(latest, config),
                    0.0,
                )
                eps_limit = max(config.eps_output_limit_kw, 0.0)
                current_solar_to_home = min(
                    current_solar,
                    current_house,
                    eps_limit,
                )
                remaining_load = max(current_house - current_solar_to_home, 0.0)
                available_battery_ac = max(battery_kwh - floor_kwh, 0.0) * max(
                    config.discharge_efficiency,
                    0.01,
                )
                current_battery_to_home = min(
                    remaining_load,
                    max(config.max_discharge_kw, 0.0),
                    available_battery_ac,
                    max(eps_limit - current_solar_to_home, 0.0),
                )
                solar_surplus = max(current_solar - current_solar_to_home, 0.0)
                current_solar_to_battery = min(
                    solar_surplus,
                    max(config.max_charge_kw, 0.0),
                    max(capacity - battery_kwh, 0.0)
                    / max(config.charge_efficiency, 0.01),
                )

        coverage = covered / intervals if intervals else 0.0
        load_served_percent = (
            100.0 if island_demand <= 1e-9 else 100.0 * served / island_demand
        )
        energy_limited = max(unserved - eps_limited, 0.0)
        outage_survived = covered >= 3 and unserved <= 0.001
        ending_soc = 100.0 * battery_kwh / capacity
        minimum_soc = 100.0 * min_battery_kwh / capacity
        battery_above_floor = max(battery_kwh - floor_kwh, 0.0)
        average_post_solar_kw = (
            post_solar_demand / outage_hours if outage_hours > 1e-9 else 0.0
        )
        remaining_runtime = None
        if average_post_solar_kw > 0.05:
            remaining_runtime = (
                battery_above_floor
                * max(config.discharge_efficiency, 0.01)
                / average_post_solar_kw
            )

        return ScenarioSummary(
            key=SCENARIO_FULL_ISLAND,
            label=SCENARIO_LABELS[SCENARIO_FULL_ISLAND],
            description=SCENARIO_DESCRIPTIONS[SCENARIO_FULL_ISLAND],
            ready=covered >= 3,
            samples=len(ordered),
            data_coverage=round(coverage * 100, 1),
            import_cost_pence=0.0,
            cheap_import_cost_pence=0.0,
            day_import_cost_pence=0.0,
            export_income_pence=0.0,
            power_down_income_pence=0.0,
            standing_charge_pence=0.0,
            energy_net_cost_pence=0.0,
            total_cost_pence=0.0,
            house_consumption_kwh=round(house, 3),
            grid_import_kwh=0.0,
            cheap_grid_import_kwh=0.0,
            day_grid_import_kwh=0.0,
            grid_export_kwh=0.0,
            solar_generation_kwh=round(solar, 3),
            solar_to_home_kwh=round(solar_to_home, 3),
            solar_to_battery_kwh=round(solar_to_battery, 3),
            solar_export_kwh=0.0,
            solar_curtailed_kwh=round(curtailed, 3),
            battery_charge_kwh=round(battery_charge, 3),
            battery_grid_charge_kwh=0.0,
            battery_solar_charge_kwh=round(solar_to_battery, 3),
            battery_to_home_kwh=round(battery_to_home, 3),
            battery_export_kwh=0.0,
            ending_soc_percent=round(ending_soc, 1),
            financially_comparable=False,
            grid_available=False,
            outage_survived=outage_survived if covered >= 3 else None,
            outage_status=(
                "survived"
                if outage_survived
                else "shortfall" if covered >= 3 else "unavailable"
            ),
            outage_duration_hours=round(outage_hours, 2),
            load_served_kwh=round(served, 3),
            unserved_load_kwh=round(unserved, 3),
            load_served_percent=round(load_served_percent, 1),
            starting_soc_percent=round(starting_soc_percent, 1),
            minimum_soc_percent=round(minimum_soc, 1),
            conservation_threshold_percent=round(conservation_threshold_percent, 1),
            emergency_floor_percent=round(emergency_floor_percent, 1),
            eps_limited_unserved_kwh=round(eps_limited, 3),
            energy_limited_unserved_kwh=round(energy_limited, 3),
            first_shortfall_at=first_shortfall_at,
            estimated_remaining_runtime_hours=(
                round(remaining_runtime, 2) if remaining_runtime is not None else None
            ),
            battery_energy_above_floor_kwh=round(battery_above_floor, 3),
            island_demand_kwh=round(island_demand, 3),
            ev_energy_intentionally_shed_kwh=round(ev_energy_shed, 3),
            ev_charging_allowed_in_island=False,
            current_house_load_kw=_round(current_house),
            current_ev_shed_kw=_round(current_ev_shed),
            current_solar_power_kw=_round(current_solar),
            current_grid_import_kw=0.0 if current_house is not None else None,
            current_grid_export_kw=0.0 if current_house is not None else None,
            current_solar_to_home_kw=_round(current_solar_to_home),
            current_solar_to_battery_kw=_round(current_solar_to_battery),
            current_solar_export_kw=0.0 if current_house is not None else None,
            current_grid_to_battery_kw=0.0 if current_house is not None else None,
            current_battery_to_home_kw=_round(current_battery_to_home),
            current_battery_export_kw=0.0 if current_house is not None else None,
            current_battery_soc_percent=round(ending_soc, 1),
        )

    @staticmethod
    def _add_import(
        acc: dict[str, float | int],
        energy: float,
        rate: float,
        cheap: bool,
    ) -> None:
        energy = max(energy, 0.0)
        cost = energy * rate
        acc["import"] = float(acc["import"]) + energy
        acc["import_cost"] = float(acc["import_cost"]) + cost
        if cheap:
            acc["cheap_import"] = float(acc["cheap_import"]) + energy
            acc["cheap_import_cost"] = float(acc["cheap_import_cost"]) + cost
        else:
            acc["day_import"] = float(acc["day_import"]) + energy
            acc["day_import_cost"] = float(acc["day_import_cost"]) + cost

    def _summary_from_simulation(
        self,
        key: str,
        state: SimulationState,
        day_records: list[Snapshot],
    ) -> ScenarioSummary:
        """Convert the main KEMS simulation result to a comparison summary."""
        standing = _standing_charge(day_records)
        energy_net = state.simulated_cost_pence or 0.0

        # SimulationState already carries the current KEMS routing plan. Preserve
        # it on the scenario summary so Home Assistant clients can display
        # instantaneous flows instead of trying to differentiate cumulative kWh.
        current_house = _round(state.current_simulated_house_load_kw)
        current_solar = _round(state.current_simulated_solar_power_kw)
        current_grid_import = _round(state.current_simulated_grid_import_kw)
        current_grid_export = _round(state.current_simulated_grid_export_kw)
        current_grid_to_battery = _round(
            state.current_simulated_battery_charge_power_kw
        )
        current_solar_to_battery = _round(
            state.current_simulated_solar_to_battery_power_kw
        )
        current_battery_to_home = _round(
            state.current_simulated_battery_to_home_power_kw
        )
        current_battery_export = _round(state.current_simulated_battery_export_power_kw)

        # Split grid export into its solar and battery components. Then solve
        # the home balance for solar-to-home after removing any grid-to-battery
        # charging from total site import.
        grid_export_value = current_grid_export or 0.0
        battery_export_value = current_battery_export or 0.0
        current_solar_export = round(
            max(grid_export_value - battery_export_value, 0.0), 3
        )
        house_value = current_house or 0.0
        battery_home_value = current_battery_to_home or 0.0
        grid_import_value = current_grid_import or 0.0
        grid_charge_value = current_grid_to_battery or 0.0
        house_grid_value = max(grid_import_value - grid_charge_value, 0.0)
        current_solar_to_home = round(
            max(house_value - battery_home_value - house_grid_value, 0.0), 3
        )

        return ScenarioSummary(
            key=key,
            label=SCENARIO_LABELS[key],
            description=SCENARIO_DESCRIPTIONS[key],
            ready=state.ready,
            samples=state.samples,
            data_coverage=round(state.data_coverage, 1),
            import_cost_pence=_round(state.simulated_import_cost_pence, 2) or 0.0,
            cheap_import_cost_pence=(
                _round(state.simulated_cheap_import_cost_pence, 2) or 0.0
            ),
            day_import_cost_pence=(
                _round(state.simulated_day_import_cost_pence, 2) or 0.0
            ),
            export_income_pence=_round(state.simulated_export_income_pence, 2) or 0.0,
            power_down_income_pence=(
                _round(state.simulated_saving_session_bonus_pence, 2) or 0.0
            ),
            standing_charge_pence=round(standing, 2),
            energy_net_cost_pence=round(energy_net, 2),
            total_cost_pence=round(energy_net + standing, 2),
            house_consumption_kwh=_round(state.actual_house_consumption_kwh) or 0.0,
            grid_import_kwh=_round(state.simulated_grid_import_kwh) or 0.0,
            cheap_grid_import_kwh=_round(state.simulated_cheap_import_kwh) or 0.0,
            day_grid_import_kwh=_round(state.simulated_day_import_kwh) or 0.0,
            grid_export_kwh=_round(state.simulated_grid_export_kwh) or 0.0,
            solar_generation_kwh=_round(state.simulated_solar_generation_kwh) or 0.0,
            solar_to_home_kwh=_round(state.simulated_solar_to_home_kwh) or 0.0,
            solar_to_battery_kwh=_round(state.simulated_solar_to_battery_kwh) or 0.0,
            solar_export_kwh=_round(state.simulated_solar_export_kwh) or 0.0,
            solar_curtailed_kwh=_round(state.simulated_solar_curtailed_kwh) or 0.0,
            battery_charge_kwh=_round(state.simulated_battery_charge_kwh) or 0.0,
            battery_grid_charge_kwh=_round(state.simulated_grid_to_battery_kwh) or 0.0,
            battery_solar_charge_kwh=(
                _round(state.simulated_solar_to_battery_kwh) or 0.0
            ),
            battery_to_home_kwh=_round(state.simulated_battery_to_home_kwh) or 0.0,
            battery_export_kwh=_round(state.simulated_battery_export_kwh) or 0.0,
            ending_soc_percent=_round(state.simulated_battery_soc, 1),
            current_house_load_kw=current_house,
            current_solar_power_kw=current_solar,
            current_grid_import_kw=current_grid_import,
            current_grid_export_kw=current_grid_export,
            current_solar_to_home_kw=current_solar_to_home,
            current_solar_to_battery_kw=current_solar_to_battery,
            current_solar_export_kw=current_solar_export,
            current_grid_to_battery_kw=current_grid_to_battery,
            current_battery_to_home_kw=current_battery_to_home,
            current_battery_export_kw=current_battery_export,
            current_battery_soc_percent=_round(state.simulated_battery_soc, 1),
        )

    @staticmethod
    def _with_savings(
        summary: ScenarioSummary,
        baseline: ScenarioSummary,
    ) -> ScenarioSummary:
        """Add an exact, auditable saving decomposition versus no-system."""
        day_reduction = baseline.day_import_cost_pence - summary.day_import_cost_pence
        cheap_change = (
            baseline.cheap_import_cost_pence - summary.cheap_import_cost_pence
        )
        if not summary.financially_comparable:
            return replace(
                summary,
                saving_vs_no_system_pence=0.0,
                day_rate_import_reduction_pence=0.0,
                cheap_rate_import_change_pence=0.0,
            )
        saving = baseline.total_cost_pence - summary.total_cost_pence
        return replace(
            summary,
            saving_vs_no_system_pence=round(saving, 2),
            day_rate_import_reduction_pence=round(day_reduction, 2),
            cheap_rate_import_change_pence=round(cheap_change, 2),
        )

    def _build_periods(
        self,
        daily: dict[date, dict[str, ScenarioSummary]],
        today: date,
    ) -> dict[str, ScenarioPeriodComparison]:
        result: dict[str, ScenarioPeriodComparison] = {}
        for key, days in PERIOD_SPECS:
            if key == "today":
                start = end = today
                label = "Today"
            elif key == "yesterday":
                start = end = today - timedelta(days=1)
                label = "Yesterday"
            else:
                end = today
                start = today - timedelta(days=days - 1)
                label = "7 days" if key == "7_days" else "30 days"
            included_dates = sorted(day for day in daily if start <= day <= end)
            scenario_summaries: list[ScenarioSummary] = []
            for scenario_key in FINANCIAL_SCENARIO_KEYS:
                parts = [daily[day][scenario_key] for day in included_dates]
                if parts:
                    scenario_summaries.append(
                        self._aggregate_summaries(scenario_key, parts)
                    )
            result[key] = ScenarioPeriodComparison(
                key=key,
                label=label,
                start_date=start,
                end_date=end,
                days_included=len(included_dates),
                scenarios=tuple(scenario_summaries),
            )
        return result

    @staticmethod
    def _aggregate_summaries(key: str, parts: list[ScenarioSummary]) -> ScenarioSummary:
        """Sum compatible daily scenario results into one reporting period."""
        if not parts:
            return ScenarioSummary(key=key, label=SCENARIO_LABELS[key])
        numeric_fields = (
            "import_cost_pence",
            "cheap_import_cost_pence",
            "day_import_cost_pence",
            "export_income_pence",
            "power_down_income_pence",
            "standing_charge_pence",
            "energy_net_cost_pence",
            "total_cost_pence",
            "saving_vs_no_system_pence",
            "day_rate_import_reduction_pence",
            "cheap_rate_import_change_pence",
            "house_consumption_kwh",
            "grid_import_kwh",
            "cheap_grid_import_kwh",
            "day_grid_import_kwh",
            "grid_export_kwh",
            "solar_generation_kwh",
            "solar_to_home_kwh",
            "solar_to_battery_kwh",
            "solar_export_kwh",
            "solar_curtailed_kwh",
            "battery_charge_kwh",
            "battery_grid_charge_kwh",
            "battery_solar_charge_kwh",
            "battery_to_home_kwh",
            "battery_export_kwh",
        )
        values = {
            field: round(sum(float(getattr(item, field) or 0.0) for item in parts), 3)
            for field in numeric_fields
        }
        samples = sum(item.samples for item in parts)
        weighted_coverage = sum(
            item.data_coverage * max(item.samples, 1) for item in parts
        ) / sum(max(item.samples, 1) for item in parts)
        latest = parts[-1]
        return ScenarioSummary(
            key=key,
            label=latest.label,
            description=latest.description,
            ready=all(item.ready for item in parts),
            samples=samples,
            data_coverage=round(weighted_coverage, 1),
            ending_soc_percent=latest.ending_soc_percent,
            current_house_load_kw=latest.current_house_load_kw,
            current_solar_power_kw=latest.current_solar_power_kw,
            current_grid_import_kw=latest.current_grid_import_kw,
            current_grid_export_kw=latest.current_grid_export_kw,
            current_solar_to_home_kw=latest.current_solar_to_home_kw,
            current_solar_to_battery_kw=latest.current_solar_to_battery_kw,
            current_solar_export_kw=latest.current_solar_export_kw,
            current_grid_to_battery_kw=latest.current_grid_to_battery_kw,
            current_battery_to_home_kw=latest.current_battery_to_home_kw,
            current_battery_export_kw=latest.current_battery_export_kw,
            current_battery_soc_percent=latest.current_battery_soc_percent,
            **values,
        )

    def _today_timeline(
        self,
        day_records: list[Snapshot],
        now: datetime,
        config: SimulationConfig,
        forecast: float | None,
        *,
        previous_basic_soc: float | None,
        previous_no_export_soc: float | None,
        previous_full_soc: float | None,
    ) -> tuple[ScenarioTimelinePoint, ...]:
        """Return a replay timeline sampled every 30 minutes plus the latest point."""
        records = sorted(day_records, key=lambda item: item.timestamp)
        checkpoints: list[int] = [0]
        last_time = records[0].timestamp
        for index, record in enumerate(records[1:], 1):
            if record.timestamp - last_time >= timedelta(minutes=TIMELINE_STEP_MINUTES):
                checkpoints.append(index)
                last_time = record.timestamp
        if checkpoints[-1] != len(records) - 1:
            checkpoints.append(len(records) - 1)
        if len(checkpoints) > MAX_TIMELINE_POINTS:
            step = max((len(checkpoints) - 1) / (MAX_TIMELINE_POINTS - 1), 1)
            reduced = sorted({round(i * step) for i in range(MAX_TIMELINE_POINTS - 1)})
            checkpoints = [
                checkpoints[min(index, len(checkpoints) - 1)] for index in reduced
            ]
            if checkpoints[-1] != len(records) - 1:
                checkpoints.append(len(records) - 1)

        result: list[ScenarioTimelinePoint] = []
        standing = _standing_charge(records)
        for index in checkpoints:
            prefix = records[: index + 1]
            timestamp = min(prefix[-1].timestamp, now)
            if len(prefix) < 2:
                costs = {key: standing for key in FINANCIAL_SCENARIO_KEYS}
                island = ScenarioSummary(
                    key=SCENARIO_FULL_ISLAND,
                    label=SCENARIO_LABELS[SCENARIO_FULL_ISLAND],
                    financially_comparable=False,
                    grid_available=False,
                    outage_status="unavailable",
                    load_served_percent=100.0,
                    starting_soc_percent=(
                        previous_full_soc
                        if previous_full_soc is not None
                        else config.battery_initial_percent
                    ),
                    ending_soc_percent=(
                        previous_full_soc
                        if previous_full_soc is not None
                        else config.battery_initial_percent
                    ),
                )
            else:
                simple, _ = self._simple_day_scenarios(
                    prefix,
                    config,
                    initial_basic_soc_percent=(
                        previous_basic_soc
                        if previous_basic_soc is not None
                        else config.battery_initial_percent
                    ),
                )
                no_export = self._summary_from_simulation(
                    SCENARIO_KEMS_NO_EXPORT,
                    self._simulation.simulate_today(
                        prefix,
                        timestamp,
                        replace(
                            config,
                            battery_initial_percent=(
                                previous_no_export_soc
                                if previous_no_export_soc is not None
                                else config.battery_initial_percent
                            ),
                            export_tariff_status="awaiting",
                            battery_export_enabled=False,
                            strategy="self_use",
                        ),
                        forecast,
                        current_snapshot=prefix[-1],
                    ),
                    prefix,
                )
                full = self._summary_from_simulation(
                    SCENARIO_KEMS_FULL,
                    self._simulation.simulate_today(
                        prefix,
                        timestamp,
                        replace(
                            config,
                            battery_initial_percent=(
                                previous_full_soc
                                if previous_full_soc is not None
                                else config.battery_initial_percent
                            ),
                            export_tariff_status="active",
                            battery_export_enabled=True,
                            strategy="paced_export",
                        ),
                        forecast,
                        current_snapshot=prefix[-1],
                    ),
                    prefix,
                )
                island = self._island_replay(
                    prefix,
                    config,
                    initial_soc_percent=(
                        previous_full_soc
                        if previous_full_soc is not None
                        else config.battery_initial_percent
                    ),
                )
                costs = {
                    SCENARIO_NO_SYSTEM: simple[SCENARIO_NO_SYSTEM].total_cost_pence,
                    SCENARIO_SOLAR_ONLY: simple[SCENARIO_SOLAR_ONLY].total_cost_pence,
                    SCENARIO_SOLAR_BATTERY: (
                        simple[SCENARIO_SOLAR_BATTERY].total_cost_pence
                    ),
                    SCENARIO_KEMS_NO_EXPORT: no_export.total_cost_pence,
                    SCENARIO_KEMS_FULL: full.total_cost_pence,
                }
            result.append(
                ScenarioTimelinePoint(
                    timestamp=timestamp,
                    no_system_cost_pence=round(costs[SCENARIO_NO_SYSTEM], 2),
                    solar_only_cost_pence=round(costs[SCENARIO_SOLAR_ONLY], 2),
                    solar_battery_cost_pence=round(costs[SCENARIO_SOLAR_BATTERY], 2),
                    kems_no_export_cost_pence=round(costs[SCENARIO_KEMS_NO_EXPORT], 2),
                    kems_full_cost_pence=round(costs[SCENARIO_KEMS_FULL], 2),
                    island_load_served_percent=island.load_served_percent,
                    island_unserved_load_kwh=island.unserved_load_kwh,
                    island_soc_percent=island.ending_soc_percent,
                    island_status=island.outage_status,
                )
            )
        return tuple(result)
