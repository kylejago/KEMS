"""Alpha9.66 removes the abandoned anti-import control architecture."""

from __future__ import annotations

import json
from pathlib import Path

from kems_core import ControlState
from kems_core.control_write_authority import assess_foxess_control_write_authority

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
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


def _decision(control: ControlState, *, cheap: bool = False):
    return assess_foxess_control_write_authority(
        control,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=True,
        cheap_period_confirmed=cheap,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
    )


def test_removed_grid_bias_module_and_runtime_fields_do_not_exist() -> None:
    assert not (KEMS / "kems_core" / "grid_import_prevention.py").exists()

    const_source = (KEMS / "const.py").read_text(encoding="utf-8")
    models_source = (KEMS / "kems_core" / "models.py").read_text(encoding="utf-8")
    coordinator_source = (KEMS / "coordinator.py").read_text(encoding="utf-8")
    settings_source = (KEMS / "settings.py").read_text(encoding="utf-8")

    for source in (const_source, models_source, coordinator_source, settings_source):
        assert "grid_import_prevention" not in source
        assert "desired_grid_bias" not in source


def test_non_cheap_live_control_is_plain_self_use() -> None:
    result = _decision(_control())

    assert result.commands_permitted is True
    assert result.action == "self_use"
    assert result.force_charge_power_kw is None


def test_cheap_force_charge_is_retained_unchanged() -> None:
    result = _decision(
        _control(
            desired_work_mode="Force Charge",
            desired_charge_power_kw=7.0,
            operating_reason="awaiting_export_tariff_charge",
        ),
        cheap=True,
    )

    assert result.commands_permitted is True
    assert result.action == "force_charge"
    assert result.force_charge_power_kw == 7.0


def test_live_backend_contains_no_force_discharge_write_path() -> None:
    source = (KEMS / "foxess_control_backend.py").read_text(encoding="utf-8")
    live = source.split("async def async_update", 1)[1]

    assert '_entity_id(entities, "force_discharge_power")' not in live
    assert 'decision.action == "grid_bias_force_discharge"' not in live
    assert "fixed_50w" not in source
    assert "grid_bias" not in source
    assert '"normal_non_cheap_mode": "Self Use"' in source


def test_command_shadow_contains_no_operational_grid_bias() -> None:
    source = (KEMS / "kems_core" / "foxess_command_shadow.py").read_text(
        encoding="utf-8"
    )

    assert "grid_import_prevention" not in source
    assert "desired_grid_bias" not in source
    assert "FIXED_GRID_BIAS" not in source


def test_import_and_export_power_limits_remain_outside_live_writes() -> None:
    source = (KEMS / "foxess_control_backend.py").read_text(encoding="utf-8")
    live = source.split("async def async_update", 1)[1].split("payload = {", 1)[0]

    assert '_entity_id(entities, "import_power_limit")' not in live
    assert '_entity_id(entities, "export_power_limit")' not in live


def test_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.68"
    assert reason.startswith("Alpha9.68 adds date-aware electricity tariff fallbacks")
    assert "Self Use outside confirmed cheap periods" in reason
    assert "confirmed-cheap Force Charge" in reason
    assert "Min SoC-on-grid" in reason
    assert "Import Power Limit write" in reason
    assert "Export Power Limit write" in reason
