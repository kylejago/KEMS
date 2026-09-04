"""Alpha8.79 FoxESS command-shadow translation regression tests."""

from __future__ import annotations

import json
from pathlib import Path

from kems_core.foxess_command_shadow import (
    DIFF,
    MATCH,
    PASS,
    WAIT,
    build_foxess_command_shadow,
)
from kems_core.models import ControlState

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
ADAPTER = INTEGRATION / "foxess_command_shadow.py"
DIAGNOSTICS = INTEGRATION / "diagnostics.py"
CONTRACT = INTEGRATION / "foxess_modbus_contract.py"
MANIFEST = INTEGRATION / "manifest.json"


def _control(**overrides: object) -> ControlState:
    values: dict[str, object] = {
        "operating_reason": "normal",
        "desired_work_mode": "Self Use",
        "desired_min_soc_percent": 10.0,
        "desired_grid_export_allowed": True,
        "data_fresh": True,
        "plan_safe": True,
    }
    values.update(overrides)
    return ControlState(**values)


def test_force_charge_maps_to_reviewed_remote_control_surface() -> None:
    """Force Charge should map to FoxESS's virtual work mode and native kW."""
    result = build_foxess_command_shadow(
        _control(
            desired_work_mode="Force Charge",
            desired_charge_power_kw=4.2,
            desired_grid_export_allowed=False,
        ),
        {
            "work_mode": "Force Charge",
            "force_charge_power_kw": 4.2,
            "min_soc_on_grid_percent": 10,
            "export_power_limit_w": 0,
        },
    )

    proposed = result["proposed_foxess_command"]
    assert result["translation_status"] == PASS
    assert result["parity_result"] == MATCH
    assert proposed["work_mode"] == "Force Charge"
    assert proposed["force_charge_power_kw"] == 4.2
    assert proposed["force_discharge_power_kw"] is None
    assert proposed["export_power_limit_w"] == 0


def test_force_discharge_uses_deliberate_export_not_total_battery_output() -> None:
    """House support must never inflate FoxESS's deliberate grid-feed setpoint."""
    result = build_foxess_command_shadow(
        _control(
            desired_work_mode="Feed-in First",
            desired_battery_to_home_power_kw=2.0,
            desired_battery_export_power_kw=3.0,
            desired_total_discharge_power_kw=5.0,
        )
    )

    proposed = result["proposed_foxess_command"]
    assert result["translation_status"] == PASS
    assert result["parity_result"] == WAIT
    assert proposed["work_mode"] == "Force Discharge"
    assert proposed["force_discharge_power_kw"] == 3.0
    assert proposed["force_discharge_power_kw"] != 5.0


def test_read_only_parity_reports_difference_without_authorising_commands() -> None:
    """Observed hardware disagreement is evidence, never a write trigger."""
    result = build_foxess_command_shadow(
        _control(desired_work_mode="Self Use"),
        {
            "work_mode": "Feed-in First",
            "min_soc_on_grid_percent": 10,
            "export_power_limit_w": 7000,
        },
    )

    assert result["parity_result"] == DIFF
    assert result["parity"]["work_mode"]["status"] == DIFF
    assert result["commands_permitted"] is False
    assert result["real_hardware_writes"] == "blocked"
    assert result["maximum_allowed_stage"] == "shadow"


def test_stale_unsafe_and_island_decisions_fail_closed() -> None:
    """Untrusted or unresolved decisions must remain WAIT."""
    cases = (
        _control(data_fresh=False),
        _control(plan_safe=False),
        _control(
            island_mode_active=True,
            desired_work_mode="Self Use / EPS",
        ),
        _control(
            operating_reason="emergency_stop",
            desired_work_mode="Stop KEMS writes",
        ),
    )

    for control in cases:
        result = build_foxess_command_shadow(control)
        assert result["translation_status"] == WAIT
        assert result["parity_result"] == WAIT
        assert result["commands_permitted"] is False


def test_on_grid_reserve_and_kh133_export_limit_use_reviewed_units() -> None:
    """KEMS reserve maps to Min SoC (On Grid); KH_133 export limit remains W."""
    result = build_foxess_command_shadow(
        _control(
            desired_min_soc_percent=17.0,
            desired_grid_export_allowed=True,
        ),
        {
            "work_mode": "Self Use",
            "min_soc_on_grid_percent": 17,
            "export_power_limit_w": 7000,
        },
        export_limit_kw=7.0,
    )

    proposed = result["proposed_foxess_command"]
    assert proposed["min_soc_on_grid_percent"] == 17.0
    assert proposed["export_power_limit_w"] == 7000
    assert result["parity_result"] == MATCH


def test_ha_adapter_is_device_scoped_and_has_no_write_surface() -> None:
    """The HA layer must only read the authoritative FoxESS device."""
    source = ADAPTER.read_text(encoding="utf-8")

    assert "_telemetry_device_ids" in source
    assert "_command_candidates" in source
    assert "device_id" in source
    assert 'FOXESS_PLATFORM = "foxess_modbus"' in source
    assert '"min_soc_on_grid"' in source
    assert '"force_charge_power"' in source
    assert '"force_discharge_power"' in source
    for forbidden in (
        ".services.async_call(",
        "async_select_option(",
        "async_set_native_value(",
        "write_register(",
        "write_registers(",
        "ModbusClient",
    ):
        assert forbidden not in source


def test_diagnostics_contract_and_release_identity_expose_shadow_only_scope() -> None:
    """Alpha8.79 should be visible while the hardware-write boundary stays frozen."""
    diagnostics = DIAGNOSTICS.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert (
        '"foxess_command_shadow": build_foxess_command_shadow_snapshot' in diagnostics
    )
    assert '"force_charge_power"' in contract
    assert '"force_discharge_power"' in contract
    assert '"writes_permitted": False' in contract
    assert '"hardware_writes": "blocked"' in contract
    assert manifest["version"] == "0.8.0-alpha8.79"
