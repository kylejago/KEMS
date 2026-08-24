"""User-facing KEMS product and tariff-strategy definitions.

Alpha8.13 deliberately exposes only two products to normal users: Live Data and
KEMS.  The historical Battery & Solar / Full KEMS / Full KEMS Agile keys remain
accepted as compatibility aliases so existing config entries migrate without
losing the strategy they previously selected.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SYSTEM_TYPE_LIVE_DATA = "live_data"
SYSTEM_TYPE_KEMS = "kems"

# Legacy persisted values.  They are not user-facing product choices anymore.
SYSTEM_TYPE_BATTERY_SOLAR = "battery_solar"
SYSTEM_TYPE_FULL_KEMS = "full_kems"
SYSTEM_TYPE_FULL_KEMS_AGILE = "full_kems_agile"
LEGACY_KEMS_SYSTEM_TYPES = (
    SYSTEM_TYPE_BATTERY_SOLAR,
    SYSTEM_TYPE_FULL_KEMS,
    SYSTEM_TYPE_FULL_KEMS_AGILE,
)

SYSTEM_TYPES = (SYSTEM_TYPE_LIVE_DATA, SYSTEM_TYPE_KEMS)

EXPORT_TARIFF_TYPE_NONE = "none"
EXPORT_TARIFF_TYPE_FIXED = "fixed"
EXPORT_TARIFF_TYPE_AGILE = "agile"
EXPORT_TARIFF_TYPES = (
    EXPORT_TARIFF_TYPE_NONE,
    EXPORT_TARIFF_TYPE_FIXED,
    EXPORT_TARIFF_TYPE_AGILE,
)
EXPORT_TARIFF_TYPE_LABELS = {
    EXPORT_TARIFF_TYPE_NONE: "No paid export",
    EXPORT_TARIFF_TYPE_FIXED: "Fixed export tariff",
    EXPORT_TARIFF_TYPE_AGILE: "Agile Outgoing",
}

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


_LIVE_DATA = SystemTypeDefinition(
    key=SYSTEM_TYPE_LIVE_DATA,
    label="Live Data",
    description="Measured property monitoring only; no KEMS simulation or control.",
    simulation=False,
    control=False,
    smart_import=False,
    smart_export=False,
)
_KEMS = SystemTypeDefinition(
    key=SYSTEM_TYPE_KEMS,
    label="KEMS",
    description=(
        "KEMS automatically uses the configured system and export tariff: self-use "
        "with no paid export, fixed-export optimisation, or Agile export optimisation."
    ),
    simulation=True,
    control=True,
    smart_import=True,
    smart_export=True,
)

# Compatibility lookups deliberately map all retired products to the one KEMS
# product. SYSTEM_TYPES controls what appears in normal selectors and contains
# only Live Data and KEMS.
SYSTEM_TYPE_DEFINITIONS = {
    SYSTEM_TYPE_LIVE_DATA: _LIVE_DATA,
    SYSTEM_TYPE_KEMS: _KEMS,
    SYSTEM_TYPE_BATTERY_SOLAR: _KEMS,
    SYSTEM_TYPE_FULL_KEMS: _KEMS,
    SYSTEM_TYPE_FULL_KEMS_AGILE: _KEMS,
}


def normalise_system_type(value: object) -> str:
    """Return Live Data or KEMS, accepting all historical KEMS product keys."""
    text = str(value or "").strip().lower()
    if text == SYSTEM_TYPE_LIVE_DATA:
        return SYSTEM_TYPE_LIVE_DATA
    return SYSTEM_TYPE_KEMS


def export_tariff_type_from_options(options: Mapping[str, Any]) -> str:
    """Return the configured user tariff type, preserving legacy intent.

    Existing installations pre-date ``export_tariff_type``. Their former product
    choice is therefore the safest migration source: Battery & Solar means no
    paid export, Full KEMS means fixed paid export, and Full KEMS Agile means
    Agile Outgoing. New KEMS installations fall back to the existing paid-export
    status until the user explicitly chooses an export tariff type.
    """
    explicit = str(options.get("export_tariff_type") or "").strip().lower()
    if explicit in EXPORT_TARIFF_TYPES:
        return explicit

    legacy = str(options.get("system_type") or "").strip().lower()
    if legacy == SYSTEM_TYPE_BATTERY_SOLAR:
        return EXPORT_TARIFF_TYPE_NONE
    if legacy == SYSTEM_TYPE_FULL_KEMS_AGILE:
        return EXPORT_TARIFF_TYPE_AGILE
    if legacy == SYSTEM_TYPE_FULL_KEMS:
        return EXPORT_TARIFF_TYPE_FIXED

    status = str(options.get("export_tariff_status") or "active").strip().lower()
    return EXPORT_TARIFF_TYPE_NONE if status == "awaiting" else EXPORT_TARIFF_TYPE_FIXED


def kems_strategy_key(export_tariff_type: str) -> str:
    """Return the retained internal replay selected by the KEMS product."""
    if export_tariff_type == EXPORT_TARIFF_TYPE_AGILE:
        return "agile_smart_export"
    if export_tariff_type == EXPORT_TARIFF_TYPE_NONE:
        return "kems_no_export"
    return "kems_forecast"


def kems_strategy_label(export_tariff_type: str) -> str:
    """Return a transparent user-facing explanation of KEMS's active strategy."""
    return {
        EXPORT_TARIFF_TYPE_NONE: "Self-use — no paid export",
        EXPORT_TARIFF_TYPE_FIXED: "Fixed export optimisation",
        EXPORT_TARIFF_TYPE_AGILE: "Agile export optimisation",
    }.get(export_tariff_type, "Fixed export optimisation")


def migrated_product_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Collapse legacy product options to KEMS while preserving export intent."""
    values = dict(options)
    legacy = str(values.get("system_type") or "").strip().lower()
    if legacy in LEGACY_KEMS_SYSTEM_TYPES:
        values.setdefault("export_tariff_type", export_tariff_type_from_options(values))
        values["system_type"] = SYSTEM_TYPE_KEMS
    return values


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
