"""Home Assistant-independent FoxESS calculations."""

from __future__ import annotations


def calculate_battery_power_kw(
    voltage: float | None,
    current: float | None,
) -> float | None:
    """Calculate battery power from FoxESS voltage and current sensors."""
    if voltage is None or current is None:
        return None
    return round(voltage * current / 1000, 3)
