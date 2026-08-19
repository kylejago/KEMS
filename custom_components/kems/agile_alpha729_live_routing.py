"""Alpha 7.29 live house-demand parity for the Agile workspace.

The Agile live-routing card historically labelled an elapsed simulated half-hour
average as "House demand".  That value is useful digital-twin evidence, but it is
not the same instantaneous KEMS house-load measurement shown on the Live tab.

Alpha7.29 keeps the simulated value as explicit evidence while making the primary
Agile house-demand reading come from ``sensor.kems_house_load``.  This module is
reporting-only: it does not alter the rolling optimiser, dispatch targets, safety
checks, SOC trajectory, price-horizon handling, or hardware-write boundary.
"""

from __future__ import annotations

import math
from typing import Any

from . import agile_smart_export_runtime_base as runtime
from . import dashboard as dashboard_module

_LIVE_SENSOR = "sensor.kems_agile_live_scenario"
_HOUSE_SENSOR = "sensor.kems_house_load"


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _house_state(self) -> tuple[float | None, str | None]:
    """Return the exact live KEMS house-load state and update timestamp."""
    source = self._hass.states.get(_HOUSE_SENSOR)
    if source is None:
        return None, None
    value = _number(source.state)
    updated = getattr(source, "last_updated", None)
    return value, updated.isoformat() if updated is not None else None


def _publish_with_live_house_parity(self, state: dict[str, Any]) -> None:
    """Publish live house demand while retaining the simulated slot average."""
    alpha729_original_publish(self, state)

    live_state = self._hass.states.get(_LIVE_SENSOR)
    attrs = dict(live_state.attributes) if live_state is not None else {}
    simulated_house_kw = _number(attrs.get("current_house_load_kw"))
    simulated_basis = attrs.get("routing_basis")
    live_house_kw, live_updated = _house_state(self)

    attrs["simulated_house_load_kw"] = simulated_house_kw
    attrs["simulated_house_load_basis"] = simulated_basis
    attrs["live_house_load_kw"] = (
        round(live_house_kw, 3) if live_house_kw is not None else None
    )
    attrs["live_house_load_source"] = _HOUSE_SENSOR
    attrs["live_house_load_last_updated"] = live_updated
    attrs["house_load_parity_available"] = live_house_kw is not None
    attrs["house_load_display_basis"] = (
        "live KEMS house load"
        if live_house_kw is not None
        else "simulated elapsed-slot average fallback"
    )
    attrs["house_load_difference_kw"] = (
        round(live_house_kw - simulated_house_kw, 3)
        if live_house_kw is not None and simulated_house_kw is not None
        else None
    )

    if live_house_kw is not None:
        attrs["current_house_load_kw"] = round(live_house_kw, 3)

    state["live_house_load_parity"] = {
        "available": live_house_kw is not None,
        "source_entity": _HOUSE_SENSOR,
        "live_house_load_kw": (
            round(live_house_kw, 3) if live_house_kw is not None else None
        ),
        "simulated_house_load_kw": simulated_house_kw,
        "simulated_house_load_basis": simulated_basis,
        "difference_kw": attrs.get("house_load_difference_kw"),
        "display_basis": attrs.get("house_load_display_basis"),
        "last_updated": live_updated,
        "reporting_only": True,
    }

    self._set(
        _LIVE_SENSOR,
        live_state.state if live_state is not None else "Ready",
        attrs,
    )


def _patch_agile_dashboard(content: str) -> str:
    """Label live demand and simulated slot-average demand separately."""
    marker = "        title: Current Agile Smart Export power routing\n"
    start = content.find(marker)
    if start < 0:
        return content
    end = content.find("\n      - type:", start + len(marker))
    if end < 0:
        end = len(content)
    block = content[start:end]

    block = block.replace("| Flow | Simulated power |", "| Flow | Power |", 1)
    old_house = (
        "| House demand | {{ state_attr(e, 'current_house_load_kw') if "
        "state_attr(e, 'current_house_load_kw') is not none else '—' }} kW |"
    )
    new_house = (
        "| House demand (live) | {{ states('sensor.kems_house_load') }} kW |\n"
        "          | Digital-twin slot-average demand | {{ state_attr(e, "
        "'simulated_house_load_kw') if state_attr(e, 'simulated_house_load_kw') "
        "is not none else '—' }} kW |"
    )
    block = block.replace(old_house, new_house, 1)

    note_anchor = (
        "          **Routing slot:** {{ state_attr(e, 'routing_slot') or '—' }}"
    )
    note = (
        "\n\n          **House-demand basis:** `sensor.kems_house_load` — the same live "
        "measurement shown on the Live tab. The digital-twin elapsed-slot "
        "average is retained separately for simulation evidence."
    )
    if "**House-demand basis:**" not in block and note_anchor in block:
        block = block.replace(note_anchor, note_anchor + note, 1)

    return content[:start] + block + content[end:]


def install_alpha729_live_routing_parity_patch() -> None:
    """Install reporting-only live house-demand parity exactly once."""
    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_alpha729_live_routing", False):
        global alpha729_original_publish
        alpha729_original_publish = publish
        _publish_with_live_house_parity._kems_alpha729_live_routing = True
        runtime.EfficientAgileSmartExportManager._publish = (
            _publish_with_live_house_parity
        )

    original_dashboard = dashboard_module._combined_master_dashboard_bytes
    if getattr(original_dashboard, "_kems_alpha729_live_routing", False):
        return

    def combined_dashboard_with_alpha729() -> bytes:
        content = original_dashboard().decode("utf-8")
        return _patch_agile_dashboard(content).encode("utf-8")

    combined_dashboard_with_alpha729._kems_alpha729_live_routing = True
    dashboard_module._combined_master_dashboard_bytes = combined_dashboard_with_alpha729
