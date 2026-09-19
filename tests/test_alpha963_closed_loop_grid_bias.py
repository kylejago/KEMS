"""Alpha9.63 closed-loop grid-import prevention regressions."""

from __future__ import annotations

import json
from pathlib import Path

from kems_core import ControlState
from kems_core.control_write_authority import assess_foxess_control_write_authority
from kems_core.foxess_command_shadow import build_foxess_command_shadow
from kems_core.grid_import_prevention import grid_bias_required_correction_kw

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def _control(**overrides: object) -> ControlState:
    values: dict[str, object] = {
        "operating_mode": "control",
        "operating_reason": "awaiting_export_tariff",
        "desired_work_mode": "Self Use",
        "desired_charge_power_kw": 0.0,
        "desired_battery_export_power_kw": 0.0,
        "desired_grid_export_allowed": False,
        "desired_min_soc_percent": 15.0,
        "desired_grid_bias_export_power_kw": 0.01,
        "grid_import_prevention_bias_w": 10.0,
        "grid_import_prevention_bias_active": True,
        "grid_import_prevention_target_grid_power_w": -10.0,
        "grid_import_prevention_observed_grid_power_w": 14.0,
        "total_kh7_ac_output_kw": 1.203,
        "grid_available": True,
        "island_mode_active": False,
        "data_fresh": True,
        "plan_safe": True,
        "preflight_passed": 15,
        "preflight_total": 15,
    }
    values.update(overrides)
    return ControlState(**values)


def _decision(control: ControlState, **overrides: object):
    args: dict[str, object] = {
        "technical_ready": True,
        "binding_ready": True,
        "reviewed_version_matches": True,
        "no_paid_export_mode": True,
        "cheap_period_confirmed": False,
        "user_commissioned": True,
        "master_control_enabled": True,
        "emergency_stop": False,
        "grid_bias_force_discharge_ready": True,
        "grid_bias_engaged": False,
        "grid_bias_previous_correction_kw": 0.0,
        "inverter_limit_kw": 7.0,
    }
    args.update(overrides)
    return assess_foxess_control_write_authority(control, **args)


def test_diagnostic_case_uses_24w_grid_error_correction() -> None:
    result = _decision(_control())

    assert grid_bias_required_correction_kw(14.0, -10.0) == 0.024
    assert result.action == "grid_bias_force_discharge"
    assert result.grid_bias_error_w == 24.0
    assert result.grid_bias_requested_correction_kw == 0.024
    assert result.grid_bias_applied_correction_kw == 0.024
    assert result.force_discharge_power_kw == 1.227


def test_shadow_diagnostic_case_targets_1227w_total_output() -> None:
    shadow = build_foxess_command_shadow(
        _control(),
        observed={"export_power_limit_w": 14500.0},
        export_limit_kw=6.4,
    )
    bias = shadow["grid_import_prevention_bias"]
    proposed = shadow["proposed_foxess_command"]

    assert bias["configured_w"] == 10.0
    assert bias["target_grid_power_w"] == -10.0
    assert bias["observed_grid_power_w"] == 14.0
    assert bias["grid_error_w"] == 24.0
    assert bias["requested_correction_kw"] == 0.024
    assert proposed["grid_bias_export_power_kw"] == 0.01
    assert proposed["grid_bias_requested_correction_kw"] == 0.024
    assert proposed["force_discharge_power_kw"] == 1.227


def test_correction_is_hard_capped_at_100w() -> None:
    assert grid_bias_required_correction_kw(100.0, -10.0) == 0.1
    assert grid_bias_required_correction_kw(500.0, -10.0) == 0.1


def test_live_controller_slews_by_at_most_50w_per_scan() -> None:
    first = _decision(
        _control(grid_import_prevention_observed_grid_power_w=100.0),
    )
    second = _decision(
        _control(grid_import_prevention_observed_grid_power_w=100.0),
        grid_bias_engaged=True,
        grid_bias_previous_correction_kw=first.grid_bias_applied_correction_kw,
    )

    assert first.grid_bias_requested_correction_kw == 0.1
    assert first.grid_bias_applied_correction_kw == 0.05
    assert first.force_discharge_power_kw == 1.253
    assert second.grid_bias_applied_correction_kw == 0.1
    assert second.force_discharge_power_kw == 1.303


def test_live_controller_holds_previous_correction_inside_5w_deadband() -> None:
    result = _decision(
        _control(grid_import_prevention_observed_grid_power_w=-8.0),
        grid_bias_engaged=True,
        grid_bias_previous_correction_kw=0.024,
    )

    assert result.grid_bias_error_w == 2.0
    assert result.grid_bias_requested_correction_kw == 0.002
    assert result.grid_bias_applied_correction_kw == 0.024
    assert result.force_discharge_power_kw == 1.227


def test_material_natural_export_releases_remote_trim() -> None:
    result = _decision(
        _control(grid_import_prevention_observed_grid_power_w=-50.0),
        grid_bias_engaged=True,
        grid_bias_previous_correction_kw=0.024,
    )

    assert result.action == "self_use"
    assert result.grid_bias_live is False


def test_backend_exposes_controller_proof_without_export_limit_writes() -> None:
    source = BACKEND.read_text(encoding="utf-8")

    assert "grid_import_prevention_error_w" in source
    assert "grid_import_prevention_requested_correction_kw" in source
    assert "grid_import_prevention_applied_correction_kw" in source
    assert "grid_import_prevention_controller_correction_kw" in source
    assert "grid_import_prevention_max_step_kw" in source
    assert '"export_power_limit_write": "never_written_by_alpha9.64"' in source
    assert '_entity_id(entities, "export_power_limit")' not in source


def test_alpha963_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.64"
    assert reason.startswith("Alpha9.64 adds a fast FoxESS grid-trim loop")
    assert "correction = observed grid power - target grid power" in reason
    assert "capped at 100 W" in reason
    assert "rate-limited to 50 W per control scan" in reason
    assert "5 W error deadband" in reason
    assert "Export Power Limit writes remain blocked" in reason
