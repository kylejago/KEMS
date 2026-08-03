"""Read-only proposal solar, battery, import, and export simulation."""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import fmean

from .models import SimulationConfig, SimulationState, Snapshot
from .system_profile import FOXHOLE_PROPOSAL_PROFILE

MAX_INTERVAL_HOURS = 0.5
MAX_CHEAP_PERIOD_LOOKAHEAD_HOURS = 24.0
RECENT_LOAD_WINDOW_HOURS = 1.0
HOME_RESERVE_SAFETY_FACTOR = 1.10


def _interval_hours(current: datetime, following: datetime) -> float:
    """Return a safe interval duration in hours."""
    seconds = max((following - current).total_seconds(), 0.0)
    return min(seconds / 3600, MAX_INTERVAL_HOURS)


def _load_kw(snapshot: Snapshot) -> float | None:
    """Return the best available house-load observation."""
    if snapshot.house_load_kw is not None:
        return max(snapshot.house_load_kw, 0.0)
    if snapshot.grid_import_kw is not None:
        return max(snapshot.grid_import_kw, 0.0)
    return None


class SimulationEngine:
    """Compare observed operation with the proposed KEMS strategy."""

    def simulate_today(
        self,
        records: list[Snapshot],
        now: datetime,
        config: SimulationConfig,
        forecast_energy_until_offpeak_kwh: float | None = None,
        current_snapshot: Snapshot | None = None,
    ) -> SimulationState:
        """Simulate the current local day from retained observations."""
        today = sorted(
            (record for record in records if record.timestamp.date() == now.date()),
            key=lambda record: record.timestamp,
        )
        live_snapshot = current_snapshot or (today[-1] if today else None)
        if len(today) < 2:
            return self._empty_current_state(live_snapshot, config)

        capacity = max(config.battery_capacity_kwh, 0.1)
        reserve_kwh = capacity * config.battery_reserve_percent / 100
        initial_soc = today[0].battery_soc
        if initial_soc is None:
            battery_kwh = self._battery_energy_at_day_start(
                records,
                today[0],
                capacity,
                reserve_kwh,
                config,
            )
        else:
            battery_kwh = capacity * min(max(initial_soc, 0.0), 100.0) / 100

        actual_import_cost = 0.0
        actual_export_income = 0.0
        simulated_import_cost = 0.0
        simulated_export_income = 0.0
        actual_house = 0.0
        actual_ev = 0.0
        actual_solar = 0.0
        actual_battery_charge = 0.0
        actual_battery_discharge = 0.0
        actual_import = 0.0
        actual_export = 0.0
        baseline_import_cost = 0.0
        simulated_import = 0.0
        simulated_export = 0.0
        simulated_solar = 0.0
        simulated_curtailment = 0.0
        battery_charge = 0.0
        battery_to_home = 0.0
        battery_export = 0.0
        avoided_day_import = 0.0
        covered = 0
        intervals = 0
        effective_export_rate = max(config.export_rate_pence, 0.0)

        for index, (current, following) in enumerate(
            zip(today, today[1:], strict=False)
        ):
            hours = _interval_hours(current.timestamp, following.timestamp)
            if hours <= 0:
                continue
            intervals += 1

            rate = current.current_import_rate
            load_kw = _load_kw(current)
            if rate is None or load_kw is None:
                continue
            covered += 1

            # KEMS deliberately models Kyle's fixed 12p export tariff (or the
            # configured replacement value). Flux/time-of-use export rates are
            # not pulled into the proposal simulation.
            export_rate = effective_export_rate
            solar_kw = self._simulated_solar_power(current, config)
            actual_import_kw = (
                max(current.grid_import_kw, 0.0)
                if current.grid_import_kw is not None
                else max(load_kw - max(current.solar_power_kw or 0.0, 0.0), 0.0)
            )
            actual_export_kw = max(current.grid_export_kw or 0.0, 0.0)

            actual_house_kwh = load_kw * hours
            actual_import_kwh = actual_import_kw * hours
            actual_export_kwh = actual_export_kw * hours
            actual_house += actual_house_kwh
            actual_ev += max(current.ev_power_kw or 0.0, 0.0) * hours
            actual_solar += max(current.solar_power_kw or 0.0, 0.0) * hours
            battery_power_kw = current.battery_power_kw or 0.0
            if config.battery_power_positive_is_discharge:
                actual_battery_discharge += max(battery_power_kw, 0.0) * hours
                actual_battery_charge += max(-battery_power_kw, 0.0) * hours
            else:
                actual_battery_charge += max(battery_power_kw, 0.0) * hours
                actual_battery_discharge += max(-battery_power_kw, 0.0) * hours
            actual_import += actual_import_kwh
            actual_export += actual_export_kwh
            baseline_import_cost += actual_house_kwh * rate
            actual_import_cost += actual_import_kwh * rate
            actual_export_income += actual_export_kwh * export_rate

            solar_energy = solar_kw * hours
            simulated_solar += solar_energy
            interval_import = 0.0
            interval_export = 0.0
            interval_curtailment = 0.0
            inverter_capacity = max(config.inverter_limit_kw, 0.0) * hours
            export_capacity = min(
                max(config.export_limit_kw, 0.0) * hours,
                inverter_capacity,
            )

            if current.cheap_period_confirmed:
                house_grid_kwh = actual_house_kwh
                charge_input_kwh = min(
                    min(config.max_charge_kw, config.inverter_limit_kw) * hours,
                    max(capacity - battery_kwh, 0.0)
                    / max(config.charge_efficiency, 0.01),
                )
                battery_kwh += charge_input_kwh * config.charge_efficiency
                battery_charge += charge_input_kwh * config.charge_efficiency
                interval_import = house_grid_kwh + charge_input_kwh
                interval_export, interval_curtailment = self._limit_export(
                    solar_energy,
                    export_capacity,
                )
            else:
                if config.strategy == "self_use":
                    solar_to_home = min(
                        solar_energy,
                        actual_house_kwh,
                        inverter_capacity,
                    )
                    net_load_kwh = actual_house_kwh - solar_to_home
                    solar_export_request = max(solar_energy - solar_to_home, 0.0)
                    inverter_used = solar_to_home
                else:
                    # Kyle's preferred policy: power the home from battery and
                    # export available solar, subject to the KH7 AC limit.
                    net_load_kwh = actual_house_kwh
                    solar_export_request = solar_energy
                    inverter_used = 0.0

                available_to_load = max(battery_kwh - reserve_kwh, 0.0)
                max_deliverable = min(
                    config.max_discharge_kw * hours,
                    max(inverter_capacity - inverter_used, 0.0),
                )
                delivered = min(
                    net_load_kwh,
                    max_deliverable,
                    available_to_load * config.discharge_efficiency,
                )
                battery_kwh -= delivered / max(config.discharge_efficiency, 0.01)
                battery_to_home += delivered
                avoided_day_import += delivered
                interval_import = max(net_load_kwh - delivered, 0.0)
                inverter_used += delivered

                solar_export_capacity = min(
                    export_capacity,
                    max(inverter_capacity - inverter_used, 0.0),
                )
                solar_export, solar_curtailed = self._limit_export(
                    solar_export_request,
                    solar_export_capacity,
                )
                interval_export = solar_export
                interval_curtailment += solar_curtailed
                inverter_used += solar_export

                if config.battery_export_enabled:
                    forecast_required = self._remaining_load_requirement(
                        today,
                        index + 1,
                        config,
                        forecast_energy_until_offpeak_kwh,
                    )
                    required_stored = forecast_required / max(
                        config.discharge_efficiency,
                        0.01,
                    )
                    surplus_stored = max(
                        battery_kwh - reserve_kwh - required_stored,
                        0.0,
                    )
                    remaining_hours = self._hours_until_next_cheap(current)
                    target_export_kw = self._paced_export_target_kw(
                        surplus_stored,
                        remaining_hours,
                        config,
                    )
                    discharge_headroom = max(
                        config.max_discharge_kw * hours - delivered,
                        0.0,
                    )
                    export_headroom = max(export_capacity - interval_export, 0.0)
                    inverter_headroom = max(inverter_capacity - inverter_used, 0.0)
                    exported_from_battery = min(
                        surplus_stored * config.discharge_efficiency,
                        target_export_kw * hours,
                        discharge_headroom,
                        export_headroom,
                        inverter_headroom,
                    )
                    battery_kwh -= exported_from_battery / max(
                        config.discharge_efficiency,
                        0.01,
                    )
                    battery_export += exported_from_battery
                    interval_export += exported_from_battery

            battery_kwh = min(max(battery_kwh, reserve_kwh), capacity)
            simulated_import += interval_import
            simulated_export += interval_export
            simulated_curtailment += interval_curtailment
            simulated_import_cost += interval_import * rate
            simulated_export_income += interval_export * export_rate

        coverage = covered / intervals if intervals else 0.0
        if covered == 0:
            return SimulationState(samples=len(today), data_coverage=0.0)

        current_plan = self._current_plan(
            live_snapshot or today[-1],
            today,
            battery_kwh,
            reserve_kwh,
            capacity,
            config,
            forecast_energy_until_offpeak_kwh,
        )
        actual_cost = actual_import_cost - actual_export_income
        simulated_cost = simulated_import_cost - simulated_export_income
        actual_avoided_import_value = baseline_import_cost - actual_import_cost
        simulated_avoided_import_value = baseline_import_cost - simulated_import_cost
        actual_system_value = actual_avoided_import_value + actual_export_income
        simulated_system_value = (
            simulated_avoided_import_value + simulated_export_income
        )

        return SimulationState(
            ready=covered >= 3,
            samples=len(today),
            actual_cost_pence=round(actual_cost, 2),
            simulated_cost_pence=round(simulated_cost, 2),
            saving_pence=round(actual_cost - simulated_cost, 2),
            actual_import_cost_pence=round(actual_import_cost, 2),
            actual_export_income_pence=round(actual_export_income, 2),
            simulated_import_cost_pence=round(simulated_import_cost, 2),
            simulated_export_income_pence=round(simulated_export_income, 2),
            actual_house_consumption_kwh=round(actual_house, 3),
            actual_ev_energy_kwh=round(actual_ev, 3),
            actual_solar_generation_kwh=round(actual_solar, 3),
            actual_battery_charge_kwh=round(actual_battery_charge, 3),
            actual_battery_discharge_kwh=round(actual_battery_discharge, 3),
            actual_grid_import_kwh=round(actual_import, 3),
            actual_grid_export_kwh=round(actual_export, 3),
            simulated_grid_import_kwh=round(simulated_import, 3),
            simulated_grid_export_kwh=round(simulated_export, 3),
            simulated_solar_generation_kwh=round(simulated_solar, 3),
            simulated_solar_curtailed_kwh=round(simulated_curtailment, 3),
            simulated_battery_charge_kwh=round(battery_charge, 3),
            simulated_battery_to_home_kwh=round(battery_to_home, 3),
            simulated_battery_export_kwh=round(battery_export, 3),
            simulated_battery_soc=round(100 * battery_kwh / capacity, 1),
            avoided_day_rate_import_kwh=round(avoided_day_import, 3),
            baseline_no_system_cost_pence=round(baseline_import_cost, 2),
            actual_avoided_import_value_pence=round(actual_avoided_import_value, 2),
            simulated_avoided_import_value_pence=round(
                simulated_avoided_import_value,
                2,
            ),
            actual_system_value_pence=round(actual_system_value, 2),
            simulated_system_value_pence=round(simulated_system_value, 2),
            current_simulated_house_load_kw=current_plan["house"],
            current_simulated_solar_power_kw=current_plan["solar"],
            current_simulated_grid_import_kw=current_plan["grid_import"],
            current_simulated_grid_export_kw=current_plan["grid_export"],
            current_simulated_battery_power_kw=current_plan["battery"],
            current_simulated_battery_to_home_power_kw=current_plan["battery_to_home"],
            current_simulated_battery_export_power_kw=current_plan["battery_export"],
            target_battery_export_power_kw=current_plan["target_battery_export"],
            exportable_battery_energy_kwh=current_plan["exportable_battery"],
            reserved_for_home_kwh=current_plan["reserved_for_home"],
            hours_until_next_cheap_period=current_plan["hours_until_cheap"],
            projected_soc_at_cheap_period_percent=current_plan[
                "projected_soc_at_cheap"
            ],
            home_reserve_forecast_source=current_plan["reserve_source"],
            projected_grid_import_before_cheap_kwh=current_plan[
                "projected_grid_import"
            ],
            battery_export_paused_for_home_reserve=current_plan[
                "export_paused_for_home"
            ],
            effective_export_rate_pence=round(effective_export_rate, 4),
            inverter_limit_kw=config.inverter_limit_kw,
            export_limit_kw=min(config.export_limit_kw, config.inverter_limit_kw),
            strategy=config.strategy,
            proposal_solar_active=config.proposal_solar_enabled
            and all(item.solar_power_kw is None for item in today),
            battery_export_enabled=config.battery_export_enabled,
            data_coverage=round(100 * coverage, 1),
        )

    def _empty_current_state(
        self,
        snapshot: Snapshot | None,
        config: SimulationConfig,
    ) -> SimulationState:
        """Expose proposal solar immediately, before two history samples exist."""
        if snapshot is None:
            return SimulationState()
        solar = self._simulated_solar_power(snapshot, config)
        return SimulationState(
            samples=1,
            current_simulated_house_load_kw=_load_kw(snapshot),
            current_simulated_solar_power_kw=solar,
            effective_export_rate_pence=config.export_rate_pence,
            inverter_limit_kw=config.inverter_limit_kw,
            export_limit_kw=min(config.export_limit_kw, config.inverter_limit_kw),
            strategy=config.strategy,
            proposal_solar_active=config.proposal_solar_enabled
            and snapshot.solar_power_kw is None,
            battery_export_enabled=config.battery_export_enabled,
        )

    def _battery_energy_at_day_start(
        self,
        records: list[Snapshot],
        first_today: Snapshot,
        capacity: float,
        reserve_kwh: float,
        config: SimulationConfig,
    ) -> float:
        """Carry the cheap-period charge before midnight into the new day."""
        initial = (
            capacity
            * min(
                max(config.battery_initial_percent, 0.0),
                100.0,
            )
            / 100
        )
        previous = sorted(
            (
                record
                for record in records
                if record.timestamp < first_today.timestamp
                and (first_today.timestamp - record.timestamp).total_seconds()
                <= 12 * 3600
            ),
            key=lambda record: record.timestamp,
        )
        cheap_tail: list[Snapshot] = []
        for record in reversed(previous):
            if record.cheap_period_confirmed:
                cheap_tail.append(record)
                continue
            if cheap_tail:
                break
            # The latest pre-midnight observation was not cheap, so there is
            # no cheap session crossing into this local day.
            break
        if not cheap_tail:
            return min(max(initial, reserve_kwh), capacity)

        battery_kwh = max(reserve_kwh, min(initial, capacity))
        session = [*reversed(cheap_tail), first_today]
        for current, following in zip(session, session[1:], strict=False):
            if not current.cheap_period_confirmed:
                continue
            hours = _interval_hours(current.timestamp, following.timestamp)
            charge_input_kwh = min(
                min(config.max_charge_kw, config.inverter_limit_kw) * hours,
                max(capacity - battery_kwh, 0.0) / max(config.charge_efficiency, 0.01),
            )
            battery_kwh += charge_input_kwh * config.charge_efficiency
        return min(max(battery_kwh, reserve_kwh), capacity)

    @staticmethod
    def _limit_export(requested_kwh: float, limit_kwh: float) -> tuple[float, float]:
        """Apply the configured grid-export and inverter limits."""
        exported = min(max(requested_kwh, 0.0), max(limit_kwh, 0.0))
        return exported, max(requested_kwh - exported, 0.0)

    @staticmethod
    def _simulated_solar_power(
        snapshot: Snapshot,
        config: SimulationConfig,
    ) -> float:
        """Use live FoxESS PV when present, otherwise the proposal model."""
        if snapshot.solar_power_kw is not None:
            return min(
                max(snapshot.solar_power_kw, 0.0),
                max(config.inverter_limit_kw, 0.0),
            )
        if not config.proposal_solar_enabled:
            return 0.0
        return min(
            FOXHOLE_PROPOSAL_PROFILE.estimate_power_kw(
                snapshot.timestamp,
                config.proposal_solar_factor,
            ),
            max(config.inverter_limit_kw, 0.0),
        )

    def _remaining_load_requirement(
        self,
        today: list[Snapshot],
        start_index: int,
        config: SimulationConfig,
        forecast_energy_until_offpeak_kwh: float | None,
    ) -> float:
        """Estimate AC house energy to preserve before the next cheap period."""
        known = 0.0
        reached_cheap_period = False
        for current, following in zip(
            today[start_index:],
            today[start_index + 1 :],
            strict=False,
        ):
            if current.cheap_period_confirmed:
                reached_cheap_period = True
                break
            hours = _interval_hours(current.timestamp, following.timestamp)
            load = _load_kw(current)
            if load is None:
                continue
            if config.strategy == "self_use":
                solar = self._simulated_solar_power(current, config)
                load = max(load - solar, 0.0)
            known += load * hours

        # The learned forecast covers the unobserved tail after the latest
        # retained snapshot. When it is unavailable, never assume zero demand:
        # preserve a conservative recent/current-load estimate instead.
        if not reached_cheap_period and today:
            latest = today[-1]
            tail_required, _ = self._home_energy_requirement(
                latest,
                today,
                config,
                forecast_energy_until_offpeak_kwh,
            )
            known += tail_required
        return known

    @staticmethod
    def _hours_until_next_cheap(snapshot: Snapshot) -> float | None:
        """Return hours until the next tariff cheap-period start."""
        target = snapshot.next_offpeak_start
        if target is None or target <= snapshot.timestamp:
            return None
        hours = (target - snapshot.timestamp).total_seconds() / 3600
        if hours > MAX_CHEAP_PERIOD_LOOKAHEAD_HOURS:
            return None
        return max(hours, 0.0)

    @staticmethod
    def _recent_average_load_kw(
        records: list[Snapshot],
        reference: Snapshot,
    ) -> float | None:
        """Return the recent average load ending at the reference snapshot."""
        cutoff = reference.timestamp - timedelta(hours=RECENT_LOAD_WINDOW_HOURS)
        values = [
            load
            for item in records
            if cutoff <= item.timestamp <= reference.timestamp
            if (load := _load_kw(item)) is not None
        ]
        if not values:
            return None
        return max(fmean(values), 0.0)

    def _home_energy_requirement(
        self,
        snapshot: Snapshot,
        records: list[Snapshot],
        config: SimulationConfig,
        forecast_energy_until_offpeak_kwh: float | None,
    ) -> tuple[float, str]:
        """Return conservative AC home energy needed before cheap power."""
        remaining_hours = self._hours_until_next_cheap(snapshot)
        if remaining_hours is None:
            return 0.0, "unavailable"

        if forecast_energy_until_offpeak_kwh is not None:
            required = max(forecast_energy_until_offpeak_kwh, 0.0)
            source = "learned_profile"
        else:
            recent_load = self._recent_average_load_kw(records, snapshot)
            if recent_load is not None:
                required = recent_load * remaining_hours
                source = "recent_average"
            else:
                current_load = _load_kw(snapshot)
                if current_load is None:
                    return 0.0, "unavailable"
                required = current_load * remaining_hours
                source = "current_load"

        if config.strategy == "self_use":
            # This is deliberately conservative: only subtract current modelled
            # solar from the fallback, never future solar that may not arrive.
            current_solar = self._simulated_solar_power(snapshot, config)
            required = max(required - current_solar * remaining_hours, 0.0)

        return required * HOME_RESERVE_SAFETY_FACTOR, source

    @staticmethod
    def _paced_export_target_kw(
        surplus_stored_kwh: float,
        remaining_hours: float | None,
        config: SimulationConfig,
    ) -> float:
        """Spread exportable battery energy evenly until the cheap period."""
        if config.strategy != "paced_export" or remaining_hours is None:
            return 0.0
        if remaining_hours <= 0 or surplus_stored_kwh <= 0:
            return 0.0
        deliverable_ac = surplus_stored_kwh * config.discharge_efficiency
        return min(deliverable_ac / remaining_hours, config.max_discharge_kw)

    def _current_plan(
        self,
        snapshot: Snapshot,
        today: list[Snapshot],
        battery_kwh: float,
        reserve_kwh: float,
        capacity: float,
        config: SimulationConfig,
        forecast_energy_until_offpeak_kwh: float | None,
    ) -> dict[str, float | str | bool | None]:
        """Return the current simulated power flow for dashboard comparison."""
        load = _load_kw(snapshot)
        if load is None:
            return {
                "house": None,
                "solar": None,
                "grid_import": None,
                "grid_export": None,
                "battery": None,
                "battery_to_home": None,
                "battery_export": None,
                "target_battery_export": None,
                "exportable_battery": None,
                "reserved_for_home": None,
                "hours_until_cheap": None,
                "projected_soc_at_cheap": None,
                "reserve_source": "unavailable",
                "projected_grid_import": None,
                "export_paused_for_home": False,
            }
        solar = self._simulated_solar_power(snapshot, config)
        inverter_limit = max(config.inverter_limit_kw, 0.0)
        export_limit = min(max(config.export_limit_kw, 0.0), inverter_limit)

        if snapshot.cheap_period_confirmed:
            charge_kw = min(
                config.max_charge_kw,
                inverter_limit,
                max(capacity - battery_kwh, 0.0) / max(config.charge_efficiency, 0.01),
            )
            return {
                "house": round(load, 3),
                "solar": round(solar, 3),
                "grid_import": round(load + charge_kw, 3),
                "grid_export": round(min(solar, export_limit), 3),
                "battery": round(-charge_kw * config.charge_efficiency, 3),
                "battery_to_home": 0.0,
                "battery_export": 0.0,
                "target_battery_export": 0.0,
                "exportable_battery": 0.0,
                "reserved_for_home": 0.0,
                "hours_until_cheap": 0.0,
                "projected_soc_at_cheap": round(100 * battery_kwh / capacity, 1),
                "reserve_source": "cheap_period",
                "projected_grid_import": 0.0,
                "export_paused_for_home": False,
            }

        if config.strategy == "self_use":
            solar_to_home = min(solar, load, inverter_limit)
            net_load = load - solar_to_home
            inverter_used = solar_to_home
            solar_export_request = max(solar - solar_to_home, 0.0)
        else:
            net_load = load
            inverter_used = 0.0
            solar_export_request = solar

        available_ac = max(battery_kwh - reserve_kwh, 0.0) * (
            config.discharge_efficiency
        )
        home_from_battery = min(
            net_load,
            config.max_discharge_kw,
            available_ac,
            max(inverter_limit - inverter_used, 0.0),
        )
        grid_import = max(net_load - home_from_battery, 0.0)
        inverter_used += home_from_battery
        solar_export = min(
            solar_export_request,
            export_limit,
            max(inverter_limit - inverter_used, 0.0),
        )
        inverter_used += solar_export

        required_home_energy, reserve_source = self._home_energy_requirement(
            snapshot,
            today,
            config,
            forecast_energy_until_offpeak_kwh,
        )
        reserved_for_home = min(required_home_energy, available_ac)
        projected_grid_import = max(required_home_energy - available_ac, 0.0)
        exportable_battery = max(available_ac - required_home_energy, 0.0)
        surplus_stored = exportable_battery / max(
            config.discharge_efficiency,
            0.01,
        )
        remaining_hours = self._hours_until_next_cheap(snapshot)
        target_export_kw = 0.0
        if config.battery_export_enabled:
            target_export_kw = self._paced_export_target_kw(
                surplus_stored,
                remaining_hours,
                config,
            )
        battery_export_kw = min(
            target_export_kw,
            max(config.max_discharge_kw - home_from_battery, 0.0),
            max(export_limit - solar_export, 0.0),
            max(inverter_limit - inverter_used, 0.0),
        )

        projected_stored = battery_kwh - (reserved_for_home + exportable_battery) / max(
            config.discharge_efficiency, 0.01
        )
        projected_soc = 100 * max(projected_stored, reserve_kwh) / capacity
        export_paused = bool(
            config.battery_export_enabled
            and remaining_hours is not None
            and required_home_energy > 0
            and exportable_battery <= 0.001
        )

        return {
            "house": round(load, 3),
            "solar": round(solar, 3),
            "grid_import": round(grid_import, 3),
            "grid_export": round(solar_export + battery_export_kw, 3),
            "battery": round(home_from_battery + battery_export_kw, 3),
            "battery_to_home": round(home_from_battery, 3),
            "battery_export": round(battery_export_kw, 3),
            "target_battery_export": round(target_export_kw, 3),
            "exportable_battery": round(exportable_battery, 3),
            "reserved_for_home": round(reserved_for_home, 3),
            "hours_until_cheap": (
                round(remaining_hours, 2) if remaining_hours is not None else None
            ),
            "projected_soc_at_cheap": round(projected_soc, 1),
            "reserve_source": reserve_source,
            "projected_grid_import": round(projected_grid_import, 3),
            "export_paused_for_home": export_paused,
        }
