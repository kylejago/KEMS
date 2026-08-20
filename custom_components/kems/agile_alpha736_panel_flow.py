"""Alpha7.36 panel flow parity for the simplified KEMS product model.

Panel5 consumed an older compact Agile scenario feed while the Alpha7.30+
Home Assistant dashboard used the coherent current-routing snapshot. This
reporting-only patch republishes that final snapshot in the existing compact
ESPHome protocol and exposes the current simulated SOC as a flat live-scenario
attribute. It does not alter optimisation, tariffs, control commands, safety
validation, or hardware writes.
"""

from __future__ import annotations

import math
from typing import Any

from . import agile_smart_export_runtime_base as runtime

_LIVE_SENSOR = "sensor.kems_agile_live_scenario"
_LEGACY_PANEL_FLOW_SENSOR = "sensor.kems_agile_smart_export_flow_now"
_PANEL_FLOW_SENSOR = "sensor.kems_panel_full_kems_agile_flow_now"


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _value(value: Any, digits: int = 3) -> str:
    """Format one compact panel value, using -1 for unavailable data."""
    number = _number(value)
    if number is None:
        return "-1"
    return f"{number:.{digits}f}"


def _compact_flow(snapshot: dict[str, Any]) -> str:
    """Encode the final current-routing snapshot for ESPHome."""
    if not snapshot.get("available"):
        return "H=-1,S=-1,GI=-1,GE=-1,SH=-1,SB=-1,SE=-1,GB=-1,BH=-1,BE=-1,SOC=-1"

    house = snapshot.get("simulated_house_load_kw")
    if _number(house) is None:
        house = snapshot.get("live_house_load_kw")

    return ",".join(
        (
            f"H={_value(house)}",
            f"S={_value(snapshot.get('solar_power_kw'))}",
            f"GI={_value(snapshot.get('grid_import_kw'))}",
            f"GE={_value(snapshot.get('grid_export_kw'))}",
            f"SH={_value(snapshot.get('solar_to_home_kw'))}",
            f"SB={_value(snapshot.get('solar_to_battery_kw'))}",
            f"SE={_value(snapshot.get('solar_export_kw'))}",
            f"GB={_value(snapshot.get('grid_to_battery_kw'))}",
            f"BH={_value(snapshot.get('battery_to_home_kw'))}",
            f"BE={_value(snapshot.get('battery_export_kw'))}",
            f"SOC={_value(snapshot.get('simulated_soc_percent'), 1)}",
        )
    )


def _publish_with_panel_flow(self, state: dict[str, Any]) -> None:
    """Republish the final Agile routing snapshot for Panel6."""
    alpha736_original_publish(self, state)

    snapshot = state.get("current_routing_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {"available": False}

    flow = _compact_flow(snapshot)
    attributes = {
        "version": "0.7.0-alpha7.36",
        "source": "current_routing_snapshot",
        "reporting_only": True,
        "routing_action": snapshot.get("routing_action"),
        "dispatch_mode": snapshot.get("dispatch_mode"),
        "simulated_soc_percent": snapshot.get("simulated_soc_percent"),
    }

    # Keep the legacy compact entity correct for already-flashed Panel5 units
    # while Panel6 migrates to the explicit product-named feed.
    self._set(_LEGACY_PANEL_FLOW_SENSOR, flow, attributes)
    self._set(_PANEL_FLOW_SENSOR, flow, attributes)

    live_state = self._hass.states.get(_LIVE_SENSOR)
    if live_state is not None:
        live_attributes = dict(live_state.attributes)
        live_attributes["simulated_soc_percent"] = snapshot.get("simulated_soc_percent")
        live_attributes["panel_flow_state"] = flow
        live_attributes["panel_flow_source"] = _PANEL_FLOW_SENSOR
        self._set(_LIVE_SENSOR, live_state.state, live_attributes)


def install_alpha736_panel_flow_patch() -> None:
    """Install the reporting-only Panel6 parity wrapper exactly once."""
    publish = runtime.EfficientAgileSmartExportManager._publish
    if getattr(publish, "_kems_alpha736_panel_flow", False):
        return

    global alpha736_original_publish
    alpha736_original_publish = publish
    _publish_with_panel_flow._kems_alpha736_panel_flow = True
    runtime.EfficientAgileSmartExportManager._publish = _publish_with_panel_flow
