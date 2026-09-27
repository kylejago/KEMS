"""Read-only shared-bus EV/house power-balance evidence.

The EPS/Henley distribution feeds both the household and the Ohme consumer
unit. These are net metering comparisons, never physical circuit isolation,
a closed-loop controller, or authority to change the KH7 work mode.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from math import isfinite

from .models import Snapshot
from .no_export_cheap import split_no_export_demand

_REQUIRED = (
    "house_load_kw",
    "battery_power_kw",
    "solar_power_kw",
    "grid_import_kw",
    "grid_export_kw",
)
_TOLERANCE_KW = 0.25


@dataclass(frozen=True, slots=True)
class SharedBusBalance:
    """One timestamped measured comparison, not a physical dispatch verdict."""

    status: str
    reason: str
    timestamp: str
    cheap_period_confirmed: bool
    ev_power_kw: float | None = None
    site_load_kw: float | None = None
    non_ev_house_kw: float | None = None
    solar_kw: float | None = None
    battery_discharge_kw: float | None = None
    house_battery_allowance_kw: float | None = None
    battery_above_house_allowance_kw: float | None = None
    grid_import_kw: float | None = None
    grid_export_kw: float | None = None
    conservative_ev_grid_requirement_kw: float | None = None
    grid_requirement_shortfall_kw: float | None = None
    candidate_inverter_site_output_ceiling_kw: float | None = None
    load_scope_reason: str | None = None
    hardware_write_authorised: bool = False

    def to_dict(self) -> dict[str, object]:
        """Expose only read-only diagnostic values."""
        return asdict(self)


def assess_shared_bus_balance(
    snapshot: Snapshot,
    *,
    no_paid_export_mode: bool,
    battery_positive_is_discharge: bool,
    inverter_limit_kw: float,
    max_age_seconds: float = 180,
) -> SharedBusBalance:
    """Assess the *observed* EV net allocation using existing KEMS telemetry.

    The lower bound on EV-equivalent grid import gives surplus PV the benefit
    of the doubt. It is not a statement about which electrons fed the charger.
    Battery charge or inverter losses make the comparison conservative; they
    must be accounted for before a physical output-control design is approved.
    """
    common = {
        "timestamp": snapshot.timestamp.isoformat(),
        "cheap_period_confirmed": snapshot.cheap_period_confirmed,
    }

    def unavailable(reason: str, *, status: str = "unavailable") -> SharedBusBalance:
        return SharedBusBalance(status=status, reason=reason, **common)

    if not no_paid_export_mode:
        return unavailable(
            "Paid-export operation is outside this no-export audit",
            status="not_applicable",
        )
    if snapshot.ev_charging is not True:
        if snapshot.ev_charging is False and not (snapshot.ev_power_kw or 0.0) > 0.1:
            return unavailable("EV is not charging", status="idle")
        return unavailable("Ohme charging state is unknown or inconsistent")
    ev = snapshot.ev_power_kw
    if ev is None or not isfinite(ev) or ev <= 0.1:
        return unavailable("Active Ohme power is unavailable or inconsistent")
    if snapshot.ev_power_age_seconds is None or snapshot.ev_power_age_seconds > 90.0:
        return unavailable("Ohme power report is too old for a matched EV audit")
    if snapshot.ev_load_in_house_load is None:
        return unavailable("EV membership in FoxESS Load Power is unproven")
    if snapshot.stale_fields and any(key in snapshot.stale_fields for key in _REQUIRED):
        return unavailable("A physical FoxESS balance input is stale")
    values = [getattr(snapshot, key) for key in _REQUIRED]
    if any(value is None or not isfinite(value) for value in values):
        return unavailable(
            "Complete finite physical FoxESS power readings are required"
        )
    # FoxESS may retain an unchanged zero feed-in reading while a fresh
    # sibling from the same device proves polling is still active. Reuse
    # KEMS's existing effective cohort age for that one static zero only.
    if (
        snapshot.source_data_age_seconds is None
        or snapshot.source_data_age_seconds > max_age_seconds
    ):
        return unavailable("FoxESS device cohort freshness is unavailable")
    if any(key not in snapshot.source_age_seconds for key in _REQUIRED):
        return unavailable("Required physical source report timestamps are missing")
    if any(
        age > max_age_seconds
        and not (key == "grid_export_kw" and snapshot.grid_export_kw == 0.0)
        for key, age in snapshot.source_age_seconds.items()
        if key in _REQUIRED
    ):
        return unavailable("A changing physical source exceeds the audit age limit")

    split = split_no_export_demand(snapshot, snapshot.house_load_kw)
    if not split.ev_separation_proven:
        return unavailable(split.reason)
    solar = max(float(snapshot.solar_power_kw), 0.0)
    battery_signed = float(snapshot.battery_power_kw)
    battery_discharge = max(
        battery_signed if battery_positive_is_discharge else -battery_signed,
        0.0,
    )
    home = split.house_kw
    home_battery_allowance = max(home - min(solar, home), 0.0)
    battery_excess = max(battery_discharge - home_battery_allowance, 0.0)
    pv_surplus = max(solar - home, 0.0)
    # PV on the same bus can reduce EV grid import; no per-circuit source claim.
    ev_grid_requirement = max(split.ev_grid_kw - pv_surplus, 0.0)
    grid_shortfall = max(
        ev_grid_requirement - max(float(snapshot.grid_import_kw), 0.0), 0.0
    )
    consistent = battery_excess <= _TOLERANCE_KW and grid_shortfall <= _TOLERANCE_KW
    reason = (
        "Observed whole-site allocation is consistent with the conservative "
        "EV-grid/house-battery bound, not circuit isolation or KH7 command proof"
        if consistent
        else "Observed battery discharge exceeds non-EV residual demand "
        "and/or grid import is below the conservative EV requirement"
    )
    return SharedBusBalance(
        status="net_allocation_consistent" if consistent else "deviation",
        reason=reason,
        **common,
        ev_power_kw=round(ev, 3),
        site_load_kw=round(split.site_kw, 3),
        non_ev_house_kw=round(home, 3),
        solar_kw=round(solar, 3),
        battery_discharge_kw=round(battery_discharge, 3),
        house_battery_allowance_kw=round(home_battery_allowance, 3),
        battery_above_house_allowance_kw=round(battery_excess, 3),
        grid_import_kw=round(float(snapshot.grid_import_kw), 3),
        grid_export_kw=round(float(snapshot.grid_export_kw), 3),
        conservative_ev_grid_requirement_kw=round(ev_grid_requirement, 3),
        grid_requirement_shortfall_kw=round(grid_shortfall, 3),
        candidate_inverter_site_output_ceiling_kw=round(
            min(home, max(float(inverter_limit_kw), 0.0)), 3
        ),
        load_scope_reason=split.reason,
    )


def summarise_shared_bus_audits(
    records: Sequence[Snapshot],
    now: datetime,
    *,
    lookback_hours: float = 24.0,
    max_samples: int = 72,
) -> dict[str, object]:
    """Bounded, retained evidence from KEMS's existing five-minute snapshots.

    A historical series of matching readings can inform commissioning review.
    It never converts a measurement verdict into hardware command permission.
    """
    cutoff = now - timedelta(hours=max(lookback_hours, 0.0))
    recent = [
        item.shared_bus_ev_audit
        for item in records
        if item.timestamp >= cutoff
        and isinstance(item.shared_bus_ev_audit, dict)
        and item.shared_bus_ev_audit.get("status")
    ]
    counts = Counter(str(item["status"]) for item in recent)
    return {
        "lookback_hours": lookback_hours,
        "recorded_samples": len(recent),
        "status_counts": dict(sorted(counts.items())),
        "samples": recent[-max(max_samples, 1) :],
        "physical_isolation_proven": False,
        "hardware_write_authorised": False,
        "sample_period_note": (
            "Existing KEMS history samples at five-minute intervals; short "
            "charging transitions need separate time-aligned observation"
        ),
    }
