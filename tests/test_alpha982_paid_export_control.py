"""Alpha9.82 paid-export authority and safety regressions."""

from __future__ import annotations

from pathlib import Path

from kems_core import ControlState
from kems_core.control_write_authority import (
    assess_foxess_control_write_authority,
    resolve_live_min_soc_on_grid,
)

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
COORDINATOR = KEMS / "coordinator.py"
COMMISSIONING = KEMS / "commissioning.py"


def _control(**overrides: object) -> ControlState:
    values: dict[str, object] = {
        "operating_mode": "control",
        "operating_reason": "paced_export",
        "desired_work_mode": "Feed-in First",
        "desired_charge_power_kw": 0.0,
        "desired_battery_to_home_power_kw": 0.8,
        "desired_battery_export_power_kw": 5.0,
        "desired_total_discharge_power_kw": 5.8,
        "desired_min_soc_percent": 15.0,
        "desired_grid_export_allowed": True,
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
        "no_paid_export_mode": False,
        "cheap_period_confirmed": False,
        "user_commissioned": True,
        "master_control_enabled": True,
        "emergency_stop": False,
        "effective_export_limit_kw": 6.4,
    }
    args.update(overrides)
    return assess_foxess_control_write_authority(control, **args)


def test_paid_export_can_authorise_only_bounded_force_discharge() -> None:
    result = _decision(_control(desired_battery_export_power_kw=5.0))

    assert result.commands_permitted is True
    assert result.action == "force_discharge"
    assert result.force_discharge_power_kw == 5.0
    assert result.export_power_limit_kw == 6.4
    assert result.min_soc_on_grid_percent == 15.0


def test_paid_export_is_clamped_to_proven_effective_ceiling() -> None:
    result = _decision(_control(desired_battery_export_power_kw=7.0))

    assert result.commands_permitted is True
    assert result.force_discharge_power_kw == 6.4
    assert result.export_power_limit_kw == 6.4


def test_paid_export_without_a_proven_ceiling_fails_closed() -> None:
    result = _decision(
        _control(desired_battery_export_power_kw=2.0),
        effective_export_limit_kw=None,
    )

    assert result.commands_permitted is False
    assert result.action == "release"
    assert "positive proven" in result.reason


def test_no_paid_export_never_inherits_force_discharge_authority() -> None:
    result = _decision(
        _control(desired_battery_export_power_kw=2.0),
        no_paid_export_mode=True,
    )

    assert result.commands_permitted is False
    assert result.action == "release"
    assert "No-paid-export policy" in result.reason


def test_power_down_deliberate_export_remains_blocked_in_alpha982() -> None:
    result = _decision(
        _control(
            operating_reason="power_down_session",
            desired_battery_export_power_kw=2.0,
        )
    )

    assert result.commands_permitted is False
    assert result.action == "release"
    assert "Power Down deliberate export" in result.reason


def test_export_uses_15_percent_target_but_idle_self_use_returns_to_10_percent() -> (
    None
):
    export = _decision(_control(desired_min_soc_percent=15.0))
    assert export.action == "force_discharge"
    assert (
        resolve_live_min_soc_on_grid(
            export,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=10.0,
        )
        == 15.0
    )

    idle = _decision(
        _control(
            desired_work_mode="Self Use",
            desired_battery_export_power_kw=0.0,
            desired_total_discharge_power_kw=0.8,
            desired_min_soc_percent=15.0,
        )
    )
    assert idle.action == "self_use"
    assert (
        resolve_live_min_soc_on_grid(
            idle,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=10.0,
        )
        == 10.0
    )


def test_first_physical_export_is_staged_and_limit_is_verified_first() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    live = source.split("async def async_update", 1)[1]

    assert "_PAID_EXPORT_STAGE_KW = 1.0" in source
    assert "_PAID_EXPORT_PROOF_SAMPLES = 2" in source
    assert "_PAID_EXPORT_FAILURE_SAMPLES = 3" in source
    assert "requested_discharge = min(" in live
    assert "requested_discharge," in live
    export_write = live.index("export_limit_ok = await self._async_number(")
    export_verify = live.index(
        "self._async_wait_number(\n"
        "                                entities,\n"
        '                                "export_power_limit"'
    )
    discharge_write = live.index("discharge_ok = await self._async_number(")
    mode_write = live.index(
        '"Force Discharge",\n                                writes,'
    )

    assert export_write < export_verify < discharge_write < mode_write
    assert "battery-discharge and grid-export directions proven" in source


def test_paid_export_baseline_and_shutdown_restore_are_explicit() -> None:
    source = BACKEND.read_text(encoding="utf-8")

    assert "previous_force_discharge_power_kw" in source
    assert "previous_export_power_limit_w" in source
    assert "_async_complete_paid_export_baseline" in source
    assert "_async_restore_paid_export_settings" in source
    assert "restore pre-KEMS local mode, Min SoC-on-grid, Force Discharge" in source
    assert '"import_power_limit_write": "never_written_by_alpha9.82"' in source


def test_fixed_and_agile_export_use_separate_planning_authorities() -> None:
    source = COORDINATOR.read_text(encoding="utf-8")

    assert "elif tariff_type == EXPORT_TARIFF_TYPE_AGILE:" in source
    assert "Fixed export uses the normal fixed-rate KEMS simulation." in source
    assert "control_simulation = simulation" in source
    assert (
        "tariff_type == EXPORT_TARIFF_TYPE_AGILE\n"
        "                and not snapshot.saving_session_active"
    ) in source


def test_paid_tariff_requires_force_discharge_and_export_limit_bindings() -> None:
    source = COMMISSIONING.read_text(encoding="utf-8")

    assert "export_tariff_type_from_options(coordinator.entry.options)" in source
    assert (
        'control_command_keys.extend(("force_discharge_power", "export_power_limit"))'
        in source
    )
    assert "Force Discharge" in source
    assert "Export Power Limit" in source


def test_paid_export_physical_proof_is_session_scoped() -> None:
    source = BACKEND.read_text(encoding="utf-8")

    setup = source.split("async def async_setup", 1)[1].split(
        "async def _async_save", 1
    )[0]
    save = source.split("async def _async_save", 1)[1].split(
        "async def _foxess_version", 1
    )[0]
    assert "self._paid_export_live_proven = False" in setup
    assert 'data.get("paid_export_live_proven"' not in setup
    assert '"paid_export_live_proven"' not in save
    assert "if no_paid_export_mode:" in source
    assert "self._paid_export_live_proven = False" in source


def test_alpha982_release_identity_and_dormant_no_export_contract() -> None:
    import json

    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.82"
    assert reason.startswith("Alpha9.82")
    assert "1.0 kW" in reason
    assert "two low-solar samples" in reason
    assert "15% planning/export target" in reason
    assert "10% on the commissioned KH7" in reason
    assert "Power Down deliberate export is deliberately not promoted" in reason
    assert "Import Power Limit is never written" in reason
    assert "No paid export still hard-blocks deliberate Force Discharge" in reason
    assert "Today-to-Tomorrow plan discontinuity" in reason
    assert "new export writes remain dormant" in reason
