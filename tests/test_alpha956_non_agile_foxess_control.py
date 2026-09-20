"""Alpha9.56 bounded non-Agile FoxESS control regressions, retained by Alpha9.66."""

from __future__ import annotations

import json
from pathlib import Path

from kems_core import ControlState
from kems_core.control_write_authority import assess_foxess_control_write_authority

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
COMMISSIONING = KEMS / "commissioning.py"
SWITCH = KEMS / "switch.py"
CONTRACT = KEMS / "foxess_modbus_contract.py"
CONFIG_FLOW = KEMS / "config_flow.py"
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
    }
    args.update(overrides)
    return assess_foxess_control_write_authority(control, **args)


def test_self_use_is_live_outside_cheap_periods() -> None:
    result = _decision(_control())

    assert result.backend_available is True
    assert result.commands_permitted is True
    assert result.action == "self_use"
    assert result.min_soc_on_grid_percent == 15.0
    assert "Self Use" in result.reason


def test_confirmed_cheap_force_charge_is_live() -> None:
    result = _decision(
        _control(
            operating_reason="awaiting_export_tariff_charge",
            desired_work_mode="Force Charge",
            desired_charge_power_kw=6.25,
        ),
        cheap_period_confirmed=True,
    )

    assert result.commands_permitted is True
    assert result.action == "force_charge"
    assert result.force_charge_power_kw == 6.25


def test_force_charge_without_confirmed_cheap_period_fails_closed() -> None:
    result = _decision(
        _control(
            desired_work_mode="Force Charge",
            desired_charge_power_kw=6.0,
        )
    )

    assert result.commands_permitted is False
    assert result.action == "release"
    assert "confirmed cheap period" in result.reason


def test_deliberate_export_is_never_live() -> None:
    result = _decision(
        _control(
            desired_work_mode="Feed-in First",
            desired_battery_export_power_kw=2.0,
            desired_grid_export_allowed=True,
        )
    )

    assert result.commands_permitted is False
    assert result.action == "release"
    assert "outside the current live scope" in result.reason


def test_paid_or_agile_export_mode_is_never_live() -> None:
    result = _decision(_control(), no_paid_export_mode=False)

    assert result.commands_permitted is False
    assert result.action == "release"
    assert "Paid/Agile export control" in result.reason


def test_island_and_emergency_states_release_control() -> None:
    island = _decision(_control(island_mode_active=True, grid_available=False))
    stop = _decision(_control(), emergency_stop=True)

    assert island.commands_permitted is False
    assert island.action == "release"
    assert stop.commands_permitted is False
    assert stop.action == "release"


def test_every_explicit_control_gate_is_required() -> None:
    assert _decision(_control(), technical_ready=False).commands_permitted is False
    assert _decision(_control(), binding_ready=False).commands_permitted is False
    assert (
        _decision(_control(), reviewed_version_matches=False).backend_available is False
    )
    assert _decision(_control(), user_commissioned=False).commands_permitted is False
    assert (
        _decision(_control(), master_control_enabled=False).commands_permitted is False
    )
    assert _decision(_control(operating_mode="simulate")).commands_permitted is False
    assert _decision(_control(data_fresh=False)).commands_permitted is False
    assert _decision(_control(plan_safe=False)).commands_permitted is False


def test_backend_live_write_surface_has_no_force_discharge_path() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    live = source.split("async def async_update", 1)[1]

    assert (
        'required_keys = ("work_mode", "force_charge_power", "min_soc_on_grid")'
        in source
    )
    assert '_entity_id(entities, "force_discharge_power")' not in live
    assert 'decision.action == "grid_bias_force_discharge"' not in live
    assert '"import_power_limit"' not in live.split("payload = {", 1)[0]
    assert '"export_power_limit"' not in live.split("payload = {", 1)[0]
    assert '"deliberate_force_discharge": "blocked_in_current_release"' in source


def test_commissioning_still_exposes_explicit_opt_in_control() -> None:
    source = COMMISSIONING.read_text(encoding="utf-8")
    assert '"eligible_with_explicit_opt_in"' in source


def test_commissioning_acknowledgement_switch_refuses_early_enable() -> None:
    source = SWITCH.read_text(encoding="utf-8")
    flow = CONFIG_FLOW.read_text(encoding="utf-8")
    control_schema = flow.split("CONTROL_SCHEMA = vol.Schema(", 1)[1].split(
        "class KEMSConfigFlow", 1
    )[0]

    assert "class KEMSCommissionedForControlSwitch" in source
    assert 'if not readiness.get("ready_for_control")' in source
    assert "KEMS control-critical commissioning evidence is not ready" in source
    assert "CONF_SYSTEM_COMMISSIONED" not in control_schema


def test_static_contract_is_bounded_not_general_write_authority() -> None:
    source = CONTRACT.read_text(encoding="utf-8")

    assert '"hardware_writes": "conditional_bounded_control"' in source
    assert '"maximum_allowed_stage": "control"' in source
    assert "Self Use" in source
    assert "confirmed-cheap" in source
    assert "Min SoC-on-grid" in source
    assert "deliberate Force Discharge in the current release" in source
    assert '"export-power-limit writes"' in source
    assert '"import-power-limit writes"' in source


def test_current_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.68"
    assert reason.startswith("Alpha9.68")
    assert "Self Use" in reason
    assert "confirmed-cheap Force Charge" in reason
    assert "Min SoC-on-grid" in reason
    assert "Deliberate/economic Force Discharge" in reason
    assert "Import Power Limit" in reason
    assert "Export Power Limit" in reason
