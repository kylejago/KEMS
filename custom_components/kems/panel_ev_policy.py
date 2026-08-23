"""Project KEMS EV shadow policy onto the managed ESPHome panel payload."""

# ruff: noqa: E501

from __future__ import annotations

PANEL_EV_POLICY_VERSION = "0.8.0-alpha8-panel.1"


def apply_ev_policy_panel(content: str) -> str:
    """Add EV policy input and blocked-red semantics to the proven panel config."""
    if f'panel_config_version: "{PANEL_EV_POLICY_VERSION}"' in content:
        return content

    replacements = (
        (
            '  panel_config_version: "0.8.0-alpha8-panel.0"\n',
            f'  panel_config_version: "{PANEL_EV_POLICY_VERSION}"\n',
        ),
        (
            "  ev_charging: binary_sensor.kems_ev_charging\n",
            "  ev_charging: binary_sensor.kems_ev_charging\n"
            "  ev_allowed: binary_sensor.kems_ev_charging_allowed_by_control\n",
        ),
        (
            "  - platform: homeassistant\n"
            "    id: ha_ev_charging\n"
            "    entity_id: ${ev_charging}\n",
            "  - platform: homeassistant\n"
            "    id: ha_ev_charging\n"
            "    entity_id: ${ev_charging}\n"
            "  - platform: homeassistant\n"
            "    id: ha_ev_allowed\n"
            "    entity_id: ${ev_allowed}\n",
        ),
        (
            "      const bool ev_connected = id(ha_ev_connected).state;\n"
            "      const bool ev_charging = id(ha_ev_charging).state;\n",
            "      const bool ev_connected = id(ha_ev_connected).state;\n"
            "      const bool ev_charging = id(ha_ev_charging).state;\n"
            "      const bool ev_allowed_by_kems = id(ha_ev_allowed).state;\n"
            "      const bool agile_ev_mode = selected_scenario == 7;\n"
            "      const bool ev_blocked_by_kems =\n"
            "        agile_ev_mode && ev_connected && !ev_allowed_by_kems;\n"
            "      const bool ev_charging_for_display =\n"
            "        ev_charging && (!agile_ev_mode || ev_allowed_by_kems);\n",
        ),
        (
            "      const bool ev_from_grid =\n        ev_charging && source_grid_active;\n"
            "      const bool ev_from_solar =\n        ev_charging && source_solar_active;\n"
            "      const bool ev_from_battery =\n        ev_charging && source_battery_active;\n",
            "      const bool ev_from_grid =\n        ev_charging_for_display && source_grid_active;\n"
            "      const bool ev_from_solar =\n        ev_charging_for_display && source_solar_active;\n"
            "      const bool ev_from_battery =\n        ev_charging_for_display && source_battery_active;\n",
        ),
        (
            "      if (ev_charging) {\n"
            "        rect(7, 15, 10, 16, pulse(MAGENTA));\n",
            "      if (ev_blocked_by_kems) {\n"
            "        rect(7, 15, 10, 16, RED);\n"
            "      } else if (ev_charging_for_display) {\n"
            "        rect(7, 15, 10, 16, pulse(MAGENTA));\n",
        ),
    )
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Managed panel EV-policy marker missing: {old[:60]!r}")
        content = content.replace(old, new, 1)
    return content


def install_panel_ev_policy() -> None:
    """Install the transformed managed-panel payload before HA synchronises it."""
    from . import dashboard as dashboard_module
    from . import panel as panel_module

    original = dashboard_module._managed_panel_bytes
    if getattr(original, "_kems_panel_ev_policy", False):
        return

    def managed_panel_with_ev_policy() -> bytes:
        content = original().decode("utf-8")
        return apply_ev_policy_panel(content).encode("utf-8")

    managed_panel_with_ev_policy._kems_panel_ev_policy = True
    dashboard_module._managed_panel_bytes = managed_panel_with_ev_policy
    panel_module.PANEL_CONFIG_VERSION = PANEL_EV_POLICY_VERSION
