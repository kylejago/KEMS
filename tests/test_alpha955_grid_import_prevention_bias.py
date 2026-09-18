"""Alpha9.55 grid import prevention bias regressions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from kems_core import ControlConfig, ControlState, Snapshot
from kems_core.foxess_command_shadow import build_foxess_command_shadow
from kems_core.grid_import_prevention import apply_grid_import_prevention_bias

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
CONST = INTEGRATION / "const.py"
CONFIG_FLOW = INTEGRATION / "config_flow.py"
TRANSLATIONS = INTEGRATION / "translations" / "en.json"
NOW = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)


def _control(**overrides: object) -> ControlState:
    values: dict[str, object] = {
        "operating_mode": "simulate",
        "operating_reason": "agile_rolling_price_optimised",
        "desired_work_mode": "Self Use",
        "desired_charge_power_kw": 0.0,
        "desired_battery_to_home_power_kw": 0.5,
        "desired_battery_export_power_kw": 0.0,
        "desired_total_discharge_power_kw": 0.5,
        "desired_min_soc_percent": 15.0,
        "desired_grid_export_allowed": False,
        "grid_available": True,
        "island_mode_active": False,
        "total_kh7_ac_output_kw": 0.8,
        "data_fresh": True,
        "plan_safe": True,
        "commands_permitted": False,
        "real_backend_available": False,
    }
    values.update(overrides)
    return ControlState(**values)


def _snapshot(**overrides: object) -> Snapshot:
    values: dict[str, object] = {
        "timestamp": NOW,
        "battery_soc": 50.0,
        "grid_import_kw": 0.005,
        "grid_export_kw": 0.0,
        "off_peak": False,
        "intelligent_slot": False,
        "ev_charging": False,
    }
    values.update(overrides)
    return Snapshot(**values)


def _config(**overrides: object) -> ControlConfig:
    values: dict[str, object] = {
        "grid_import_prevention_bias_w": 10.0,
        "normal_reserve_percent": 15.0,
        "export_limit_kw": 6.4,
        "inverter_limit_kw": 7.0,
        "max_discharge_kw": 7.0,
    }
    values.update(overrides)
    return ControlConfig(**values)


def test_10w_bias_activates_near_zero_even_without_economic_export() -> None:
    state = apply_grid_import_prevention_bias(
        _control(desired_grid_export_allowed=False),
        _snapshot(grid_import_kw=0.005),
        _config(),
    )

    assert state.grid_import_prevention_bias_active is True
    assert state.grid_import_prevention_bias_w == 10.0
    assert state.grid_import_prevention_target_grid_power_w == -10.0
    assert state.grid_import_prevention_observed_grid_power_w == 5.0
    assert state.desired_grid_bias_export_power_kw == 0.01
    assert state.desired_battery_export_power_kw == 0.0
    assert state.desired_grid_export_allowed is False
    assert state.grid_import_prevention_bias_suppressed_reason is None


def test_bias_shadow_is_separate_from_no_paid_export_authority() -> None:
    state = apply_grid_import_prevention_bias(
        _control(desired_grid_export_allowed=False),
        _snapshot(),
        _config(),
    )
    shadow = build_foxess_command_shadow(
        state,
        observed={"export_power_limit_w": 14500.0},
        export_limit_kw=6.4,
    )
    proposed = shadow["proposed_foxess_command"]

    assert shadow["translation_status"] == "PASS"
    assert shadow["grid_import_prevention_bias"]["active"] is True
    assert shadow["grid_import_prevention_bias"]["configured_w"] == 10.0
    assert (
        shadow["grid_import_prevention_bias"]["economic_export_authority_unchanged"]
        is True
    )
    assert proposed["work_mode"] == "Force Discharge"
    assert proposed["force_discharge_power_kw"] == 0.01
    assert proposed["export_power_limit_w"] == 10
    assert proposed["grid_export_allowed"] is False
    assert proposed["grid_bias_export_allowed"] is True
    assert proposed["grid_bias_export_power_kw"] == 0.01
    assert shadow["commands_permitted"] is False
    assert shadow["real_hardware_writes"] == "blocked"


def test_zero_setting_disables_bias_and_preserves_alpha954_no_export_shadow() -> None:
    state = apply_grid_import_prevention_bias(
        _control(),
        _snapshot(),
        _config(grid_import_prevention_bias_w=0.0),
    )
    shadow = build_foxess_command_shadow(
        state,
        observed={"export_power_limit_w": 14500.0},
        export_limit_kw=6.4,
    )
    proposed = shadow["proposed_foxess_command"]

    assert state.grid_import_prevention_bias_active is False
    assert state.grid_import_prevention_bias_suppressed_reason == "disabled"
    assert state.desired_grid_bias_export_power_kw == 0.0
    assert proposed["work_mode"] == "Self Use"
    assert proposed["force_discharge_power_kw"] is None
    assert proposed["export_power_limit_w"] == 0


def test_bias_suppresses_during_cheap_charge() -> None:
    state = apply_grid_import_prevention_bias(
        _control(desired_work_mode="Force Charge", desired_charge_power_kw=4.0),
        _snapshot(off_peak=True),
        _config(),
    )

    assert state.grid_import_prevention_bias_active is False
    assert state.grid_import_prevention_bias_suppressed_reason == "cheap_period"


def test_bias_suppresses_at_reserve_floor() -> None:
    state = apply_grid_import_prevention_bias(
        _control(desired_min_soc_percent=15.0),
        _snapshot(battery_soc=15.0),
        _config(),
    )

    assert state.grid_import_prevention_bias_active is False
    assert (
        state.grid_import_prevention_bias_suppressed_reason
        == "battery_at_or_below_reserve"
    )


def test_bias_suppresses_in_island_mode() -> None:
    state = apply_grid_import_prevention_bias(
        _control(island_mode_active=True, grid_available=False),
        _snapshot(),
        _config(),
    )

    assert state.grid_import_prevention_bias_active is False
    assert (
        state.grid_import_prevention_bias_suppressed_reason
        == "island_or_grid_unavailable"
    )


def test_bias_suppresses_during_deliberate_economic_export() -> None:
    state = apply_grid_import_prevention_bias(
        _control(
            desired_work_mode="Feed-in First",
            desired_battery_export_power_kw=2.0,
            desired_total_discharge_power_kw=2.5,
            desired_grid_export_allowed=True,
        ),
        _snapshot(),
        _config(),
    )

    assert state.grid_import_prevention_bias_active is False
    assert state.grid_import_prevention_bias_suppressed_reason == "deliberate_export"


def test_bias_suppresses_outside_small_grid_trim_window() -> None:
    state = apply_grid_import_prevention_bias(
        _control(),
        _snapshot(grid_import_kw=0.25),
        _config(),
    )

    assert state.grid_import_prevention_bias_active is False
    assert (
        state.grid_import_prevention_bias_suppressed_reason
        == "grid_exchange_outside_trim_window"
    )


def test_bias_cannot_bypass_user_kems_export_ceiling() -> None:
    state = apply_grid_import_prevention_bias(
        _control(),
        _snapshot(),
        _config(export_limit_kw=0.0),
    )

    assert state.grid_import_prevention_bias_active is False
    assert (
        state.grid_import_prevention_bias_suppressed_reason
        == "kems_export_ceiling_below_bias"
    )


def test_user_setting_is_safe_default_and_exposed_in_control_options() -> None:
    const_source = CONST.read_text(encoding="utf-8")
    flow_source = CONFIG_FLOW.read_text(encoding="utf-8")
    translations = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
    control = translations["options"]["step"]["control"]

    assert (
        'CONF_GRID_IMPORT_PREVENTION_BIAS_W = "grid_import_prevention_bias_w"'
        in const_source
    )
    assert "CONF_GRID_IMPORT_PREVENTION_BIAS_W: 0.0" in const_source
    assert (
        'vol.Required(CONF_GRID_IMPORT_PREVENTION_BIAS_W): _number(0, 100, 5, "W")'
        in flow_source
    )
    assert (
        control["data"]["grid_import_prevention_bias_w"]
        == "Grid import prevention bias (W)"
    )
    description = control["data_description"]["grid_import_prevention_bias_w"]
    assert "0 disables it" in description
    assert "not paid-export income" in description
    assert "sends no hardware writes" in description
