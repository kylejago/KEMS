"""Solar-routing reporting fixes for Agile Smart Export.

This wrapper keeps the proven optimiser untouched while restoring Solar -> Home
into daily/rolling comparison payloads and the managed dashboard.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import agile_smart_export as _base
from .kems_core import SimulationConfig, Snapshot
from .tariff import TariffSettings

_BASE_AGGREGATE = _base._aggregate
_BaseManager = _base.AgileSmartExportManager


def aggregate_with_solar_to_home(
    days: list[dict[str, Any]],
    key: str,
    label: str,
) -> dict[str, Any]:
    """Preserve Solar -> Home when ready daily results are aggregated."""
    period = _BASE_AGGREGATE(days, key, label)
    ready = [item for item in days if item and item.get("ready")]
    if not ready:
        return period

    for strategy_name in ("full_kems_forecast", "agile_smart_export"):
        items = [item[strategy_name] for item in ready]
        values = [item.get("solar_to_home_kwh") for item in items]
        period[strategy_name]["solar_to_home_kwh"] = (
            round(sum(float(value) for value in values), 3)
            if values and all(value is not None for value in values)
            else None
        )
    return period


class ReportingAgileSmartExportManager(_BaseManager):
    """Add reporting fields without changing Agile dispatch decisions."""

    def _compare_day(
        self,
        records: list[Snapshot],
        config: SimulationConfig,
        tariff: TariffSettings,
        agile_soc: float,
        full_soc: float,
        learned_forecast: float | None,
        projection: bool = False,
    ) -> dict[str, Any]:
        result = super()._compare_day(
            records,
            config,
            tariff,
            agile_soc,
            full_soc,
            learned_forecast,
            projection,
        )
        if len(records) < 2:
            return result

        full_records = [replace(records[0], battery_soc=None), *records[1:]]
        full = self._simulation.simulate_today(
            full_records,
            full_records[-1].timestamp,
            replace(
                config,
                battery_initial_percent=full_soc,
                export_tariff_status="active",
                battery_export_enabled=True,
                strategy="paced_export",
                forecast_aware=True,
            ),
            learned_forecast,
            current_snapshot=full_records[-1],
        )
        result["full_kems_forecast"]["solar_to_home_kwh"] = round(
            float(full.simulated_solar_to_home_kwh or 0),
            3,
        )
        return result


def install_reporting_patch() -> None:
    """Install the aggregate and dashboard reporting patch once."""
    _base._aggregate = aggregate_with_solar_to_home

    try:
        from . import dashboard as dashboard_module
    except ImportError:
        return

    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_solar_home_reporting", False):
        return

    def combined_master_dashboard_bytes() -> bytes:
        content = original().decode()
        needle = (
            "          | Solar export | {{ full.get('solar_export_kwh', '—') }} kWh | "
            "{{ agile.get('solar_export_kwh', '—') }} kWh |\n"
        )
        row = (
            "          | Solar → home | {{ full.get('solar_to_home_kwh', '—') }} kWh | "
            "{{ agile.get('solar_to_home_kwh', '—') }} kWh |\n"
        )
        if row not in content and needle in content:
            content = content.replace(needle, needle + row, 1)
        return content.encode()

    combined_master_dashboard_bytes._kems_solar_home_reporting = True
    dashboard_module._combined_master_dashboard_bytes = combined_master_dashboard_bytes
