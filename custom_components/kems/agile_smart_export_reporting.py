"""Reporting refinements for Agile Smart Export.

This layer keeps the proven optimiser dispatch decisions untouched while
restoring Solar -> Home into comparison payloads, exposing current battery SOC,
and making the hypothetical fixed-rate benchmark explicit in the dashboard.
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from . import agile_smart_export as _base

_BASE_AGGREGATE = _base._aggregate
_BASE_COMPARE_DAY = _base.AgileSmartExportManager._compare_day
_BASE_PUBLISH = _base.AgileSmartExportManager._publish


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


def compare_day_with_solar_to_home(
    self,
    records,
    config,
    tariff,
    agile_soc,
    full_soc,
    learned_forecast,
    projection=False,
):
    """Add Full KEMS Solar -> Home without changing either dispatch strategy."""
    result = _BASE_COMPARE_DAY(
        self,
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


def _planned_soc_now(state: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    """Return the Agile plan SOC at the end of the current half-hour slot."""
    generated_at = state.get("generated_at")
    if not generated_at:
        return None, {"available": False}
    try:
        now = datetime.fromisoformat(str(generated_at)).astimezone(UTC)
    except ValueError:
        return None, {"available": False}

    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        try:
            start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
            end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
        except (KeyError, ValueError):
            continue
        if start <= now < end:
            value = slot.get("ending_soc_percent")
            return (
                (float(value) if value is not None else None),
                {
                    "available": value is not None,
                    "slot": slot.get("label"),
                    "valid_from": slot.get("valid_from"),
                    "valid_to": slot.get("valid_to"),
                    "meaning": "simulated battery SOC at the end of the current Agile half-hour slot",
                },
            )
    return None, {"available": False}


def publish_with_planned_soc(self, state: dict[str, Any]) -> None:
    """Publish normal Agile entities plus the current planned battery SOC."""
    _BASE_PUBLISH(self, state)
    value, attrs = _planned_soc_now(state)
    self._set(
        "sensor.kems_agile_planned_battery_soc_now",
        _base._state(value),
        {
            "friendly_name": "Agile Smart Export planned battery SOC now",
            "unit_of_measurement": "%",
            "mode": "simulation_only",
            **attrs,
        },
    )


def install_reporting_patch() -> None:
    """Install aggregate, day-summary, SOC, and dashboard reporting patches once."""
    if not getattr(_base._aggregate, "_kems_solar_home_reporting", False):
        aggregate_with_solar_to_home._kems_solar_home_reporting = True
        _base._aggregate = aggregate_with_solar_to_home

    compare = _base.AgileSmartExportManager._compare_day
    if not getattr(compare, "_kems_solar_home_reporting", False):
        compare_day_with_solar_to_home._kems_solar_home_reporting = True
        _base.AgileSmartExportManager._compare_day = compare_day_with_solar_to_home

    publish = _base.AgileSmartExportManager._publish
    if not getattr(publish, "_kems_soc_reporting", False):
        publish_with_planned_soc._kems_soc_reporting = True
        _base.AgileSmartExportManager._publish = publish_with_planned_soc

    try:
        from . import dashboard as dashboard_module
    except ImportError:
        return

    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_agile_reporting", False):
        return

    def combined_master_dashboard_bytes() -> bytes:
        content = original().decode()

        solar_needle = (
            "          | Solar export | {{ full.get('solar_export_kwh', '—') }} kWh | "
            "{{ agile.get('solar_export_kwh', '—') }} kWh |\n"
        )
        solar_row = (
            "          | Solar → home | {{ full.get('solar_to_home_kwh', '—') }} kWh | "
            "{{ agile.get('solar_to_home_kwh', '—') }} kWh |\n"
        )
        if solar_row not in content and solar_needle in content:
            content = content.replace(solar_needle, solar_needle + solar_row, 1)

        plan_entity = (
            "          - entity: sensor.kems_agile_smart_export_plan\n"
            "            name: Current Smart Export action\n"
        )
        soc_entities = (
            "          - entity: sensor.kems_battery_state_of_charge\n"
            "            name: Live battery SOC\n"
            "          - entity: sensor.kems_agile_planned_battery_soc_now\n"
            "            name: Agile planned SOC — end of current slot\n"
        )
        if soc_entities not in content and plan_entity in content:
            content = content.replace(plan_entity, plan_entity + soc_entities, 1)

        history_entity = (
            "          - type: entity\n"
            "            entity: sensor.kems_agile_history_coverage\n"
            "            name: Historical replay coverage\n"
            "            icon: mdi:calendar-check-outline\n"
        )
        backfill_entity = (
            "          - type: entity\n"
            "            entity: sensor.kems_agile_history_backfill\n"
            "            name: HA statistics backfill coverage\n"
            "            icon: mdi:database-clock-outline\n"
        )
        if backfill_entity not in content and history_entity in content:
            content = content.replace(
                history_entity,
                history_entity + backfill_entity,
                1,
            )

        replacements = {
            "Tariff-only benchmark today": "Hypothetical fixed-rate benchmark today",
            "Agile income gain vs fixed 12p": "Extra Agile income vs hypothetical 12p",
            "Fixed 12p income on same dispatch": "Hypothetical income at 12p — same dispatch",
            "Fixed 12p income on Agile dispatch": "Hypothetical income at 12p — same dispatch",
            "Agile tariff gain vs fixed 12p": "Extra income from Agile pricing vs 12p benchmark",
            "365-day Agile tariff gain vs 12p": "365-day Agile pricing gain vs 12p benchmark",
            "All-time Agile tariff gain vs 12p": "All-time Agile pricing gain vs 12p benchmark",
            "Agile tariff gain vs 12p |": "Agile pricing gain vs 12p benchmark |",
        }
        for old, new in replacements.items():
            content = content.replace(old, new)

        battery_export_row = (
            "          | Battery export | {{ full.get('battery_export_kwh', '—') }} kWh | "
            "{{ agile.get('battery_export_kwh', '—') }} kWh |\n"
        )
        end_soc_row = (
            "          | End battery SOC | {{ (full.get('ending_soc_percent') ~ '%') if "
            "full.get('ending_soc_percent') is not none else '—' }} | {{ "
            "(agile.get('ending_soc_percent') ~ '%') if agile.get('ending_soc_percent') "
            "is not none else '—' }} |\n"
        )
        if end_soc_row not in content and battery_export_row in content:
            content = content.replace(
                battery_export_row,
                battery_export_row + end_soc_row,
                1,
            )

        old_history = (
            "          **12-month result ready:** {{ h.attributes.twelve_month_ready if h else false }}\n\n"
            "          KEMS does **not** invent missing historical house-load or strategy observations. "
            "The 365-day result becomes authoritative only when this reaches **365/365 valid daily replays**."
        )
        new_history = (
            "          **12-month calculation ready:** {{ h.attributes.twelve_month_ready if h else false }}  \n"
            "          {% set b = states.sensor.kems_agile_history_backfill %}\n"
            "          **Native KEMS days:** {{ b.attributes.native_kems_days if b else '—' }}  \n"
            "          **HA statistics backfilled days:** {{ b.attributes.ha_statistics_backfilled_days if b else '—' }}  \n"
            "          **Insufficient historical days:** {{ b.attributes.insufficient_days if b else '—' }}  \n"
            "          **Backfill resolution:** {{ b.attributes.backfill_resolution if b else '—' }}\n\n"
            "          KEMS does **not** invent missing historical house-load, solar or Intelligent bonus slots. "
            "Native KEMS days retain the original high-resolution observations and forecast decisions. "
            "Backfilled days use Home Assistant hourly long-term statistics and the normal configured off-peak "
            "schedule, so they are clearly labelled as lower-fidelity historical replay rather than native evidence."
        )
        content = content.replace(old_history, new_history)

        old_note = (
            "*The strategy winner uses net energy cost plus the configured simulation "
            "battery-wear allowance. The fixed-12p comparison uses the exact same Agile "
            "dispatch, so it isolates tariff value rather than dispatch changes.*"
        )
        new_note = (
            "*The strategy winner uses net energy cost plus the configured simulation "
            "battery-wear allowance. **12p is only a hypothetical benchmark — it is not "
            "an Agile rate.** KEMS prices the exact same Agile dispatch at a flat 12p/kWh "
            "to isolate the value of Agile's variable half-hour pricing from the value of "
            "changing the dispatch itself.*"
        )
        content = content.replace(old_note, new_note)
        return content.encode()

    combined_master_dashboard_bytes._kems_agile_reporting = True
    dashboard_module._combined_master_dashboard_bytes = combined_master_dashboard_bytes
