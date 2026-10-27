"""Alpha9.151: panel display mode must never alter KEMS control."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PANEL = KEMS / "kems16x16.yaml"
DASH = ROOT / "dashboards" / "kems_master_dashboard.yaml"


def test_panel_exposes_exactly_live_data_and_full_kems_agile_display():
    source = PANEL.read_text()
    options = source.split('name: "Display Mode"', 1)[1].split(
        "  - platform: template", 1
    )[0]
    assert re.findall(r'^      - "([^"]+)"$', options, flags=re.MULTILINE) == [
        "Live Data",
        "KEMS",
    ]
    assert 'const bool live_mode = display_mode != "KEMS";' in source
    assert "const int selected_scenario = live_mode ? -1 : 7;" in source
    assert "Battery & Solar" not in source
    assert "Full KEMS Agile" in source  # Alias documented, no option
    assert "restore_value: true" in options
    assert 'initial_option: "Live Data"' in options


def test_live_faceplate_uses_real_home_assistant_solar_house_and_soc():
    source = PANEL.read_text()
    assert "live_solar_power: sensor.kems_solar_power" in source
    assert "live_house_load: sensor.kems_house_load" in source
    assert "live_battery_soc: sensor.kems_battery_state_of_charge" in source
    assert "live_grid_export: sensor.kems_grid_export" in source
    assert "live_grid_import: sensor.kems_grid_import" in source
    assert "live_house_load_kw" not in source  # Not virtual comparison
    assert "solar_producing =" in source
    assert "id(ha_live_solar_power).state" in source
    assert "id(ha_live_house_load).state" in source
    assert "battery_charge_from_solar =" in source
    assert "battery_charging && solar_producing" in source
    assert "        solar_producing = false;\n        solar_to_home_active = false;" not in source
    assert "id(ha_live_battery_soc).state" in source
    assert "scenario_soc >= 0.0f" in source  # KEMS face remains separate


def test_schedule_has_adjustable_local_time_and_safe_defaults():
    source = PANEL.read_text()
    assert "timezone: Europe/London" in source
    assert "platform: homeassistant" in source
    assert "interval: 10s" in source
    assert "if (enabled && now.is_valid())" in source
    assert "if (start_of_day < end_of_day)" in source
    assert "else if (start_of_day > end_of_day)" in source
    assert "id(panel_schedule_dimmed)" in source
    assert "id(panel_saved_brightness)" in source
    assert "call.set_brightness(id(panel_saved_brightness))" in source
    assert 'initial_option: "06:00"' in source
    assert 'initial_option: "22:00"' in source
    assert "restore_mode: RESTORE_DEFAULT_ON" in source
    assert "start_of_day == end_of_day" not in source  # always on
    assert source.count('      - "23:30"') == 2


def test_panel_window_covers_day_and_overnight_without_hardware_changes():
    # These conditions mirror the strictly local, display-only schedule.
    def active(start: int, end: int, minute: int) -> bool:
        if start < end:
            return start <= minute < end
        if start > end:
            return minute >= start or minute < end
        return True

    assert not active(360, 1320, 359)
    assert active(360, 1320, 360)
    assert active(360, 1320, 1319)
    assert not active(360, 1320, 1320)
    assert active(1320, 360, 1439)
    assert active(1320, 360, 0)
    assert not active(1320, 360, 720)
    assert all(active(0, 0, x) for x in (0, 360, 1439))
    panel = PANEL.read_text()
    assert "async_set_runtime_option" not in panel
    assert "CONF_OPERATING_MODE" not in panel
    assert "foxess" not in panel.casefold()


def test_system_page_controls_panel_only_and_keeps_kems_control():
    dashboard = DASH.read_text()
    assert dashboard == (KEMS / "kems_master_dashboard.yaml").read_text()
    system_page = dashboard.split("  - title: System", 1)[1]
    for entity in (
        "select.kems16x16_display_mode",
        "switch.kems16x16_panel_automatic_schedule",
        "select.kems16x16_panel_on_time",
        "select.kems16x16_panel_off_time",
    ):
        assert entity in system_page
    assert "Product = **KEMS**" in system_page
    assert "Mode = **Control**" in system_page
    assert "Europe/London" in system_page


def test_manifest_panel_release_and_existing_web_contract():
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    assert manifest["version"] == "0.9.0-alpha9.151"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.4"
    assert bundle["components"]["property_web"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["pi_agent"]["version"] == "0.9.0-alpha9-web.0"
    assert (
        'PANEL_CONFIG_VERSION = "0.9.0-alpha9-panel.4"'
        in (KEMS / "panel.py").read_text()
    )
    assert 'panel_config_version: "0.9.0-alpha9-panel.4"' in PANEL.read_text()
    assert bundle["maintenance"]["reason"].startswith("Alpha9.151:")
