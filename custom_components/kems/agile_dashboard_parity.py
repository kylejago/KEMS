"""Canonical same-window Agile reporting and dashboard parity.

This Alpha8 module carries forward the proven Alpha7.44 reporting-only
behaviour without keeping the version-named patch module in the executable
runtime chain.

It keeps the optimiser and event-priority logic untouched while ensuring that:

* simulated house energy is measured directly from the retained demand
  intervals used by the Agile replay;
* period aggregation carries solar generation, solar-to-home and
  grid-to-battery evidence;
* the Today table compares actual and simulated values over the same
  midnight-to-now window using the headline bill basis; and
* every Agile half-hour settlement slot is reported with the current KEMS
  decision without guessing unpublished prices.

Real FoxESS hardware writes remain blocked.
"""

# ruff: noqa: E501

from __future__ import annotations

import math
from datetime import UTC, datetime, time, timedelta
from typing import Any

from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .tariff import TariffSettings

_TODAY_SUMMARY = "sensor.kems_agile_today_to_now_summary"
_SLOT_DECISIONS = "sensor.kems_agile_slot_decisions_today"
_SENSOR_IDS = (_TODAY_SUMMARY, _SLOT_DECISIONS)

_TODAY_CARD_START = """      - type: markdown
        title: Today totals — actual vs Full KEMS Agile
"""
_PLAN_GRID_START = """      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Plan now
"""

_REPLACEMENT_CARDS = r"""      - type: markdown
        title: Today so far — actual vs Full KEMS Agile
        content: |
          {% set live = state_attr('sensor.kems_agile_live_today_summary', 'totals') or {} %}
          {% set sim = state_attr('sensor.kems_agile_today_to_now_summary', 'simulated') or {} %}
          | Metric | Actual / observed | Agile simulation |
          |---|---:|---:|
          | House energy | {{ states('sensor.kems_whole_home_energy_today') }} kWh | {{ (sim.get('house_energy_kwh') | round(3)) if sim.get('house_energy_kwh') is not none else '—' }}{% if sim.get('house_energy_kwh') is not none %} kWh{% endif %} |
          | Solar generation | {{ (live.get('solar_generation_kwh') | round(3)) if live.get('solar_generation_kwh') is not none else '—' }}{% if live.get('solar_generation_kwh') is not none %} kWh{% endif %} | {{ (sim.get('solar_generation_kwh') | round(3)) if sim.get('solar_generation_kwh') is not none else '—' }}{% if sim.get('solar_generation_kwh') is not none %} kWh{% endif %} |
          | Grid import | {{ states('sensor.kems_observed_grid_import_today') }} kWh | {{ (sim.get('grid_import_kwh') | round(3)) if sim.get('grid_import_kwh') is not none else '—' }}{% if sim.get('grid_import_kwh') is not none %} kWh{% endif %} |
          | Grid export | {{ states('sensor.kems_observed_grid_export_today') }} kWh | {{ (sim.get('grid_export_kwh') | round(3)) if sim.get('grid_export_kwh') is not none else '—' }}{% if sim.get('grid_export_kwh') is not none %} kWh{% endif %} |
          | Battery charged | {{ (live.get('battery_charge_kwh') | round(3)) if live.get('battery_charge_kwh') is not none else '—' }}{% if live.get('battery_charge_kwh') is not none %} kWh{% endif %} | {{ (sim.get('battery_charge_kwh') | round(3)) if sim.get('battery_charge_kwh') is not none else '—' }}{% if sim.get('battery_charge_kwh') is not none %} kWh{% endif %} |
          | Battery discharged | {{ (live.get('battery_discharge_kwh') | round(3)) if live.get('battery_discharge_kwh') is not none else '—' }}{% if live.get('battery_discharge_kwh') is not none %} kWh{% endif %} | {{ (sim.get('battery_discharge_kwh') | round(3)) if sim.get('battery_discharge_kwh') is not none else '—' }}{% if sim.get('battery_discharge_kwh') is not none %} kWh{% endif %} |
          | Export income | {{ states('sensor.kems_observed_export_income_today') }} p | {{ (sim.get('export_income_pence') | round(2)) if sim.get('export_income_pence') is not none else '—' }}{% if sim.get('export_income_pence') is not none %} p{% endif %} |
          | Headline electricity bill | **{{ states('sensor.kems_observed_cost_today') }} p** | **{{ (sim.get('headline_bill_pence') | round(2)) if sim.get('headline_bill_pence') is not none else '—' }}{% if sim.get('headline_bill_pence') is not none %} p{% endif %}** |
          | Economic outcome incl. battery wear | — | {{ (sim.get('economic_outcome_pence') | round(2)) if sim.get('economic_outcome_pence') is not none else '—' }}{% if sim.get('economic_outcome_pence') is not none %} p{% endif %} |

          *Both columns cover the same midnight-to-now demand window. A larger simulated grid-import total can be correct when KEMS used cheap power to charge the simulated battery. Missing physical solar/battery sources remain unavailable rather than being replaced with zero.*

      - type: markdown
        title: Period bill summary
        content: |
          {% set periods = state_attr('sensor.kems_agile_smart_export_plan', 'periods') or {} %}
          | Period | Actual / observed | Full KEMS Agile simulation |
          |---|---:|---:|
          | Today | {{ states('sensor.kems_observed_cost_today') }} p | {{ ((periods.get('today', {}) or {}).get('agile_smart_export', {}) or {}).get('energy_net_cost_pence', '—') }} p |
          | Last 7 days | {{ states('sensor.kems_week_energy_summary') }} p | {{ ((periods.get('7_days', {}) or {}).get('agile_smart_export', {}) or {}).get('energy_net_cost_pence', '—') }} p |
          | Last 30 days | {{ states('sensor.kems_month_energy_summary') }} p | {{ ((periods.get('30_days', {}) or {}).get('agile_smart_export', {}) or {}).get('energy_net_cost_pence', '—') }} p |
          | All tracked | {{ states('sensor.kems_all_time_energy_summary') }} p | {{ ((periods.get('all_time', {}) or {}).get('agile_smart_export', {}) or {}).get('energy_net_cost_pence', '—') }} p |

          *Headline bill basis: import cost + standing charge − export income. Battery-wear assumptions remain available in KEMS diagnostics and the Today economic-outcome row.*

      - type: markdown
        title: Today's Agile half-hour slots and decisions
        content: |
          Octopus Agile settles every 30 minutes, so KEMS shows each half-hour rather than combining two potentially different prices into one hourly row.

          {% set slots = state_attr('sensor.kems_agile_slot_decisions_today', 'slots') or [] %}
          | Slot | Price | KEMS decision |
          |---|---:|---|
          {% for slot in slots %}| {{ '▶ ' if slot.get('status') == 'current' else '' }}{{ slot.get('label') }} | {{ (slot.get('rate_pence') | round(2)) if slot.get('rate_pence') is not none else '—' }}{% if slot.get('rate_pence') is not none %}p{% endif %} | {{ slot.get('decision') }} |
          {% endfor %}
"""


def _number(value: Any) -> float | None:
    """Return a finite number when possible."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _dt(value: Any) -> datetime | None:
    """Return one aware UTC timestamp."""
    if isinstance(value, datetime):
        parsed = value
    elif value is not None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _house_energy(records: list[Any]) -> float | None:
    """Integrate the demand intervals used by the Agile replay."""
    total = 0.0
    samples = 0
    for current, following in zip(records, records[1:], strict=False):
        hours = min(
            max((following.timestamp - current.timestamp).total_seconds(), 0.0)
            / 3600.0,
            0.5,
        )
        if hours <= 0:
            continue
        load = agile._load(current)
        if load is None:
            continue
        total += max(float(load), 0.0) * hours
        samples += 1
    return round(total, 3) if samples else None


def _augment_aggregate(
    days: list[dict[str, Any]],
    key: str,
    label: str,
) -> dict[str, Any]:
    """Preserve flow evidence that the legacy period aggregator dropped."""
    result = _original_aggregate(days, key, label)
    if not result.get("ready"):
        return result
    ready = [item for item in days if item and item.get("ready")]
    for strategy_name in ("agile_smart_export", "full_kems_forecast"):
        target = result.get(strategy_name)
        if not isinstance(target, dict):
            continue
        source_items = [
            item.get(strategy_name)
            for item in ready
            if isinstance(item.get(strategy_name), dict)
        ]
        for field in (
            "house_load_kwh",
            "solar_generation_kwh",
            "solar_to_home_kwh",
            "grid_to_battery_kwh",
        ):
            values = [
                _number(item.get(field))
                for item in source_items
                if item.get(field) is not None
            ]
            values = [value for value in values if value is not None]
            if values:
                target[field] = round(sum(values), 3)
    return result


def _event_overlap(
    event: dict[str, Any],
    slot_start: datetime,
    slot_end: datetime,
) -> bool:
    start = _dt(event.get("start"))
    end = _dt(event.get("end"))
    return bool(start and end and start < slot_end and end > slot_start)


def _friendly_actions(actions: Any) -> str:
    """Turn historical simulation action labels into compact operator wording."""
    values = [str(item) for item in actions or [] if str(item) != "future slot"]
    if not values:
        return "Hold battery / normal solar"
    labels = {
        "store solar": "Store solar",
        "cheap charge": "Cheap charge",
        "export solar": "Solar export",
        "battery to home": "Battery → home",
        "protected import": "Protected grid import",
        "store solar for higher Agile slot": "Store solar for later",
        "export battery at high Agile price": "Battery export",
    }
    return " + ".join(
        labels.get(item, item.replace("_", " ").title()) for item in values
    )


def _slot_decisions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Build every expected local-day Agile half-hour with the live plan decision."""
    now = _dt(state.get("generated_at"))
    if now is None:
        return []
    local_now = now.astimezone(agile.LONDON)
    day = local_now.date()
    start_local = datetime.combine(day, time.min, tzinfo=agile.LONDON)
    end_local = datetime.combine(
        day + timedelta(days=1),
        time.min,
        tzinfo=agile.LONDON,
    )
    cursor = start_local.astimezone(UTC)
    end = end_local.astimezone(UTC)

    published = {
        str(item.get("valid_from")): item
        for item in state.get("today_slots", [])
        if isinstance(item, dict) and item.get("valid_from")
    }
    rolling_state = self._hass.states.get("sensor.kems_agile_rolling_export_plan")
    rolling_attrs = dict(rolling_state.attributes) if rolling_state is not None else {}
    selected = {
        str(item.get("valid_from")): item
        for item in rolling_attrs.get("selected_slots", [])
        if isinstance(item, dict) and item.get("valid_from")
    }
    power_down = state.get("power_down_priority")
    power_down = power_down if isinstance(power_down, dict) else {}
    happy = state.get("happy_hour_plan")
    happy = happy if isinstance(happy, dict) else {}
    tariff = getattr(self, "_rolling_tariff", None)

    output: list[dict[str, Any]] = []
    while cursor < end:
        slot_end = min(cursor + timedelta(minutes=30), end)
        key = cursor.isoformat()
        item = published.get(key)
        chosen = selected.get(key)
        local = cursor.astimezone(agile.LONDON)
        if slot_end <= now:
            status = "past"
        elif cursor <= now < slot_end:
            status = "current"
        else:
            status = "future"

        if power_down.get("available") and _event_overlap(power_down, cursor, slot_end):
            decision = "Power Down — house first + maximum safe export"
        elif happy.get("available") and _event_overlap(happy, cursor, slot_end):
            decision = "Happy Hour — maximum safe battery charge"
        elif isinstance(chosen, dict):
            energy = max(
                _number(chosen.get("planned_battery_export_kwh")) or 0.0,
                0.0,
            )
            if chosen.get("happy_hour_headroom_preparation"):
                decision = f"Happy Hour prep — export {energy:.3f} kWh"
            elif chosen.get("deadline_forced"):
                decision = f"Deadline guard — export {energy:.3f} kWh"
            else:
                decision = f"Planned battery export {energy:.3f} kWh"
        elif isinstance(tariff, TariffSettings) and agile._in_window(
            local.time(), tariff.offpeak_start, tariff.offpeak_end
        ):
            decision = "Cheap period — charge battery / home from grid"
        elif item is None:
            decision = (
                "Waiting for Octopus price — capacity reserved"
                if status == "future"
                else "Price unavailable — no deliberate battery export"
            )
        elif status == "past":
            decision = _friendly_actions(item.get("actions"))
        else:
            decision = "Hold battery / normal solar routing"

        output.append(
            {
                "valid_from": key,
                "valid_to": slot_end.isoformat(),
                "label": local.strftime("%H:%M"),
                "status": status,
                "rate_pence": _number(item.get("rate_pence")) if item else None,
                "known_price": item is not None,
                "decision": decision,
                "planned_battery_export_kwh": (
                    round(
                        max(
                            _number(chosen.get("planned_battery_export_kwh")) or 0.0,
                            0.0,
                        ),
                        3,
                    )
                    if isinstance(chosen, dict)
                    else 0.0
                ),
                "ending_soc_percent": (
                    _number(item.get("ending_soc_percent")) if item else None
                ),
            }
        )
        cursor = slot_end
    return output


def _simulated_today(state: dict[str, Any]) -> dict[str, Any]:
    periods = state.get("periods")
    periods = periods if isinstance(periods, dict) else {}
    today = periods.get("today")
    today = today if isinstance(today, dict) else {}
    sim = today.get("agile_smart_export")
    sim = sim if isinstance(sim, dict) else {}
    solar_charge = _number(sim.get("solar_to_battery_kwh"))
    grid_charge = _number(sim.get("grid_to_battery_kwh"))
    battery_home = _number(sim.get("battery_to_home_kwh"))
    battery_export = _number(sim.get("battery_export_kwh"))
    return {
        "house_energy_kwh": _number(sim.get("house_load_kwh")),
        "solar_generation_kwh": _number(sim.get("solar_generation_kwh")),
        "grid_import_kwh": _number(sim.get("grid_import_kwh")),
        "grid_export_kwh": _number(sim.get("grid_export_kwh")),
        "battery_charge_kwh": (
            round((solar_charge or 0.0) + (grid_charge or 0.0), 3)
            if solar_charge is not None or grid_charge is not None
            else None
        ),
        "battery_discharge_kwh": (
            round((battery_home or 0.0) + (battery_export or 0.0), 3)
            if battery_home is not None or battery_export is not None
            else None
        ),
        "export_income_pence": _number(sim.get("export_income_pence")),
        "headline_bill_pence": _number(sim.get("energy_net_cost_pence")),
        "economic_outcome_pence": _number(sim.get("economic_net_cost_pence")),
        "battery_wear_cost_pence": _number(sim.get("battery_wear_cost_pence")),
        "data_coverage": _number(sim.get("data_coverage")),
    }


def improve_dashboard_parity(content: str) -> str:
    """Replace the incorrect totals card and add the compact slot table."""
    start = content.find(_TODAY_CARD_START)
    if start < 0:
        raise ValueError("Agile Today totals dashboard marker missing")
    plan = content.find(_PLAN_GRID_START, start)
    if plan < 0:
        raise ValueError("Agile Plan now dashboard marker missing")
    return content[:start] + _REPLACEMENT_CARDS.rstrip() + "\n\n" + content[plan:]


def install_dashboard_parity() -> None:
    """Install same-window totals, period flow parity and slot decisions."""
    global _original_aggregate

    aggregate = agile._aggregate
    if not getattr(aggregate, "_kems_dashboard_parity", False):
        _original_aggregate = aggregate
        _augment_aggregate._kems_dashboard_parity = True
        agile._aggregate = _augment_aggregate

    agile_day = agile.AgileSmartExportManager._agile_day
    if not getattr(agile_day, "_kems_dashboard_parity", False):
        original_agile_day = agile_day

        def agile_day_with_dashboard_parity(self, records, *args, **kwargs):
            summary, plan = original_agile_day(self, records, *args, **kwargs)
            summary = dict(summary)
            summary["house_load_kwh"] = _house_energy(records)
            return summary, plan

        agile_day_with_dashboard_parity._kems_dashboard_parity = True
        agile.AgileSmartExportManager._agile_day = agile_day_with_dashboard_parity

    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_dashboard_parity", False):
        original_publish = publish

        def publish_with_dashboard_parity(self, state: dict[str, Any]) -> None:
            original_publish(self, state)
            simulated = _simulated_today(state)
            generated_at = state.get("generated_at")
            ready = simulated.get("house_energy_kwh") is not None
            self._set(
                _TODAY_SUMMARY,
                "Ready" if ready else "Waiting for same-window replay",
                {
                    "friendly_name": "Full KEMS Agile today-to-now summary",
                    "window": "local midnight to latest retained sample",
                    "generated_at": generated_at,
                    "simulated": simulated,
                    "headline_bill_basis": (
                        "import cost + standing charge - export income"
                    ),
                    "economic_outcome_includes_battery_wear": True,
                    "same_demand_window_as_actual": True,
                    "reporting_only": True,
                    "hardware_writes": "blocked",
                },
            )

            slots = _slot_decisions(self, state)
            known = sum(1 for item in slots if item["known_price"])
            selected_count = sum(
                1
                for item in slots
                if float(item.get("planned_battery_export_kwh") or 0.0) > 0
            )
            self._set(
                _SLOT_DECISIONS,
                f"{known}/{len(slots)} prices · {selected_count} export slots",
                {
                    "friendly_name": "Full KEMS Agile slot decisions today",
                    "settlement_period_minutes": 30,
                    "slots": slots,
                    "generated_at": generated_at,
                    "unpublished_prices_are_not_guessed": True,
                    "event_priority": (
                        "safety > Power Down > Happy Hour > Agile price"
                    ),
                    "reporting_only": True,
                    "hardware_writes": "blocked",
                },
            )

        publish_with_dashboard_parity._kems_dashboard_parity = True
        runtime.EfficientAgileSmartExportManager._publish = publish_with_dashboard_parity

    shutdown = runtime.EfficientAgileSmartExportManager.async_shutdown
    if not getattr(shutdown, "_kems_dashboard_parity", False):
        original_shutdown = shutdown

        async def shutdown_with_dashboard_parity(self) -> None:
            await original_shutdown(self)
            for entity_id in _SENSOR_IDS:
                self._hass.states.async_remove(entity_id)

        shutdown_with_dashboard_parity._kems_dashboard_parity = True
        runtime.EfficientAgileSmartExportManager.async_shutdown = (
            shutdown_with_dashboard_parity
        )

    from . import dashboard as dashboard_module

    combined = dashboard_module._combined_master_dashboard_bytes
    if getattr(combined, "_kems_dashboard_parity", False):
        return
    original_dashboard = combined

    def combined_dashboard_parity() -> bytes:
        content = original_dashboard().decode("utf-8")
        return improve_dashboard_parity(content).encode("utf-8")

    combined_dashboard_parity._kems_dashboard_parity = True
    dashboard_module._combined_master_dashboard_bytes = combined_dashboard_parity
