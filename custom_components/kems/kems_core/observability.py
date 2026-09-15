"""Home Assistant-independent observability helpers for KEMS."""

from __future__ import annotations

from .models import SimulationState

_EXPORT_EPSILON_KW_KWH = 0.001


def full_kems_battery_export_present(simulation: SimulationState) -> bool | None:
    """Return whether the authoritative Full KEMS simulation contains export."""
    if not simulation.ready:
        return None

    evidence = (
        simulation.simulated_battery_export_kwh,
        simulation.current_simulated_battery_export_power_kw,
        simulation.target_battery_export_power_kw,
    )
    known = [float(value) for value in evidence if value is not None]
    if not known:
        return None
    return any(value > _EXPORT_EPSILON_KW_KWH for value in known)
