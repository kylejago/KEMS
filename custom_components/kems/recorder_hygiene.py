"""Recorder-safe Home Assistant presentation entities for KEMS.

Alpha9.16 keeps the rich live dashboard/Pi-Web payloads available in Home
Assistant while marking the deliberately large presentation attributes as
unrecorded.  Home Assistant 2026.9 limits recorded state attributes to 16 KiB;
these payloads are current presentation data, not historical database evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .agile_slots_state import _attributes as agile_slot_attributes
from .energy_bill_presentation import _payload as energy_bill_payload
from .entity import KEMSEntity
from .sensor import KEMSSensor

SCENARIO_RECORDER_SAFE_KEYS = frozenset(
    {
        "scenario_comparison_today",
        "scenario_comparison_yesterday",
        "scenario_comparison_7_days",
        "scenario_comparison_30_days",
    }
)
SCENARIO_UNRECORDED_ATTRIBUTES = frozenset({"periods", "timeline", "scenarios"})
AGILE_SLOTS_UNRECORDED_ATTRIBUTES = frozenset(
    {
        "today_slots",
        "tomorrow_slots",
        "today_agile",
        "current_day_settlement_reconciliation",
    }
)
ENERGY_COST_UNRECORDED_ATTRIBUTES = frozenset({"periods"})


class RecorderSafeScenarioSensor(KEMSSensor):
    """Scenario sensor whose large replay payload stays live but unrecorded."""

    _unrecorded_attributes = SCENARIO_UNRECORDED_ATTRIBUTES


class KEMSAgileSlotsSensor(KEMSEntity, SensorEntity):
    """Customer-facing Agile slot table with Recorder-safe large attributes."""

    _attr_name = "Agile slots"
    _attr_icon = "mdi:table-clock"
    _unrecorded_attributes = AGILE_SLOTS_UNRECORDED_ATTRIBUTES

    def __init__(self, coordinator: Any) -> None:
        """Initialise the coordinator-backed Agile slot presentation."""
        super().__init__(coordinator, "agile_slots")
        self._cached_data: Any = None
        self._cached_attributes: Mapping[str, Any] | None = None

    def _attributes(self) -> Mapping[str, Any]:
        """Return one detached presentation payload per coordinator update."""
        data = self.coordinator.data
        if data is not self._cached_data or self._cached_attributes is None:
            self._cached_data = data
            self._cached_attributes = agile_slot_attributes(self.coordinator)
        return self._cached_attributes

    @property
    def native_value(self) -> str:
        """Return the same compact state used by the legacy presentation entity."""
        attributes = self._attributes()
        return f"{attributes['today_count']}/{attributes['today_expected']} today"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Keep the full live slot contract available to dashboards and Pi/Web."""
        return self._attributes()


class KEMSEnergyCostComparisonSensor(KEMSEntity, SensorEntity):
    """Canonical Live Data vs KEMS bill comparison with live-only period detail."""

    _attr_name = "Energy cost comparison"
    _attr_icon = "mdi:home-currency-gbp"
    _attr_native_unit_of_measurement = "p"
    _unrecorded_attributes = ENERGY_COST_UNRECORDED_ATTRIBUTES

    def __init__(self, coordinator: Any) -> None:
        """Initialise the coordinator-backed bill comparison."""
        super().__init__(coordinator, "energy_cost_comparison")
        self._cached_data: Any = None
        self._cached_payload: Mapping[str, Any] | None = None

    def _payload(self) -> Mapping[str, Any]:
        """Calculate the canonical bill payload once per coordinator data object."""
        data = self.coordinator.data
        if data is not self._cached_data or self._cached_payload is None:
            self._cached_data = data
            self._cached_payload = energy_bill_payload(self.coordinator) or {}
        return self._cached_payload

    @property
    def native_value(self) -> float | None:
        """Return today's KEMS bill-equivalent energy cost in pence."""
        value = self._payload().get("today_kems_total_energy_cost_pence")
        return None if value is None else float(value)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Keep the complete live financial contract available to dashboards."""
        return self._payload()


def install_alpha916_recorder_hygiene() -> None:
    """Replace only oversized presentation entities with Recorder-safe variants."""
    from . import sensor as sensor_platform

    setup = sensor_platform.async_setup_entry
    if getattr(setup, "_kems_alpha916_recorder_hygiene", False):
        return

    original_setup = setup

    async def setup_with_recorder_hygiene(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        extra_entities_added = False

        def add_entities(
            entities: list[Any],
            update_before_add: bool = False,
        ) -> None:
            nonlocal extra_entities_added
            repaired: list[Any] = []
            for entity in entities:
                if (
                    isinstance(entity, KEMSSensor)
                    and entity.entity_description.key in SCENARIO_RECORDER_SAFE_KEYS
                ):
                    repaired.append(
                        RecorderSafeScenarioSensor(
                            entity.coordinator,
                            entity.entity_description,
                        )
                    )
                else:
                    repaired.append(entity)

            if not extra_entities_added:
                coordinator = entry.runtime_data
                repaired.extend(
                    (
                        KEMSAgileSlotsSensor(coordinator),
                        KEMSEnergyCostComparisonSensor(coordinator),
                    )
                )
                extra_entities_added = True

            async_add_entities(repaired, update_before_add)

        await original_setup(hass, entry, add_entities)

    setup_with_recorder_hygiene._kems_alpha916_recorder_hygiene = True
    sensor_platform.async_setup_entry = setup_with_recorder_hygiene
