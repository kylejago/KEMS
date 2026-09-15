"""Home Assistant-independent observability helpers for KEMS."""

from __future__ import annotations

from .models import ScenarioComparisonState


def full_kems_battery_export_enabled(
    scenarios: ScenarioComparisonState,
) -> bool | None:
    """Return Full KEMS battery-export capability when that model is ready."""
    full_kems = scenarios.scenario("kems_full")
    if full_kems is None or not full_kems.ready:
        return None
    return True
