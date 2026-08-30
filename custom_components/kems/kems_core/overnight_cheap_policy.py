"""Cheap-period authority for KEMS.

The configured overnight tariff window remains independently authoritative.
Alpha8.58 additionally allows a daytime Intelligent dispatch only when tariff
resolution has already recorded a fail-closed multi-signal confirmation in the
snapshot. Older retained Intelligent observations without that evidence remain
inert, so replay cannot promote historical raw flags into cheap import.
"""

from __future__ import annotations

from .models import Snapshot


def _confirmed_cheap_period(snapshot: Snapshot) -> bool:
    """Return whether overnight or explicitly confirmed Intelligent cheap is active."""
    if snapshot.off_peak is True:
        return True

    intelligent_fresh = "intelligent_slot" not in snapshot.tariff_stale_fields
    evidence = snapshot.intelligent_slot_evidence or {}
    return bool(
        snapshot.intelligent_slot is True
        and intelligent_fresh
        and snapshot.ev_charging is True
        and evidence.get("large_import_permitted") is True
    )


def install_overnight_only_cheap_policy() -> None:
    """Install the resolved cheap-period policy on every Snapshot.

    The legacy function name is retained for runtime/import compatibility; the
    policy itself now includes Alpha8.58's explicitly confirmed Intelligent
    extra-slot authority.
    """
    current = Snapshot.cheap_period_confirmed
    if getattr(current.fget, "_kems_confirmed_cheap", False):
        return
    _confirmed_cheap_period._kems_confirmed_cheap = True
    Snapshot.cheap_period_confirmed = property(_confirmed_cheap_period)
