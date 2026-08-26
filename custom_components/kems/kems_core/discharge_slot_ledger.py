"""Pure total-discharge allocation for KEMS Agile deadline planning.

KEMS must reach the configured battery SOC target by the instant cheap power
starts. Battery-to-home and battery-to-grid are two destinations for the same
battery discharge; future house reserve is not guaranteed future discharge.

This helper therefore allocates one authoritative total-battery-discharge
obligation over the remaining settlement slots. Shared-inverter solar headroom,
house-first routing, export limits, Power Down exclusions and a rolling safety
margin are all represented without mutating Home Assistant state.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class DischargeSlotAllocation:
    """One settlement slot in the authoritative total-discharge ledger."""

    valid_from: datetime
    valid_to: datetime
    rate_pence: float
    total_discharge_capacity_kwh: float
    house_battery_capacity_kwh: float
    export_capacity_kwh: float
    planned_total_discharge_kwh: float
    planned_house_battery_kwh: float
    planned_battery_export_kwh: float

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible allocation evidence."""
        payload = asdict(self)
        payload["valid_from"] = self.valid_from.isoformat()
        payload["valid_to"] = self.valid_to.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class TotalDischargePlan:
    """Price-ranked total-discharge allocation through the cheap-start deadline."""

    required_total_discharge_kwh: float
    allocated_total_discharge_kwh: float
    total_discharge_capacity_kwh: float
    unallocated_total_discharge_kwh: float
    planned_house_battery_kwh: float
    planned_battery_export_kwh: float
    total_export_capacity_kwh: float
    safety_headroom_kwh: float
    required_current_total_discharge_kwh: float
    house_kw: float
    allocations: tuple[DischargeSlotAllocation, ...]

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible ledger evidence."""
        return {
            "required_total_discharge_kwh": round(self.required_total_discharge_kwh, 3),
            "allocated_total_discharge_kwh": round(
                self.allocated_total_discharge_kwh, 3
            ),
            "total_discharge_capacity_kwh": round(self.total_discharge_capacity_kwh, 3),
            "unallocated_total_discharge_kwh": round(
                self.unallocated_total_discharge_kwh, 3
            ),
            "planned_house_battery_kwh": round(self.planned_house_battery_kwh, 3),
            "planned_battery_export_kwh": round(self.planned_battery_export_kwh, 3),
            "total_export_capacity_kwh": round(self.total_export_capacity_kwh, 3),
            "safety_headroom_kwh": round(self.safety_headroom_kwh, 3),
            "required_current_total_discharge_kwh": round(
                self.required_current_total_discharge_kwh, 3
            ),
            "house_kw": round(self.house_kw, 3),
            "allocations": [item.to_dict() for item in self.allocations],
        }


def required_total_discharge_kwh(
    *,
    battery_capacity_kwh: float,
    soc_percent: float,
    target_soc_percent: float,
    discharge_efficiency: float,
) -> float:
    """Return AC battery discharge required to arrive at the target SOC."""
    capacity = max(float(battery_capacity_kwh), 0.0)
    soc = min(max(float(soc_percent), 0.0), 100.0)
    target = min(max(float(target_soc_percent), 0.0), 100.0)
    efficiency = max(float(discharge_efficiency), 0.0)
    stored_delta = capacity * max(soc - target, 0.0) / 100.0
    return round(stored_delta * efficiency, 3)


def _dt(value: Any) -> datetime | None:
    """Return one aware timestamp normalised to UTC."""
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
    """Return one finite numeric value when possible."""
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
    """Return overlap duration in hours."""
    start = max(first_start, second_start)
    end = min(first_end, second_end)
    return max((end - start).total_seconds() / 3600.0, 0.0)


def _excluded(
    start: datetime,
    end: datetime,
    windows: Iterable[tuple[datetime, datetime]],
) -> bool:
    """Return whether a settlement slot overlaps an excluded event window."""
    return any(
        _overlap_hours(start, end, left, right) > _EPSILON for left, right in windows
    )


def allocate_total_discharge_slots(
    *,
    slots: Iterable[dict[str, Any]],
    capacity_segments: Iterable[dict[str, Any]],
    now: datetime,
    deadline: datetime,
    required_discharge_kwh: float,
    house_kw: float,
    export_limit_kw: float,
    safety_headroom_kwh: float = 0.0,
    excluded_windows: Iterable[tuple[datetime, datetime]] = (),
) -> TotalDischargePlan:
    """Allocate one total battery-discharge obligation over physical capacity.

    The five-minute ``capacity_segments`` already account for solar occupying the
    shared inverter before battery output. For each segment we then split the
    dispatchable battery output house-first and grid-export second. Price ranking
    chooses when the total battery discharge happens; the destination split does
    not change the total-discharge obligation.
    """
    now_utc = now.astimezone(UTC)
    deadline_utc = deadline.astimezone(UTC)
    required = max(float(required_discharge_kwh), 0.0)
    house = max(float(house_kw), 0.0)
    export_limit = max(float(export_limit_kw), 0.0)
    safety = max(float(safety_headroom_kwh), 0.0)
    windows = tuple(
        (left.astimezone(UTC), right.astimezone(UTC))
        for left, right in excluded_windows
    )
    segments = tuple(capacity_segments)

    candidates: list[dict[str, Any]] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        raw_start = _dt(slot.get("valid_from"))
        raw_end = _dt(slot.get("valid_to"))
        rate = _number(slot.get("rate_pence"))
        if raw_start is None or raw_end is None or rate is None:
            continue
        if _excluded(raw_start, raw_end, windows):
            continue

        active_start = max(raw_start, now_utc)
        active_end = min(raw_end, deadline_utc)
        if active_end <= active_start:
            continue

        total_capacity = 0.0
        house_capacity = 0.0
        export_capacity = 0.0
        for segment in segments:
            segment_start = _dt(segment.get("start"))
            segment_end = _dt(segment.get("end"))
            solar_kw = _number(segment.get("solar_kw"))
            battery_kw = _number(segment.get("battery_kw"))
            if (
                segment_start is None
                or segment_end is None
                or solar_kw is None
                or battery_kw is None
            ):
                continue
            hours = _overlap_hours(
                active_start,
                active_end,
                segment_start,
                segment_end,
            )
            if hours <= _EPSILON:
                continue

            battery_headroom_kw = max(battery_kw, 0.0)
            solar_to_home_kw = min(house, max(solar_kw, 0.0))
            house_battery_kw = min(
                max(house - solar_to_home_kw, 0.0),
                battery_headroom_kw,
            )
            export_kw = min(
                max(battery_headroom_kw - house_battery_kw, 0.0),
                export_limit,
            )
            dispatchable_total_kw = house_battery_kw + export_kw
            total_capacity += dispatchable_total_kw * hours
            house_capacity += house_battery_kw * hours
            export_capacity += export_kw * hours

        candidates.append(
            {
                "valid_from": raw_start,
                "valid_to": raw_end,
                "rate_pence": rate,
                "total_capacity_kwh": max(total_capacity, 0.0),
                "house_capacity_kwh": max(house_capacity, 0.0),
                "export_capacity_kwh": max(export_capacity, 0.0),
                "allocation_kwh": 0.0,
                "is_current": raw_start <= now_utc < raw_end,
            }
        )

    total_capacity = sum(item["total_capacity_kwh"] for item in candidates)
    current = next((item for item in candidates if item["is_current"]), None)
    current_capacity = current["total_capacity_kwh"] if current is not None else 0.0
    future_capacity = max(total_capacity - current_capacity, 0.0)
    required_current = max(required + safety - future_capacity, 0.0)

    remaining = min(required, total_capacity)
    if current is not None and remaining > _EPSILON:
        forced = min(required_current, current_capacity, remaining)
        current["allocation_kwh"] = forced
        remaining -= forced

    for item in sorted(
        candidates,
        key=lambda value: (-value["rate_pence"], value["valid_from"]),
    ):
        if remaining <= _EPSILON:
            break
        spare = max(item["total_capacity_kwh"] - item["allocation_kwh"], 0.0)
        allocated = min(spare, remaining)
        item["allocation_kwh"] += allocated
        remaining -= allocated

    allocations: list[DischargeSlotAllocation] = []
    for item in sorted(candidates, key=lambda value: value["valid_from"]):
        planned_total = max(float(item["allocation_kwh"]), 0.0)
        planned_house = min(float(item["house_capacity_kwh"]), planned_total)
        planned_export = min(
            max(planned_total - planned_house, 0.0),
            float(item["export_capacity_kwh"]),
        )
        allocations.append(
            DischargeSlotAllocation(
                valid_from=item["valid_from"],
                valid_to=item["valid_to"],
                rate_pence=round(float(item["rate_pence"]), 5),
                total_discharge_capacity_kwh=round(
                    float(item["total_capacity_kwh"]), 3
                ),
                house_battery_capacity_kwh=round(float(item["house_capacity_kwh"]), 3),
                export_capacity_kwh=round(float(item["export_capacity_kwh"]), 3),
                planned_total_discharge_kwh=round(planned_total, 3),
                planned_house_battery_kwh=round(planned_house, 3),
                planned_battery_export_kwh=round(planned_export, 3),
            )
        )

    allocated_total = sum(item.planned_total_discharge_kwh for item in allocations)
    planned_house = sum(item.planned_house_battery_kwh for item in allocations)
    planned_export = sum(item.planned_battery_export_kwh for item in allocations)
    total_export_capacity = sum(item.export_capacity_kwh for item in allocations)
    return TotalDischargePlan(
        required_total_discharge_kwh=round(required, 3),
        allocated_total_discharge_kwh=round(allocated_total, 3),
        total_discharge_capacity_kwh=round(total_capacity, 3),
        unallocated_total_discharge_kwh=round(max(required - allocated_total, 0.0), 3),
        planned_house_battery_kwh=round(planned_house, 3),
        planned_battery_export_kwh=round(planned_export, 3),
        total_export_capacity_kwh=round(total_export_capacity, 3),
        safety_headroom_kwh=round(min(safety, total_capacity), 3),
        required_current_total_discharge_kwh=round(
            min(required_current, current_capacity, required), 3
        ),
        house_kw=round(house, 3),
        allocations=tuple(allocations),
    )
