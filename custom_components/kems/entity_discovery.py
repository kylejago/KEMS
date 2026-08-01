"""Automatic discovery of Octopus, Ohme, and FoxESS source entities."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_BATTERY_CURRENT,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_VOLTAGE,
    CONF_CURRENT_EXPORT_RATE,
    CONF_CURRENT_IMPORT_RATE,
    CONF_ELECTRICITY_STANDING_CHARGE,
    CONF_EV_CHARGING,
    CONF_EV_CONNECTED,
    CONF_EV_POWER,
    CONF_EV_SOC,
    CONF_EV_STATUS,
    CONF_GAS_COST_TODAY,
    CONF_GAS_CURRENT_RATE,
    CONF_GAS_METER_TOTAL,
    CONF_GAS_STANDING_CHARGE,
    CONF_GAS_USAGE_TODAY,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_HOUSE_LOAD,
    CONF_INTELLIGENT_SLOT,
    CONF_NEXT_IMPORT_RATE,
    CONF_NEXT_OFFPEAK_START,
    CONF_OFF_PEAK,
    CONF_OFFPEAK_END,
    CONF_SOLAR_POWER,
)


@dataclass(frozen=True, slots=True)
class Candidate:
    """Normalised Home Assistant entity metadata used for scoring."""

    entity_id: str
    platform: str
    domain: str
    text: str
    unit: str
    device_class: str


@dataclass(frozen=True, slots=True)
class DiscoveryRule:
    """Scoring rule for one KEMS source field."""

    key: str
    platforms: tuple[str, ...]
    domains: tuple[str, ...]
    token_groups: tuple[tuple[str, ...], ...]
    excluded_tokens: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    device_classes: tuple[str, ...] = ()
    exact_patterns: tuple[str, ...] = ()
    minimum_score: int = 45


@dataclass(frozen=True, slots=True)
class DiscoveryMatch:
    """Best entity match and its confidence score."""

    entity_id: str
    score: int


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Entity mappings discovered with high confidence."""

    mappings: dict[str, str]
    scores: dict[str, int]
    ambiguous: tuple[str, ...]

    def summary(self) -> str:
        """Return a compact human-readable summary."""
        if not self.mappings:
            return "No high-confidence source entities were detected."
        return "\n".join(
            f"• {key}: {entity_id}" for key, entity_id in sorted(self.mappings.items())
        )


OCTOPUS_PLATFORMS = ("octopus_energy",)
OCTOPUS_INTELLIGENT_PLATFORMS = ("octopus_intelligent",)
OHME_PLATFORMS = ("ohme",)
FOXESS_PLATFORMS = ("foxess_modbus",)

RULES = (
    DiscoveryRule(
        CONF_CURRENT_IMPORT_RATE,
        OCTOPUS_PLATFORMS,
        ("sensor",),
        (("current",), ("rate", "price"), ("import", "electricity")),
        excluded_tokens=("next", "export", "gas", "standing"),
        units=("gbp/kwh", "£/kwh", "p/kwh"),
        exact_patterns=("sensor.octopus_energy_electricity_*_current_rate",),
    ),
    DiscoveryRule(
        CONF_NEXT_IMPORT_RATE,
        OCTOPUS_PLATFORMS,
        ("sensor",),
        (("next",), ("rate", "price"), ("import", "electricity")),
        excluded_tokens=("export", "gas", "standing"),
        units=("gbp/kwh", "£/kwh", "p/kwh"),
        exact_patterns=("sensor.octopus_energy_electricity_*_next_rate",),
    ),
    DiscoveryRule(
        CONF_CURRENT_EXPORT_RATE,
        OCTOPUS_PLATFORMS,
        ("sensor",),
        (("current",), ("rate", "price"), ("export",)),
        excluded_tokens=("next", "import", "gas", "standing"),
        units=("gbp/kwh", "£/kwh", "p/kwh"),
    ),
    DiscoveryRule(
        CONF_ELECTRICITY_STANDING_CHARGE,
        OCTOPUS_PLATFORMS,
        ("sensor",),
        (("standing",), ("charge",), ("electricity", "electric")),
        excluded_tokens=("gas",),
        units=("gbp", "£", "p"),
        exact_patterns=("sensor.octopus_energy_electricity_*_current_standing_charge",),
    ),
    DiscoveryRule(
        CONF_OFF_PEAK,
        OCTOPUS_PLATFORMS,
        ("binary_sensor",),
        (("off peak", "offpeak"),),
        excluded_tokens=("next", "start", "end"),
        exact_patterns=("binary_sensor.octopus_energy_electricity_*_off_peak",),
    ),
    DiscoveryRule(
        CONF_INTELLIGENT_SLOT,
        OCTOPUS_INTELLIGENT_PLATFORMS + OCTOPUS_PLATFORMS,
        ("binary_sensor",),
        (("intelligent",), ("slot", "dispatch")),
        excluded_tokens=("next 1", "next 2", "next 3", "planned"),
        exact_patterns=(
            "binary_sensor.octopus_intelligent_*_octopus_intelligent_slot",
            "binary_sensor.octopus_energy_*_intelligent_dispatching",
        ),
    ),
    DiscoveryRule(
        CONF_NEXT_OFFPEAK_START,
        OCTOPUS_INTELLIGENT_PLATFORMS + OCTOPUS_PLATFORMS,
        ("sensor",),
        (("next",), ("off peak", "offpeak"), ("start",)),
        device_classes=("timestamp",),
        exact_patterns=(
            "sensor.octopus_intelligent_*_octopus_intelligent_next_offpeak_start",
        ),
    ),
    DiscoveryRule(
        CONF_OFFPEAK_END,
        OCTOPUS_INTELLIGENT_PLATFORMS + OCTOPUS_PLATFORMS,
        ("sensor",),
        (("off peak", "offpeak"), ("end",)),
        excluded_tokens=("next rate",),
        device_classes=("timestamp",),
        exact_patterns=(
            "sensor.octopus_intelligent_*_octopus_intelligent_offpeak_end",
        ),
    ),
    DiscoveryRule(
        CONF_GAS_CURRENT_RATE,
        OCTOPUS_PLATFORMS,
        ("sensor",),
        (("gas",), ("current",), ("rate", "price")),
        excluded_tokens=("next", "electricity", "export", "standing"),
        units=("gbp/kwh", "£/kwh", "p/kwh"),
        exact_patterns=("sensor.octopus_energy_gas_*_current_rate",),
    ),
    DiscoveryRule(
        CONF_GAS_STANDING_CHARGE,
        OCTOPUS_PLATFORMS,
        ("sensor",),
        (("gas",), ("standing",), ("charge",)),
        excluded_tokens=("electricity", "electric"),
        units=("gbp", "£", "p"),
        exact_patterns=("sensor.octopus_energy_gas_*_current_standing_charge",),
    ),
    DiscoveryRule(
        CONF_GAS_USAGE_TODAY,
        OCTOPUS_PLATFORMS,
        ("sensor",),
        (("gas",), ("consumption", "usage"), ("current", "today", "accumulative")),
        excluded_tokens=("cost", "rate", "standing"),
        units=("kwh", "m3", "m³"),
        device_classes=("energy", "gas"),
        exact_patterns=(
            "sensor.octopus_energy_gas_*_current_accumulative_consumption_kwh",
            "sensor.octopus_energy_gas_*_current_accumulative_consumption_m3",
        ),
    ),
    DiscoveryRule(
        CONF_GAS_COST_TODAY,
        OCTOPUS_PLATFORMS,
        ("sensor",),
        (("gas",), ("cost",), ("current", "today", "accumulative")),
        excluded_tokens=("rate", "standing"),
        units=("gbp", "£", "p"),
        device_classes=("monetary",),
        exact_patterns=("sensor.octopus_energy_gas_*_current_accumulative_cost",),
    ),
    DiscoveryRule(
        CONF_GAS_METER_TOTAL,
        OCTOPUS_PLATFORMS,
        ("sensor",),
        (("gas",), ("consumption", "usage", "meter")),
        excluded_tokens=("cost", "rate", "standing", "current accumulative", "today"),
        units=("kwh", "m3", "m³"),
        device_classes=("energy", "gas"),
        exact_patterns=(
            "sensor.octopus_energy_gas_*_current_total_consumption_kwh",
            "sensor.octopus_energy_gas_*_current_total_consumption_m3",
        ),
    ),
    DiscoveryRule(
        CONF_EV_STATUS,
        OHME_PLATFORMS,
        ("sensor",),
        (("status",),),
        excluded_tokens=("schedule", "slot"),
        device_classes=("enum",),
        exact_patterns=("sensor.ohme_*_status",),
    ),
    DiscoveryRule(
        CONF_EV_CONNECTED,
        OHME_PLATFORMS,
        ("binary_sensor",),
        (("connected", "plugged"),),
        excluded_tokens=("internet", "cloud"),
    ),
    DiscoveryRule(
        CONF_EV_CHARGING,
        OHME_PLATFORMS,
        ("binary_sensor",),
        (("charging",),),
        excluded_tokens=("schedule", "approve"),
    ),
    DiscoveryRule(
        CONF_EV_POWER,
        OHME_PLATFORMS,
        ("sensor",),
        (("power",),),
        excluded_tokens=("energy", "target"),
        units=("kw", "w"),
        device_classes=("power",),
        exact_patterns=("sensor.ohme_*_power",),
    ),
    DiscoveryRule(
        CONF_EV_SOC,
        OHME_PLATFORMS,
        ("sensor",),
        (("vehicle battery", "soc", "state of charge", "battery level"),),
        excluded_tokens=("target", "charger"),
        units=("%",),
        device_classes=("battery",),
        exact_patterns=("sensor.ohme_*_vehicle_battery",),
    ),
    DiscoveryRule(
        CONF_HOUSE_LOAD,
        FOXESS_PLATFORMS + OCTOPUS_PLATFORMS,
        ("sensor",),
        (("load power", "house load", "consumption power", "current demand"),),
        excluded_tokens=("phase", "r phase", "s phase", "t phase"),
        units=("kw", "w"),
        device_classes=("power",),
        exact_patterns=(
            "sensor.foxess_*load*power*",
            "sensor.octopus_energy_electricity_*_current_demand",
        ),
    ),
    DiscoveryRule(
        CONF_BATTERY_SOC,
        FOXESS_PLATFORMS,
        ("sensor",),
        (("battery",), ("soc", "state of charge")),
        excluded_tokens=("minimum", "maximum", "min soc", "max soc", "soh"),
        units=("%",),
        device_classes=("battery",),
    ),
    DiscoveryRule(
        CONF_BATTERY_POWER,
        FOXESS_PLATFORMS,
        ("sensor",),
        (("battery",), ("power",)),
        excluded_tokens=("limit", "total", "today"),
        units=("kw", "w"),
        device_classes=("power",),
    ),
    DiscoveryRule(
        CONF_BATTERY_VOLTAGE,
        FOXESS_PLATFORMS,
        ("sensor",),
        (("battery",), ("voltage",)),
        excluded_tokens=("cell", "pv", "grid"),
        units=("v",),
        device_classes=("voltage",),
    ),
    DiscoveryRule(
        CONF_BATTERY_CURRENT,
        FOXESS_PLATFORMS,
        ("sensor",),
        (("battery",), ("current",)),
        excluded_tokens=("maximum", "minimum", "limit", "cell"),
        units=("a",),
        device_classes=("current",),
    ),
    DiscoveryRule(
        CONF_SOLAR_POWER,
        FOXESS_PLATFORMS,
        ("sensor",),
        (("pv power", "solar power", "generation power"),),
        excluded_tokens=("pv1", "pv2", "string", "daily", "total"),
        units=("kw", "w"),
        device_classes=("power",),
    ),
    DiscoveryRule(
        CONF_GRID_IMPORT,
        FOXESS_PLATFORMS + OCTOPUS_PLATFORMS,
        ("sensor",),
        (("grid consumption", "grid import", "from grid", "current demand"),),
        excluded_tokens=("total", "daily", "export", "feed"),
        units=("kw", "w"),
        device_classes=("power",),
        exact_patterns=(
            "sensor.foxess_*grid*consumption*",
            "sensor.octopus_energy_electricity_*_current_demand",
        ),
    ),
    DiscoveryRule(
        CONF_GRID_EXPORT,
        FOXESS_PLATFORMS,
        ("sensor",),
        (("feed in", "grid export", "to grid"),),
        excluded_tokens=("energy", "total", "daily", "import", "consumption"),
        units=("kw", "w"),
        device_classes=("power",),
    ),
)


def _normalise(value: str | None) -> str:
    """Normalise metadata for fuzzy token matching."""
    return " ".join(
        (value or "").casefold().replace("_", " ").replace("-", " ").split()
    )


def score_candidate(candidate: Candidate, rule: DiscoveryRule) -> int:
    """Score one candidate against one discovery rule."""
    if candidate.domain not in rule.domains:
        return -1000
    if any(token in candidate.text for token in rule.excluded_tokens):
        return -1000

    for index, pattern in enumerate(rule.exact_patterns):
        if fnmatch(candidate.entity_id.casefold(), pattern.casefold()):
            return 300 - (index * 20)

    score = 15
    if candidate.platform in rule.platforms:
        score += 45

    for group in rule.token_groups:
        if not any(token in candidate.text for token in group):
            return -1000
        score += 18

    if rule.units and candidate.unit in rule.units:
        score += 10
    if rule.device_classes and candidate.device_class in rule.device_classes:
        score += 10
    return score


def discover_from_candidates(candidates: Iterable[Candidate]) -> DiscoveryResult:
    """Discover entity mappings from normalised candidates."""
    candidate_list = list(candidates)
    mappings: dict[str, str] = {}
    scores: dict[str, int] = {}
    ambiguous: list[str] = []

    for rule in RULES:
        ranked = sorted(
            (
                DiscoveryMatch(candidate.entity_id, score_candidate(candidate, rule))
                for candidate in candidate_list
            ),
            key=lambda match: match.score,
            reverse=True,
        )
        if not ranked or ranked[0].score < rule.minimum_score:
            continue
        if len(ranked) > 1 and ranked[0].score - ranked[1].score < 8:
            ambiguous.append(rule.key)
            continue
        mappings[rule.key] = ranked[0].entity_id
        scores[rule.key] = ranked[0].score

    return DiscoveryResult(mappings, scores, tuple(sorted(ambiguous)))


async def async_discover_entities(hass: HomeAssistant) -> DiscoveryResult:
    """Inspect entity-registry metadata and current states."""
    registry = er.async_get(hass)
    candidates: list[Candidate] = []

    for entry in registry.entities.values():
        state = hass.states.get(entry.entity_id)
        attributes = state.attributes if state is not None else {}
        friendly_name = str(attributes.get("friendly_name", ""))
        original_name = str(entry.original_name or "")
        unique_id = str(entry.unique_id or "")
        text = _normalise(
            " ".join((entry.entity_id, friendly_name, original_name, unique_id))
        )
        candidates.append(
            Candidate(
                entity_id=entry.entity_id,
                platform=_normalise(entry.platform),
                domain=entry.entity_id.split(".", 1)[0],
                text=text,
                unit=_normalise(str(attributes.get("unit_of_measurement", ""))),
                device_class=_normalise(str(attributes.get("device_class", ""))),
            )
        )

    return discover_from_candidates(candidates)
