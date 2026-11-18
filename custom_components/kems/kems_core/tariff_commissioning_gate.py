"""Fail-closed tariff commissioning without optional Intelligent-source deadlocks.

An unavailable Intelligent *extra-slot* signal must never authorise cheap import.
It must also not veto independently scheduled overnight cheap charging or
ordinary paid daytime operation with no confirmed/active EV charge.
"""

from __future__ import annotations

from typing import Any


def tariff_data_commissioning_ready(snapshot: Any) -> bool:
    """Require live price/regular tariff proof; isolate optional extra-slot age."""
    if getattr(snapshot, "current_import_rate", None) is None:
        return False
    stale = set(getattr(snapshot, "tariff_stale_fields", ()) or ())
    if stale - {"intelligent_slot"}:
        return False
    if "intelligent_slot" not in stale:
        return True

    # Only the configured 23:30–05:30 tariff schedule can authorise cheap
    # charging here. Snapshot.off_peak is the verified local schedule, *not*
    # a stale Intelligent binary. A bad Intelligent feed cannot override it.
    if getattr(snapshot, "off_peak", None) is True:
        return True

    # In an ordinary priced daytime slot, the stale extra-slot source must
    # not disable self-use/export when the EV is idle. Any EV actually
    # charging without confirmed cheap authority remains fail-closed.
    return bool(
        getattr(snapshot, "off_peak", None) is False
        and getattr(snapshot, "intelligent_slot", None) is False
        and getattr(snapshot, "ev_charging", None) is False
        and getattr(snapshot, "cheap_period_confirmed", None) is False
    )
