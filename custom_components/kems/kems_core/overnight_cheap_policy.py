"""Alpha7.34 overnight-only cheap-period policy.

The configured overnight tariff window is the sole control/simulation authority
for cheap power.  Older retained snapshots can contain Intelligent-dispatch and
EV-charging observations from releases that treated those combinations as a
cheap period.  Installing this policy makes those historical hints inert too,
so replay and live control use the same overnight-only rule.
"""

from __future__ import annotations

from .models import Snapshot


def _overnight_only_cheap_period(snapshot: Snapshot) -> bool:
    """Return whether tariff resolution marked the configured window active."""
    return snapshot.off_peak is True


def install_overnight_only_cheap_policy() -> None:
    """Replace the legacy Intelligent-slot fallback on every Snapshot."""
    current = Snapshot.cheap_period_confirmed
    if getattr(current.fget, "_kems_overnight_only", False):
        return
    _overnight_only_cheap_period._kems_overnight_only = True
    Snapshot.cheap_period_confirmed = property(_overnight_only_cheap_period)
