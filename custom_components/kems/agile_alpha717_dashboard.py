"""Alpha 7.17 live dispatch target dashboard patch."""

from __future__ import annotations

from . import dashboard as dashboard_module

_ROLLING_MARKER = """          - entity: sensor.kems_agile_rolling_export_plan
            name: Current rolling allocation
"""

_ROLLING_REPLACEMENT = """          - entity: sensor.kems_agile_rolling_export_plan
            name: Current rolling allocation
          - entity: sensor.kems_agile_dispatch_mode
            name: Live dispatch mode
          - entity: sensor.kems_agile_battery_discharge_target_now
            name: Battery discharge target now
          - entity: sensor.kems_agile_battery_export_target_now
            name: Battery export target now
          - entity: sensor.kems_agile_dispatch_shortfall_now
            name: Simulated discharge shortfall
"""

_ROUTING_HEADER = "| Flow | Simulated power |"
_ROUTING_HEADER_REPLACEMENT = "| Flow | Rolling target / simulated power |"

_ROUTING_NOTE = (
    "          **Power basis:** battery/grid export use the current rolling target "
    "when available; other flows use the elapsed current-slot simulation average.  \n"
)

_ROUTING_NOTE_MARKER = (
    "          **Current decision:** {{ state_attr(e, 'current_action') or "
    "states('sensor.kems_agile_smart_export_plan') }}  \n"
)


def install_alpha717_dashboard_patch() -> None:
    """Expose the current rolling dispatch target and power basis."""
    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_alpha717_dashboard", False):
        return

    def combined_dashboard_with_alpha717() -> bytes:
        content = original().decode("utf-8")
        if "entity: sensor.kems_agile_dispatch_mode" not in content:
            content = content.replace(
                _ROLLING_MARKER,
                _ROLLING_REPLACEMENT,
                1,
            )
        content = content.replace(
            _ROUTING_HEADER,
            _ROUTING_HEADER_REPLACEMENT,
            1,
        )
        if (
            "**Power basis:** battery/grid export use the current rolling target"
            not in content
        ):
            content = content.replace(
                _ROUTING_NOTE_MARKER,
                f"{_ROUTING_NOTE}{_ROUTING_NOTE_MARKER}",
                1,
            )
        return content.encode("utf-8")

    combined_dashboard_with_alpha717._kems_alpha717_dashboard = True
    dashboard_module._combined_master_dashboard_bytes = combined_dashboard_with_alpha717
