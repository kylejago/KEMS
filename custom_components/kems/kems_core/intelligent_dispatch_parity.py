"""Read-only comparison of legacy Octopus dispatch and Ohme charging evidence.

The legacy planned-dispatch sensor observes Octopus intent. Ohme status/power
observes actual charging. Agreement is useful for migration diagnostics but
NEVER proves the supplier's billed discount or grants tariff/control authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

MIN_ACTIVE_POWER_KW = 0.5


def fixed_overnight_offpeak(now: datetime) -> bool:
    """Exclude the contracted 23:30-05:30 window from daytime comparisons."""
    minutes = now.hour * 60 + now.minute
    return minutes >= 23 * 60 + 30 or minutes < 5 * 60 + 30


def compare_intelligent_and_ohme(
    *,
    now: datetime,
    legacy_slot: bool | None,
    legacy_planned_dispatch: bool | None,
    ohme_charge_mode: str | None,
    ohme_power_kw: float | None,
    ohme_charging: bool | None,
    ohme_plan_active: bool | None,
) -> dict[str, Any]:
    """Classify a point-in-time observation without changing KEMS decisions."""
    mode = (
        str(ohme_charge_mode).strip().casefold().replace("_", " ").replace("-", " ")
        if ohme_charge_mode is not None
        else None
    )
    smart_mode = None if not mode else mode in {"smart charge", "smart charging"}
    measured_charge = (
        None if ohme_power_kw is None else ohme_power_kw >= MIN_ACTIVE_POWER_KW
    )
    # The cloud charging status is supplementary only: power establishes that
    # the EV is physically drawing energy, even when status has not caught up.
    smart_charging_now = (
        None
        if smart_mode is None or measured_charge is None
        else bool(smart_mode and measured_charge)
    )
    overnight = fixed_overnight_offpeak(now)
    if overnight:
        classification = "overnight_excluded"
    elif legacy_planned_dispatch is None or smart_charging_now is None:
        classification = "evidence_incomplete"
    elif legacy_planned_dispatch and smart_charging_now:
        classification = "both_active"
    elif legacy_planned_dispatch:
        classification = "legacy_only"
    elif smart_charging_now:
        classification = "ohme_only"
    else:
        classification = "both_inactive"
    return {
        "timestamp": now.isoformat(),
        "classification": classification,
        "fixed_overnight": overnight,
        "legacy_intelligent_slot": legacy_slot,
        "legacy_planned_dispatch": legacy_planned_dispatch,
        "ohme_charge_mode": ohme_charge_mode,
        "ohme_smart_mode": smart_mode,
        "ohme_charging_status": ohme_charging,
        "ohme_power_kw": ohme_power_kw,
        "ohme_measured_charging": measured_charge,
        "ohme_smart_charging_now": smart_charging_now,
        "ohme_planned_slot_active": ohme_plan_active,
        "supplier_discount_confirmed": False,
        "read_only": True,
        "controls_tariff_or_battery": False,
    }
