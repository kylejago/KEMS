"""Home Assistant-independent Ohme status interpretation."""

from __future__ import annotations


def interpret_charger_status(status: str | None) -> tuple[bool | None, bool | None]:
    """Return connected and charging flags from an Ohme charger status."""
    if status is None:
        return None, None

    normalised = status.strip().casefold().replace("-", "_").replace(" ", "_")
    if normalised in {"", "unknown", "unavailable"}:
        return None, None
    if normalised == "unplugged":
        return False, False

    connected_states = {
        "charging",
        "finished",
        "finished_charging",
        "paused",
        "pending_approval",
        "plugged_in",
    }
    if normalised in connected_states:
        return True, normalised == "charging"
    return None, None


def combine_charger_evidence(
    *,
    status: str | None,
    explicit_connected: bool | None,
    explicit_charging: bool | None,
    power_kw: float | None,
) -> tuple[bool | None, bool | None]:
    """Combine fresh Ohme readings, prioritising an actual charging power draw.

    The Ohme cloud status can briefly lag at "Plugged in" or "Unplugged" while
    its fresh power sensor reports EV consumption. Never discharge the battery
    into the EV merely because a text state has not caught up yet.
    """
    status_connected, status_charging = interpret_charger_status(status)
    connected_signals = [
        value for value in (status_connected, explicit_connected) if value is not None
    ]
    charging_signals = [
        value for value in (status_charging, explicit_charging) if value is not None
    ]
    connected = all(connected_signals) if connected_signals else None
    charging = all(charging_signals) if charging_signals else None
    if power_kw is not None and power_kw > 0.1:
        return True, True
    return connected, charging
