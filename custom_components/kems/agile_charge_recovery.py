"""Full KEMS Agile 100% charge intent with profit-first solar recovery.

KEMS keeps the user's 100% battery charge target even when the configured
23:30-05:30 cheap window cannot physically reach it from the 10% reserve. The
battery therefore charges as hard as permitted throughout every authoritative
cheap slot.

After the cheap window, 100% remains the recovery aim rather than a hard gate on
battery export. The existing Full KEMS Agile price/forecast optimiser remains
free to export battery energy before 100% when that is the highest-value feasible
way to create forecast solar headroom. House protection, the configured reserve,
deadline reconciliation and Power Down priority remain authoritative.

This module changes simulation/shadow planning only. Real hardware writes remain
blocked.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import agile_smart_export as agile

_FULL_SOC_PERCENT = 100.0


def _force_full_charge_target(records: list[Any]) -> list[Any]:
    """Keep 100% as the requested target in every authoritative cheap slot."""
    return [
        (
            replace(item, forecast_maximum_overnight_soc_percent=_FULL_SOC_PERCENT)
            if bool(getattr(item, "cheap_period_confirmed", False))
            else item
        )
        for item in records
    ]


def install_charge_recovery_policy() -> None:
    """Install 100% charge intent without blocking profit-first headroom export."""
    method = agile.AgileSmartExportManager._agile_day
    if getattr(method, "_kems_charge_recovery_policy", False):
        return
    original = method

    def agile_day_with_charge_recovery(
        self,
        records,
        rates,
        config,
        tariff,
        initial_soc,
    ):
        summary, plan = original(
            self,
            _force_full_charge_target(list(records)),
            rates,
            config,
            tariff,
            initial_soc,
        )
        summary = dict(summary)
        summary.update(
            {
                "charge_target_soc_percent": _FULL_SOC_PERCENT,
                "battery_reserve_target_soc_percent": round(
                    float(config.battery_reserve_percent), 1
                ),
                "morning_solar_recovery_target_soc_percent": _FULL_SOC_PERCENT,
                "morning_solar_recovery_policy": (
                    "solar normally recovers remaining battery headroom; "
                    "profit-first forecast headroom export may occur before 100%"
                ),
                "full_soc_is_export_gate": False,
                "forecast_headroom_export_can_precede_full_soc": True,
                "hardware_writes": "blocked",
            }
        )
        return summary, plan

    agile_day_with_charge_recovery._kems_charge_recovery_policy = True
    agile.AgileSmartExportManager._agile_day = agile_day_with_charge_recovery
