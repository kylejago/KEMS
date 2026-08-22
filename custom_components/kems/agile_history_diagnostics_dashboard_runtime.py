"""Alpha 7.15 sensor-backed Agile history diagnostics dashboard patch."""

from __future__ import annotations

from . import agile_alpha714_dashboard as alpha714
from . import dashboard as dashboard_module

_BACKFILL_DIAGNOSTICS_ENTITIES_CARD = r"""
      - type: entities
        title: Historical backfill diagnostics
        show_header_toggle: false
        entities:
          - entity: sensor.kems_agile_history_backfill
            name: Settled historical coverage
          - entity: sensor.kems_agile_backfill_method
            name: Backfill method
          - entity: sensor.kems_agile_backfill_reason
            name: Backfill reason
          - entity: sensor.kems_agile_backfill_direct_sources
            name: Configured live-source statistics
          - entity: sensor.kems_agile_backfill_grid_import
            name: Energy grid import
          - entity: sensor.kems_agile_backfill_grid_export
            name: Energy grid export
          - entity: sensor.kems_agile_backfill_solar
            name: Energy solar
          - entity: sensor.kems_agile_backfill_battery_discharge
            name: Energy battery discharge
          - entity: sensor.kems_agile_backfill_battery_charge
            name: Energy battery charge
          - entity: sensor.kems_agile_backfill_battery_soc
            name: Energy battery SOC
"""


def install_alpha715_dashboard_patch() -> None:
    """Replace the fragile Markdown diagnostics block with normal HA entities."""
    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_alpha715_dashboard", False):
        return

    def combined_dashboard_with_alpha715() -> bytes:
        content = original().decode("utf-8")
        if alpha714._BACKFILL_DIAGNOSTICS_CARD in content:
            content = content.replace(
                alpha714._BACKFILL_DIAGNOSTICS_CARD,
                _BACKFILL_DIAGNOSTICS_ENTITIES_CARD,
                1,
            )
        return content.encode("utf-8")

    combined_dashboard_with_alpha715._kems_alpha715_dashboard = True
    dashboard_module._combined_master_dashboard_bytes = combined_dashboard_with_alpha715
