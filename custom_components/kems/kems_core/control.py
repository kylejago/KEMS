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
        snapshot_age = max((now - snapshot.timestamp).total_seconds(), 0.0)
        age = max(snapshot_age, snapshot.source_data_age_seconds or 0.0)
        fresh = age <= max(config.stale_data_seconds, 30) and not snapshot.stale_fields
        passed, total = run_preflight_suite(config)

        island_active = inputs.island_active or not inputs.grid_available
        eps_utilisation = (
            100 * inputs.house_load_kw / max(config.eps_limit_kw, 0.1)
            if island_active
            else 0.0
        )
        if not island_active:
            eps_status = "not_active"
        elif eps_utilisation > 100.0:
            eps_status = "unsafe"
        elif eps_utilisation >= config.eps_critical_percent:
            eps_status = "critical"
        elif eps_utilisation >= config.eps_warning_percent:
            eps_status = "elevated"
        else:
            eps_status = "normal"

        total_site_import = max(
            (
                simulation.current_simulated_total_site_import_kw
                if simulation.current_simulated_total_site_import_kw is not None
                else snapshot.grid_import_kw or 0.0
            ),
            0.0,
        )
        site_headroom = (
            None
            if config.site_import_limit_kw is None
            else round(config.site_import_limit_kw - total_site_import, 3)
        )
        site_exceeded = bool(site_headroom is not None and site_headroom < -1e-6)
        total_kh7 = max(simulation.current_simulated_total_kh7_output_kw or 0.0, 0.0)
        grid_bypass = max(
            (
                simulation.current_simulated_grid_bypass_power_kw
                if simulation.current_simulated_grid_bypass_power_kw is not None
                else total_site_import
            ),
            0.0,
        )

        base = {
            "operating_mode": _valid_mode(config.operating_mode),
            "virtual_scenario": _valid_scenario(config.virtual_scenario),
            "grid_available": inputs.grid_available,
            "island_mode_active": island_active,
            "whole_house_eps_load_kw": (
                round(inputs.house_load_kw, 3) if island_active else 0.0
            ),
            "virtual_scenario_house_load_kw": round(inputs.house_load_kw, 3),
            "virtual_scenario_solar_power_kw": round(inputs.solar_power_kw, 3),
            "island_conservation_threshold_percent": round(
                config.island_reserve_percent, 1
            ),
            "island_emergency_floor_percent": round(config.normal_reserve_percent, 1),
            "eps_headroom_kw": (
                round(max(config.eps_limit_kw - inputs.house_load_kw, 0.0), 3)
                if island_active
                else round(config.eps_limit_kw, 3)
            ),
            "eps_utilisation_percent": round(eps_utilisation, 1),
            "eps_warning": island_active
            and eps_utilisation >= config.eps_warning_percent,
            "eps_critical": island_active
            and eps_utilisation >= config.eps_critical_percent,
            "eps_status": eps_status,
            "eps_load_reduction_required_kw": (
                round(max(inputs.house_load_kw - config.eps_limit_kw, 0.0), 3)
                if island_active
                else 0.0
            ),
            "total_kh7_ac_output_kw": round(total_kh7, 3),
            "kh7_output_headroom_kw": round(
                max(config.inverter_limit_kw - total_kh7, 0.0), 3
            ),
            "grid_bypass_power_kw": round(grid_bypass, 3),
            "total_site_import_kw": round(total_site_import, 3),
            "site_import_limit_kw": config.site_import_limit_kw,
            "site_import_headroom_kw": site_headroom,
            "site_import_limit_exceeded": site_exceeded,
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
            return _control_state(
                base,
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
            return _control_state(
                base,
                operating_reason="stale_data_failsafe",
                desired_work_mode="No change",
                desired_min_soc_percent=config.normal_reserve_percent,
                desired_ev_charging_allowed=False,
                desired_grid_export_allowed=False,
                plan_safe=False,
                blocked_reason=(
                    "Required source data is stale: " + ", ".join(snapshot.stale_fields)
                    if snapshot.stale_fields
                    else "Required source data is stale"
                ),
                next_action="Wait for fresh Modbus and tariff data",
            )

        if inputs.grid_unstable:
            return _control_state(
                base,
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
            return _control_state(
                base,
                operating_reason="observe_only",
                desired_work_mode="No change",
                desired_min_soc_percent=config.normal_reserve_percent,
                plan_safe=True,
                blocked_reason="Observe mode never produces commands",
                next_action="Continue recording live sources",
            )

        if inputs.cheap_period:
            if simulation.no_export_mode_active:
                if simulation.current_simulated_grid_bypass_power_kw is not None:
                    planned_house_grid = max(
                        simulation.current_simulated_grid_bypass_power_kw,
                        0.0,
                    )
                else:
                    solar_to_home = min(
                        inputs.solar_power_kw,
                        inputs.house_load_kw,
                        config.inverter_limit_kw,
                    )
                    planned_house_grid = max(
                        inputs.house_load_kw - solar_to_home,
                        0.0,
                    )
            else:
                planned_house_grid = inputs.house_load_kw
            available_site_headroom = (
                config.max_charge_kw
                if config.site_import_limit_kw is None
                else max(config.site_import_limit_kw - planned_house_grid, 0.0)
            )
            requested_charge = (
                max(simulation.current_simulated_battery_charge_power_kw or 0.0, 0.0)
                if simulation.no_export_mode_active
                else config.max_charge_kw
            )
            desired_charge = min(requested_charge, available_site_headroom)
            planned_site_import = planned_house_grid + desired_charge
            planned_site_headroom = (
                None
                if config.site_import_limit_kw is None
                else round(config.site_import_limit_kw - planned_site_import, 3)
            )
            safe = bool(
                config.site_import_limit_kw is None
                or planned_site_import <= config.site_import_limit_kw + 1e-6
            )
            return _control_state(
                base,
                operating_reason=(
                    "awaiting_export_tariff_charge"
                    if simulation.no_export_mode_active
                    else "confirmed_cheap_charge"
                ),
                desired_work_mode="Force Charge",
                desired_charge_power_kw=round(desired_charge, 3),
                desired_min_soc_percent=config.normal_reserve_percent,
                desired_ev_charging_allowed=True,
                desired_grid_export_allowed=False,
                grid_bypass_power_kw=round(planned_house_grid, 3),
                total_site_import_kw=round(planned_site_import, 3),
                site_import_headroom_kw=planned_site_headroom,
                site_import_limit_exceeded=not safe,
                plan_safe=safe,
                blocked_reason=(
                    "Configured site-import limit leaves no safe charging headroom"
                    if not safe
                    else _backend_block_reason(config)
                ),
                next_action=(
                    "Charge only to the solar-aware no-export target and "
                    "supply the remaining home demand from cheap grid power"
                    if simulation.no_export_mode_active
                    else "Charge battery at the available site-import headroom "
                    "and supply home from grid"
                ),
            )

        house = inputs.house_load_kw
        solar_output = min(max(inputs.solar_power_kw, 0.0), config.inverter_limit_kw)

        if simulation.no_export_mode_active:
            solar_to_home = min(solar_output, house)
            battery_home = max(
                simulation.current_simulated_battery_to_home_power_kw or 0.0,
                0.0,
            )
            battery_home = min(
                battery_home,
                config.max_discharge_kw,
                max(config.inverter_limit_kw - solar_to_home, 0.0),
            )
            grid_import = max(
                (
                    simulation.current_simulated_grid_import_kw
                    if simulation.current_simulated_grid_import_kw is not None
                    else house - solar_to_home - battery_home
                ),
                0.0,
            )
            total_output = solar_to_home + battery_home
            site_headroom = (
                None
                if config.site_import_limit_kw is None
                else round(config.site_import_limit_kw - grid_import, 3)
            )
            site_exceeded = bool(site_headroom is not None and site_headroom < -1e-6)
            safe = (
                total_output <= config.inverter_limit_kw + 1e-6
                and battery_home <= config.max_discharge_kw + 1e-6
                and not site_exceeded
            )
            return _control_state(
                base,
                operating_reason=(
                    "awaiting_export_tariff_power_down"
                    if inputs.saving_session_active
                    else "awaiting_export_tariff"
                ),
                desired_work_mode="Self Use",
                desired_battery_to_home_power_kw=round(battery_home, 3),
                desired_battery_export_power_kw=0.0,
                desired_total_discharge_power_kw=round(battery_home, 3),
                desired_min_soc_percent=config.normal_reserve_percent,
                desired_ev_charging_allowed=not inputs.saving_session_active,
                desired_grid_export_allowed=False,
                total_kh7_ac_output_kw=round(total_output, 3),
                kh7_output_headroom_kw=round(
                    max(config.inverter_limit_kw - total_output, 0.0), 3
                ),
                grid_bypass_power_kw=round(grid_import, 3),
                total_site_import_kw=round(grid_import, 3),
                site_import_headroom_kw=site_headroom,
                site_import_limit_exceeded=site_exceeded,
                plan_safe=safe,
                blocked_reason=(
                    "Configured site-import limit exceeded"
                    if site_exceeded
                    else _backend_block_reason(config)
                ),
                next_action=(
                    "Use solar and battery for the home; keep deliberate grid "
                    "export disabled until the export tariff is active"
                ),
            )
        battery_output_headroom = max(config.inverter_limit_kw - solar_output, 0.0)
        battery_output_limit = min(config.max_discharge_kw, battery_output_headroom)
        battery_home = min(
            max(simulation.current_simulated_battery_to_home_power_kw or house, 0.0),
            battery_output_limit,
        )
        if inputs.saving_session_active:
            requested_session_export = (
                simulation.current_simulated_battery_export_power_kw
                if simulation.current_simulated_battery_export_power_kw is not None
                else simulation.saving_session_export_target_kw
            )
            export = max(requested_session_export or 0.0, 0.0)
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

        export = min(
            export,
            max(battery_output_limit - battery_home, 0.0),
            config.export_limit_kw,
        )
        battery_output = battery_home + export
        total_output = solar_output + battery_output
        grid_import = max(
            (
                simulation.current_simulated_grid_import_kw
                if simulation.current_simulated_grid_import_kw is not None
                else house - battery_home
            ),
            0.0,
        )
        site_headroom = (
            None
            if config.site_import_limit_kw is None
            else round(config.site_import_limit_kw - grid_import, 3)
        )
        site_exceeded = bool(site_headroom is not None and site_headroom < -1e-6)
        safe = (
            total_output <= config.inverter_limit_kw + 1e-6
            and battery_output <= config.max_discharge_kw + 1e-6
            and not site_exceeded
        )
        return _control_state(
            base,
            operating_reason=reason,
            desired_work_mode="Feed-in First" if export > 0 else "Self Use",
            desired_battery_to_home_power_kw=round(battery_home, 3),
            desired_battery_export_power_kw=round(export, 3),
            desired_total_discharge_power_kw=round(battery_output, 3),
            desired_min_soc_percent=config.normal_reserve_percent,
            desired_ev_charging_allowed=not inputs.saving_session_active,
            desired_grid_export_allowed=True,
            total_kh7_ac_output_kw=round(total_output, 3),
            kh7_output_headroom_kw=round(
                max(config.inverter_limit_kw - total_output, 0.0), 3
            ),
            grid_bypass_power_kw=round(grid_import, 3),
            total_site_import_kw=round(grid_import, 3),
            site_import_headroom_kw=site_headroom,
            site_import_limit_exceeded=site_exceeded,
            plan_safe=safe,
            blocked_reason=(
                "Combined solar and battery output exceeds the KH7 limit"
                if total_output > config.inverter_limit_kw + 1e-6
                else (
                    "Configured site-import limit exceeded"
                    if site_exceeded
                    else _backend_block_reason(config)
                )
            ),
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
        emergency_floor = min(
            config.normal_reserve_percent,
            config.island_reserve_percent,
        )
        conservation_threshold = max(
            config.island_reserve_percent,
            emergency_floor,
        )
        battery_above_floor = inputs.battery_soc_percent > emergency_floor + 1e-6
        battery_to_house = (
            min(
                shortfall,
                config.max_discharge_kw,
                max(config.eps_limit_kw - solar_to_house, 0.0),
            )
            if battery_above_floor
            else 0.0
        )
        solar_to_battery = min(
            max(solar - solar_to_house, 0.0),
            config.max_charge_kw,
            max(config.eps_limit_kw - solar_to_house, 0.0),
        )
        usable_battery = (
            max(
                config.battery_capacity_kwh
                * (inputs.battery_soc_percent - emergency_floor)
                / 100,
                0.0,
            )
            * config.discharge_efficiency
        )
        runtime = None if shortfall <= 0.01 else usable_battery / shortfall
        safe = load <= config.eps_limit_kw + 1e-6
        if inputs.battery_soc_percent <= emergency_floor + 1e-6:
            battery_status = "emergency_floor"
        elif inputs.battery_soc_percent < conservation_threshold:
            battery_status = "conservation"
        else:
            battery_status = "normal"
        if solar_to_battery > 0:
            action = "Use solar for the house and charge the battery with the surplus"
        elif battery_to_house > 0:
            action = "Use solar first and battery only for the remaining house load"
        else:
            action = "House is covered by solar; preserve the battery"
        if battery_status == "conservation" and safe:
            action = (
                "Battery is below the island conservation threshold; "
                "reduce discretionary whole-house load"
            )
        elif battery_status == "emergency_floor" and shortfall > 0.01 and safe:
            action = (
                "Battery has reached the emergency floor; reduce load and wait "
                "for solar or grid restoration"
            )
        if not safe:
            action = "Reduce whole-house load immediately to stay within EPS capacity"

        return _control_state(
            base,
            operating_reason="whole_house_island",
            desired_work_mode="Self Use / EPS",
            desired_charge_power_kw=round(solar_to_battery, 3),
            desired_battery_to_home_power_kw=round(battery_to_house, 3),
            desired_total_discharge_power_kw=round(battery_to_house, 3),
            desired_min_soc_percent=emergency_floor,
            desired_ev_charging_allowed=False,
            desired_grid_export_allowed=False,
            solar_to_house_kw=round(solar_to_house, 3),
            solar_to_battery_kw=round(solar_to_battery, 3),
            battery_to_house_kw=round(battery_to_house, 3),
            island_battery_status=battery_status,
            estimated_outage_runtime_hours=(
                None if runtime is None else round(runtime, 2)
            ),
            total_kh7_ac_output_kw=round(solar_to_house + battery_to_house, 3),
            kh7_output_headroom_kw=round(
                max(config.eps_limit_kw - solar_to_house - battery_to_house, 0.0),
                3,
            ),
            grid_bypass_power_kw=0.0,
            total_site_import_kw=0.0,
            site_import_headroom_kw=config.site_import_limit_kw,
            site_import_limit_exceeded=False,
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


def _control_state(base: dict[str, object], **overrides: object) -> ControlState:
    """Build a control state while allowing branch-specific topology overrides."""
    return ControlState(**{**base, **overrides})


def _valid_mode(value: str) -> str:
    return value if value in OPERATING_MODES else "simulate"


def _valid_scenario(value: str) -> str:
    return value if value in VIRTUAL_SCENARIOS else "normal"


def _backend_block_reason(config: ControlConfig) -> str:
    """Explain why alpha6 will not issue a real inverter write."""
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
    return "Real FoxESS control backend is intentionally unavailable in alpha6"


def run_preflight_suite(config: ControlConfig) -> tuple[int, int]:
    """Run fast deterministic safety checks used by diagnostics and tests."""
    checks = (
        config.inverter_limit_kw > 0,
        config.eps_limit_kw > 0,
        config.eps_limit_kw <= config.inverter_limit_kw,
        0 <= config.normal_reserve_percent < 100,
        config.island_reserve_percent >= config.normal_reserve_percent,
        config.max_charge_kw > 0,
        config.max_discharge_kw <= config.inverter_limit_kw,
        config.export_limit_kw <= config.inverter_limit_kw,
        config.site_import_limit_kw is None or config.site_import_limit_kw > 0,
        config.eps_warning_percent < config.eps_critical_percent,
        config.eps_critical_percent <= 100,
        config.stale_data_seconds >= 30,
        config.grid_stability_seconds >= 30,
        config.battery_capacity_kwh > 0,
        config.discharge_efficiency > 0,
    )
    return sum(checks), len(checks)
