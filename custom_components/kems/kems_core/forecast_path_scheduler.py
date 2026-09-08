"""Pure forecast-aware battery export scheduling for KEMS Agile.

The allocator may use high-confidence future solar to improve the timing of
battery export, but it never treats future solar as energy that already exists.
Every candidate plan is replayed chronologically against the current stored
battery energy, conservative house demand, charge/discharge efficiencies and the
configured battery floor.  Deliberate export is accepted only when the battery
path remains above the optimiser target at every step.

This module is intentionally pure: it does not mutate Home Assistant state and
cannot authorise hardware writes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

_EPSILON = 1e-9
_BINARY_SEARCH_STEPS = 28


@dataclass(frozen=True, slots=True)
class ForecastPathSlotAllocation:
    """One settlement-slot allocation from the path-constrained optimiser."""

    valid_from: datetime
    valid_to: datetime
    rate_pence: float
    export_capacity_kwh: float
    planned_house_battery_kwh: float
    planned_battery_export_kwh: float
    planned_total_discharge_kwh: float

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible allocation evidence."""
        payload = asdict(self)
        payload["valid_from"] = self.valid_from.isoformat()
        payload["valid_to"] = self.valid_to.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class ForecastPathPlan:
    """Chronologically feasible profit-ranked export plan."""

    available: bool
    reason: str
    initial_soc_percent: float
    target_soc_percent: float
    ending_soc_percent: float
    minimum_soc_percent: float
    planned_battery_export_kwh: float
    planned_house_battery_kwh: float
    planned_total_discharge_kwh: float
    forecast_solar_input_kwh: float
    forecast_solar_stored_kwh: float
    forecast_solar_spill_kwh: float
    safety_headroom_kwh: float
    future_export_capacity_margin_kwh: float
    allocations: tuple[ForecastPathSlotAllocation, ...]

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible planning evidence."""
        return {
            "available": self.available,
            "reason": self.reason,
            "initial_soc_percent": round(self.initial_soc_percent, 3),
            "target_soc_percent": round(self.target_soc_percent, 3),
            "ending_soc_percent": round(self.ending_soc_percent, 3),
            "minimum_soc_percent": round(self.minimum_soc_percent, 3),
            "planned_battery_export_kwh": round(self.planned_battery_export_kwh, 3),
            "planned_house_battery_kwh": round(self.planned_house_battery_kwh, 3),
            "planned_total_discharge_kwh": round(self.planned_total_discharge_kwh, 3),
            "forecast_solar_input_kwh": round(self.forecast_solar_input_kwh, 3),
            "forecast_solar_stored_kwh": round(self.forecast_solar_stored_kwh, 3),
            "forecast_solar_spill_kwh": round(self.forecast_solar_spill_kwh, 3),
            "safety_headroom_kwh": round(self.safety_headroom_kwh, 3),
            "future_export_capacity_margin_kwh": round(
                self.future_export_capacity_margin_kwh, 3
            ),
            "allocations": [item.to_dict() for item in self.allocations],
        }


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _overlap_hours(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> float:
    start = max(first_start, second_start)
    end = min(first_end, second_end)
    return max((end - start).total_seconds() / 3600.0, 0.0)


def _excluded(
    start: datetime,
    end: datetime,
    windows: tuple[tuple[datetime, datetime], ...],
) -> bool:
    return any(
        _overlap_hours(start, end, left, right) > _EPSILON for left, right in windows
    )


def allocate_forecast_path_exports(
    *,
    slots: Iterable[dict[str, Any]],
    capacity_segments: Iterable[dict[str, Any]],
    now: datetime,
    deadline: datetime,
    battery_capacity_kwh: float,
    soc_percent: float,
    target_soc_percent: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    max_charge_kw: float,
    house_kw: float,
    export_limit_kw: float,
    minimum_export_rate_pence: float,
    safety_headroom_kwh: float = 0.0,
    excluded_windows: Iterable[tuple[datetime, datetime]] = (),
) -> ForecastPathPlan:
    """Maximise export value without borrowing forecast solar before it arrives.

    Forecast solar can refill energy exported earlier, and earlier export can make
    room that prevents later solar spill.  Candidate slots are therefore ranked
    by price, but every tentative allocation is replayed chronologically.  A
    candidate is rejected if deliberate discharge would take stored energy below
    the optimiser target before the forecast refill actually occurs.
    """
    now_utc = now.astimezone(UTC)
    deadline_utc = deadline.astimezone(UTC)
    capacity = max(float(battery_capacity_kwh), 0.1)
    initial_soc = min(max(float(soc_percent), 0.0), 100.0)
    target_soc = min(max(float(target_soc_percent), 0.0), 100.0)
    initial_stored = capacity * initial_soc / 100.0
    target_stored = capacity * target_soc / 100.0
    charge_eff = max(min(float(charge_efficiency), 1.0), 0.01)
    discharge_eff = max(min(float(discharge_efficiency), 1.0), 0.01)
    charge_limit = max(float(max_charge_kw), 0.0)
    house = max(float(house_kw), 0.0)
    export_limit = max(float(export_limit_kw), 0.0)
    floor_rate = max(float(minimum_export_rate_pence), 0.0)
    safety = max(float(safety_headroom_kwh), 0.0)
    windows = tuple(
        (left.astimezone(UTC), right.astimezone(UTC))
        for left, right in excluded_windows
    )

    if deadline_utc <= now_utc or initial_stored + _EPSILON < target_stored:
        return ForecastPathPlan(
            available=False,
            reason="deadline elapsed or current SOC is already below optimiser target",
            initial_soc_percent=initial_soc,
            target_soc_percent=target_soc,
            ending_soc_percent=initial_soc,
            minimum_soc_percent=initial_soc,
            planned_battery_export_kwh=0.0,
            planned_house_battery_kwh=0.0,
            planned_total_discharge_kwh=0.0,
            forecast_solar_input_kwh=0.0,
            forecast_solar_stored_kwh=0.0,
            forecast_solar_spill_kwh=0.0,
            safety_headroom_kwh=safety,
            future_export_capacity_margin_kwh=0.0,
            allocations=(),
        )

    raw_segments: list[dict[str, Any]] = []
    for item in capacity_segments:
        start = _dt(item.get("start"))
        end = _dt(item.get("end"))
        solar_kw = _number(item.get("solar_kw"))
        battery_kw = _number(item.get("battery_kw"))
        if start is None or end is None or solar_kw is None or battery_kw is None:
            continue
        active_start = max(start, now_utc)
        active_end = min(end, deadline_utc)
        if active_end <= active_start:
            continue
        raw_segments.append(
            {
                "start": active_start,
                "end": active_end,
                "solar_kw": max(solar_kw, 0.0),
                "battery_kw": max(battery_kw, 0.0),
            }
        )
    raw_segments.sort(key=lambda item: item["start"])
    if not raw_segments:
        return ForecastPathPlan(
            available=False,
            reason="no physical capacity segments are available",
            initial_soc_percent=initial_soc,
            target_soc_percent=target_soc,
            ending_soc_percent=initial_soc,
            minimum_soc_percent=initial_soc,
            planned_battery_export_kwh=0.0,
            planned_house_battery_kwh=0.0,
            planned_total_discharge_kwh=0.0,
            forecast_solar_input_kwh=0.0,
            forecast_solar_stored_kwh=0.0,
            forecast_solar_spill_kwh=0.0,
            safety_headroom_kwh=safety,
            future_export_capacity_margin_kwh=0.0,
            allocations=(),
        )

    candidates: list[dict[str, Any]] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        start = _dt(slot.get("valid_from"))
        end = _dt(slot.get("valid_to"))
        rate = _number(slot.get("rate_pence"))
        if start is None or end is None or rate is None:
            continue
        active_start = max(start, now_utc)
        active_end = min(end, deadline_utc)
        if active_end <= active_start or _excluded(start, end, windows):
            continue
        candidates.append(
            {
                "valid_from": start,
                "valid_to": end,
                "active_start": active_start,
                "active_end": active_end,
                "rate_pence": rate,
                "export_capacity_kwh": 0.0,
                "house_battery_kwh": 0.0,
                "allocation_kwh": 0.0,
                "segment_caps": {},
                "is_current": start <= now_utc < end,
            }
        )

    for index, segment in enumerate(raw_segments):
        seg_start = segment["start"]
        seg_end = segment["end"]
        solar_kw = segment["solar_kw"]
        battery_kw = segment["battery_kw"]
        solar_to_home_kw = min(house, solar_kw)
        house_battery_kw = min(max(house - solar_to_home_kw, 0.0), battery_kw)
        export_kw = min(
            max(battery_kw - house_battery_kw, 0.0),
            export_limit,
        )
        for candidate in candidates:
            hours = _overlap_hours(
                seg_start,
                seg_end,
                candidate["active_start"],
                candidate["active_end"],
            )
            if hours <= _EPSILON:
                continue
            export_capacity = export_kw * hours
            candidate["export_capacity_kwh"] += export_capacity
            candidate["house_battery_kwh"] += house_battery_kw * hours
            if export_capacity > _EPSILON:
                candidate["segment_caps"][index] = export_capacity

    def simulate(allocations: dict[datetime, float]) -> dict[str, float | bool]:
        battery = initial_stored
        minimum = battery
        stored_solar = 0.0
        spill = 0.0
        solar_input = 0.0
        house_battery_total = 0.0
        feasible = True

        for index, segment in enumerate(raw_segments):
            hours = (segment["end"] - segment["start"]).total_seconds() / 3600.0
            solar_kw = segment["solar_kw"]
            battery_kw = segment["battery_kw"]
            solar_to_home_kw = min(house, solar_kw)
            house_battery_kw = min(max(house - solar_to_home_kw, 0.0), battery_kw)
            house_ac = house_battery_kw * hours
            house_battery_total += house_ac

            export_ac = 0.0
            for candidate in candidates:
                capacity_share = candidate["segment_caps"].get(index, 0.0)
                slot_capacity = candidate["export_capacity_kwh"]
                allocation = allocations.get(candidate["valid_from"], 0.0)
                if capacity_share > _EPSILON and slot_capacity > _EPSILON:
                    export_ac += allocation * capacity_share / slot_capacity

            stored_discharge = (house_ac + export_ac) / discharge_eff
            battery -= stored_discharge
            minimum = min(minimum, battery)
            if battery + 1e-7 < target_stored:
                feasible = False
                break

            surplus_solar_ac = max(solar_kw - solar_to_home_kw, 0.0) * hours
            solar_input += surplus_solar_ac
            charge_ac = min(surplus_solar_ac, charge_limit * hours)
            stored_gain = min(charge_ac * charge_eff, max(capacity - battery, 0.0))
            battery += stored_gain
            stored_solar += stored_gain
            spill += max(surplus_solar_ac - stored_gain / charge_eff, 0.0)

        if battery + 1e-7 < target_stored:
            feasible = False
        return {
            "feasible": feasible,
            "ending_stored_kwh": max(battery, 0.0),
            "minimum_stored_kwh": max(minimum, 0.0),
            "stored_solar_kwh": stored_solar,
            "solar_input_kwh": solar_input,
            "spill_kwh": spill,
            "house_battery_kwh": house_battery_total,
        }

    allocations: dict[datetime, float] = {
        item["valid_from"]: 0.0 for item in candidates
    }
    baseline = simulate(allocations)
    if not bool(baseline["feasible"]):
        return ForecastPathPlan(
            available=False,
            reason="protected house path reaches the optimiser target before deadline",
            initial_soc_percent=initial_soc,
            target_soc_percent=target_soc,
            ending_soc_percent=100.0 * float(baseline["ending_stored_kwh"]) / capacity,
            minimum_soc_percent=100.0
            * float(baseline["minimum_stored_kwh"])
            / capacity,
            planned_battery_export_kwh=0.0,
            planned_house_battery_kwh=float(baseline["house_battery_kwh"]),
            planned_total_discharge_kwh=float(baseline["house_battery_kwh"]),
            forecast_solar_input_kwh=float(baseline["solar_input_kwh"]),
            forecast_solar_stored_kwh=float(baseline["stored_solar_kwh"]),
            forecast_solar_spill_kwh=float(baseline["spill_kwh"]),
            safety_headroom_kwh=safety,
            future_export_capacity_margin_kwh=0.0,
            allocations=(),
        )

    ranked = sorted(
        (
            item
            for item in candidates
            if item["rate_pence"] + _EPSILON >= floor_rate
            and item["export_capacity_kwh"] > _EPSILON
        ),
        key=lambda item: (-item["rate_pence"], item["valid_from"]),
    )
    for candidate in ranked:
        low = allocations[candidate["valid_from"]]
        high = candidate["export_capacity_kwh"]
        for _ in range(_BINARY_SEARCH_STEPS):
            midpoint = (low + high) / 2.0
            trial = dict(allocations)
            trial[candidate["valid_from"]] = midpoint
            if bool(simulate(trial)["feasible"]):
                low = midpoint
            else:
                high = midpoint
        allocations[candidate["valid_from"]] = low

    current = next((item for item in candidates if item["is_current"]), None)
    if (
        current is not None
        and safety > _EPSILON
        and current["rate_pence"] + _EPSILON >= floor_rate
    ):
        future = [item for item in candidates if item["valid_from"] > now_utc]
        future_capacity = sum(item["export_capacity_kwh"] for item in future)
        future_planned = sum(allocations[item["valid_from"]] for item in future)
        margin = max(future_capacity - future_planned, 0.0)
        shift_needed = max(safety - margin, 0.0)
        current_spare = max(
            current["export_capacity_kwh"] - allocations[current["valid_from"]], 0.0
        )
        shift_needed = min(shift_needed, current_spare)
        if shift_needed > _EPSILON:
            # Headroom is a capacity preference, not permission to undo the
            # price ranking.  Moving a higher-value future allocation into a
            # cheaper active slot caused live low-value partial exports as the
            # rolling plan moved between coordinator scans.  Only equal/lower
            # value donors may be shifted into the current slot.
            donors = sorted(
                (
                    item
                    for item in future
                    if allocations[item["valid_from"]] > _EPSILON
                    and item["rate_pence"] <= current["rate_pence"] + _EPSILON
                ),
                key=lambda item: (item["rate_pence"], -item["valid_from"].timestamp()),
            )
            for donor in donors:
                if shift_needed <= _EPSILON:
                    break
                donor_key = donor["valid_from"]
                current_key = current["valid_from"]
                maximum_shift = min(allocations[donor_key], shift_needed)
                low = 0.0
                high = maximum_shift
                for _ in range(_BINARY_SEARCH_STEPS):
                    midpoint = (low + high) / 2.0
                    trial = dict(allocations)
                    trial[donor_key] -= midpoint
                    trial[current_key] += midpoint
                    if bool(simulate(trial)["feasible"]):
                        low = midpoint
                    else:
                        high = midpoint
                allocations[donor_key] -= low
                allocations[current_key] += low
                shift_needed -= low

    outcome = simulate(allocations)
    slot_allocations: list[ForecastPathSlotAllocation] = []
    for item in sorted(candidates, key=lambda value: value["valid_from"]):
        export = max(allocations[item["valid_from"]], 0.0)
        house_energy = max(item["house_battery_kwh"], 0.0)
        slot_allocations.append(
            ForecastPathSlotAllocation(
                valid_from=item["valid_from"],
                valid_to=item["valid_to"],
                rate_pence=round(float(item["rate_pence"]), 5),
                export_capacity_kwh=round(float(item["export_capacity_kwh"]), 3),
                planned_house_battery_kwh=round(house_energy, 3),
                planned_battery_export_kwh=round(export, 3),
                planned_total_discharge_kwh=round(house_energy + export, 3),
            )
        )

    planned_export = sum(item.planned_battery_export_kwh for item in slot_allocations)
    planned_house = sum(item.planned_house_battery_kwh for item in slot_allocations)
    future_capacity = sum(
        item.export_capacity_kwh
        for item in slot_allocations
        if item.valid_from > now_utc
    )
    future_planned = sum(
        item.planned_battery_export_kwh
        for item in slot_allocations
        if item.valid_from > now_utc
    )
    return ForecastPathPlan(
        available=True,
        reason=(
            "high-confidence forecast solar included only after chronological arrival; "
            "Agile export ranked by value subject to SOC and physical path constraints"
        ),
        initial_soc_percent=initial_soc,
        target_soc_percent=target_soc,
        ending_soc_percent=100.0 * float(outcome["ending_stored_kwh"]) / capacity,
        minimum_soc_percent=100.0 * float(outcome["minimum_stored_kwh"]) / capacity,
        planned_battery_export_kwh=planned_export,
        planned_house_battery_kwh=planned_house,
        planned_total_discharge_kwh=planned_house + planned_export,
        forecast_solar_input_kwh=float(outcome["solar_input_kwh"]),
        forecast_solar_stored_kwh=float(outcome["stored_solar_kwh"]),
        forecast_solar_spill_kwh=float(outcome["spill_kwh"]),
        safety_headroom_kwh=safety,
        future_export_capacity_margin_kwh=max(future_capacity - future_planned, 0.0),
        allocations=tuple(slot_allocations),
    )
