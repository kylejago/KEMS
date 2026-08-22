"""Alpha 7.16 rolling Agile export dashboard patch."""

from __future__ import annotations

from . import dashboard as dashboard_module

_ROLLING_CARD = r"""
      - type: entities
        title: Rolling Agile battery export plan
        show_header_toggle: false
        entities:
          - entity: sensor.kems_agile_rolling_export_plan
            name: Current rolling allocation
          - entity: sensor.kems_agile_rolling_next_export_slot
            name: Next planned battery export slot
          - entity: sensor.kems_agile_rolling_exportable_energy
            name: Battery energy currently available for export
          - entity: sensor.kems_agile_rolling_protected_house_energy
            name: Battery energy protected for the house
          - entity: sensor.kems_agile_rolling_capacity_margin
            name: Remaining deadline capacity margin
"""

_MARKER = """      - type: history-graph
        title: Agile scenario economics — 24 hours
"""


def install_alpha716_dashboard_patch() -> None:
    """Insert rolling-replan visibility into the Agile live scenario view."""
    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_alpha716_dashboard", False):
        return

    def combined_dashboard_with_alpha716() -> bytes:
        content = original().decode("utf-8")
        if (
            "title: Rolling Agile battery export plan" not in content
            and _MARKER in content
        ):
            content = content.replace(_MARKER, f"{_ROLLING_CARD}\n{_MARKER}", 1)
        return content.encode("utf-8")

    combined_dashboard_with_alpha716._kems_alpha716_dashboard = True
    dashboard_module._combined_master_dashboard_bytes = combined_dashboard_with_alpha716
