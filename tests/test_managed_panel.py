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
    assert 'ws://127.0.0.1:{ingress_port}/ws' in sync
    assert "async_auto_install_managed_panel" in sync


def test_first_managed_adoption_still_requires_one_manual_flash() -> None:
    """A pre-managed local file must not be automatically flashed on adoption."""
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    assert "elif panel_changed:" in sync
    assert "first managed" in sync
    assert "subsequent managed" in sync
