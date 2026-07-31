"""Read-only proposal solar, battery, import, and export simulation."""

from __future__ import annotations

from datetime import datetime

from .models import SimulationConfig, SimulationState, Snapshot
from .system_profile import FOXHOLE_PROPOSAL_PROFILE

MAX_INTERVAL_HOURS = 0.5


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
    ) -> SimulationState:
        """Simulate the current local day from retained observations."""
        today = sorted(
            (record for record in records if record.timestamp.date() == now.date()),
            key=lambda record: record.timestamp,
        )
        if len(today) < 2:
            return self._empty_current_state(today, config)

        capacity = max(config.battery_capacity_kwh, 0.1)
        reserve_kwh = capacity * config.battery_reserve_percent / 100
        initial_soc = today[0].battery_soc
        if initial_soc is None:
            initial_soc = config.battery_initial_percent
        battery_kwh = capacity * min(max(initial_soc, 0.0), 100.0) / 100

        actual_import_cost = 0.0
        actual_export_income = 0.0
        simulated_import_cost = 0.0
        simulated_export_income = 0.0
        actual_house = 0.0
        actual_import = 0.0
        actual_export = 0.0
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
        effective_export_rate = config.export_rate_pence

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

            export_rate = (
                current.current_export_rate
                if current.current_export_rate is not None
                else config.export_rate_pence
            )
            effective_export_rate = export_rate
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
            actual_import += actual_import_kwh
            actual_export += actual_export_kwh
            actual_import_cost += actual_import_kwh * rate
            actual_export_income += actual_export_kwh * export_rate

            solar_energy = solar_kw * hours
            simulated_solar += solar_energy
            interval_import = 0.0
            interval_export = 0.0
            interval_curtailment = 0.0

            if current.cheap_period_confirmed:
                house_grid_kwh = load_kw * hours
                charge_input_kwh = min(
                    config.max_charge_kw * hours,
                    max(capacity - battery_kwh, 0.0)
                    / max(config.charge_efficiency, 0.01),
                )
                battery_kwh += charge_input_kwh * config.charge_efficiency
                battery_charge += charge_input_kwh * config.charge_efficiency
                interval_import = house_grid_kwh + charge_input_kwh
                interval_export, interval_curtailment = self._limit_export(
                    solar_energy,
                    config.export_limit_kw * hours,
                )
            else:
                if config.strategy == "self_use":
                    solar_to_home = min(solar_energy, actual_house_kwh)
                    net_load_kwh = actual_house_kwh - solar_to_home
                    solar_export_request = max(solar_energy - solar_to_home, 0.0)
                else:
                    net_load_kwh = actual_house_kwh
                    solar_export_request = solar_energy

                available_to_load = max(battery_kwh - reserve_kwh, 0.0)
                max_deliverable = config.max_discharge_kw * hours
                delivered = min(
                    net_load_kwh,
                    max_deliverable,
                    available_to_load * config.discharge_efficiency,
                )
                battery_kwh -= delivered / max(config.discharge_efficiency, 0.01)
                battery_to_home += delivered
                avoided_day_import += delivered
                interval_import = max(net_load_kwh - delivered, 0.0)

                export_capacity = config.export_limit_kw * hours
                solar_export, solar_curtailed = self._limit_export(
                    solar_export_request,
                    export_capacity,
                )
                interval_export = solar_export
                interval_curtailment += solar_curtailed

                if config.battery_export_enabled and export_capacity > interval_export:
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
                    discharge_headroom = max(max_deliverable - delivered, 0.0)
                    export_headroom = max(export_capacity - interval_export, 0.0)
                    exported_from_battery = min(
                        surplus_stored * config.discharge_efficiency,
                        discharge_headroom,
                        export_headroom,
                    )
                    battery_kwh -= exported_from_battery / max(
                        config.discharge_efficiency,
                        0.01,
                    )
                    battery_export += exported_from_battery
                    interval_export += exported_from_battery

            simulated_import += interval_import
            simulated_export += interval_export
            simulated_curtailment += interval_curtailment
            simulated_import_cost += interval_import * rate
            simulated_export_income += interval_export * export_rate

        coverage = covered / intervals if intervals else 0.0
        if covered == 0:
            return SimulationState(samples=len(today), data_coverage=0.0)

        current_plan = self._current_plan(
            today[-1],
            battery_kwh,
            reserve_kwh,
            capacity,
            config,
            forecast_energy_until_offpeak_kwh,
        )
        actual_cost = actual_import_cost - actual_export_income
        simulated_cost = simulated_import_cost - simulated_export_income

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
            current_simulated_house_load_kw=current_plan["house"],
            current_simulated_solar_power_kw=current_plan["solar"],
            current_simulated_grid_import_kw=current_plan["grid_import"],
            current_simulated_grid_export_kw=current_plan["grid_export"],
            current_simulated_battery_power_kw=current_plan["battery"],
            effective_export_rate_pence=round(effective_export_rate, 4),
            export_limit_kw=config.export_limit_kw,
            proposal_solar_active=config.proposal_solar_enabled
            and all(item.solar_power_kw is None for item in today),
            battery_export_enabled=config.battery_export_enabled,
            data_coverage=round(100 * coverage, 1),
        )

    def _empty_current_state(
        self,
        today: list[Snapshot],
        config: SimulationConfig,
    ) -> SimulationState:
        """Expose proposal solar immediately, before two history samples exist."""
        if not today:
            return SimulationState()
        latest = today[-1]
        solar = self._simulated_solar_power(latest, config)
        return SimulationState(
            samples=1,
            current_simulated_house_load_kw=_load_kw(latest),
            current_simulated_solar_power_kw=solar,
            effective_export_rate_pence=config.export_rate_pence,
            export_limit_kw=config.export_limit_kw,
            proposal_solar_active=config.proposal_solar_enabled
            and latest.solar_power_kw is None,
            battery_export_enabled=config.battery_export_enabled,
        )

    @staticmethod
    def _limit_export(requested_kwh: float, limit_kwh: float) -> tuple[float, float]:
        """Apply the configured grid-export limit."""
        exported = min(max(requested_kwh, 0.0), max(limit_kwh, 0.0))
        return exported, max(requested_kwh - exported, 0.0)

    @staticmethod
    def _simulated_solar_power(
        snapshot: Snapshot,
        config: SimulationConfig,
    ) -> float:
        """Use live FoxESS PV when present, otherwise the proposal model."""
        if snapshot.solar_power_kw is not None:
            return max(snapshot.solar_power_kw, 0.0)
        if not config.proposal_solar_enabled:
            return 0.0
        return FOXHOLE_PROPOSAL_PROFILE.estimate_power_kw(
            snapshot.timestamp,
            config.proposal_solar_factor,
        )

    def _remaining_load_requirement(
        self,
        today: list[Snapshot],
        start_index: int,
        config: SimulationConfig,
        forecast_energy_until_offpeak_kwh: float | None,
    ) -> float:
        """Estimate energy to preserve before the next confirmed cheap period."""
        known = 0.0
        for current, following in zip(
            today[start_index:],
            today[start_index + 1 :],
            strict=False,
        ):
            if current.cheap_period_confirmed:
                break
            hours = _interval_hours(current.timestamp, following.timestamp)
            load = _load_kw(current)
            if load is None:
                continue
            if config.strategy == "self_use":
                solar = self._simulated_solar_power(current, config)
                load = max(load - solar, 0.0)
            known += load * hours
        return known + max(forecast_energy_until_offpeak_kwh or 0.0, 0.0)

    def _current_plan(
        self,
        snapshot: Snapshot,
        battery_kwh: float,
        reserve_kwh: float,
        capacity: float,
        config: SimulationConfig,
        forecast_energy_until_offpeak_kwh: float | None,
    ) -> dict[str, float | None]:
        """Return the current simulated power flow for dashboard comparison."""
        load = _load_kw(snapshot)
        if load is None:
            return {
                "house": None,
                "solar": None,
                "grid_import": None,
                "grid_export": None,
                "battery": None,
            }
        solar = self._simulated_solar_power(snapshot, config)
        export_limit = max(config.export_limit_kw, 0.0)

        if snapshot.cheap_period_confirmed:
            charge_kw = min(
                config.max_charge_kw,
                max(capacity - battery_kwh, 0.0) / max(config.charge_efficiency, 0.01),
            )
            return {
                "house": round(load, 3),
                "solar": round(solar, 3),
                "grid_import": round(load + charge_kw, 3),
                "grid_export": round(min(solar, export_limit), 3),
                "battery": round(-charge_kw * config.charge_efficiency, 3),
            }

        net_load = load if config.strategy == "export_first" else max(load - solar, 0.0)
        available_ac = max(battery_kwh - reserve_kwh, 0.0) * config.discharge_efficiency
        home_from_battery = min(net_load, config.max_discharge_kw, available_ac)
        grid_import = max(net_load - home_from_battery, 0.0)
        solar_export = min(
            solar if config.strategy == "export_first" else max(solar - load, 0.0),
            export_limit,
        )
        battery_export_kw = 0.0
        if config.battery_export_enabled:
            forecast_stored = max(forecast_energy_until_offpeak_kwh or 0.0, 0.0) / max(
                config.discharge_efficiency,
                0.01,
            )
            surplus_ac = (
                max(
                    battery_kwh - reserve_kwh - forecast_stored,
                    0.0,
                )
                * config.discharge_efficiency
            )
            battery_export_kw = min(
                surplus_ac,
                max(config.max_discharge_kw - home_from_battery, 0.0),
                max(export_limit - solar_export, 0.0),
            )
        return {
            "house": round(load, 3),
            "solar": round(solar, 3),
            "grid_import": round(grid_import, 3),
            "grid_export": round(solar_export + battery_export_kw, 3),
            "battery": round(home_from_battery + battery_export_kw, 3),
        }
