"""Regression coverage for alpha7.20 pre-install evidence and readiness split."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
PREINSTALL = ROOT / "custom_components" / "kems" / "agile_alpha720_preinstall.py"
DASHBOARD = ROOT / "custom_components" / "kems" / "agile_alpha720_dashboard.py"
RUNTIME = ROOT / "custom_components" / "kems" / "agile_smart_export_runtime.py"
DIAGNOSTICS = ROOT / "custom_components" / "kems" / "diagnostics.py"


def test_preinstall_evidence_uses_historical_gti_and_proposal_geometry() -> None:
    source = PREINSTALL.read_text(encoding="utf-8")
    assert "https://archive-api.open-meteo.com/v1/archive" in source
    assert '"hourly": "global_tilted_irradiance"' in source
    assert "FOXHOLE_PROPOSAL_PROFILE.arrays" in source
    assert '"actual_solar_generation": False' in source
    assert '"comparison_class": "hypothetical_preinstall_evidence"' in source
    assert '"method": "ha_house_load+open_meteo_proposal_solar"' in source


def test_preinstall_evidence_preserves_native_and_direct_history_priority() -> None:
    source = PREINSTALL.read_text(encoding="utf-8")
    assert "baseline = await original_records(" in source
    assert "backfill._merge_native_and_backfill(baseline, list(evidence_records))" in source
    assert '"native_kems_days": len(native_days)' in source
    assert '"proposal_reconstructed_days": len(reconstructed_days)' in source
    assert '"proposal_solar_reconstruction_used": True' in source
    assert "days(evidence_records) - baseline_days" in source


def test_preinstall_reconstruction_is_daily_cached_and_fail_safe() -> None:
    source = PREINSTALL.read_text(encoding="utf-8")
    assert '_kems_alpha720_evidence_day", None) != local_day' in source
    assert "network evidence must never break KEMS" in source
    assert "historical irradiance fetch failed" in source
    assert "recorder.get_statistics is unavailable" in source


def test_shadow_diagnostics_are_exported_with_split_readiness() -> None:
    source = DIAGNOSTICS.read_text(encoding="utf-8")
    assert '"shadow_validation": shadow_validation' in source
    assert '"shadow_readiness": shadow_readiness' in source
    assert '"digital_twin_ready": bool(shadow_validation.get("ready_for_shadow"))' in source
    assert '"hardware_shadow_ready": bool(commissioning.get("ready_for_shadow"))' in source
    assert '"real_hardware_writes"' in source


def test_alpha720_dashboard_distinguishes_digital_twin_and_hardware_shadow() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "Pre-install historical evidence" in source
    assert "Historical proposal-solar reconstruction" in source
    assert "Digital-twin shadow readiness" in source
    assert "Hardware shadow readiness" in source
    assert "Shadow readiness — digital twin vs hardware" in source
    assert '_inject_after_cards(content, "history", _HISTORY_CARD)' in source
    assert '_inject_after_cards(content, "control", _CONTROL_CARD)' in source


def test_alpha720_runtime_keeps_alpha719_compositor_order() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert (
        "install_alpha719_validation_patch()\n"
        "install_dashboard_consolidation()\n"
        "install_alpha719_dashboard_patch()"
    ) in source
    assert (
        "install_alpha719_dashboard_patch()\n"
        "install_alpha720_preinstall_patch()\n"
        "install_alpha720_dashboard_patch()"
    ) in source


def test_alpha720_introduces_no_hardware_write_path() -> None:
    source = PREINSTALL.read_text(encoding="utf-8").lower()
    dashboard = DASHBOARD.read_text(encoding="utf-8").lower()
    forbidden = (
        "foxess_modbus.write",
        'hass.services.async_call("foxess',
        "hass.services.async_call('foxess',",
        "commands_permitted = true",
    )
    assert not any(value in source for value in forbidden)
    assert "neither stage sends inverter writes" in dashboard
