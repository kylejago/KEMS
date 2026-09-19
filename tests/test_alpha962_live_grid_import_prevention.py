"""Alpha9.62 bounded live grid-import prevention regressions."""

from __future__ import annotations

from pathlib import Path

from kems_core import ControlState
from kems_core.control_write_authority import assess_foxess_control_write_authority
from kems_core.foxess_command_shadow import build_foxess_command_shadow

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
CONTRACT = KEMS / "foxess_modbus_contract.py"


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
        "total_kh7_ac_output_kw": 1.281,
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
        "inverter_limit_kw": 7.0,
    }
    args.update(overrides)
    return assess_foxess_control_write_authority(control, **args)


def test_live_grid_bias_uses_total_kh7_output_not_tiny_export_power() -> None:
    result = _decision(_control())

    assert result.commands_permitted is True
    assert result.action == "grid_bias_force_discharge"
    assert result.force_discharge_power_kw == 1.291
    assert result.grid_bias_live is True
    assert result.grid_bias_shadow_only is False


def test_grid_bias_shadow_translation_uses_total_inverter_output_setpoint() -> None:
    shadow = build_foxess_command_shadow(
        _control(),
        observed={"export_power_limit_w": 14500.0},
        export_limit_kw=6.4,
    )
    proposed = shadow["proposed_foxess_command"]

    assert proposed["work_mode"] == "Force Discharge"
    assert proposed["force_discharge_power_kw"] == 1.291
    assert proposed["grid_bias_export_power_kw"] == 0.01
    assert proposed["grid_export_allowed"] is False


def test_grid_bias_hysteresis_enters_on_import_and_releases_on_material_export() -> None:
    enter = _decision(_control(grid_import_prevention_observed_grid_power_w=5.0))
    already_exporting = _decision(
        _control(grid_import_prevention_observed_grid_power_w=-5.0)
    )
    remain = _decision(
        _control(grid_import_prevention_observed_grid_power_w=-20.0),
        grid_bias_engaged=True,
    )
    release = _decision(
        _control(grid_import_prevention_observed_grid_power_w=-50.0),
        grid_bias_engaged=True,
    )

    assert enter.action == "grid_bias_force_discharge"
    assert already_exporting.action == "self_use"
    assert remain.action == "grid_bias_force_discharge"
    assert release.action == "self_use"


def test_grid_bias_cannot_bypass_control_or_export_safety_gates() -> None:
    assert _decision(_control(), master_control_enabled=False).commands_permitted is False
    assert _decision(_control(), technical_ready=False).commands_permitted is False
    assert _decision(_control(), no_paid_export_mode=False).commands_permitted is False

    deliberate = _decision(
        _control(
            desired_grid_export_allowed=True,
            desired_battery_export_power_kw=1.0,
        )
    )
    assert deliberate.commands_permitted is False
    assert deliberate.action == "release"


def test_missing_force_discharge_binding_keeps_bias_shadow_only() -> None:
    result = _decision(_control(), grid_bias_force_discharge_ready=False)

    assert result.commands_permitted is True
    assert result.action == "self_use"
    assert result.grid_bias_shadow_only is True


def test_backend_write_surface_is_narrow_grid_bias_exception() -> None:
    source = BACKEND.read_text(encoding="utf-8")

    assert '_entity_id(entities, "force_discharge_power")' in source
    assert 'decision.action == "grid_bias_force_discharge"' in source
    assert '"Force Discharge"' in source
    assert '"export_power_limit"' not in source.split(
        "async def async_update", 1
    )[1].split('payload = {', 1)[0]
    assert '"blocked_except_bounded_grid_bias_trim"' in source
    assert '"never_written_by_alpha9.62"' in source


def test_contract_keeps_economic_export_blocked() -> None:
    source = CONTRACT.read_text(encoding="utf-8")

    assert "bounded grid-import prevention trim" in source
    assert "Force Discharge outside bounded grid-import prevention trim" in source
    assert '"deliberate economic export"' in source
    assert '"Agile/paid-export control"' in source
    assert '"export-power-limit writes"' in source


def test_alpha962_release_identity_and_scope() -> None:
    import json

    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.62"
    assert reason.startswith("Alpha9.62 promotes the optional Grid import prevention bias")
    assert "desired total KH7 AC output plus the configured tiny bias" in reason
    assert "at least 5 W import" in reason
    assert "natural export reaches 50 W" in reason
    assert "Deliberate/economic Force Discharge" in reason
    assert "Export Power Limit writes remain blocked" in reason
