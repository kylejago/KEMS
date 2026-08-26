"""Conservative solar-to-house credit for rolling battery protection.

KEMS keeps the normal battery reserve and forecast pre-cheap SOC floor intact.
This helper only reduces the additional battery energy reserved for future house
load when a sufficiently confident hourly solar forecast overlaps that load.
It deliberately ignores the current partial forecast hour and never credits more
than 90% of the gross protected house demand.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from .models import ForecastPlanState, LearnedState, SolarForecastState

MIN_SOLAR_NET_DEMAND_CONFIDENCE_PERCENT = 70.0
MAX_SOLAR_HOUSE_CREDIT_FRACTION = 0.90
_EPSILON = 1e-6


@dataclass(frozen=True, slots=True)
class SolarNetDemandProjection:
    """Explainable reduction from gross to forecast net house demand."""

    active: bool
    gross_house_kwh: float
    solar_to_house_credit_kwh: float
    net_house_kwh: float
    confidence_percent: float
    conservative_house_kw: float
    forecast_source: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible evidence."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IdleSolarRouting:
    """Solar-first AC routing while deliberate battery discharge is idle."""

    solar_to_home_kw: float
    solar_to_battery_kw: float
    solar_export_kw: float
    solar_curtailment_kw: float
    grid_import_kw: float
    grid_export_kw: float
    kh7_ac_output_kw: float


def _forecast_confidence(
    forecast: SolarForecastState | None,
    forecast_plan: ForecastPlanState | None,
) -> float:
    """Use the lower non-zero confidence shared by forecast and plan."""
    values = [
        float(value)
        for value in (
            getattr(forecast, "confidence_percent", None),
            getattr(forecast_plan, "confidence_percent", None),
        )
        if value is not None and float(value) > 0.0
    ]
    return min(values) if values else 0.0


def project_solar_net_house_demand(
    *,
    now: datetime,
    deadline: datetime,
    gross_house_kwh: float,
    forecast: SolarForecastState | None,
    forecast_plan: ForecastPlanState | None,
    learned: LearnedState | None,
) -> SolarNetDemandProjection:
    """Return conservative house energy still requiring stored battery energy.

    Only hourly solar that occurs after the current partial hour and before the
    next cheap-period deadline is eligible. Each hour can offset at most the
    conservative house energy in that same hour, preventing a large midday PV
    total from being treated as if it could cover unrelated evening demand.
    """
    gross = max(float(gross_house_kwh), 0.0)
    confidence = _forecast_confidence(forecast, forecast_plan)
    source = str(getattr(forecast, "source", "unavailable") or "unavailable")
    now_utc = now.astimezone(UTC)
    deadline_utc = deadline.astimezone(UTC)

    def inactive(reason: str) -> SolarNetDemandProjection:
        return SolarNetDemandProjection(
            active=False,
            gross_house_kwh=round(gross, 3),
            solar_to_house_credit_kwh=0.0,
            net_house_kwh=round(gross, 3),
            confidence_percent=round(confidence, 1),
            conservative_house_kw=0.0,
            forecast_source=source,
            reason=reason,
        )

    if gross <= _EPSILON:
        return inactive("no protected house energy remains")
    if deadline_utc <= now_utc:
        return inactive("cheap-period deadline has arrived")
    if forecast is None or not forecast.ready or not forecast.hourly:
        return inactive("hourly solar forecast unavailable")
    if confidence + _EPSILON < MIN_SOLAR_NET_DEMAND_CONFIDENCE_PERCENT:
        return inactive("solar forecast confidence below safe credit threshold")

    remaining_hours = max(
        (deadline_utc - now_utc).total_seconds() / 3600.0,
        0.25,
    )
    gross_average_kw = gross / remaining_hours
    typical_kw = max(
        float(getattr(learned, "typical_house_load_kw", 0.0) or 0.0),
        0.0,
    )
    plan_house = getattr(forecast_plan, "expected_house_remaining_today_kwh", None)
    plan_average_kw = (
        max(float(plan_house), 0.0) / remaining_hours
        if plan_house is not None
        else 0.0
    )
    conservative_house_kw = max(gross_average_kw, typical_kw, plan_average_kw)
    if conservative_house_kw <= _EPSILON:
        return inactive("conservative house profile unavailable")

    raw_credit = 0.0
    for item in sorted(forecast.hourly, key=lambda value: value.timestamp):
        start = item.timestamp
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        start = start.astimezone(UTC)
        # Do not credit the current partial hour: it may already contain energy
        # that has happened and its scaled daily total is less reliable mid-hour.
        if start < now_utc:
            continue
        end = start + timedelta(hours=1)
        overlap_end = min(end, deadline_utc)
        if overlap_end <= start:
            continue
        hours = (overlap_end - start).total_seconds() / 3600.0
        solar_kwh = max(float(item.solar_energy_kwh), 0.0) * hours
        house_kwh = conservative_house_kw * hours
        raw_credit += min(solar_kwh, house_kwh)

    # The fused forecast is already conservative, but retain an additional
    # confidence haircut and at least 10% of gross house demand as battery
    # protection. Rolling replanning tightens this again as the day unfolds.
    confidence_fraction = min(
        max(confidence / 100.0, 0.0),
        MAX_SOLAR_HOUSE_CREDIT_FRACTION,
    )
    credit = min(
        raw_credit * confidence_fraction,
        gross * MAX_SOLAR_HOUSE_CREDIT_FRACTION,
    )
    credit = max(credit, 0.0)
    net = max(gross - credit, 0.0)
    if credit <= _EPSILON:
        return inactive("no forecast solar overlaps protected house demand")

    return SolarNetDemandProjection(
        active=True,
        gross_house_kwh=round(gross, 3),
        solar_to_house_credit_kwh=round(credit, 3),
        net_house_kwh=round(net, 3),
        confidence_percent=round(confidence, 1),
        conservative_house_kw=round(conservative_house_kw, 3),
        forecast_source=source,
        reason=(
            "high-confidence hourly solar overlaps future house demand; "
            "battery protects only the conservative net remainder"
        ),
    )


def route_idle_solar_first(
    *,
    house_kw: float,
    solar_kw: float,
    requested_solar_to_battery_kw: float,
    grid_to_battery_kw: float,
    battery_export_kw: float,
    inverter_limit_kw: float,
    export_limit_kw: float,
    export_allowed: bool,
) -> IdleSolarRouting:
    """Route solar to the house before idle-period charging/export.

    This helper is intentionally limited to a zero-battery-discharge snapshot.
    Cheap-period grid bypass is handled by the caller and deliberate battery
    discharge continues to use the existing shared-inverter headroom logic.
    """
    house = max(float(house_kw), 0.0)
    solar = max(float(solar_kw), 0.0)
    solar_to_home = min(house, solar)
    remaining_solar = max(solar - solar_to_home, 0.0)
    solar_to_battery = min(
        max(float(requested_solar_to_battery_kw), 0.0),
        remaining_solar,
    )
    remaining_solar = max(remaining_solar - solar_to_battery, 0.0)

    grid_charge = max(float(grid_to_battery_kw), 0.0)
    battery_export = max(float(battery_export_kw), 0.0)
    inverter_limit = max(float(inverter_limit_kw), 0.0)
    export_limit = min(max(float(export_limit_kw), 0.0), inverter_limit)
    export_headroom = max(export_limit - battery_export, 0.0)
    inverter_headroom = max(inverter_limit - solar_to_home, 0.0)
    solar_export = (
        min(remaining_solar, export_headroom, inverter_headroom)
        if export_allowed
        else 0.0
    )
    solar_curtailment = max(remaining_solar - solar_export, 0.0)
    grid_import = max(house - solar_to_home, 0.0) + grid_charge
    grid_export = solar_export + battery_export
    kh7_ac_output = solar_to_home + solar_export + battery_export

    return IdleSolarRouting(
        solar_to_home_kw=round(solar_to_home, 3),
        solar_to_battery_kw=round(solar_to_battery, 3),
        solar_export_kw=round(solar_export, 3),
        solar_curtailment_kw=round(solar_curtailment, 3),
        grid_import_kw=round(grid_import, 3),
        grid_export_kw=round(grid_export, 3),
        kh7_ac_output_kw=round(kh7_ac_output, 3),
    )
