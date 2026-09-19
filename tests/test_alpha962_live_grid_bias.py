"""Alpha9.62 bounded live grid-import-prevention regressions."""

from __future__ import annotations

import json
from pathlib import Path

from kems_core import ControlState
from kems_core.control_write_authority import assess_foxess_control_write_authority
from kems_core.grid_bias_closed_loop import (
    GRID_BIAS_DEADBAND_W,
    GRID_BIAS_MAX_ADJUSTMENT_W,
    GRID_BIAS_MAX_COMMAND_W,
    next_grid_bias_control_step,
)

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
CONTRACT = KEMS / "foxess_modbus_contract.py"
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
        "grid_import_prevention_observed_grid_power_w": 20.0,
        "grid_available": True,
        "island_mode_active": False,
        "data_fresh": True,
        "plan_safe": True,
        "preflight_passed": 15,
        "preflight_total": 15,
    }
    values.update(overrides)
    return ControlState(**values)


def _authority(control: ControlState, *, bias_kw: float | None, **overrides: object):
    args: dict[str, object] = {
        "technical_ready": True,
        "binding_ready": True,
        "reviewed_version_matches": True,
        "no_paid_export_mode": True,
        "cheap_period_confirmed": False,
        "user_commissioned": True,
        "master_control_enabled": True,
        "emergency_stop": False,
        "grid_bias_force_discharge_kw": bias_kw,
    }
    args.update(overrides)
    return assess_foxess_control_write_authority(control, **args)


def test_live_baseline_enters_at_configured_10w_not_30w_error_or_dormant_7kw() -> None:
    step = next_grid_bias_control_step(_control(), 0.0)

    assert step.active is True
    assert step.reason == "enter_bounded_grid_bias"
    assert step.observed_grid_power_w == 20.0
    assert step.target_grid_power_w == -10.0
    assert step.error_w == 30.0
    assert step.previous_setpoint_kw == 0.0
    assert step.requested_setpoint_kw == 0.01
    assert step.correction_w == 10.0


def test_second_scan_corrects_residual_grid_error_from_kems_owned_setpoint() -> None:
    step = next_grid_bias_control_step(
        _control(grid_import_prevention_observed_grid_power_w=5.0),
        0.01,
    )

    assert step.error_w == 15.0
    assert step.requested_setpoint_kw == 0.025
    assert step.correction_w == 15.0
    assert step.reason == "increase_bounded_grid_bias"


def test_deadband_holds_owned_setpoint_without_write_chatter() -> None:
    step = next_grid_bias_control_step(
        _control(grid_import_prevention_observed_grid_power_w=-8.0),
        0.025,
    )

    assert GRID_BIAS_DEADBAND_W == 5.0
    assert step.within_deadband is True
    assert step.requested_setpoint_kw == 0.025
    assert step.correction_w == 0.0
    assert step.reason == "hold_within_deadband"


def test_overexport_steps_down_and_can_exit_remote_control() -> None:
    step = next_grid_bias_control_step(
        _control(grid_import_prevention_observed_grid_power_w=-50.0),
        0.025,
    )

    assert step.error_w == -40.0
    assert step.requested_setpoint_kw == 0.0
    assert step.active is False
    assert step.correction_w == -25.0


def test_grid_bias_rate_limit_is_25w_per_scan() -> None:
    step = next_grid_bias_control_step(
        _control(grid_import_prevention_observed_grid_power_w=100.0),
        0.01,
    )

    assert GRID_BIAS_MAX_ADJUSTMENT_W == 25.0
    assert step.error_w == 110.0
    assert step.requested_setpoint_kw == 0.035
    assert step.correction_w == 25.0


def test_grid_bias_hard_ceiling_is_100w() -> None:
    step = next_grid_bias_control_step(
        _control(grid_import_prevention_observed_grid_power_w=100.0),
        0.09,
    )

    assert GRID_BIAS_MAX_COMMAND_W == 100.0
    assert step.requested_setpoint_kw == 0.1
    assert step.saturated is True


def test_suppressed_bias_clears_live_setpoint() -> None:
    step = next_grid_bias_control_step(
        _control(
            grid_import_prevention_bias_active=False,
            desired_grid_bias_export_power_kw=0.0,
        ),
        0.035,
    )

    assert step.active is False
    assert step.reason == "bias_not_requested"
    assert step.requested_setpoint_kw == 0.0


def test_explicit_closed_loop_setpoint_unlocks_only_bounded_grid_bias() -> None:
    decision = _authority(_control(), bias_kw=0.01)

    assert decision.commands_permitted is True
    assert decision.action == "grid_bias"
    assert decision.force_discharge_power_kw == 0.01
    assert decision.grid_bias_live is True
    assert decision.grid_bias_shadow_only is False


def test_general_force_discharge_is_still_blocked() -> None:
    decision = _authority(
        _control(
            desired_work_mode="Feed-in First",
            desired_battery_export_power_kw=1.0,
            desired_grid_export_allowed=True,
        ),
        bias_kw=0.01,
    )

    assert decision.commands_permitted is False
    assert decision.action == "release"


def test_bias_above_100w_is_rejected_fail_closed() -> None:
    decision = _authority(_control(), bias_kw=0.101)

    assert decision.commands_permitted is False
    assert decision.action == "release"
    assert "100 W ceiling" in decision.reason


def test_cheap_period_suppresses_live_force_discharge_bias() -> None:
    decision = _authority(
        _control(),
        bias_kw=0.01,
        cheap_period_confirmed=True,
    )

    assert decision.commands_permitted is True
    assert decision.action == "self_use"
    assert "Cheap period suppresses" in decision.reason


def test_backend_never_inherits_dormant_force_discharge_number_and_sets_power_first() -> (
    None
):
    source = BACKEND.read_text(encoding="utf-8")

    assert "grid_bias_force_discharge_kw" in source
    assert "next_grid_bias_control_step(" in source
    assert "GRID_BIAS_MAX_COMMAND_KW" in source
    assert '"force_discharge_power"' in source
    assert '_entity_id(entities, "export_power_limit")' not in source
    assert '"export_power_limit_write": "never_written_by_alpha9.62"' in source

    power_write = source.index(
        "discharge_power_entity,\n                            "
        "float(decision.force_discharge_power_kw),"
    )
    mode_write = source.index(
        'work_mode_entity,\n                                "Force Discharge",'
    )
    assert power_write < mode_write


def test_runtime_contract_requires_1w_force_discharge_resolution() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")

    assert "_REVIEWED_GRID_BIAS_STEP_KW = 0.001" in source
    assert "step <= _REVIEWED_GRID_BIAS_STEP_KW" in source
    assert "live_command_ceiling_kw" in source
    assert "Alpha9.62 opt-in non-Agile control" in contract
    assert "bounded <=100 W closed-loop" in contract
    assert "Force Discharge outside bounded grid-bias control" in contract


def test_alpha962_release_identity_and_safety_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.62"
    assert reason.startswith(
        "Alpha9.62 advances the existing Grid import prevention bias"
    )
    assert "10 W in the commissioning evidence" in reason
    assert "5 W deadband" in reason
    assert "25 W change per coordinator scan" in reason
    assert "hard 100 W Force Discharge ceiling" in reason
    assert "foxess_modbus v1.15.0" in reason
    assert "1 W (0.001 kW) resolution" in reason
    assert "does not grant general Force Discharge" in reason
    assert "never writes FoxESS Export Power Limit" in reason
    assert "Alpha9.61 Intelligent-slot confirmation" in reason
    assert "Alpha9.60 no-export forecast-target authority" in reason
