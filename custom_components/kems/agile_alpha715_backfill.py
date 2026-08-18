"""Alpha 7.15 Energy-history compatibility and visible diagnostics."""

from __future__ import annotations

from typing import Any

from . import agile_history_backfill as base
from . import agile_history_backfill_v2 as enhanced

_DIAGNOSTIC_ENTITY_IDS = {
    "method": "sensor.kems_agile_backfill_method",
    "reason": "sensor.kems_agile_backfill_reason",
    "direct": "sensor.kems_agile_backfill_direct_sources",
    "grid_import": "sensor.kems_agile_backfill_grid_import",
    "grid_export": "sensor.kems_agile_backfill_grid_export",
    "solar": "sensor.kems_agile_backfill_solar",
    "battery_discharge": "sensor.kems_agile_backfill_battery_discharge",
    "battery_charge": "sensor.kems_agile_backfill_battery_charge",
    "battery_soc": "sensor.kems_agile_backfill_battery_soc",
}


def _append_nested(target: list[str], values: Any, key: str) -> None:
    """Append statistic IDs from one legacy Energy flow list."""
    if not isinstance(values, list):
        return
    for item in values:
        if isinstance(item, dict):
            enhanced._append(target, item.get(key))


def _energy_sources_compatible(values: Any) -> dict[str, list[str]]:
    """Accept both current and legacy Home Assistant Energy grid schemas."""
    result = _ORIGINAL_ENERGY_SOURCES(values)
    if not isinstance(values, list):
        return result

    for source in values:
        if not isinstance(source, dict) or source.get("type") != "grid":
            continue
        _append_nested(result["grid_import"], source.get("flow_from"), "stat_energy_from")
        _append_nested(result["grid_export"], source.get("flow_to"), "stat_energy_to")
    return result


def _reason_label(state: dict[str, Any]) -> str:
    """Return a short dashboard-safe reason while keeping the full text as an attribute."""
    method = str(state.get("backfill_method") or "none")
    reason = str(state.get("energy_fallback_reason") or state.get("reason") or "")
    lowered = reason.lower()
    if method == "energy_dashboard_counters":
        return "Recovered via Energy counters"
    if method == "direct_power_statistics":
        return "Recovered via power statistics"
    if "needs grid import" in lowered:
        return "Missing Energy sources"
    if "fewer than 75%" in lowered:
        return "Insufficient hourly coverage"
    if "query failed" in lowered:
        return "Statistics query failed"
    if "not configured" in lowered or "are not configured" in lowered:
        return "Direct sources unavailable"
    return "No historical backfill" if not reason else reason[:250]


def _source_diagnostic(state: dict[str, Any], kind: str) -> tuple[str, dict[str, Any]]:
    """Build one visible Energy-source status from the backfill attributes."""
    sources = state.get("energy_fallback_sources", {})
    source_ids = sources.get(kind, []) if isinstance(sources, dict) else []
    if not isinstance(source_ids, list):
        source_ids = []

    diagnostics = state.get("energy_source_diagnostics", {})
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    matching = [
        diagnostics.get(entity_id, {})
        for entity_id in source_ids
        if isinstance(diagnostics.get(entity_id, {}), dict)
    ]
    rows = sum(int(item.get("historical_rows") or 0) for item in matching)
    oldest_values = [str(item.get("oldest")) for item in matching if item.get("oldest")]
    oldest = min(oldest_values) if oldest_values else None

    if not source_ids:
        status = "Missing"
    elif matching and rows > 0:
        status = "Historical data available"
    else:
        status = "Configured — no usable history yet"
    return status, {
        "friendly_name": f"Agile backfill {kind.replace('_', ' ')}",
        "statistic_ids": source_ids,
        "historical_rows": rows,
        "oldest": oldest,
    }


def _publish_diagnostic_entities(self) -> None:
    """Publish robust entities instead of relying on a complex Markdown loop."""
    state = dict(self._state)
    method = str(state.get("backfill_method") or "none")
    full_reason = str(state.get("energy_fallback_reason") or state.get("reason") or "")
    self._hass.states.async_set(
        _DIAGNOSTIC_ENTITY_IDS["method"],
        method,
        {
            "friendly_name": "Agile historical backfill method",
            "energy_fallback_used": bool(state.get("energy_fallback_used")),
        },
    )
    self._hass.states.async_set(
        _DIAGNOSTIC_ENTITY_IDS["reason"],
        _reason_label(state),
        {
            "friendly_name": "Agile historical backfill reason",
            "full_reason": full_reason,
        },
    )

    direct = state.get("direct_source_diagnostics", {})
    direct = direct if isinstance(direct, dict) else {}
    usable = [
        item
        for item in direct.values()
        if isinstance(item, dict) and item.get("long_term_statistics")
    ]
    configured = [item for item in direct.values() if isinstance(item, dict)]
    self._hass.states.async_set(
        _DIAGNOSTIC_ENTITY_IDS["direct"],
        f"{len(usable)}/{len(configured)} available",
        {
            "friendly_name": "Configured live-source long-term statistics",
            "sources": direct,
        },
    )

    for kind in (
        "grid_import",
        "grid_export",
        "solar",
        "battery_discharge",
        "battery_charge",
        "battery_soc",
    ):
        status, attributes = _source_diagnostic(state, kind)
        self._hass.states.async_set(_DIAGNOSTIC_ENTITY_IDS[kind], status, attributes)


def install_alpha715_backfill_patch() -> None:
    """Install Energy schema compatibility and sensor-backed diagnostics once."""
    global _ORIGINAL_ENERGY_SOURCES

    current_sources = enhanced._energy_sources
    if not getattr(current_sources, "_kems_alpha715_compat", False):
        _ORIGINAL_ENERGY_SOURCES = current_sources
        _energy_sources_compatible._kems_alpha715_compat = True
        enhanced._energy_sources = _energy_sources_compatible

    target = base.AgileHistoryBackfill
    current_augment = target._augment_state
    if not getattr(current_augment, "_kems_alpha715_diagnostics", False):
        original_augment = current_augment

        def augment_with_diagnostics(self, values: dict[str, Any]) -> None:
            original_augment(self, values)
            _publish_diagnostic_entities(self)

        augment_with_diagnostics._kems_alpha715_diagnostics = True
        target._augment_state = augment_with_diagnostics

    current_shutdown = target.async_shutdown
    if not getattr(current_shutdown, "_kems_alpha715_diagnostics", False):
        original_shutdown = current_shutdown

        async def shutdown_with_diagnostics(self) -> None:
            await original_shutdown(self)
            for entity_id in _DIAGNOSTIC_ENTITY_IDS.values():
                self._hass.states.async_remove(entity_id)

        shutdown_with_diagnostics._kems_alpha715_diagnostics = True
        target.async_shutdown = shutdown_with_diagnostics


_ORIGINAL_ENERGY_SOURCES = enhanced._energy_sources
