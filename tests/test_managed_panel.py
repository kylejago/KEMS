"""Tests for the HACS-installed managed KEMS 16x16 ESPHome panel."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGED = ROOT / "custom_components" / "kems" / "kems16x16.yaml"


def test_managed_panel_keeps_known_working_hardware_and_alpha7_modes() -> None:
    """The shipped panel must retain the proven hardware/layout contract."""
    assert PACKAGED.exists()
    content = PACKAGED.read_text(encoding="utf-8")
    assert content.startswith("# KEMS-MANAGED-ESPHOME-PANEL")
    assert "led_pin: GPIO21" in content
    assert "platform: esp32_rmt_led_strip" in content
    assert "num_leds: 256" in content
    assert "rgb_order: GRB" in content
    assert "int mx = 15 - x;" in content
    assert 'display_mode == "Full KEMS Forecast"' in content
    assert "sensor.kems_compare_full_kems_forecast_cost_today" in content
    assert "sensor.kems_compare_full_kems_forecast_flow_now" in content


def test_managed_panel_exposes_agile_smart_export_simulation() -> None:
    """The panel should render Agile through the same compact scenario protocol."""
    content = PACKAGED.read_text(encoding="utf-8")
    assert 'panel_config_version: "0.7.0-alpha7-panel4"' in content
    assert '- "Agile Smart Export"' in content
    assert 'display_mode == "Agile Smart Export"' in content
    assert "selected_scenario = 7;" in content
    assert "sensor.kems_agile_smart_export_cost_today" in content
    assert "sensor.kems_agile_smart_export_flow_now" in content
    assert "id: ha_agile_cost" in content
    assert "id: ha_agile_flow" in content
    assert "float scenario_cost[8]" in content
    assert "flow_state = &id(ha_agile_flow).state;" in content
    assert '"SE=%f,GB=%f,BH=%f,BE=%f,SOC=%f"' in content


def test_kems_startup_refreshes_only_an_existing_panel_config() -> None:
    """Existing kems16x16.yaml opts in; KEMS must not create it for everyone."""
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    assert 'MANAGED_PANEL_FILENAME = "kems16x16.yaml"' in sync
    assert 'hass.config.path("esphome", MANAGED_PANEL_FILENAME)' in sync
    assert "if not target.exists():" in sync
    assert "_sync_existing_panel_file" in sync
    assert "os.replace(temporary, target)" in sync


def test_adopted_managed_panel_queues_automatic_esphome_ota() -> None:
    """Only a previously managed panel should automatically compile and flash."""
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    assert 'MANAGED_PANEL_HEADER = b"# KEMS-MANAGED-ESPHOME-PANEL"' in sync
    assert "_panel_is_kems_managed" in sync
    assert "panel_changed and panel_was_managed" in sync
    assert '"command": "firmware/install"' in sync
    assert '"configuration": MANAGED_PANEL_FILENAME' in sync
    assert '"port": "OTA"' in sync
    assert "SUPERVISOR_TOKEN" in sync
    assert "ws://127.0.0.1:{ingress_port}/ws" in sync
    assert "async_auto_install_managed_panel" in sync


def test_first_managed_adoption_still_requires_one_manual_flash() -> None:
    """A pre-managed local file must not be automatically flashed on adoption."""
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    assert "elif panel_changed:" in sync
    assert "first managed" in sync
    assert "subsequent managed" in sync


def test_managed_panel_has_startup_and_ota_completion_animation() -> None:
    """A managed panel should visibly show boot, waiting, success and fault states."""
    content = PACKAGED.read_text(encoding="utf-8")
    assert "panel_boot_started_ms" in content
    assert "panel_boot_ha_seen" in content
    assert "draw_boot_frame" in content
    assert "draw_waiting_frame" in content
    assert "draw_success_frame" in content
    assert "draw_error_frame" in content
    assert "boot_elapsed < 3800" in content
    assert "boot_elapsed < 20000" in content
    assert "ha_kems_status).has_state()" in content


def test_managed_panel_reports_firmware_for_ota_verification() -> None:
    """The ESP32 must report the exact managed config version after OTA."""
    content = PACKAGED.read_text(encoding="utf-8")
    assert 'panel_config_version: "0.7.0-alpha7-panel4"' in content
    assert 'name: "Panel Firmware Version"' in content
    assert "id: panel_firmware_version" in content
    assert 'return {"${panel_config_version}"};' in content


def test_managed_panel_ota_tracks_queue_and_reconnect_health() -> None:
    """KEMS should distinguish queued OTA from verified firmware success."""
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    panel_health = (ROOT / "custom_components" / "kems" / "panel.py").read_text(
        encoding="utf-8"
    )
    assert 'last_ota_result="queued"' in sync
    assert "async_verify_panel_firmware" in sync
    assert 'PANEL_CONFIG_VERSION = "0.7.0-alpha7-panel4"' in panel_health
    assert 'status="Success"' in panel_health
