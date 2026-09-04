"""Tests for the HACS-installed managed KEMS 16x16 ESPHome panel."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGED = ROOT / "custom_components" / "kems" / "kems16x16.yaml"


def test_managed_panel_keeps_known_working_hardware_and_simple_product_modes() -> None:
    """The shipped panel must retain hardware while exposing only four products."""
    assert PACKAGED.exists()
    content = PACKAGED.read_text(encoding="utf-8")
    assert content.startswith("# KEMS-MANAGED-ESPHOME-PANEL")
    assert "led_pin: GPIO21" in content
    assert "platform: esp32_rmt_led_strip" in content
    assert "num_leds: 256" in content
    assert "rgb_order: GRB" in content
    assert "int mx = 15 - x;" in content
    assert 'initial_option: "Live Data"' in content
    for option in ("Live Data", "Battery & Solar", "Full KEMS", "Full KEMS Agile"):
        assert f'- "{option}"' in content
    for obsolete in (
        "No system",
        "Solar only",
        "Solar + battery",
        "KEMS no-export",
        "Full KEMS Forecast",
        "Agile Smart Export",
        "Full Island Mode",
    ):
        assert f'- "{obsolete}"' not in content


def test_alpha8_panel_uses_current_agile_routing_snapshot_feed() -> None:
    """Full KEMS Agile keeps the final coherent routing feed in Alpha8."""
    content = PACKAGED.read_text(encoding="utf-8")
    assert 'panel_config_version: "0.8.0-alpha8-panel.1"' in content
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    assert "PANEL6_VERSION_LINE" not in sync
    assert "PANEL7_VERSION_LINE" not in sync
    assert "return PACKAGED_PANEL_PATH.read_bytes()" in sync
    assert 'display_mode == "Full KEMS Agile"' in content
    assert "selected_scenario = 7;" in content
    assert "scenario_agile_flow: sensor.kems_panel_full_kems_agile_flow_now" in content
    assert "id: ha_agile_flow" in content
    assert "flow_state = &id(ha_agile_flow).state;" in content
    assert '"SE=%f,GB=%f,BH=%f,BE=%f,SOC=%f"' in content


def test_panel_subscribes_only_to_reachable_scenario_feeds() -> None:
    """The four display modes must not subscribe to retired scenario entities."""
    content = PACKAGED.read_text(encoding="utf-8")
    for active in (
        "scenario_solar_battery: sensor.kems_compare_solar_and_battery_cost_today",
        "scenario_full_kems_forecast: sensor.kems_compare_full_kems_forecast_cost_today",
        "scenario_agile: sensor.kems_agile_smart_export_cost_today",
        "scenario_solar_battery_flow: sensor.kems_compare_solar_and_battery_flow_now",
        "scenario_full_kems_forecast_flow: sensor.kems_compare_full_kems_forecast_flow_now",
        "scenario_agile_flow: sensor.kems_panel_full_kems_agile_flow_now",
    ):
        assert active in content
    for retired in (
        "scenario_no_system",
        "scenario_solar_only",
        "scenario_kems_no_export",
        "scenario_full_kems:",
        "scenario_no_system_flow",
        "scenario_solar_only_flow",
        "scenario_kems_no_export_flow",
        "scenario_full_kems_flow",
        "scenario_full_island_flow",
        "ha_no_system_cost",
        "ha_solar_only_cost",
        "ha_kems_no_export_cost",
        "ha_full_kems_cost",
        "ha_no_system_flow",
        "ha_solar_only_flow",
        "ha_kems_no_export_flow",
        "ha_full_kems_flow",
        "ha_full_island_flow",
        "scenario_cost[8]",
    ):
        assert retired not in content
    assert "selected_scenario = 2;" in content
    assert "selected_scenario = 5;" in content
    assert "selected_scenario = 7;" in content


def test_panel_routes_battery_export_visually_through_house_bus() -> None:
    """Battery export must light the battery-to-hub connector without falsifying BH."""
    content = PACKAGED.read_text(encoding="utf-8")
    assert "battery_home_power > POWER_DEADBAND_KW" in content
    assert "battery_export_power > POWER_DEADBAND_KW" in content
    assert "const bool battery_to_bus_active =" in content
    assert "battery_discharging ||\n        export_from_battery;" in content
    assert "const bool source_battery_active = battery_to_bus_active;" in content
    assert "else if (battery_to_bus_active)" in content
    assert (
        "battery_discharging =\n          battery_home_power > POWER_DEADBAND_KW;"
        in content
    )


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


def test_legacy_kems_panel_is_migrated_without_another_manual_flash() -> None:
    """A recognisable pre-header KEMS panel is safe to enter the managed OTA path."""
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    assert "LEGACY_PANEL_MARKERS" in sync
    assert 'b"name: kems16x16"' in sync
    assert "b'name: \"Panel Firmware Version\"'" in sync
    assert 'b"id: panel_firmware_version"' in sync
    assert "return all(marker in content for marker in LEGACY_PANEL_MARKERS)" in sync


def test_first_managed_adoption_still_requires_one_manual_flash() -> None:
    """A non-KEMS local file must not be automatically flashed on adoption."""
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


def test_managed_panel_reports_alpha8_firmware_for_ota_verification() -> None:
    """The generated ESP32 config must report the Alpha8 panel.1 target after OTA."""
    content = PACKAGED.read_text(encoding="utf-8")
    assert 'name: "Panel Firmware Version"' in content
    assert "id: panel_firmware_version" in content
    assert 'return {"${panel_config_version}"};' in content
    panel_health = (ROOT / "custom_components" / "kems" / "panel.py").read_text(
        encoding="utf-8"
    )
    assert 'PANEL_CONFIG_VERSION = "0.8.0-alpha8-panel.1"' in panel_health


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
    assert 'PANEL_CONFIG_VERSION = "0.8.0-alpha8-panel.1"' in panel_health
    assert 'status="Success"' in panel_health
