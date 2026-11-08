"""Meter-backed *completed* Happy Hour slot flow presentation.

This is reporting only. The independent reward-hour financial ledger remains
unchanged and is authoritative for credit estimates. Source-side routing is
explicitly inferred from validated physical energy balances, not measured
as a grid/solar-to-house/battery separation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from .kems_core.slot_flow import build_slot_flow

_MAX_GAP = timedelta(minutes=10)
_EPSILON = 1e-6


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    if isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return result.astimezone(UTC) if result.tzinfo else None
        except ValueError:
            pass
    return None


def _value(item: Any, field: str) -> float | None:
    try:
        value = float(getattr(item, field, None))
    except (TypeError, ValueError, OverflowError):
        return None
    return value if isfinite(value) else None


def _integrate(
    records: list[Any],
    *,
    start: datetime,
    end: datetime,
    field: str,
    sign: int = 0,
) -> tuple[float, bool]:
    """Integrate sampled power with a bounded ten-minute coverage gap."""
    samples: list[tuple[datetime, float]] = []
    for item in records:
        timestamp = _dt(getattr(item, "timestamp", None))
        value = _value(item, field)
        if timestamp is None or value is None:
            continue
        if sign == -1:
            value = max(-value, 0.0)
        elif sign == 1:
            value = max(value, 0.0)
        else:
            value = max(value, 0.0)
        samples.append((timestamp, value))
    samples.sort()
    seed = next((v for v in reversed(samples) if v[0] <= start), None)
    if seed is None or start - seed[0] > _MAX_GAP:
        return 0.0, False
    cursor, power = start, seed[1]
    energy = 0.0
    for at, new_power in samples:
        if at <= start or at <= cursor:
            continue
        if at > end:
            break
        if at - cursor > _MAX_GAP:
            return 0.0, False
        energy += power * (at - cursor).total_seconds() / 3600.0
        cursor, power = at, new_power
    if end - cursor > _MAX_GAP:
        return 0.0, False
    return energy + power * (end - cursor).total_seconds() / 3600.0, True


def overlay_completed_happy_hour_flow(
    state: dict[str, Any],
    *,
    completed_booked_hours: list[dict[str, Any]],
    meter_samples: list[Any],
    physical_history: list[Any],
    now: datetime,
) -> dict[str, Any]:
    """Replace completed simulator flow only where physical sources agree.

    Never edit raw optimisation/settlement keys, claim inferred routing as
    physical circuit measurements, or allocate import to a missing interval.
    """
    audit: dict[str, Any] = {
        "status": "no_verified_completed_slots",
        "hardware_writes": "none",
        "completed_slots_with_physical_flow": 0,
        "incomplete_meter_slots": 0,
        "energy_balance_failed_slots": 0,
        "scope": "flow_* display only; no financial settlement edits",
    }
    slots = state.get("today_slots")
    if not isinstance(slots, list) or now.tzinfo is None:
        return audit
    now_utc = now.astimezone(UTC)
    windows: list[tuple[datetime, datetime, str]] = []
    for record in completed_booked_hours:
        if (
            not isinstance(record, dict)
            or record.get("booking_source") != "octopus_joined_events"
            or not record.get("event_id")
        ):
            continue
        begin, end = _dt(record.get("start")), _dt(record.get("end"))
        if (
            begin is not None
            and end is not None
            and abs((end - begin).total_seconds() - 3600.0) < 1
            and end <= now_utc
        ):
            windows.append((begin, end, str(record["event_id"])))
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        begin, end = _dt(slot.get("valid_from")), _dt(slot.get("valid_to"))
        if begin is None or end is None or end > now_utc:
            continue
        match = next(
            (item for item in windows if item[0] <= begin < end <= item[1]),
            None,
        )
        if match is None:
            continue
        import_kwh, import_ok = _integrate(
            meter_samples, start=begin, end=end, field="grid_import_kw"
        )
        if not import_ok:
            audit["incomplete_meter_slots"] += 1
            continue
        sources: dict[str, float] = {"import": import_kwh}
        for label, field, sign in (
            ("solar", "solar_power_kw", 0),
            ("house", "house_load_kw", 0),
            ("battery_charge", "battery_power_kw", -1),
            ("battery_discharge", "battery_power_kw", 1),
            ("export", "grid_export_kw", 0),
        ):
            value, coverage = _integrate(
                physical_history,
                start=begin,
                end=end,
                field=field,
                sign=sign,
            )
            if not coverage:
                audit["incomplete_meter_slots"] += 1
                break
            sources[label] = value
        else:
            balance = abs(
                sources["import"]
                + sources["solar"]
                + sources["battery_discharge"]
                - sources["house"]
                - sources["battery_charge"]
                - sources["export"]
            )
            if balance > max(0.2, 0.07 * sources["house"]):
                audit["energy_balance_failed_slots"] += 1
                continue
            # Allocate solar to house first for a *labelled estimate*,
            # leaving any solar surplus free to charge battery. The energy
            # values themselves came from independent physical power streams.
            solar_export = min(sources["export"], sources["solar"])
            battery_export = sources["export"] - solar_export
            battery_home = max(sources["battery_discharge"] - battery_export, 0.0)
            available_solar = max(sources["solar"] - solar_export, 0.0)
            solar_home = min(available_solar, sources["house"])
            solar_battery = min(
                max(available_solar - solar_home, 0.0),
                sources["battery_charge"],
            )
            grid_battery = min(
                max(sources["battery_charge"] - solar_battery, 0.0),
                sources["import"],
            )
            slot.update(
                build_slot_flow(
                    grid_import_kwh=sources["import"],
                    solar_generation_kwh=sources["solar"],
                    solar_to_home_kwh=solar_home,
                    solar_to_battery_kwh=solar_battery,
                    solar_export_kwh=solar_export,
                    grid_to_battery_kwh=grid_battery,
                    battery_to_home_kwh=battery_home,
                    battery_export_kwh=battery_export,
                    estimated_soc_percent=None,
                    basis=(
                        "completed Happy Hour physical energy; "
                        "solar routing inferred, SOC not backcast"
                    ),
                    scope="observed completed reward half-hour",
                )
            )
            slot["flow_happy_hour_booking_id"] = match[2]
            slot["flow_happy_hour_meter_import_kwh"] = round(import_kwh, 3)
            slot["flow_happy_hour_energy_balance_gap_kwh"] = round(balance, 3)
            slot["flow_happy_hour_authority"] = (
                "physical meter-backed display only; no live write"
            )
            audit["completed_slots_with_physical_flow"] += 1
    if audit["completed_slots_with_physical_flow"]:
        audit["status"] = "verified_completed_happy_hour_flows"
    return audit
