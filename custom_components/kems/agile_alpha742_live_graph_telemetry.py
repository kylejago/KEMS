"""Recorder-friendly live power series for the Alpha7.42 Agile dashboard.

The focused Full KEMS Agile view needs a stable set of numeric entities for the
live graph even before every physical source is commissioned. Missing physical
solar, battery or export readings are published as unavailable, never as zero.
This module is reporting-only and does not affect dispatch or hardware writes.
"""

from __future__ import annotations

import math
from typing import Any

from . import agile_smart_export_runtime_base as runtime
from .kems_core import SimulationConfig

_LIVE_POWER_SENSORS = {
    "sensor.kems_agile_actual_house_load_power": (
        "Full KEMS Agile actual house load",
        "house_load_kw",
    ),
    "sensor.kems_agile_actual_solar_power": (
        "Full KEMS Agile actual solar power",
        "solar_power_kw",
    ),
    "sensor.kems_agile_actual_grid_import_power": (
        "Full KEMS Agile actual grid import",
        "grid_import_kw",
    ),
    "sensor.kems_agile_actual_grid_export_power": (
        "Full KEMS Agile actual grid export",
        "grid_export_kw",
    ),
}
_LIVE_BATTERY_SENSOR = "sensor.kems_agile_actual_battery_net_power"
_SENSOR_IDS = (*_LIVE_POWER_SENSORS, _LIVE_BATTERY_SENSOR)

_AGILE_VIEW_START = (
    "  - title: Full KEMS Agile\n"
    "    path: full-kems-agile\n"
    "    icon: mdi:transmission-tower-export\n"
)
_COMPARE_VIEW_START = (
    "  - title: Compare\n" "    path: compare\n" "    icon: mdi:compare-horizontal\n"
)

_REPLACEMENTS = {
    "sensor.kems_house_load": "sensor.kems_agile_actual_house_load_power",
    "sensor.kems_solar_power": "sensor.kems_agile_actual_solar_power",
    "sensor.kems_battery_power": "sensor.kems_agile_actual_battery_net_power",
    "sensor.kems_grid_import": "sensor.kems_agile_actual_grid_import_power",
    "sensor.kems_grid_export": "sensor.kems_agile_actual_grid_export_power",
}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _publish_power_sensor(
    self,
    entity_id: str,
    friendly_name: str,
    value: Any,
    *,
    source: str,
) -> None:
    number = _number(value)
    self._set(
        entity_id,
        round(number, 3) if number is not None else "unavailable",
        {
            "friendly_name": friendly_name,
            "unit_of_measurement": "kW",
            "device_class": "power",
            "state_class": "measurement",
            "source": source,
            "missing_physical_data_is_not_zero": True,
            "reporting_only": True,
            "hardware_writes": "blocked",
        },
    )


def _publish_with_alpha742_live_graph(self, state: dict[str, Any]) -> None:
    """Publish a stable live-power mirror after the focused Agile telemetry."""
    alpha742_live_original_publish(self, state)
    records = list(getattr(self, "_panel_today_records", []) or [])
    current = records[-1] if records else None
    stale = set(getattr(current, "stale_fields", ()) or ()) if current else set()

    for entity_id, (friendly_name, field) in _LIVE_POWER_SENSORS.items():
        value = None
        if current is not None and field not in stale:
            value = getattr(current, field, None)
        _publish_power_sensor(
            self,
            entity_id,
            friendly_name,
            value,
            source=f"live KEMS snapshot: {field}",
        )

    battery = None
    if current is not None and "battery_power_kw" not in stale:
        battery = _number(getattr(current, "battery_power_kw", None))
    config = getattr(self, "_rolling_config", None)
    positive_discharge = (
        bool(config.battery_power_positive_is_discharge)
        if isinstance(config, SimulationConfig)
        else True
    )
    if battery is not None and not positive_discharge:
        battery = -battery
    _publish_power_sensor(
        self,
        _LIVE_BATTERY_SENSOR,
        "Full KEMS Agile actual battery net power",
        battery,
        source="live KEMS snapshot: battery_power_kw; positive discharge / negative charge",
    )


def improve_alpha742_live_graph_dashboard(content: str) -> str:
    """Use the stable actual graph entities only inside the Full KEMS Agile view."""
    start = content.find(_AGILE_VIEW_START)
    if start < 0:
        raise ValueError("Alpha7.42 live graph Agile view marker missing")
    end = content.find(_COMPARE_VIEW_START, start + len(_AGILE_VIEW_START))
    if end < 0:
        raise ValueError("Alpha7.42 live graph Compare marker missing")
    view = content[start:end]
    for old, new in _REPLACEMENTS.items():
        view = view.replace(old, new)
    return content[:start] + view + content[end:]


def install_alpha742_live_graph_telemetry_patch() -> None:
    """Install live graph telemetry after the Alpha7.42 focused view."""
    global alpha742_live_original_publish
    global alpha742_live_original_shutdown

    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_alpha742_live_graph", False):
        alpha742_live_original_publish = publish
        _publish_with_alpha742_live_graph._kems_alpha742_live_graph = True
        runtime.EfficientAgileSmartExportManager._publish = (
            _publish_with_alpha742_live_graph
        )

    shutdown = runtime.EfficientAgileSmartExportManager.async_shutdown
    if not getattr(shutdown, "_kems_alpha742_live_graph", False):
        alpha742_live_original_shutdown = shutdown

        async def shutdown_with_alpha742_live_graph(self) -> None:
            await alpha742_live_original_shutdown(self)
            for entity_id in _SENSOR_IDS:
                self._hass.states.async_remove(entity_id)

        shutdown_with_alpha742_live_graph._kems_alpha742_live_graph = True
        runtime.EfficientAgileSmartExportManager.async_shutdown = (
            shutdown_with_alpha742_live_graph
        )

    from . import dashboard as dashboard_module

    original_dashboard = dashboard_module._combined_master_dashboard_bytes
    if getattr(original_dashboard, "_kems_alpha742_live_graph", False):
        return

    def combined_alpha742_live_graph_dashboard() -> bytes:
        content = original_dashboard().decode("utf-8")
        return improve_alpha742_live_graph_dashboard(content).encode("utf-8")

    combined_alpha742_live_graph_dashboard._kems_alpha742_live_graph = True
    dashboard_module._combined_master_dashboard_bytes = (
        combined_alpha742_live_graph_dashboard
    )
