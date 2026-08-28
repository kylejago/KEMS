"""Reconcile current-day Agile accounting with settled digital-twin outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .agile_tomorrow_soc_handoff import TomorrowSocHandoffAgileSmartExportManager

FIXED_EXPORT_BENCHMARK_PENCE = 12.0
DEFAULT_BATTERY_WEAR_PENCE_PER_KWH = 2.0
SETTLEMENT_SOURCE = "settled shadow digital-twin outcome"


def _number(value: Any) -> float | None:
    """Return one finite numeric value when available."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _sum_slots(slots: list[dict[str, Any]], field: str) -> float:
    """Sum one numeric half-hour energy field without inventing missing values."""
    return sum(
        number
        for item in slots
        if (number := _number(item.get(field))) is not None
    )


def _slot_hours(slot: dict[str, Any]) -> float | None:
    """Return the represented slot duration in hours."""
    try:
        start = datetime.fromisoformat(str(slot["valid_from"]))
        end = datetime.fromisoformat(str(slot["valid_to"]))
    except (KeyError, TypeError, ValueError):
        return None
    hours = (end - start).total_seconds() / 3600.0
    return hours if hours > 0 else None


def _today_settlements(
    settled_half_hours: list[dict[str, Any]],
    now: datetime,
) -> dict[str, dict[str, Any]]:
    """Index today's retained digital-twin settlements by local slot start."""
    indexed: dict[str, dict[str, Any]] = {}
    for item in settled_half_hours:
        if not isinstance(item, dict) or item.get("basis") != "digital_twin":
            continue
        slot_value = item.get("slot")
        try:
            slot_start = datetime.fromisoformat(str(slot_value))
        except (TypeError, ValueError):
            continue
        if slot_start.tzinfo is None:
            continue
        if slot_start.date() != now.astimezone(slot_start.tzinfo).date():
            continue
        outcome = item.get("outcome")
        if not isinstance(outcome, dict):
            continue
        if _number(outcome.get("battery_to_home_kw")) is None:
            continue
        if _number(outcome.get("battery_export_kw")) is None:
            continue
        indexed[slot_start.isoformat()] = item
    return indexed


def _reconcile_comparison(today: dict[str, Any]) -> None:
    """Keep the Today winner consistent with reconciled Agile economics."""
    agile = today.get("agile_smart_export")
    full = today.get("full_kems_forecast")
    comparison = today.get("comparison")
    if not isinstance(agile, dict) or not isinstance(full, dict):
        return
    if not isinstance(comparison, dict):
        comparison = {}
        today["comparison"] = comparison
    agile_cost = _number(agile.get("economic_net_cost_pence"))
    full_cost = _number(full.get("economic_net_cost_pence"))
    if agile_cost is None or full_cost is None:
        return
    advantage = round(full_cost - agile_cost, 2)
    comparison["agile_advantage_pence"] = advantage
    if advantage > 0:
        comparison["winner"] = "Agile Smart Export"
        comparison["winner_margin_pence"] = advantage
    elif advantage < 0:
        comparison["winner"] = "Full KEMS Forecast"
        comparison["winner_margin_pence"] = round(abs(advantage), 2)
    else:
        comparison["winner"] = "Tie"
        comparison["winner_margin_pence"] = 0.0


def reconcile_current_day_settlements(
    state: dict[str, Any],
    settled_half_hours: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Settle current-day export accounting from completed shadow outcomes.

    Import energy and import cost remain owned by the established day replay.
    Completed shadow half-hours authoritatively replace battery-to-home and
    battery-export energy for matching slots. Export income and the dependent
    current-day economic totals are then rebuilt from those reconciled slots.
    """
    slots_value = state.get("today_slots")
    periods = state.get("periods")
    if not isinstance(slots_value, list) or not isinstance(periods, dict):
        return {"applied": False, "reason": "current day replay unavailable"}
    slots = [item for item in slots_value if isinstance(item, dict)]
    today = periods.get("today")
    if not isinstance(today, dict):
        return {"applied": False, "reason": "today period unavailable"}
    agile = today.get("agile_smart_export")
    if not isinstance(agile, dict) or not agile.get("ready"):
        return {"applied": False, "reason": "today Agile period unavailable"}

    settlements = _today_settlements(settled_half_hours, now)
    applied = 0
    for slot in slots:
        local_from = slot.get("local_from")
        try:
            local_key = datetime.fromisoformat(str(local_from)).isoformat()
        except (TypeError, ValueError):
            continue
        settlement = settlements.get(local_key)
        if settlement is None:
            continue
        hours = _slot_hours(slot)
        if hours is None:
            continue
        outcome = settlement["outcome"]
        battery_home_kw = max(_number(outcome.get("battery_to_home_kw")) or 0.0, 0.0)
        battery_export_kw = max(_number(outcome.get("battery_export_kw")) or 0.0, 0.0)
        battery_home_kwh = round(battery_home_kw * hours, 3)
        battery_export_kwh = round(battery_export_kw * hours, 3)
        solar_export_kwh = max(_number(slot.get("solar_export_kwh")) or 0.0, 0.0)

        slot["battery_to_home_kwh"] = battery_home_kwh
        slot["battery_export_kwh"] = battery_export_kwh
        slot["grid_export_kwh"] = round(solar_export_kwh + battery_export_kwh, 3)
        slot["settlement_source"] = SETTLEMENT_SOURCE
        slot["settlement_samples"] = int(settlement.get("samples") or 0)
        applied += 1

    if not applied:
        diagnostic = {
            "active": True,
            "applied": False,
            "settled_slots_applied": 0,
            "reason": "no completed current-day shadow slots matched the day replay",
            "export_accounting_source": SETTLEMENT_SOURCE,
            "import_accounting_source": "existing Agile day replay",
            "hardware_writes": "blocked",
        }
        state["current_day_settlement_reconciliation"] = diagnostic
        return diagnostic

    grid_export_kwh = round(_sum_slots(slots, "grid_export_kwh"), 3)
    solar_export_kwh = round(_sum_slots(slots, "solar_export_kwh"), 3)
    solar_to_battery_kwh = round(_sum_slots(slots, "solar_to_battery_kwh"), 3)
    solar_to_home_kwh = round(_sum_slots(slots, "solar_to_home_kwh"), 3)
    battery_to_home_kwh = round(_sum_slots(slots, "battery_to_home_kwh"), 3)
    battery_export_kwh = round(_sum_slots(slots, "battery_export_kwh"), 3)

    export_income_pence = 0.0
    for slot in slots:
        exported = _number(slot.get("grid_export_kwh"))
        rate = _number(slot.get("rate_pence"))
        if exported is not None and rate is not None:
            export_income_pence += max(exported, 0.0) * rate
    export_income_pence = round(export_income_pence, 2)

    old_import_cost = _number(agile.get("import_cost_pence")) or 0.0
    old_export_income = _number(agile.get("export_income_pence")) or 0.0
    old_energy_net = _number(agile.get("energy_net_cost_pence"))
    standing_component = (
        old_energy_net - old_import_cost + old_export_income
        if old_energy_net is not None
        else 0.0
    )
    wear_rate = _number(
        state.get("battery_wear_assumption_pence_per_discharged_kwh")
    )
    if wear_rate is None:
        wear_rate = DEFAULT_BATTERY_WEAR_PENCE_PER_KWH
    wear_cost = round((battery_to_home_kwh + battery_export_kwh) * wear_rate, 2)
    energy_net = round(old_import_cost + standing_component - export_income_pence, 2)
    economic_net = round(energy_net + wear_cost, 2)
    fixed_income = round(grid_export_kwh * FIXED_EXPORT_BENCHMARK_PENCE, 2)

    agile.update(
        {
            "grid_export_kwh": grid_export_kwh,
            "solar_export_kwh": solar_export_kwh,
            "solar_to_battery_kwh": solar_to_battery_kwh,
            "solar_to_home_kwh": solar_to_home_kwh,
            "battery_to_home_kwh": battery_to_home_kwh,
            "battery_export_kwh": battery_export_kwh,
            "export_income_pence": export_income_pence,
            "battery_wear_cost_pence": wear_cost,
            "energy_net_cost_pence": energy_net,
            "economic_net_cost_pence": economic_net,
            "fixed_12p_same_dispatch_income_pence": fixed_income,
            "gain_vs_fixed_12p_same_dispatch_pence": round(
                export_income_pence - fixed_income,
                2,
            ),
            "weighted_achieved_export_rate_pence": (
                round(export_income_pence / grid_export_kwh, 4)
                if grid_export_kwh > 0
                else None
            ),
            "export_accounting_source": SETTLEMENT_SOURCE,
            "import_accounting_source": "existing Agile day replay",
            "settled_shadow_slots": applied,
        }
    )
    _reconcile_comparison(today)

    diagnostic = {
        "active": True,
        "applied": True,
        "settled_slots_applied": applied,
        "grid_export_kwh": grid_export_kwh,
        "battery_export_kwh": battery_export_kwh,
        "battery_to_home_kwh": battery_to_home_kwh,
        "export_income_pence": export_income_pence,
        "economic_net_cost_pence": economic_net,
        "export_accounting_source": SETTLEMENT_SOURCE,
        "import_accounting_source": "existing Agile day replay",
        "hardware_writes": "blocked",
    }
    state["current_day_settlement_reconciliation"] = diagnostic
    return diagnostic


class SettledCurrentDayAgileSmartExportManager(
    TomorrowSocHandoffAgileSmartExportManager
):
    """Make completed rolling outcomes authoritative for Today's export ledger."""

    def reconcile_current_day_settlements(
        self,
        *,
        settled_half_hours: list[dict[str, Any]],
        now: datetime,
    ) -> dict[str, Any]:
        """Reconcile and republish Today's completed digital-twin outcomes."""
        diagnostic = reconcile_current_day_settlements(
            self._state,
            settled_half_hours,
            now,
        )
        if diagnostic.get("applied"):
            # Re-publishing through the normal runtime would re-enrich settled
            # slots from the older day replay. Suppress only that enrichment for
            # this settlement publication; all ordinary sensors remain owned by
            # the normal publisher.
            panel_config = self._panel_config
            self._panel_config = None
            try:
                self._publish(self._state)
            finally:
                self._panel_config = panel_config
        return self.state
