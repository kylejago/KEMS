"""Net-site settlement reconciliation for Full KEMS Agile free-charge events.

Weekend Happy Hour is represented to the core replay as a temporary free charge
window so battery energy carries naturally into later Agile decisions.  The
legacy cheap-window replay records gross grid import and gross solar export as
separate flows, which is useful internally but is not a valid single site-meter
settlement state.  This layer converts only manually projected daytime cheap
slots to one net import-or-export route while preserving the same house energy
and battery charge.

The authoritative overnight schedule, 100% charge intent, 10% reserve, price
optimiser and hardware-write boundary are unchanged.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .kems_core import SimulationConfig
from .tariff import TariffSettings

_EPSILON = 1e-6
_EVENT_MARKER = "_kems_happy_hour_net_route"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _manual_event_slot_starts(
    records: list[Any],
    rates: list[Any],
    tariff: TariffSettings,
) -> set[datetime]:
    """Find daytime snapshots projected to cheap only by the manual event layer."""
    starts: set[datetime] = set()
    for item in records:
        if not bool(getattr(item, "cheap_period_confirmed", False)):
            continue
        local = item.timestamp.astimezone(agile.LONDON)
        if agile._in_window(local.time(), tariff.offpeak_start, tariff.offpeak_end):
            continue
        rate = agile._rate_at(rates, item.timestamp)
        if rate is not None:
            starts.add(rate.valid_from.astimezone(UTC))
    return starts


def _slot_energy(
    self,
    records: list[Any],
    start: datetime,
    end: datetime,
    config: SimulationConfig,
) -> tuple[float, float, float]:
    """Return observed/proposal house, solar and covered hours for a slot."""
    house = 0.0
    solar = 0.0
    hours_total = 0.0
    ordered = sorted(records, key=lambda item: item.timestamp)
    for current, following in zip(ordered, ordered[1:], strict=False):
        moment = current.timestamp.astimezone(UTC)
        if moment < start or moment >= end:
            continue
        hours = min(
            max((following.timestamp - current.timestamp).total_seconds(), 0.0)
            / 3600.0,
            0.5,
        )
        load = agile._load(current)
        if hours <= 0.0 or load is None:
            continue
        house += load * hours
        solar += self._simulation._simulated_solar_power(current, config) * hours
        hours_total += hours
    return max(house, 0.0), max(solar, 0.0), hours_total


def _net_event_slot(
    self,
    item: dict[str, Any],
    records: list[Any],
    config: SimulationConfig,
) -> dict[str, float] | None:
    """Replace gross event import/export with one physically net site route."""
    start = _dt(item.get("valid_from"))
    end = _dt(item.get("valid_to"))
    if start is None or end is None:
        return None
    house, solar, hours = _slot_energy(self, records, start, end, config)
    if hours <= 0.0:
        return None

    old_import = max(_number(item.get("grid_import_kwh")) or 0.0, 0.0)
    old_export = max(_number(item.get("grid_export_kwh")) or 0.0, 0.0)
    old_solar_stored = max(
        _number(item.get("solar_to_battery_kwh")) or 0.0,
        0.0,
    )
    efficiency = max(config.charge_efficiency, 0.01)
    old_solar_charge_input = old_solar_stored / efficiency
    old_grid_charge_input = max(old_import - house, 0.0)
    total_charge_input = old_solar_charge_input + old_grid_charge_input

    inverter_energy = max(config.inverter_limit_kw, 0.0) * hours
    export_energy = min(
        max(config.export_limit_kw, 0.0) * hours,
        inverter_energy,
    )
    solar_to_home = min(solar, house, inverter_energy)
    remaining_solar = max(solar - solar_to_home, 0.0)
    solar_to_battery_input = min(remaining_solar, total_charge_input)
    remaining_solar -= solar_to_battery_input
    grid_to_battery_input = max(total_charge_input - solar_to_battery_input, 0.0)
    grid_to_home = max(house - solar_to_home, 0.0)

    battery_export = max(
        _number(item.get("battery_export_kwh")) or 0.0,
        0.0,
    )
    inverter_headroom = max(
        inverter_energy - solar_to_home - total_charge_input - battery_export,
        0.0,
    )
    solar_export = min(remaining_solar, export_energy, inverter_headroom)
    gross_import = grid_to_home + grid_to_battery_input
    gross_export = solar_export + battery_export
    net = gross_import - gross_export
    grid_import = max(net, 0.0)
    grid_export = max(-net, 0.0)

    # Event policy never deliberately discharges the battery.  Keep this guard
    # explicit so a future upstream regression cannot hide behind netting.
    if battery_export > _EPSILON:
        grid_export = max(grid_export - battery_export, 0.0)
        battery_export = 0.0

    solar_to_battery_stored = solar_to_battery_input * efficiency
    grid_to_battery_stored = grid_to_battery_input * efficiency
    site_solar_export = grid_export

    item.update(
        {
            "grid_import_kwh": round(grid_import, 3),
            "grid_export_kwh": round(grid_export, 3),
            "solar_export_kwh": round(site_solar_export, 3),
            "solar_to_battery_kwh": round(solar_to_battery_stored, 3),
            "battery_export_kwh": 0.0,
            "event_solar_to_home_kwh": round(solar_to_home, 3),
            "event_grid_to_battery_kwh": round(grid_to_battery_stored, 3),
            "happy_hour_net_site_flow": True,
            _EVENT_MARKER: True,
        }
    )
    actions = list(item.get("actions") or [])
    action = "Happy Hour free charge — reconciled to net site-meter flow"
    if action not in actions:
        actions.append(action)
    item["actions"] = actions
    return {
        "old_import": old_import,
        "old_export": old_export,
        "new_import": grid_import,
        "new_export": grid_export,
        "solar_to_home": solar_to_home,
        "old_solar_stored": old_solar_stored,
        "new_solar_stored": solar_to_battery_stored,
        "new_grid_stored": grid_to_battery_stored,
    }


def _recalculate_event_summary(
    summary: dict[str, Any],
    plan: list[dict[str, Any]],
    rates: list[Any],
    deltas: list[dict[str, float]],
) -> dict[str, Any]:
    """Keep daily settlement/economics aligned with the net event route."""
    result = dict(summary)
    actual_rates = {
        rate.valid_from.astimezone(UTC).isoformat(): float(rate.value_inc_vat)
        for rate in rates
    }
    export = 0.0
    solar_export = 0.0
    battery_export = 0.0
    income = 0.0
    for item in plan:
        start = _dt(item.get("valid_from"))
        if start is None:
            continue
        exported = max(_number(item.get("grid_export_kwh")) or 0.0, 0.0)
        export += exported
        solar_export += max(_number(item.get("solar_export_kwh")) or 0.0, 0.0)
        battery_export += max(_number(item.get("battery_export_kwh")) or 0.0, 0.0)
        income += exported * actual_rates.get(start.isoformat(), 0.0)

    import_delta = sum(item["new_import"] - item["old_import"] for item in deltas)
    solar_home_delta = sum(item["solar_to_home"] for item in deltas)
    solar_stored_delta = sum(
        item["new_solar_stored"] - item["old_solar_stored"] for item in deltas
    )
    grid_stored = sum(item["new_grid_stored"] for item in deltas)
    old_grid_stored = max(
        _number(result.get("grid_to_battery_kwh")) or 0.0,
        0.0,
    )
    event_old_grid_stored = sum(
        max(
            (item["old_import"] - item["solar_to_home"])
            * 0.0,
            0.0,
        )
        for item in deltas
    )
    del event_old_grid_stored

    old_income = _number(result.get("export_income_pence")) or 0.0
    import_cost = _number(result.get("import_cost_pence")) or 0.0
    old_energy = _number(result.get("energy_net_cost_pence")) or 0.0
    standing = old_energy - import_cost + old_income
    wear = max(_number(result.get("battery_wear_cost_pence")) or 0.0, 0.0)
    fixed_income = export * agile.FIXED_EXPORT_PENCE
    energy_cost = import_cost + standing - income

    result.update(
        {
            "grid_import_kwh": round(
                max(
                    (_number(result.get("grid_import_kwh")) or 0.0) + import_delta,
                    0.0,
                ),
                3,
            ),
            "grid_export_kwh": round(export, 3),
            "solar_export_kwh": round(solar_export, 3),
            "battery_export_kwh": round(battery_export, 3),
            "solar_to_home_kwh": round(
                (_number(result.get("solar_to_home_kwh")) or 0.0)
                + solar_home_delta,
                3,
            ),
            "solar_to_battery_kwh": round(
                max(
                    (_number(result.get("solar_to_battery_kwh")) or 0.0)
                    + solar_stored_delta,
                    0.0,
                ),
                3,
            ),
            "grid_to_battery_kwh": round(
                max(old_grid_stored + grid_stored, 0.0),
                3,
            ),
            "export_income_pence": round(income, 2),
            "fixed_12p_same_dispatch_income_pence": round(fixed_income, 2),
            "gain_vs_fixed_12p_same_dispatch_pence": round(
                income - fixed_income,
                2,
            ),
            "energy_net_cost_pence": round(energy_cost, 2),
            "economic_net_cost_pence": round(energy_cost + wear, 2),
            "weighted_achieved_export_rate_pence": (
                round(income / export, 4) if export > _EPSILON else None
            ),
            "happy_hour_net_site_settlement": True,
            "happy_hour_net_site_slots": len(deltas),
        }
    )
    return result


def _install_slot_presentation_parity() -> None:
    """Preserve explicit event route fields through slot/panel enrichment."""
    slot_payload = agile.AgileSmartExportManager._slot_payload
    if not getattr(slot_payload, "_kems_event_settlement_reconciliation", False):
        original_slot_payload = slot_payload

        def slot_payload_with_event_route(self, day, result):
            payload = original_slot_payload(self, day, result)
            explicit = {
                str(item.get("valid_from")): item
                for item in (result or {}).get("slot_plan", [])
                if isinstance(item, dict) and item.get(_EVENT_MARKER)
            }
            for item in payload:
                source = explicit.get(str(item.get("valid_from")))
                if source is None:
                    continue
                item[_EVENT_MARKER] = True
                item["event_solar_to_home_kwh"] = source.get(
                    "event_solar_to_home_kwh"
                )
                item["event_grid_to_battery_kwh"] = source.get(
                    "event_grid_to_battery_kwh"
                )
                item["happy_hour_net_site_flow"] = True
            return payload

        slot_payload_with_event_route._kems_event_settlement_reconciliation = True
        agile.AgileSmartExportManager._slot_payload = slot_payload_with_event_route

    enrich = runtime._enrich_slot_routing
    if getattr(enrich, "_kems_event_settlement_reconciliation", False):
        return
    original_enrich = enrich

    def enrich_with_event_route(slots_value, records, config, simulation):
        original_enrich(slots_value, records, config, simulation)
        if not isinstance(slots_value, list):
            return
        for item in slots_value:
            if not isinstance(item, dict) or not item.get(_EVENT_MARKER):
                continue
            item["solar_to_home_kwh"] = item.get("event_solar_to_home_kwh")
            item["grid_to_battery_kwh"] = item.get("event_grid_to_battery_kwh")
            item["happy_hour_net_site_flow"] = True

    enrich_with_event_route._kems_event_settlement_reconciliation = True
    runtime._enrich_slot_routing = enrich_with_event_route


def install_event_settlement_reconciliation() -> None:
    """Install net event settlement after charge recovery and before presentation."""
    method = agile.AgileSmartExportManager._agile_day
    if not getattr(method, "_kems_event_settlement_reconciliation", False):
        original = method

        def agile_day_with_net_event(
            self,
            records,
            rates,
            config,
            tariff,
            initial_soc,
        ):
            summary, plan = original(
                self,
                records,
                rates,
                config,
                tariff,
                initial_soc,
            )
            event_starts = _manual_event_slot_starts(list(records), rates, tariff)
            if not event_starts:
                return summary, plan
            deltas = []
            for item in plan:
                start = _dt(item.get("valid_from"))
                if start is None or start not in event_starts:
                    continue
                delta = _net_event_slot(self, item, list(records), config)
                if delta is not None:
                    deltas.append(delta)
            if not deltas:
                return summary, plan
            return _recalculate_event_summary(summary, plan, rates, deltas), plan

        agile_day_with_net_event._kems_event_settlement_reconciliation = True
        agile.AgileSmartExportManager._agile_day = agile_day_with_net_event

    _install_slot_presentation_parity()
