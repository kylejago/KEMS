"""Hardware-independent KEMS control planner and pre-installation lab."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import ControlConfig, ControlState, SimulationState, Snapshot

OPERATING_MODES = ("observe", "simulate", "shadow", "control")
VIRTUAL_SCENARIOS = (
    "normal",
    "sunny_high_solar",
    "cloudy_low_solar",
    "high_house_load",
    "power_down_active",
    "grid_outage_daylight",
    "grid_outage_night",
    "grid_outage_high_load",
    "grid_flapping",
)


@dataclass(frozen=True, slots=True)
class _Inputs:
    """Normalised planning inputs after virtual scenario injection."""

    house_load_kw: float
    solar_power_kw: float
    battery_soc_percent: float
    grid_available: bool
    island_active: bool
    saving_session_active: bool
    cheap_period: bool
    grid_unstable: bool = False


class ControlEngine:
    """Create safe desired commands without writing to hardware."""

    def plan(
        self,
        snapshot: Snapshot,
        simulation: SimulationState,
        now: datetime,
        config: ControlConfig,
    ) -> ControlState:
        """Return an explainable plan for virtual or shadow operation."""
        inputs = self._inputs(snapshot, simulation, config)
        age = max((now - snapshot.timestamp).total_seconds(), 0.0)
        fresh = age <= max(config.stale_data_seconds, 30)
        passed, total = run_preflight_suite(config)

        eps_utilisation = 100 * inputs.house_load_kw / max(config.eps_limit_kw, 0.1)
        base = {
            "operating_mode": _valid_mode(config.operating_mode),
            "virtual_scenario": _valid_scenario(config.virtual_scenario),
            "grid_available": inputs.grid_available,
            "island_mode_active": inputs.island_active,
            "whole_house_eps_load_kw": round(inputs.house_load_kw, 3),
            "eps_headroom_kw": round(
                max(config.eps_limit_kw - inputs.house_load_kw, 0.0), 3
            ),
            "eps_utilisation_percent": round(eps_utilisation, 1),
            "eps_warning": eps_utilisation >= config.eps_warning_percent,
            "eps_critical": eps_utilisation >= config.eps_critical_percent,
            "data_age_seconds": round(age, 1),
            "data_fresh": fresh,
            "control_enabled": config.control_enabled,
            "commissioned": config.commissioned,
            "real_backend_available": False,
            "commands_permitted": False,
            "preflight_passed": passed,
            "preflight_total": total,
            "preflight_status": "PASS" if passed == total else "FAIL",
        }

        if config.emergency_stop:
            return ControlState(
                **base,
                operating_reason="emergency_stop",
                desired_work_mode="Stop KEMS writes",
                desired_min_soc_percent=max(
                    config.normal_reserve_percent,
                    config.island_reserve_percent if inputs.island_active else 0.0,
                ),
                desired_ev_charging_allowed=False,
                desired_grid_export_allowed=False,
                plan_safe=True,
                blocked_reason="Emergency stop is latched",
                next_action="Leave inverter in its safe local mode",
            )

        if not fresh:
            return ControlState(
                **base,
                operating_reason="stale_data_failsafe",
                desired_work_mode="No change",
                desired_min_soc_percent=config.normal_reserve_percent,
                desired_ev_charging_allowed=False,
                desired_grid_export_allowed=False,
                plan_safe=False,
                blocked_reason="Required source data is stale",
                next_action="Wait for fresh Modbus and tariff data",
            )

        if inputs.grid_unstable:
            return ControlState(
                **base,
                operating_reason="grid_restoration_hold",
                desired_work_mode="Self Use",
                desired_min_soc_percent=config.island_reserve_percent,
                desired_ev_charging_allowed=False,
                desired_grid_export_allowed=False,
                plan_safe=True,
                blocked_reason="Grid stability timer has not completed",
                next_action=(
                    f"Hold resilience mode for {config.grid_stability_seconds} seconds"
                ),
            )

        if inputs.island_active or not inputs.grid_available:
            return self._island_plan(inputs, simulation, config, base)

        mode = _valid_mode(config.operating_mode)
        if mode == "observe":
            return ControlState(
                **base,
                operating_reason="observe_only",
                desired_work_mode="No change",
                desired_min_soc_percent=config.normal_reserve_percent,
                plan_safe=True,
                blocked_reason="Observe mode never produces commands",
                next_action="Continue recording live sources",
            )

        if inputs.cheap_period:
            desired_charge = min(config.max_charge_kw, config.eps_limit_kw)
            return ControlState(
                **base,
                operating_reason="confirmed_cheap_charge",
                desired_work_mode="Force Charge",
                desired_charge_power_kw=round(desired_charge, 3),
                desired_min_soc_percent=config.normal_reserve_percent,
                desired_ev_charging_allowed=True,
                desired_grid_export_allowed=False,
                plan_safe=True,
                blocked_reason=_backend_block_reason(config),
                next_action="Charge battery and supply home from the grid",
            )

        house = inputs.house_load_kw
        battery_home = min(
            max(simulation.current_simulated_battery_to_home_power_kw or house, 0.0),
            config.max_discharge_kw,
        )
        if inputs.saving_session_active:
            export = simulation.saving_session_export_target_kw
            if export is None:
                export = min(
                    max(config.eps_limit_kw - battery_home, 0.0),
                    config.export_limit_kw,
                )
            reason = "power_down_session"
            next_action = "Supply the home and maximise safe Power Down export"
        else:
            export = max(simulation.target_battery_export_power_kw or 0.0, 0.0)
            reason = (
                "power_down_reserve"
                if simulation.battery_reserved_for_saving_session
                else "paced_export"
            )
            next_action = (
                "Protect the joined Power Down reserve"
                if simulation.battery_reserved_for_saving_session
                else "Pace export to the next confirmed cheap period"
            )

        total = min(battery_home + export, config.max_discharge_kw, config.eps_limit_kw)
        export = min(export, max(total - battery_home, 0.0), config.export_limit_kw)
        safe = total <= config.eps_limit_kw + 1e-6
        return ControlState(
            **base,
            operating_reason=reason,
            desired_work_mode="Feed-in First" if export > 0 else "Self Use",
            desired_battery_to_home_power_kw=round(battery_home, 3),
            desired_battery_export_power_kw=round(export, 3),
            desired_total_discharge_power_kw=round(battery_home + export, 3),
            desired_min_soc_percent=config.normal_reserve_percent,
            desired_ev_charging_allowed=True,
            desired_grid_export_allowed=True,
            plan_safe=safe,
            blocked_reason=_backend_block_reason(config),
            next_action=next_action,
        )

    def _island_plan(
        self,
        inputs: _Inputs,
        simulation: SimulationState,
        config: ControlConfig,
        base: dict[str, object],
    ) -> ControlState:
        """Prioritise whole-house solar, then battery, during grid loss."""
        load = max(inputs.house_load_kw, 0.0)
        solar = max(inputs.solar_power_kw, 0.0)
        solar_to_house = min(solar, load, config.eps_limit_kw)
        shortfall = max(load - solar_to_house, 0.0)
        battery_to_house = min(shortfall, config.max_discharge_kw, config.eps_limit_kw)
        solar_to_battery = min(
            max(solar - solar_to_house, 0.0),
            config.max_charge_kw,
            max(config.eps_limit_kw - solar_to_house, 0.0),
        )
        usable_battery = (
            max(
                config.battery_capacity_kwh
                * (inputs.battery_soc_percent - config.island_reserve_percent)
                / 100,
                0.0,
            )
            * config.discharge_efficiency
        )
        runtime = None if shortfall <= 0.01 else usable_battery / shortfall
        safe = load <= config.eps_limit_kw + 1e-6
        if solar_to_battery > 0:
            action = "Use solar for the house and charge the battery with the surplus"
        elif battery_to_house > 0:
            action = "Use solar first and battery only for the remaining house load"
        else:
            action = "House is covered by solar; preserve the battery"
        if not safe:
            action = "Reduce whole-house load immediately to stay within EPS capacity"

        return ControlState(
            **base,
            operating_reason="whole_house_island",
            desired_work_mode="Self Use / EPS",
            desired_charge_power_kw=round(solar_to_battery, 3),
            desired_battery_to_home_power_kw=round(battery_to_house, 3),
            desired_total_discharge_power_kw=round(battery_to_house, 3),
            desired_min_soc_percent=config.island_reserve_percent,
            desired_ev_charging_allowed=False,
            desired_grid_export_allowed=False,
            solar_to_house_kw=round(solar_to_house, 3),
            solar_to_battery_kw=round(solar_to_battery, 3),
            battery_to_house_kw=round(battery_to_house, 3),
            estimated_outage_runtime_hours=(
                None if runtime is None else round(runtime, 2)
            ),
            plan_safe=safe,
            blocked_reason=(
                "Whole-house demand exceeds the configured EPS limit"
                if not safe
                else _backend_block_reason(config)
            ),
            next_action=action,
        )

    @staticmethod
    def _inputs(
        snapshot: Snapshot,
        simulation: SimulationState,
        config: ControlConfig,
    ) -> _Inputs:
        scenario = _valid_scenario(config.virtual_scenario)
        house = max(
            (
                simulation.current_simulated_house_load_kw
                if simulation.current_simulated_house_load_kw is not None
                else snapshot.house_load_kw or snapshot.grid_import_kw or 0.0
            ),
            0.0,
        )
        solar = max(
            (
                simulation.current_simulated_solar_power_kw
                if simulation.current_simulated_solar_power_kw is not None
                else snapshot.solar_power_kw or 0.0
            ),
            0.0,
        )
        soc = simulation.simulated_battery_soc
        if soc is None:
            soc = snapshot.battery_soc
        if soc is None:
            soc = config.normal_reserve_percent
        grid_available = True
        island = False
        active_session = snapshot.saving_session_active
        unstable = False

        if scenario == "sunny_high_solar":
            solar = min(config.eps_limit_kw, max(solar, 5.5))
        elif scenario == "cloudy_low_solar":
            solar = min(solar, 0.4)
        elif scenario == "high_house_load":
            house = max(house, config.eps_limit_kw * 0.92)
        elif scenario == "power_down_active":
            active_session = True
        elif scenario == "grid_outage_daylight":
            grid_available = False
            island = True
            solar = min(config.eps_limit_kw, max(solar, 4.0))
        elif scenario == "grid_outage_night":
            grid_available = False
            island = True
            solar = 0.0
        elif scenario == "grid_outage_high_load":
            grid_available = False
            island = True
            solar = 0.0
            house = max(house, config.eps_limit_kw * 1.05)
        elif scenario == "grid_flapping":
            grid_available = True
            unstable = True

        return _Inputs(
            house_load_kw=house,
            solar_power_kw=solar,
            battery_soc_percent=min(max(float(soc), 0.0), 100.0),
            grid_available=grid_available,
            island_active=island,
            saving_session_active=active_session,
            cheap_period=snapshot.cheap_period_confirmed,
            grid_unstable=unstable,
        )


def _valid_mode(value: str) -> str:
    return value if value in OPERATING_MODES else "simulate"


def _valid_scenario(value: str) -> str:
    return value if value in VIRTUAL_SCENARIOS else "normal"


def _backend_block_reason(config: ControlConfig) -> str:
    """Explain why alpha1 will not issue a real inverter write."""
    if config.operating_mode == "simulate":
        return "Virtual backend only"
    if config.operating_mode == "shadow":
        return "Shadow mode calculates commands but sends nothing"
    if config.operating_mode == "observe":
        return "Observe mode"
    if not config.commissioned:
        return "System has not been commissioned"
    if not config.control_enabled:
        return "Master control enable is off"
    return "Real FoxESS control backend is intentionally unavailable in alpha1"


def run_preflight_suite(config: ControlConfig) -> tuple[int, int]:
    """Run fast deterministic safety checks used by diagnostics and tests."""
    checks = (
        config.eps_limit_kw > 0,
        0 <= config.normal_reserve_percent < 100,
        config.island_reserve_percent >= config.normal_reserve_percent,
        config.max_charge_kw <= config.eps_limit_kw,
        config.max_discharge_kw <= config.eps_limit_kw,
        config.export_limit_kw <= config.eps_limit_kw,
        config.eps_warning_percent < config.eps_critical_percent,
        config.eps_critical_percent <= 100,
        config.stale_data_seconds >= 30,
        config.grid_stability_seconds >= 30,
        config.battery_capacity_kwh > 0,
        config.discharge_efficiency > 0,
    )
    return sum(checks), len(checks)
