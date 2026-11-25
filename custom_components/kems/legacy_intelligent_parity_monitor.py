"""Read-only migration audit of legacy Octopus slots against native Ohme.

This module never subscribes to HA services, changes mappings, or influences
tariff resolution and FoxESS/EV control. The old integration is optional.
"""

from __future__ import annotations

from collections import Counter, deque
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .kems_core.intelligent_dispatch_parity import compare_intelligent_and_ohme
from .providers.entity_map import KEMSEntities
from .providers.ohme import OhmeProvider

LEGACY_MAX_AGE_SECONDS = 45 * 60
RECORD_LIMIT = 40
SAMPLE_INTERVAL_FLOOR_SECONDS = 45

_LEGACY_UNIQUE_IDS = {
    "intelligent_slot": "octopus_intelligent_slot",
    "planned_dispatch": "octopus_intelligent_planned_dispatch_slot",
}


class LegacyIntelligentParityMonitor:
    """Keep small, bounded daytime agreement counters in KEMS diagnostics."""

    def __init__(self, hass: HomeAssistant, entities: KEMSEntities) -> None:
        self._hass = hass
        self._ohme = OhmeProvider(hass, entities)
        self._counts: Counter[str] = Counter()
        self._last: dict[str, Any] = {}
        self._last_sample: datetime | None = None
        self._last_signature: tuple[Any, ...] | None = None
        self._transitions: deque[dict[str, Any]] = deque(maxlen=RECORD_LIMIT)
        self._legacy_entities: dict[str, str | None] = {}

    def _sources(self) -> dict[str, str | None]:
        """Resolve the legacy integration from its registered platform/unique IDs."""
        registry = er.async_get(self._hass)
        result: dict[str, str | None] = {}
        for label, unique_id in _LEGACY_UNIQUE_IDS.items():
            candidates = [
                item.entity_id
                for item in registry.entities.values()
                if item.platform == "octopus_intelligent"
                and item.domain == "binary_sensor"
                and item.unique_id == unique_id
            ]
            result[label] = candidates[0] if len(candidates) == 1 else None
        return result

    def _legacy_state(
        self, entity_id: str | None, now: datetime
    ) -> tuple[bool | None, float | None]:
        state = self._hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None, None
        reported = getattr(state, "last_reported", None) or state.last_updated
        if reported.tzinfo is None:
            reported = reported.replace(tzinfo=UTC)
        age = max((now - reported).total_seconds(), 0.0)
        if age > LEGACY_MAX_AGE_SECONDS:
            return None, round(age, 1)
        if state.state == "on":
            return True, round(age, 1)
        if state.state == "off":
            return False, round(age, 1)
        return None, round(age, 1)

    def observe(
        self,
        *,
        now: datetime | None = None,
        ohme_plan_active: bool | None = None,
    ) -> None:
        """Sample both integrations without creating control or tariff authority."""
        # The interval callback supplies UTC; use the property's configured
        # local timezone for the 23:30–05:30 comparison exclusion.
        reference = (now or dt_util.now()).astimezone(
            ZoneInfo(self._hass.config.time_zone)
        )
        if (
            self._last_sample is not None
            and (reference - self._last_sample).total_seconds()
            < SAMPLE_INTERVAL_FLOOR_SECONDS
        ):
            return
        self._last_sample = reference
        self._legacy_entities = self._sources()
        slot, slot_age = self._legacy_state(
            self._legacy_entities.get("intelligent_slot"), reference
        )
        planned, planned_age = self._legacy_state(
            self._legacy_entities.get("planned_dispatch"), reference
        )
        ohme = self._ohme.get_state(reference)
        observation = compare_intelligent_and_ohme(
            now=reference,
            legacy_slot=slot,
            legacy_planned_dispatch=planned,
            ohme_charge_mode=ohme.charge_mode,
            ohme_power_kw=ohme.power_kw,
            ohme_charging=ohme.charging,
            ohme_plan_active=ohme_plan_active,
            ohme_status=ohme.status,
        )
        observation["legacy_slot_age_seconds"] = slot_age
        observation["legacy_planned_age_seconds"] = planned_age
        observation["ohme_power_age_seconds"] = ohme.power_age_seconds
        classification = observation["classification"]
        self._counts[classification] += 1
        self._last = observation
        signature = (
            classification,
            observation["legacy_planned_dispatch"],
            observation["ohme_smart_charging_now"],
            observation["ohme_planned_slot_active"],
        )
        if signature != self._last_signature:
            self._transitions.append(observation)
            self._last_signature = signature

    @property
    def status(self) -> dict[str, Any]:
        """Expose evidence, not a claim of billing equivalence."""
        both_active = self._counts["both_active"]
        legacy_only = self._counts["legacy_only"]
        ohme_only = self._counts["ohme_only"]
        return {
            "read_only": True,
            "available_only_while_legacy_integration_installed": True,
            "legacy_version_requirement": "update to v1.9.1 and restart HA",
            "sampling_seconds": 90,
            "counts": dict(self._counts),
            "active_daytime_comparable_samples": (
                both_active + legacy_only + ohme_only
            ),
            "daytime_active_agreement_samples": both_active,
            "daytime_disagreement_samples": legacy_only + ohme_only,
            "note": (
                "Legacy planned dispatch is intended supplier scheduling; "
                "Ohme Smart charge + measured power is physical activity. "
                "Disagreements can be legitimate and agreement is not proof "
                "of Octopus settlement or whole-house discount."
            ),
            "legacy_entity_ids": dict(self._legacy_entities),
            "last_observation": dict(self._last),
            "recent_transitions": list(self._transitions),
            "used_for_tariff_or_control": False,
            "safe_to_remove_old_integration": "not_evaluated",
        }
