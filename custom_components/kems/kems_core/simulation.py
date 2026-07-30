"""Read-only battery and tariff simulation for KEMS."""

from __future__ import annotations

from datetime import datetime

from .models import SimulationConfig, SimulationState, Snapshot

MAX_INTERVAL_HOURS = 0.5


def _interval_hours(current: datetime, following: datetime) -> float:
    """Return a safe interval duration in hours."""
    seconds = max((following - current).total_seconds(), 0.0)
    return min(seconds / 3600, MAX_INTERVAL_HOURS)


class SimulationEngine:
    """Compare observed operation with a hypothetical KEMS strategy."""

    def simulate_today(
        self,
        records: list[Snapshot],
        now: datetime,
        config: SimulationConfig,
    ) -> SimulationState:
        """Simulate the current local day from retained observations."""
        today = [record for record in records if record.timestamp.date() == now.date()]
        if len(today) < 2:
            return SimulationState(samples=len(today))

        capacity = max(config.battery_capacity_kwh, 0.1)
        reserve_kwh = capacity * config.battery_reserve_percent / 100
        initial_soc = today[0].battery_soc
        if initial_soc is None:
            initial_soc = config.battery_initial_percent
        battery_kwh = capacity * min(max(initial_soc, 0.0), 100.0) / 100

        actual_cost = 0.0
        simulated_cost = 0.0
        actual_import = 0.0
        simulated_import = 0.0
        simulated_export = 0.0
        avoided_day_import = 0.0
        covered = 0
        intervals = 0

        for current, following in zip(today, today[1:], strict=False):
            hours = _interval_hours(current.timestamp, following.timestamp)
            if hours <= 0:
                continue
            intervals += 1

            rate = current.current_import_rate
            if rate is None:
                continue

            load_kw = current.house_load_kw
            if load_kw is None:
                load_kw = current.grid_import_kw
            if load_kw is None:
                continue

            covered += 1
            load_kw = max(load_kw, 0.0)
            solar_kw = max(current.solar_power_kw or 0.0, 0.0)
            actual_import_kw = current.grid_import_kw
            if actual_import_kw is None:
                actual_import_kw = max(load_kw - solar_kw, 0.0)
            actual_export_kw = max(current.grid_export_kw or 0.0, 0.0)

            actual_import_kwh = max(actual_import_kw, 0.0) * hours
            actual_export_kwh = actual_export_kw * hours
            actual_import += actual_import_kwh
            export_rate = current.current_export_rate
            if export_rate is None:
                export_rate = config.export_rate_pence
            actual_cost += actual_import_kwh * rate - actual_export_kwh * export_rate

            cheap = current.cheap_period_confirmed
            if cheap:
                house_grid_kwh = load_kw * hours
                charge_input_kwh = min(
                    config.max_charge_kw * hours,
                    max(capacity - battery_kwh, 0.0)
                    / max(config.charge_efficiency, 0.01),
                )
                battery_kwh += charge_input_kwh * config.charge_efficiency
                interval_import = house_grid_kwh + charge_input_kwh
                interval_export = (
                    solar_kw * hours if config.strategy == "export_first" else 0.0
                )
            else:
                if config.strategy == "export_first":
                    interval_export = solar_kw * hours
                    net_load_kwh = load_kw * hours
                else:
                    solar_to_load_kw = min(solar_kw, load_kw)
                    net_load_kwh = (load_kw - solar_to_load_kw) * hours
                    interval_export = max(solar_kw - load_kw, 0.0) * hours

                available_to_load = max(battery_kwh - reserve_kwh, 0.0)
                max_deliverable = config.max_discharge_kw * hours
                delivered = min(
                    net_load_kwh,
                    max_deliverable,
                    available_to_load * config.discharge_efficiency,
                )
                battery_kwh -= delivered / max(config.discharge_efficiency, 0.01)
                interval_import = max(net_load_kwh - delivered, 0.0)
                avoided_day_import += delivered

            simulated_import += interval_import
            simulated_export += interval_export
            simulated_cost += interval_import * rate - interval_export * export_rate

        coverage = covered / intervals if intervals else 0.0
        if covered == 0:
            return SimulationState(samples=len(today), data_coverage=0.0)

        return SimulationState(
            ready=covered >= 3,
            samples=len(today),
            actual_cost_pence=round(actual_cost, 2),
            simulated_cost_pence=round(simulated_cost, 2),
            saving_pence=round(actual_cost - simulated_cost, 2),
            actual_grid_import_kwh=round(actual_import, 3),
            simulated_grid_import_kwh=round(simulated_import, 3),
            simulated_grid_export_kwh=round(simulated_export, 3),
            simulated_battery_soc=round(100 * battery_kwh / capacity, 1),
            avoided_day_rate_import_kwh=round(avoided_day_import, 3),
            data_coverage=round(100 * coverage, 1),
        )
