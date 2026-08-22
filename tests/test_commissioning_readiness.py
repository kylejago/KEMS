"""Regression tests for commissioning readiness and panel health."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from kems_core.commissioning_evidence import assess_foxess_telemetry_stability

ROOT = Path(__file__).parents[1]
COMMISSIONING = ROOT / "custom_components" / "kems" / "commissioning.py"
PANEL = ROOT / "custom_components" / "kems" / "panel.py"
DIAGNOSTICS = ROOT / "custom_components" / "kems" / "diagnostics.py"
SENSOR = ROOT / "custom_components" / "kems" / "sensor.py"
DASHBOARD = ROOT / "dashboards" / "kems_master_dashboard.yaml"
EVIDENCE = (
    ROOT / "custom_components" / "kems" / "kems_core" / "commissioning_evidence.py"
)


def _record(
    timestamp: datetime,
    *,
    stale_fields: tuple[str, ...] = (),
    battery_soc: float | None = 50.0,
    battery_power_kw: float | None = 1.0,
    solar_power_kw: float | None = 2.0,
    house_load_kw: float | None = 1.5,
    grid_import_kw: float | None = 0.0,
    grid_export_kw: float | None = 0.5,
):
    return SimpleNamespace(
        timestamp=timestamp,
        stale_fields=stale_fields,
        battery_soc=battery_soc,
        battery_power_kw=battery_power_kw,
        solar_power_kw=solar_power_kw,
        house_load_kw=house_load_kw,
        grid_import_kw=grid_import_kw,
        grid_export_kw=grid_export_kw,
    )


def test_commissioning_is_read_only_and_shadow_limited() -> None:
    """The readiness layer must not unlock real inverter writes."""
    content = COMMISSIONING.read_text(encoding="utf-8")
    assert '"maximum_allowed_stage": "shadow"' in content
    assert '"ready_for_control": False' in content
    assert '"real_hardware_writes": "blocked"' in content
    assert "commands_permitted" in content
    assert "Real inverter writes remain hard-blocked" in content


def test_commissioning_checks_foxess_sources_directions_and_limits() -> None:
    """Commissioning should gate on the physical KH7 data contract."""
    content = COMMISSIONING.read_text(encoding="utf-8")
    for token in (
        'FOXESS_PLATFORM = "foxess_modbus"',
        '"battery_power_direction"',
        '"grid_direction"',
        '"kh7_limits"',
        '"eps_limit"',
        '"site_import_limit"',
        '"shadow_planner"',
        '"emergency_stop"',
    ):
        assert token in content


def test_foxess_telemetry_stability_requires_sustained_complete_samples() -> None:
    """Commissioning evidence must prove continuity rather than one live reading."""
    start = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    records = [_record(start + timedelta(seconds=30 * index)) for index in range(12)]

    evidence = assess_foxess_telemetry_stability(
        records,
        expected_interval_seconds=30,
    )

    assert evidence.ready is True
    assert evidence.state == "stable"
    assert evidence.samples == 12
    assert evidence.completeness_percent == 100.0
    assert evidence.maximum_gap_seconds == 30.0
    assert evidence.allowed_gap_seconds == 90.0


def test_foxess_telemetry_stability_fails_closed_on_missing_or_stale_data() -> None:
    """Missing/stale physical signals must prevent commissioning evidence passing."""
    start = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    records = [_record(start + timedelta(seconds=30 * index)) for index in range(12)]
    records[-1] = _record(
        records[-1].timestamp,
        stale_fields=("battery_power_kw",),
        grid_export_kw=None,
    )

    evidence = assess_foxess_telemetry_stability(
        records,
        expected_interval_seconds=30,
    )

    assert evidence.ready is False
    assert evidence.state == "incomplete"
    assert evidence.completeness_percent < 95.0
    assert evidence.missing_fields == ("grid_export_kw",)
    assert evidence.stale_fields == ("battery_power_kw",)


def test_foxess_telemetry_stability_rejects_large_update_gaps() -> None:
    """A stalled Modbus feed must remain commissioning evidence, not control proof."""
    start = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    records = [_record(start + timedelta(seconds=30 * index)) for index in range(12)]
    records[-1] = _record(records[-2].timestamp + timedelta(seconds=120))

    evidence = assess_foxess_telemetry_stability(
        records,
        expected_interval_seconds=30,
    )

    assert evidence.ready is False
    assert evidence.state == "unstable_interval"
    assert evidence.maximum_gap_seconds == 120.0


def test_foxess_telemetry_evidence_has_no_hardware_write_path() -> None:
    """The evidence primitive must stay Home Assistant-independent and read-only."""
    content = EVIDENCE.read_text(encoding="utf-8")
    assert "homeassistant" not in content.lower()
    assert ".services.async_call(" not in content
    assert "commands_permitted = True" not in content
    assert "safe_to_write_hardware = True" not in content


def test_commissioning_entities_and_dashboard_are_registered() -> None:
    """Home Assistant should expose one clear commissioning operating view."""
    sensor = SENSOR.read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")
    assert "build_commissioning_entities" in sensor
    assert "sensor.kems_commissioning_readiness" in dashboard
    assert "sensor.kems_panel_management_status" in dashboard
    assert "sensor.kems_panel_firmware_version" in dashboard
    assert "path: commissioning" in dashboard
    assert "Shadow command" in dashboard


def test_panel_health_is_persistent_and_diagnostic_visible() -> None:
    """OTA proof should survive a later Home Assistant restart and diagnostics."""
    panel = PANEL.read_text(encoding="utf-8")
    diagnostics = DIAGNOSTICS.read_text(encoding="utf-8")
    assert 'PANEL_HEALTH_STORAGE_KEY = "kems.panel_health"' in panel
    assert "Store(" in panel
    assert "last_ota_attempt" in panel
    assert "last_ota_success" in panel
    assert "esphome_job_id" in panel
    assert '"commissioning": build_commissioning_snapshot' in diagnostics
    assert '"panel_health": panel_health_snapshot' in diagnostics
