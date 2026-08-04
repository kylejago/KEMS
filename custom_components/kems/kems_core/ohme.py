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
        "paused",
        "pending_approval",
        "plugged_in",
    }
    if normalised in connected_states:
        return True, normalised == "charging"
    return None, None
