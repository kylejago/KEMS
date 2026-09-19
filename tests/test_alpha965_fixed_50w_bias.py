"""Alpha9.65 fixed 50 W anti-import bias regressions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from kems_core import ControlConfig, ControlState, Snapshot
from kems_core.control_write_authority import assess_foxess_control_write_authority
from kems_core.foxess_command_shadow import build_foxess_command_shadow
from kems_core.grid_import_prevention import (
    FIXED_GRID_BIAS_KW,
    FIXED_GRID_BIAS_W,
    apply_grid_import_prevention_bias,
)

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
FAST_LOOP = KEMS / "kems_core" / "fast_grid_trim.py"
CONFIG_FLOW = KEMS / "config_flow.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"
NOW = datetime(2026, 9, 19, 16, 30, tzinfo=UTC)


def _control(**overrides: object) -> ControlState:
    values: dict[str, object] = {
        "operating_mode": "control",
        "operating_reason": "awaiting_export_tariff",
        "desired_work_mode": "Self Use",
        "desired_charge_power_kw": 0.0,
        "desired_battery_to_home_power_kw": 1.2,
        "desired_battery_export_power_kw": 0.0,
        "desired_total_discharge_power_kw": 1.2,
        "desired_min_soc_percent": 15.0,
        "desired_grid_export_allowed": False,
        "grid_available": True,
        "island_mode_active": False,
        "total_kh7_ac_output_kw": 1.4,
        "data_fresh": True,
        "plan_safe": True,
        "preflight_passed": 15,
        "preflight_total": 15,
    }
    values.update(overrides)
    return ControlState(**values)


def _snapshot(**overrides: object) -> Snapshot:
    values: dict[str, object] = {
        "timestamp": NOW,
        "battery_soc": 50.0,
        "grid_import_kw": 0.0,
        "grid_export_kw": 0.0,
        "off_peak": False,
        "intelligent_slot": False,
        "ev_charging": False,
    }
    values.update(overrides)
    return Snapshot(**values)


def _config(**overrides: object) -> ControlConfig:
    values: dict[str, object] = {
        # Legacy stored value is intentionally ignored by Alpha9.65 policy.
        "grid_import_prevention_bias_w": 10.0,
        "normal_reserve_percent": 15.0,
        "export_limit_kw": 6.4,
        "inverter_limit_kw": 7.0,
        "max_discharge_kw": 7.0,
    }
    values.update(overrides)
    return ControlConfig(**values)


def _decision(control: ControlState):
    return assess_foxess_control_write_authority(
        control,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=True,
        cheap_period_confirmed=False,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
        grid_bias_force_discharge_ready=True,
        inverter_limit_kw=7.0,
        max_discharge_kw=7.0,
        export_limit_kw=6.4,
    )


def test_policy_is_exactly_fixed_50w_even_with_legacy_10w_option() -> None:
    state = apply_grid_import_prevention_bias(_control(), _snapshot(), _config())

    assert FIXED_GRID_BIAS_W == 50.0
    assert FIXED_GRID_BIAS_KW == 0.05
    assert state.grid_import_prevention_bias_active is True
    assert state.grid_import_prevention_bias_w == 50.0
    assert state.grid_import_prevention_target_grid_power_w == -50.0
    assert state.desired_grid_bias_export_power_kw == 0.05


def test_fixed_bias_does_not_track_measured_grid_error() -> None:
    importing = apply_grid_import_prevention_bias(
        _control(),
        _snapshot(grid_import_kw=0.8, grid_export_kw=0.0),
        _config(),
    )
    exporting = apply_grid_import_prevention_bias(
        _control(),
        _snapshot(grid_import_kw=0.0, grid_export_kw=0.4),
        _config(),
    )

    assert importing.grid_import_prevention_bias_active is True
    assert exporting.grid_import_prevention_bias_active is True
    assert importing.desired_grid_bias_export_power_kw == 0.05
    assert exporting.desired_grid_bias_export_power_kw == 0.05


def test_live_command_is_house_support_plus_exactly_50w() -> None:
    state = apply_grid_import_prevention_bias(_control(), _snapshot(), _config())
    result = _decision(state)

    assert result.commands_permitted is True
    assert result.action == "grid_bias_force_discharge"
    assert result.force_discharge_power_kw == 1.45
    assert result.grid_bias_live is True
    assert result.grid_bias_applied_correction_kw == 0.05


def test_shadow_uses_fixed_50w_and_requires_no_export_limit_write() -> None:
    state = apply_grid_import_prevention_bias(_control(), _snapshot(), _config())
    shadow = build_foxess_command_shadow(
        state,
        observed={"export_power_limit_w": 14500.0},
        export_limit_kw=6.4,
    )
    proposed = shadow["proposed_foxess_command"]

    assert proposed["work_mode"] == "Force Discharge"
    assert proposed["force_discharge_power_kw"] == 1.45
    assert proposed["grid_bias_export_power_kw"] == 0.05
    assert proposed["grid_bias_fixed_export_kw"] == 0.05
    assert proposed["export_power_limit_w"] is None
    assert shadow["grid_import_prevention_bias"]["grid_error_w"] is None
    assert (
        shadow["grid_import_prevention_bias"]["control_strategy"]
        == "fixed_50w_export_bias_no_grid_error_tracking"
    )


def test_cheap_period_suppresses_fixed_bias() -> None:
    state = apply_grid_import_prevention_bias(
        _control(desired_work_mode="Force Charge", desired_charge_power_kw=4.0),
        _snapshot(off_peak=True),
        _config(),
    )

    assert state.grid_import_prevention_bias_active is False
    assert state.grid_import_prevention_bias_suppressed_reason == "cheap_period"
    assert state.desired_grid_bias_export_power_kw == 0.0


def test_deliberate_agile_export_has_priority_and_never_stacks_50w() -> None:
    state = apply_grid_import_prevention_bias(
        _control(
            desired_work_mode="Feed-in First",
            desired_battery_export_power_kw=2.0,
            desired_total_discharge_power_kw=3.2,
            desired_grid_export_allowed=True,
        ),
        _snapshot(),
        _config(),
    )
    shadow = build_foxess_command_shadow(
        state,
        observed={"export_power_limit_w": 14500.0},
        export_limit_kw=6.4,
    )
    proposed = shadow["proposed_foxess_command"]

    assert state.grid_import_prevention_bias_active is False
    assert (
        state.grid_import_prevention_bias_suppressed_reason
        == "deliberate_export_has_priority"
    )
    assert state.desired_grid_bias_export_power_kw == 0.0
    assert proposed["force_discharge_power_kw"] == 2.0
    assert proposed["grid_bias_export_power_kw"] == 0.0


def test_fast_feedback_loop_and_tunable_option_are_removed() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    flow = CONFIG_FLOW.read_text(encoding="utf-8")

    assert not FAST_LOOP.exists()
    assert "fast_grid_trim" not in source
    assert "_async_fast_grid_trim" not in source
    assert "observed_grid_w - target_grid_w" not in source
    assert "CONF_GRID_IMPORT_PREVENTION_BIAS_W" not in flow


def test_backend_never_writes_import_or_export_power_limits() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    live = source.split("async def async_update", 1)[1]

    assert '_entity_id(entities, "import_power_limit")' not in live
    assert '_entity_id(entities, "export_power_limit")' not in live
    assert '"import_power_limit_write": "never_written_by_alpha9.65"' in source
    assert '"export_power_limit_write": "never_written_by_alpha9.65"' in source


def test_alpha965_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.65"
    assert reason.startswith("Alpha9.65 replaces the closed-loop grid trim")
    assert "fixed 50 W" in reason
    assert "no measured-grid feedback" in reason
    assert "Import Power Limit" in reason
    assert "Agile" in reason
    assert "higher priority" in reason
