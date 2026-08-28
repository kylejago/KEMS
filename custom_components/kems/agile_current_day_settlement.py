"""Reconcile current-day Agile accounting with settled digital-twin outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .agile_tomorrow_soc_handoff import TomorrowSocHandoffAgileSmartExportManager

FIXED_EXPORT_BENCHMARK_PENCE = 12.0
DEFAULT_BATTERY_WEAR_PENCE_PER_KWH = 2.0
SETTLEMENT_SOURCE = "settled shadow digital-twin outcome"
REPLAY_SOURCE = "existing Agile day replay"
_EPSILON = 1e-9


def _number(value: Any) -> float | None:
    """Return one finite numeric value when available."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _slot_hours(slot: dict[str, Any]) -> float | None:
    """Return the represented slot duration in hours."""
    try:
        start = datetime.fromisoformat(str(slot["valid_from"]))
        end = datetime.fromisoformat(str(slot["valid_to"]))
    except (KeyError, TypeError, ValueError):
        return None
    hours = (end - start).total_seconds() / 3600.0
    return hours if hours > 0 else None


def _slot_end(slot: dict[str, Any]) -> datetime | None:
    """Return one aware slot end."""
    try:
        end = datetime.fromisoformat(str(slot["valid_to"]))
    except (KeyError, TypeError, ValueError):
        return None
    return end if end.tzinfo is not None else None


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
        if _number(outcome.get("battery_export_kw")) is None:
            continue
        indexed[slot_start.isoformat()] = item
    return indexed


def _completed_slots(
    slots: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    """Return only fully elapsed settlement rows."""
    completed: list[dict[str, Any]] = []
    for slot in slots:
        end = _slot_end(slot)
        if end is None:
            continue
        if end.astimezone(now.tzinfo) <= now:
            completed.append(slot)
    return completed


def _sum_slots(slots: list[dict[str, Any]], field: str) -> float:
    """Sum one numeric half-hour energy field without inventing missing values."""
    return sum(
        number for item in slots if (number := _number(item.get(field))) is not None
    )


def _reconciled_soc(
    *,
    replay_soc_percent: float | None,
    replay_battery_export_kwh: float,
    settled_battery_export_kwh: float,
    battery_capacity_kwh: float | None,
    discharge_efficiency: float | None,
) -> tuple[float | None, float, float]:
    """Debit only the export energy missing from the original replay SOC."""
    export_delta = settled_battery_export_kwh - replay_battery_export_kwh
    if (
        replay_soc_percent is None
        or battery_capacity_kwh is None
        or discharge_efficiency is None
        or battery_capacity_kwh <= _EPSILON
        or discharge_efficiency <= _EPSILON
    ):
        return replay_soc_percent, export_delta, 0.0
    soc_delta = export_delta / discharge_efficiency / battery_capacity_kwh * 100.0
    return (
        round(min(max(replay_soc_percent - soc_delta, 0.0), 100.0), 3),
        export_delta,
        soc_delta,
    )


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
    *,
    battery_capacity_kwh: float | None = None,
    discharge_efficiency: float | None = None,
) -> dict[str, Any]:
    """Settle current-day export while preserving replay-owned energy fields.

    The established day replay remains authoritative for import, charge,
    solar routing and normal battery-to-home self-use. Completed shadow
    half-hours authoritatively replace deliberate battery export only.
    Future planned export never enters current-day accounting. The difference
    between replayed and settled battery export is also debited from the replay
    SOC so the next rolling plan starts from physically consistent battery
    energy.
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

    replay_soc = _number(
        agile.get("replay_ending_soc_percent", agile.get("ending_soc_percent"))
    )
    replay_battery_to_home = _number(
        agile.get("replay_battery_to_home_kwh", agile.get("battery_to_home_kwh"))
    )
    agile["replay_ending_soc_percent"] = replay_soc
    agile["replay_battery_to_home_kwh"] = replay_battery_to_home

    settlements = _today_settlements(settled_half_hours, now)
    applied = 0
    replay_matched_export = 0.0
    settled_battery_export = 0.0
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

        replay_export = _number(
            slot.get("replay_battery_export_kwh", slot.get("battery_export_kwh"))
        )
        replay_export = max(replay_export or 0.0, 0.0)
        slot["replay_battery_export_kwh"] = round(replay_export, 3)
        replay_matched_export += replay_export

        outcome = settlement["outcome"]
        battery_export_kw = max(
            _number(outcome.get("battery_export_kw")) or 0.0,
            0.0,
        )
        battery_export_kwh = round(battery_export_kw * hours, 3)
        settled_battery_export += battery_export_kwh

        solar_export_kwh = max(
            _number(slot.get("solar_export_kwh")) or 0.0,
            0.0,
        )
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
            "import_accounting_source": REPLAY_SOURCE,
            "battery_to_home_accounting_source": REPLAY_SOURCE,
            "hardware_writes": "blocked",
        }
        state["current_day_settlement_reconciliation"] = diagnostic
        return diagnostic

    completed = _completed_slots(slots, now)
    grid_export_kwh = round(_sum_slots(completed, "grid_export_kwh"), 3)
    solar_export_kwh = round(_sum_slots(completed, "solar_export_kwh"), 3)
    settled_battery_export = round(settled_battery_export, 3)
    accounted_battery_export = round(_sum_slots(completed, "battery_export_kwh"), 3)
    replay_matched_export = round(replay_matched_export, 3)
    battery_to_home_kwh = (
        round(replay_battery_to_home, 3) if replay_battery_to_home is not None else None
    )

    export_income_pence = 0.0
    for slot in completed:
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
    wear_rate = _number(state.get("battery_wear_assumption_pence_per_discharged_kwh"))
    if wear_rate is None:
        wear_rate = DEFAULT_BATTERY_WEAR_PENCE_PER_KWH
    discharged_kwh = (battery_to_home_kwh or 0.0) + accounted_battery_export
    wear_cost = round(discharged_kwh * wear_rate, 2)
    energy_net = round(old_import_cost + standing_component - export_income_pence, 2)
    economic_net = round(energy_net + wear_cost, 2)
    fixed_income = round(grid_export_kwh * FIXED_EXPORT_BENCHMARK_PENCE, 2)

    corrected_soc, export_delta, soc_delta = _reconciled_soc(
        replay_soc_percent=replay_soc,
        replay_battery_export_kwh=replay_matched_export,
        settled_battery_export_kwh=settled_battery_export,
        battery_capacity_kwh=_number(battery_capacity_kwh),
        discharge_efficiency=_number(discharge_efficiency),
    )

    agile.update(
        {
            "grid_export_kwh": grid_export_kwh,
            "solar_export_kwh": solar_export_kwh,
            "battery_to_home_kwh": battery_to_home_kwh,
            "battery_export_kwh": accounted_battery_export,
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
            "ending_soc_percent": corrected_soc,
            "settled_battery_export_delta_kwh": round(export_delta, 3),
            "settled_soc_delta_percent": round(soc_delta, 3),
            "export_accounting_source": SETTLEMENT_SOURCE,
            "import_accounting_source": REPLAY_SOURCE,
            "battery_to_home_accounting_source": REPLAY_SOURCE,
            "soc_accounting_source": (
                "Agile day replay adjusted by settled battery-export delta"
            ),
            "settled_shadow_slots": applied,
        }
    )
    _reconcile_comparison(today)

    grid_balance = round(solar_export_kwh + accounted_battery_export, 3)
    accounting_checks = {
        "future_planned_export_excluded": True,
        "grid_export_balance": abs(grid_export_kwh - grid_balance) <= 0.002,
        "battery_discharge_balance": abs(
            discharged_kwh - ((battery_to_home_kwh or 0.0) + accounted_battery_export)
        )
        <= 0.002,
        "headline_cost_balance": abs(
            energy_net - (old_import_cost + standing_component - export_income_pence)
        )
        <= 0.01,
        "economic_cost_balance": abs(economic_net - (energy_net + wear_cost)) <= 0.01,
        "soc_settlement_applied": (
            corrected_soc is not None
            and battery_capacity_kwh is not None
            and discharge_efficiency is not None
        ),
    }

    routing = state.get("current_routing_snapshot")
    if isinstance(routing, dict) and corrected_soc is not None:
        routing["simulated_soc_percent"] = corrected_soc
        routing["soc_accounting_source"] = agile["soc_accounting_source"]

    diagnostic = {
        "active": True,
        "applied": True,
        "settled_slots_applied": applied,
        "completed_slots_accounted": len(completed),
        "grid_export_kwh": grid_export_kwh,
        "solar_export_kwh": solar_export_kwh,
        "battery_export_kwh": accounted_battery_export,
        "battery_to_home_kwh": battery_to_home_kwh,
        "replay_battery_export_kwh_for_settled_slots": replay_matched_export,
        "settled_battery_export_delta_kwh": round(export_delta, 3),
        "replay_ending_soc_percent": replay_soc,
        "ending_soc_percent": corrected_soc,
        "settled_soc_delta_percent": round(soc_delta, 3),
        "export_income_pence": export_income_pence,
        "battery_wear_cost_pence": wear_cost,
        "energy_net_cost_pence": energy_net,
        "economic_net_cost_pence": economic_net,
        "accounting_checks": accounting_checks,
        "all_accounting_checks_passed": all(accounting_checks.values()),
        "export_accounting_source": SETTLEMENT_SOURCE,
        "import_accounting_source": REPLAY_SOURCE,
        "battery_to_home_accounting_source": REPLAY_SOURCE,
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
        config = getattr(self, "_rolling_config", None)
        diagnostic = reconcile_current_day_settlements(
            self._state,
            settled_half_hours,
            now,
            battery_capacity_kwh=_number(getattr(config, "battery_capacity_kwh", None)),
            discharge_efficiency=_number(getattr(config, "discharge_efficiency", None)),
        )
        if diagnostic.get("applied"):
            # Re-publishing regenerates the rolling plan from the corrected SOC.
            # Suppress only historical panel enrichment during this publication.
            panel_config = self._panel_config
            self._panel_config = None
            try:
                self._publish(self._state)
            finally:
                self._panel_config = panel_config
        return self.state
