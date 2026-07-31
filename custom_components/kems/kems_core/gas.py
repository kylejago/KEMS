"""Whole-home gas aggregation for KEMS."""

from __future__ import annotations

from datetime import date, datetime
from statistics import fmean

from .models import GasSummary, Snapshot


def _positive_meter_delta(records: list[Snapshot]) -> float | None:
    """Return positive cumulative-meter movement without inventing resets."""
    values = [
        record.gas_meter_total_kwh
        for record in records
        if record.gas_meter_total_kwh is not None
    ]
    if len(values) < 2:
        return None
    total = 0.0
    seen = False
    for previous, current in zip(values, values[1:], strict=False):
        delta = current - previous
        if delta >= 0:
            total += delta
            seen = True
    return round(total, 3) if seen else None


def _latest(records: list[Snapshot], field: str) -> float | None:
    """Return the most recent available numeric field."""
    for record in reversed(records):
        value = getattr(record, field)
        if value is not None:
            return float(value)
    return None


def _daily_direct_values(
    records: list[Snapshot],
    field: str,
) -> dict[date, float]:
    """Return each day's latest/max cumulative daily value."""
    values: dict[date, float] = {}
    for record in records:
        value = getattr(record, field)
        if value is None or value < 0:
            continue
        day = record.timestamp.date()
        values[day] = max(values.get(day, 0.0), float(value))
    return values


class GasEngine:
    """Calculate gas usage and cost from sparse Octopus observations."""

    def summarise(self, records: list[Snapshot], now: datetime) -> GasSummary:
        """Return today's and current-month gas totals."""
        gas_records = [
            record
            for record in records
            if any(
                value is not None
                for value in (
                    record.gas_current_rate,
                    record.gas_standing_charge,
                    record.gas_meter_total_kwh,
                    record.gas_usage_today_kwh,
                    record.gas_cost_today_pence,
                )
            )
        ]
        if not gas_records:
            return GasSummary()

        today_records = [
            record for record in gas_records if record.timestamp.date() == now.date()
        ]
        month_records = [
            record
            for record in gas_records
            if record.timestamp.year == now.year and record.timestamp.month == now.month
        ]

        daily_usage = _daily_direct_values(month_records, "gas_usage_today_kwh")
        daily_cost = _daily_direct_values(month_records, "gas_cost_today_pence")

        usage_today = daily_usage.get(now.date())
        if usage_today is None:
            usage_today = _positive_meter_delta(today_records)

        usage_month = sum(daily_usage.values()) if daily_usage else None
        if usage_month is None:
            usage_month = _positive_meter_delta(month_records)

        rate = _latest(gas_records, "gas_current_rate")
        standing = _latest(gas_records, "gas_standing_charge")

        cost_today = daily_cost.get(now.date())
        if cost_today is None and usage_today is not None and rate is not None:
            cost_today = usage_today * rate + (standing or 0.0)

        cost_month = sum(daily_cost.values()) if daily_cost else None
        if cost_month is None and usage_month is not None and rate is not None:
            observed_days = len({record.timestamp.date() for record in month_records})
            cost_month = usage_month * rate + observed_days * (standing or 0.0)

        completed_daily_usage = [
            value for day, value in daily_usage.items() if day < now.date()
        ]
        typical = (
            round(fmean(completed_daily_usage), 3)
            if completed_daily_usage
            else usage_today
        )
        observed_days = len({record.timestamp.date() for record in gas_records})
        direct_days = len(daily_usage)
        coverage = 100 * direct_days / observed_days if observed_days else 0.0

        return GasSummary(
            available=True,
            usage_today_kwh=round(usage_today, 3) if usage_today is not None else None,
            cost_today_pence=round(cost_today, 2) if cost_today is not None else None,
            usage_month_kwh=round(usage_month, 3) if usage_month is not None else None,
            cost_month_pence=round(cost_month, 2) if cost_month is not None else None,
            typical_daily_usage_kwh=typical,
            current_rate_pence=rate,
            standing_charge_pence=standing,
            days_observed=observed_days,
            data_coverage=round(coverage, 1),
        )
