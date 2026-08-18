"""Independent safety and tracking checks for KEMS shadow control."""

from __future__ import annotations

from typing import Any

from .models import ControlConfig, ControlState, SimulationState

_EPSILON = 1e-6
TRACKING_TOLERANCE_KW = 0.35


def _check(key: str, passed: bool, detail: str) -> dict[str, Any]:
    """Return one serialisable shadow-safety check."""
    return {"key": key, "passed": bool(passed), "detail": detail}


def validate_shadow_command(
    control: ControlState,
    config: ControlConfig,
) -> dict[str, Any]:
    """Validate one desired command envelope independently of ControlEngine."""
    charge = max(float(control.desired_charge_power_kw), 0.0)
    battery_home = max(float(control.desired_battery_to_home_power_kw), 0.0)
    export = max(float(control.desired_battery_export_power_kw), 0.0)
    discharge = max(float(control.desired_total_discharge_power_kw), 0.0)
    minimum_soc = float(control.desired_min_soc_percent)

    checks = [
        _check(
            "non_negative_targets",
            min(
                control.desired_charge_power_kw,
                control.desired_battery_to_home_power_kw,
                control.desired_battery_export_power_kw,
                control.desired_total_discharge_power_kw,
            )
            >= -_EPSILON,
            "charge, home, export and total-discharge requests must be non-negative",
        ),
        _check(
            "charge_limit",
            charge <= config.max_charge_kw + _EPSILON,
            f"charge {charge:.3f}kW <= configured {config.max_charge_kw:.3f}kW",
        ),
        _check(
            "discharge_limit",
            discharge <= config.max_discharge_kw + _EPSILON,
            (
                f"total discharge {discharge:.3f}kW <= configured "
                f"{config.max_discharge_kw:.3f}kW"
            ),
        ),
        _check(
            "export_limit",
            export <= config.export_limit_kw + _EPSILON,
            f"battery export {export:.3f}kW <= configured {config.export_limit_kw:.3f}kW",
        ),
        _check(
            "inverter_limit",
            float(control.total_kh7_ac_output_kw)
            <= config.inverter_limit_kw + _EPSILON,
            (
                f"KH7 output {control.total_kh7_ac_output_kw:.3f}kW <= configured "
                f"{config.inverter_limit_kw:.3f}kW"
            ),
        ),
        _check(
            "discharge_components",
            battery_home + export <= discharge + 0.01,
            "battery-to-home plus battery export must not exceed total discharge",
        ),
        _check(
            "no_charge_discharge_conflict",
            not (charge > 0.01 and discharge > 0.01),
            "a shadow command must not request battery charge and discharge together",
        ),
        _check(
            "minimum_soc",
            config.normal_reserve_percent - _EPSILON <= minimum_soc <= 100.0,
            (
                f"minimum SOC {minimum_soc:.1f}% must remain at/above normal reserve "
                f"{config.normal_reserve_percent:.1f}%"
            ),
        ),
        _check(
            "export_permission",
            bool(control.desired_grid_export_allowed) or export <= 0.01,
            "battery export must be zero whenever grid export is not permitted",
        ),
        _check(
            "island_export_block",
            not control.island_mode_active or export <= 0.01,
            "deliberate grid export must remain zero while islanded",
        ),
        _check(
            "site_import_limit",
            (
                config.site_import_limit_kw is None
                or float(control.total_site_import_kw)
                <= config.site_import_limit_kw + _EPSILON
            ),
            "planned site import must stay within the configured site limit",
        ),
        _check(
            "fresh_data",
            bool(control.data_fresh),
            "required control inputs must be fresh",
        ),
        _check(
            "planner_safe",
            bool(control.plan_safe),
            "ControlEngine must independently mark the desired plan safe",
        ),
    ]
    failed = [item for item in checks if not item["passed"]]
    return {
        "passed": not failed,
        "passed_checks": len(checks) - len(failed),
        "total_checks": len(checks),
        "failed_checks": [item["key"] for item in failed],
        "checks": checks,
    }


def shadow_plan_vs_outcome(
    control: ControlState,
    simulation: SimulationState,
    *,
    tolerance_kw: float = TRACKING_TOLERANCE_KW,
) -> dict[str, Any]:
    """Compare the desired command with the current digital-twin routing."""
    target = {
        "charge_kw": round(max(float(control.desired_charge_power_kw), 0.0), 3),
        "battery_to_home_kw": round(
            max(float(control.desired_battery_to_home_power_kw), 0.0), 3
        ),
        "battery_export_kw": round(
            max(float(control.desired_battery_export_power_kw), 0.0), 3
        ),
        "total_discharge_kw": round(
            max(float(control.desired_total_discharge_power_kw), 0.0), 3
        ),
    }

    charge = simulation.current_simulated_battery_charge_power_kw
    home = simulation.current_simulated_battery_to_home_power_kw
    export = simulation.current_simulated_battery_export_power_kw
    observed = {
        "charge_kw": None if charge is None else round(max(float(charge), 0.0), 3),
        "battery_to_home_kw": None if home is None else round(max(float(home), 0.0), 3),
        "battery_export_kw": (
            None if export is None else round(max(float(export), 0.0), 3)
        ),
        "total_discharge_kw": (
            None
            if home is None and export is None
            else round(max(float(home or 0.0), 0.0) + max(float(export or 0.0), 0.0), 3)
        ),
    }

    differences: dict[str, float | None] = {}
    within: dict[str, bool | None] = {}
    for key, target_value in target.items():
        observed_value = observed.get(key)
        if observed_value is None:
            differences[key] = None
            within[key] = None
            continue
        difference = float(observed_value) - float(target_value)
        differences[key] = round(difference, 3)
        within[key] = abs(difference) <= max(tolerance_kw, 0.0)

    scored = [value for value in within.values() if value is not None]
    score = (
        round(100.0 * sum(1 for value in scored if value) / len(scored), 1)
        if scored
        else None
    )
    return {
        "basis": "digital_twin",
        "tolerance_kw": round(max(tolerance_kw, 0.0), 3),
        "target": target,
        "outcome": observed,
        "difference": differences,
        "within_tolerance": within,
        "tracking_score_percent": score,
        "available": bool(scored),
    }
