"""Read-only Ohme extra smart-charge evidence; never grant tariff authority."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

from .const import (
    CONF_OHME_EXTRA_SLOT_TARIFF,
    CONF_OHME_PRIORITISE_SAVINGS,
    DEFAULT_OPTIONS,
    OHME_EXTRA_SLOT_EV_ONLY,
    OHME_EXTRA_SLOT_TARIFF_LABELS,
    OHME_EXTRA_SLOT_UNCONFIRMED,
)

_SMART_CHARGE_MODES = frozenset({"smart_charge", "smart_charging"})
_SOURCE_FRESH_SECONDS = 120


def ohme_extra_slot_evidence(
    options: Mapping[str, Any],
    *,
    charge_mode: Any,
    charger_status: Any,
    charging_power_kw: Any,
    regular_offpeak_state: Any,
    mode_age_seconds: Any,
    status_age_seconds: Any,
    power_age_seconds: Any,
) -> dict[str, Any]:
    """Identify a candidate, never confirmed discounted whole-home electricity.

    The Ohme app priority is manual and can change independently of KEMS.
    Max Charge, stale data and normal overnight off-peak are not extra slots.
    Physical EV battery protection is independent of this observer.
    """
    savings_declared = (
        options.get(
            CONF_OHME_PRIORITISE_SAVINGS,
            DEFAULT_OPTIONS[CONF_OHME_PRIORITISE_SAVINGS],
        )
        is True
    )
    treatment = options.get(
        CONF_OHME_EXTRA_SLOT_TARIFF,
        DEFAULT_OPTIONS[CONF_OHME_EXTRA_SLOT_TARIFF],
    )
    if treatment not in OHME_EXTRA_SLOT_TARIFF_LABELS:
        treatment = OHME_EXTRA_SLOT_UNCONFIRMED

    mode = str(charge_mode or "").strip().casefold().replace(" ", "_").replace("-", "_")
    status = str(charger_status or "").strip().casefold()
    try:
        power = float(charging_power_kw)
    except (TypeError, ValueError):
        power = 0.0
    if not isfinite(power):
        power = 0.0

    def fresh(age: Any) -> bool:
        try:
            seconds = float(age)
        except (TypeError, ValueError):
            return False
        return isfinite(seconds) and 0 <= seconds <= _SOURCE_FRESH_SECONDS

    fresh_evidence = all(
        fresh(age) for age in (mode_age_seconds, status_age_seconds, power_age_seconds)
    )
    measured_charging = status == "charging" and power >= 0.25
    candidate = bool(
        savings_declared
        and mode in _SMART_CHARGE_MODES
        and fresh_evidence
        and measured_charging
        and regular_offpeak_state == "off"
    )
    return {
        "prioritise_savings_declared": savings_declared,
        "prioritise_savings_verified_from_ohme": False,
        "declared_extra_slot_tariff": treatment,
        "declared_extra_slot_tariff_label": OHME_EXTRA_SLOT_TARIFF_LABELS[treatment],
        "observed_charge_mode": charge_mode,
        "observed_charger_status": charger_status,
        "observed_power_kw": power,
        "input_fresh": fresh_evidence,
        "regular_offpeak_state": regular_offpeak_state,
        "likely_managed_daytime_charge_candidate": candidate,
        "supplier_policy_declared_ev_only": treatment == OHME_EXTRA_SLOT_EV_ONLY,
        "estimated_ev_only_discount_candidate": bool(
            candidate and treatment == OHME_EXTRA_SLOT_EV_ONLY
        ),
        "supplier_discount_confirmed": False,
        "household_cheap_rate_authorised": False,
        "desired_extra_slot_allocation": (
            "grid_to_ev_solar_and_battery_to_house"
            if treatment == OHME_EXTRA_SLOT_EV_ONLY
            else "protect_battery_without_tariff_assumption"
        ),
        "live_house_only_discharge_authorised": False,
        "whole_home_discount_verified": False,
        "extra_daytime_grid_force_charge_authorised": False,
        "ev_battery_hold_remains_independent": True,
        "implementation_stage": (
            "ev_only_policy_declared_pending_reviewed_live_wiring"
            if treatment == OHME_EXTRA_SLOT_EV_ONLY
            else "read_only_until_octopus_reply_and_reviewed_live_wiring"
        ),
        "note": (
            "Smart Charge plus measured charging may suggest a managed session, "
            "not prove a supplier-billed whole-home rate. App preference and "
            "tariff declarations cannot enable Force Charge."
        ),
    }
