"""Physical export-capacity allocation for KEMS rolling Agile planning.

This helper turns the deadline guard's solar-aware five-minute battery-capacity
segments into settlement-slot export capacity. Battery discharge remains a
shared inverter resource: forecast/live solar occupies AC output first, any
remaining house demand is served from the battery next, and only the residual
battery headroom is available for deliberate grid export.

The helper is intentionally pure. It does not choose SOC targets, mutate
Home Assistant state, or authorize hardware writes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class PhysicalSlotAllocation:
    """One physically achievable settlement-slot battery-export allocation."""

    valid_from: datetime
    valid_to: datetime
    rate_pence: float
    capacity_kwh: float
    allocated_kwh: float

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible allocation evidence."""
        payload = asdict(self)
        payload["valid_from"] = self.valid_from.isoformat()
        payload["valid_to"] = self.valid_to.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class PhysicalSlotCapacityPlan:
    """Result of allocating desired export over real shared-inverter capacity."""

    desired_kwh: float
    allocated_kwh: float
    total_capacity_kwh: float
    unallocated_kwh: float
    house_kw: float
    allocations: tuple[PhysicalSlotAllocation, ...]

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible capacity evidence."""
        return {
            "desired_kwh": round(self.desired_kwh, 3),
            "allocated_kwh": round(self.allocated_kwh, 3),
            "total_capacity_kwh": round(self.total_capacity_kwh, 3),
            "unallocated_kwh": round(self.unallocated_kwh, 3),
            "house_kw": round(self.house_kw, 3),
            "allocations": [item.to_dict() for item in self.allocations],
        }


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
    """Return one finite float when possible."""
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
    """Return whether a slot overlaps an absolute-priority reserved window."""
    return any(
        _overlap_hours(start, end, left, right) > _EPSILON for left, right in windows
    )


def allocate_physical_export_slots(
    *,
    slots: Iterable[dict[str, Any]],
    capacity_segments: Iterable[dict[str, Any]],
    now: datetime,
    deadline: datetime,
    desired_export_kwh: float,
    house_kw: float,
    export_limit_kw: float,
    excluded_windows: Iterable[tuple[datetime, datetime]] = (),
) -> PhysicalSlotCapacityPlan:
    """Allocate export only where the battery can physically deliver it.

    ``capacity_segments`` use the deadline guard's five-minute shared-inverter
    model and therefore already account for solar occupying inverter output.
    This function additionally reserves battery output needed by the house and
    converts the remaining power into achievable battery export for each Agile
    settlement slot.
    """
    now_utc = now.astimezone(UTC)
    deadline_utc = deadline.astimezone(UTC)
    desired = max(float(desired_export_kwh), 0.0)
    house = max(float(house_kw), 0.0)
    export_limit = max(float(export_limit_kw), 0.0)
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

        capacity_kwh = 0.0
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
            solar_to_home_kw = min(house, max(solar_kw, 0.0))
            house_battery_kw = min(
                max(house - solar_to_home_kw, 0.0),
                max(battery_kw, 0.0),
            )
            export_kw = min(
                max(battery_kw - house_battery_kw, 0.0),
                export_limit,
            )
            capacity_kwh += export_kw * hours

        candidates.append(
            {
                "valid_from": raw_start,
                "valid_to": raw_end,
                "rate_pence": rate,
                "capacity_kwh": max(capacity_kwh, 0.0),
                "allocated_kwh": 0.0,
            }
        )

    total_capacity = sum(item["capacity_kwh"] for item in candidates)
    remaining = min(desired, total_capacity)
    for item in sorted(
        candidates,
        key=lambda value: (-value["rate_pence"], value["valid_from"]),
    ):
        if remaining <= _EPSILON:
            break
        allocated = min(item["capacity_kwh"], remaining)
        item["allocated_kwh"] = allocated
        remaining -= allocated

    allocations = tuple(
        PhysicalSlotAllocation(
            valid_from=item["valid_from"],
            valid_to=item["valid_to"],
            rate_pence=round(item["rate_pence"], 5),
            capacity_kwh=round(item["capacity_kwh"], 3),
            allocated_kwh=round(item["allocated_kwh"], 3),
        )
        for item in sorted(candidates, key=lambda value: value["valid_from"])
    )
    allocated = sum(item.allocated_kwh for item in allocations)
    return PhysicalSlotCapacityPlan(
        desired_kwh=round(desired, 3),
        allocated_kwh=round(allocated, 3),
        total_capacity_kwh=round(total_capacity, 3),
        unallocated_kwh=round(max(desired - allocated, 0.0), 3),
        house_kw=round(house, 3),
        allocations=allocations,
    )
