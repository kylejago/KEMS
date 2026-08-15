from pathlib import Path

ROOT = Path(__file__).parents[1]


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Missing patch anchor for {label}")
    return text.replace(old, new, 1)


# Register the three commissioning/panel sensors without disturbing the large
# existing sensor-description table.
sensor_path = ROOT / "custom_components/kems/sensor.py"
sensor = sensor_path.read_text(encoding="utf-8")
sensor = replace_once(
    sensor,
    "from .const import (\n",
    "from .commissioning import build_commissioning_entities\nfrom .const import (\n",
    label="sensor commissioning import",
)
sensor = replace_once(
    sensor,
    "    entities.append(KEMSSourceValidationSensor(coordinator))\n",
    "    entities.extend(build_commissioning_entities(hass, coordinator))\n"
    "    entities.append(KEMSSourceValidationSensor(coordinator))\n",
    label="sensor commissioning entities",
)
sensor_path.write_text(sensor, encoding="utf-8")


# The deliberate managed-panel change in this PR is the first live end-to-end
# test of the automatic compile/OTA path. The ESP32 publishes the exact version
# back to HA so KEMS can verify that the new firmware actually reconnected.
panel_path = ROOT / "custom_components/kems/kems16x16.yaml"
panel = panel_path.read_text(encoding="utf-8")
panel = replace_once(
    panel,
    "  led_pin: GPIO21\n",
    "  led_pin: GPIO21\n  panel_config_version: \"0.7.0-alpha7-panel2\"\n",
    label="panel version substitution",
)
panel = replace_once(
    panel,
    "text_sensor:\n  - platform: homeassistant\n    id: ha_kems_status\n",
    "text_sensor:\n"
    "  - platform: template\n"
    "    id: panel_firmware_version\n"
    "    name: \"Panel Firmware Version\"\n"
    "    icon: mdi:chip\n"
    "    update_interval: 60s\n"
    "    lambda: |-\n"
    "      return {\"${panel_config_version}\"};\n"
    "  - platform: homeassistant\n"
    "    id: ha_kems_status\n",
    label="panel firmware text sensor",
)
panel_path.write_text(panel, encoding="utf-8")


COMMISSIONING_VIEW = '''  - title: Commissioning\n    path: commissioning\n    icon: mdi:clipboard-check-multiple-outline\n    cards:\n      - type: markdown\n        content: |\n          # KEMS Commissioning Readiness\n          This page is deliberately read-only. It verifies the commissioned FoxESS mappings, flow directions, hardware limits, shadow plan and managed panel before KEMS is allowed to progress beyond the control lab.\n\n          **Readiness:** **{{ states('sensor.kems_commissioning_readiness') }}**  \n          **Maximum allowed stage in this build:** {{ state_attr('sensor.kems_commissioning_readiness', 'maximum_allowed_stage') or 'shadow' }}  \n          **Real hardware writes:** **{{ state_attr('sensor.kems_commissioning_readiness', 'real_hardware_writes') or 'blocked' }}**\n\n      - type: grid\n        columns: 4\n        square: false\n        cards:\n          - type: tile\n            entity: sensor.kems_commissioning_readiness\n            name: Commissioning readiness\n          - type: tile\n            entity: sensor.kems_panel_management_status\n            name: Panel / OTA\n          - type: tile\n            entity: sensor.kems_panel_firmware_version\n            name: Panel firmware\n          - type: tile\n            entity: sensor.kems_control_preflight\n            name: Control preflight\n\n      - type: markdown\n        title: Commissioning checklist\n        content: |\n          {% set checks = state_attr('sensor.kems_commissioning_readiness', 'checks') or [] %}\n          | Check | Status | Detail |\n          |---|:---:|---|\n          {% for item in checks %}\n          | {{ item.get('label', item.get('key', '—')) }} | **{{ item.get('status', '—') }}** | {{ item.get('detail', '—') }} |\n          {% endfor %}\n\n          **PASS:** {{ state_attr('sensor.kems_commissioning_readiness', 'pass_count') or 0 }} · **WAIT:** {{ state_attr('sensor.kems_commissioning_readiness', 'wait_count') or 0 }} · **FAIL:** {{ state_attr('sensor.kems_commissioning_readiness', 'fail_count') or 0 }}\n\n      - type: grid\n        columns: 2\n        square: false\n        cards:\n          - type: markdown\n            title: FoxESS discovery / mappings\n            content: |\n              {% set mappings = state_attr('sensor.kems_commissioning_readiness', 'foxess_mappings') or {} %}\n              **Available FoxESS Modbus entities:** {{ state_attr('sensor.kems_commissioning_readiness', 'foxess_registered_entity_count') or 0 }}\n\n              | KEMS source | FoxESS entity |\n              |---|---|\n              {% if mappings %}\n              {% for key, entity in mappings.items() | sort %}\n              | `{{ key }}` | `{{ entity }}` |\n              {% endfor %}\n              {% else %}\n              | — | Waiting for FoxESS commissioning |\n              {% endif %}\n          - type: markdown\n            title: Battery direction verification\n            content: |\n              **Configured positive power means discharge:** {{ state_attr('sensor.kems_commissioning_readiness', 'configured_battery_power_positive_is_discharge') }}  \n              **Detected positive power means discharge:** {{ state_attr('sensor.kems_commissioning_readiness', 'detected_battery_power_positive_is_discharge') }}  \n              **Evidence samples:** {{ state_attr('sensor.kems_commissioning_readiness', 'battery_direction_evidence_samples') or 0 }}  \n              **Confidence:** {{ state_attr('sensor.kems_commissioning_readiness', 'battery_direction_confidence_percent') or 0 }}%\n\n              KEMS learns this from real SOC movement while battery power is above the verification threshold. A mismatch blocks progression to shadow readiness.\n\n      - type: grid\n        columns: 3\n        square: false\n        cards:\n          - type: tile\n            entity: sensor.kems_house_load\n            name: FoxESS / fallback house load\n          - type: tile\n            entity: sensor.kems_solar_power\n            name: Solar power\n          - type: tile\n            entity: sensor.kems_battery_state_of_charge\n            name: Battery SOC\n          - type: tile\n            entity: sensor.kems_battery_power\n            name: Battery power\n          - type: tile\n            entity: sensor.kems_grid_import\n            name: Grid import\n          - type: tile\n            entity: sensor.kems_grid_export\n            name: Grid export\n\n      - type: grid\n        columns: 2\n        square: false\n        cards:\n          - type: entities\n            title: Shadow command — what KEMS would send\n            show_header_toggle: false\n            entities:\n              - sensor.kems_operating_mode\n              - sensor.kems_control_operating_reason\n              - sensor.kems_desired_inverter_work_mode\n              - sensor.kems_desired_battery_charge_power\n              - sensor.kems_desired_battery_to_home_power\n              - sensor.kems_desired_battery_export_power\n              - sensor.kems_desired_total_battery_discharge_power\n              - sensor.kems_desired_minimum_soc\n              - sensor.kems_control_next_action\n              - binary_sensor.kems_control_plan_safe\n              - binary_sensor.kems_control_data_fresh\n              - binary_sensor.kems_control_commands_permitted\n          - type: entities\n            title: Commissioned hardware limits\n            show_header_toggle: false\n            entities:\n              - sensor.kems_kh7_inverter_limit\n              - sensor.kems_kh7_battery_charge_limit\n              - sensor.kems_kh7_battery_discharge_limit\n              - sensor.kems_eps_output_limit\n              - sensor.kems_configured_site_import_limit\n              - sensor.kems_site_import_headroom\n              - sensor.kems_kh7_output_headroom\n\n      - type: markdown\n        title: Managed panel / automatic OTA proof\n        content: |\n          {% set p = state_attr('sensor.kems_panel_management_status', 'expected_version') %}\n          | Panel health | Value |\n          |---|---|\n          | Status | **{{ states('sensor.kems_panel_management_status') }}** |\n          | Managed by KEMS | {{ state_attr('sensor.kems_panel_management_status', 'managed') }} |\n          | Automatic OTA armed | {{ state_attr('sensor.kems_panel_management_status', 'automatic_ota_armed') }} |\n          | Expected firmware | {{ p or '—' }} |\n          | Reported firmware | {{ state_attr('sensor.kems_panel_management_status', 'reported_version') or '—' }} |\n          | Last config sync | {{ state_attr('sensor.kems_panel_management_status', 'last_config_sync') or '—' }} |\n          | Last OTA attempt | {{ state_attr('sensor.kems_panel_management_status', 'last_ota_attempt') or '—' }} |\n          | Last OTA success | {{ state_attr('sensor.kems_panel_management_status', 'last_ota_success') or '—' }} |\n          | ESPHome job ID | {{ state_attr('sensor.kems_panel_management_status', 'esphome_job_id') or '—' }} |\n          | Last OTA result | {{ state_attr('sensor.kems_panel_management_status', 'last_ota_result') or '—' }} |\n          | Last error | {{ state_attr('sensor.kems_panel_management_status', 'last_error') or 'None' }} |\n\n'''

for dashboard_path in (
    ROOT / "dashboards/kems_master_dashboard.yaml",
    ROOT / "custom_components/kems/kems_master_dashboard.yaml",
):
    dashboard = dashboard_path.read_text(encoding="utf-8")
    if "    path: commissioning\n" not in dashboard:
        anchor = "  - title: Control & EPS\n    path: control-eps\n"
        if anchor not in dashboard:
            raise RuntimeError(f"Missing dashboard commissioning anchor in {dashboard_path}")
        dashboard = dashboard.replace(anchor, COMMISSIONING_VIEW + anchor, 1)
    dashboard_path.write_text(dashboard, encoding="utf-8")


# Keep the managed dashboard regression test aware of the new view.
dashboard_test_path = ROOT / "tests/test_managed_dashboard.py"
dashboard_test = dashboard_test_path.read_text(encoding="utf-8")
dashboard_test = replace_once(
    dashboard_test,
    '        "full-kems-forecast",\n        "compare",\n',
    '        "full-kems-forecast",\n        "commissioning",\n        "compare",\n',
    label="managed dashboard commissioning path",
)
dashboard_test_path.write_text(dashboard_test, encoding="utf-8")


# Extend the panel regression test with the new end-to-end firmware proof.
panel_test_path = ROOT / "tests/test_managed_panel.py"
panel_test = panel_test_path.read_text(encoding="utf-8")
if "test_managed_panel_reports_firmware_for_ota_verification" not in panel_test:
    panel_test += '''\n\ndef test_managed_panel_reports_firmware_for_ota_verification() -> None:\n    \"\"\"The ESP32 must report the exact managed config version after OTA.\"\"\"\n    content = PACKAGED.read_text(encoding=\"utf-8\")\n    assert 'panel_config_version: \"0.7.0-alpha7-panel2\"' in content\n    assert 'name: \"Panel Firmware Version\"' in content\n    assert 'id: panel_firmware_version' in content\n    assert 'return {\"${panel_config_version}\"};' in content\n\n\ndef test_managed_panel_ota_tracks_queue_and_reconnect_health() -> None:\n    \"\"\"KEMS should distinguish queued OTA from verified firmware success.\"\"\"\n    sync = (ROOT / \"custom_components\" / \"kems\" / \"dashboard.py\").read_text(\n        encoding=\"utf-8\"\n    )\n    panel_health = (ROOT / \"custom_components\" / \"kems\" / \"panel.py\").read_text(\n        encoding=\"utf-8\"\n    )\n    assert 'last_ota_result=\"queued\"' in sync\n    assert \"async_verify_panel_firmware\" in sync\n    assert 'PANEL_CONFIG_VERSION = \"0.7.0-alpha7-panel2\"' in panel_health\n    assert 'status=\"Success\"' in panel_health\n'''
panel_test_path.write_text(panel_test, encoding="utf-8")
