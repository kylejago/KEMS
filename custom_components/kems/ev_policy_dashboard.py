"""Expose the selectable EV shadow policy on the managed KEMS dashboard."""

# ruff: noqa: E501

from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)

_AGILE_VIEW_MARKER = """  - title: Full KEMS Agile
    path: full-kems-agile
    icon: mdi:transmission-tower-export
    cards:
"""

_EV_CARDS = r"""      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: EV charging policy — shadow
            show_header_toggle: false
            entities:
              - entity: select.kems_ev_charging_policy
                name: Policy
              - entity: binary_sensor.kems_ev_connected
                name: EV connected
              - entity: binary_sensor.kems_ev_charging
                name: EV actually charging
              - entity: binary_sensor.kems_ev_charging_allowed_by_control
                name: KEMS allows charging
              - entity: sensor.kems_ev_charging_power
                name: Actual EV power
              - entity: binary_sensor.kems_cheap_period_confirmed
                name: Authoritative overnight window
          - type: markdown
            title: EV decision now
            content: |
              {% set connected = is_state('binary_sensor.kems_ev_connected', 'on') %}
              {% set charging = is_state('binary_sensor.kems_ev_charging', 'on') %}
              {% set allowed = is_state('binary_sensor.kems_ev_charging_allowed_by_control', 'on') %}
              {% set policy = states('select.kems_ev_charging_policy') %}
              **Selected policy:** {{ policy }}  
              **Decision:** {% if not connected %}EV not connected{% elif allowed and charging %}CHARGING ALLOWED{% elif allowed %}PLUGGED IN — ALLOWED{% else %}PLUGGED IN — BLOCKED BY KEMS{% endif %}  
              **Battery protection:** {% if connected and (allowed or charging) %}battery discharge/export isolated for the EV policy{% else %}normal KEMS routing{% endif %}.  

              **Default EV cheap-window mode** permits charging in the configured **23:30–05:30** overnight window and in a daytime Intelligent slot only after KEMS has fail-closed confirmation that it is genuinely cheap. Raw/unconfirmed Intelligent flags and Agile prices do not widen it. Happy Hour is a separate per-reward-hour authority. Power Down remains higher priority.

              *EV policy is shadow-only: KEMS reports what the charger should do but does not issue an Ohme control write.*
"""


def add_ev_policy_dashboard(content: str) -> str:
    """Insert EV policy cards once into the consolidated Full KEMS Agile view."""
    if "EV charging policy — shadow" in content:
        return content
    if _AGILE_VIEW_MARKER not in content:
        LOGGER.warning(
            "KEMS managed dashboard has no consolidated Full KEMS Agile view; "
            "skipping EV policy cards without blocking integration setup"
        )
        return content
    return content.replace(
        _AGILE_VIEW_MARKER,
        _AGILE_VIEW_MARKER + _EV_CARDS,
        1,
    )


def install_ev_policy_dashboard() -> None:
    """Install the reporting-only EV policy dashboard transform."""
    from . import dashboard as dashboard_module

    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_ev_policy_dashboard", False):
        return

    def combined_with_ev_policy() -> bytes:
        content = original().decode("utf-8")
        return add_ev_policy_dashboard(content).encode("utf-8")

    combined_with_ev_policy._kems_ev_policy_dashboard = True
    dashboard_module._combined_master_dashboard_bytes = combined_with_ev_policy
