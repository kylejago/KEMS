"""User-facing KEMS product types and simplified operating modes."""

from __future__ import annotations

from dataclasses import dataclass

SYSTEM_TYPE_LIVE_DATA = "live_data"
SYSTEM_TYPE_BATTERY_SOLAR = "battery_solar"
SYSTEM_TYPE_FULL_KEMS = "full_kems"
SYSTEM_TYPE_FULL_KEMS_AGILE = "full_kems_agile"

SYSTEM_TYPES = (
    SYSTEM_TYPE_LIVE_DATA,
    SYSTEM_TYPE_BATTERY_SOLAR,
    SYSTEM_TYPE_FULL_KEMS,
    SYSTEM_TYPE_FULL_KEMS_AGILE,
)

USER_MODE_LIVE = "Live"
USER_MODE_SIMULATE = "Simulate"
USER_MODE_CONTROL = "Control"
USER_MODES = (USER_MODE_LIVE, USER_MODE_SIMULATE, USER_MODE_CONTROL)


@dataclass(frozen=True, slots=True)
class SystemTypeDefinition:
    """Describe one simple user-facing KEMS capability level."""

    key: str
    label: str
    description: str
    simulation: bool
    control: bool
    smart_import: bool
    smart_export: bool


SYSTEM_TYPE_DEFINITIONS = {
    SYSTEM_TYPE_LIVE_DATA: SystemTypeDefinition(
        key=SYSTEM_TYPE_LIVE_DATA,
        label="Live Data",
        description="Live property monitoring only; no simulation or KEMS control.",
        simulation=False,
        control=False,
        smart_import=False,
        smart_export=False,
    ),
    SYSTEM_TYPE_BATTERY_SOLAR: SystemTypeDefinition(
        key=SYSTEM_TYPE_BATTERY_SOLAR,
        label="Battery & Solar",
        description=(
            "Live and simulated battery/solar optimisation using configured import "
            "and export tariffs."
        ),
        simulation=True,
        control=True,
        smart_import=False,
        smart_export=False,
    ),
    SYSTEM_TYPE_FULL_KEMS: SystemTypeDefinition(
        key=SYSTEM_TYPE_FULL_KEMS,
        label="Full KEMS",
        description=(
            "Forecast-aware whole-home optimisation with smart import tariff "
            "support."
        ),
        simulation=True,
        control=True,
        smart_import=True,
        smart_export=False,
    ),
    SYSTEM_TYPE_FULL_KEMS_AGILE: SystemTypeDefinition(
        key=SYSTEM_TYPE_FULL_KEMS_AGILE,
        label="Full KEMS Agile",
        description=(
            "Full KEMS plus dynamic smart-export optimisation such as Octopus "
            "Agile Outgoing."
        ),
        simulation=True,
        control=True,
        smart_import=True,
        smart_export=True,
    ),
}


def normalise_system_type(value: object) -> str:
    """Return a valid product type, defaulting existing installs to full Agile."""
    text = str(value or "").strip().lower()
    return text if text in SYSTEM_TYPES else SYSTEM_TYPE_FULL_KEMS_AGILE


def user_mode_from_internal(mode: object) -> str:
    """Map the engineering operating mode to the simple user-facing choice."""
    text = str(mode or "").strip().lower()
    if text == "control":
        return USER_MODE_CONTROL
    if text in {"simulate", "shadow"}:
        return USER_MODE_SIMULATE
    return USER_MODE_LIVE


def internal_mode_from_user(mode: object) -> str:
    """Map a simple user choice to the existing engineering operating mode."""
    text = str(mode or "").strip().lower()
    if text == USER_MODE_CONTROL.lower():
        return "control"
    if text == USER_MODE_SIMULATE.lower():
        return "simulate"
    return "observe"


def effective_operating_mode(system_type: object, requested_mode: object) -> str:
    """Apply product capabilities without weakening existing control gates."""
    kind = normalise_system_type(system_type)
    mode = str(requested_mode or "observe").strip().lower()
    if kind == SYSTEM_TYPE_LIVE_DATA:
        return "observe"
    if mode in {"observe", "simulate", "shadow", "control"}:
        return mode
    return "simulate"
