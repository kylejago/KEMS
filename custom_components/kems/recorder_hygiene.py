"""Recorder-safe Home Assistant presentation and runtime state for KEMS.

Alpha9.16 kept the first reported rich dashboard/Pi-Web payloads available in
Home Assistant while marking their deliberately large presentation attributes as
unrecorded. Alpha9.17 extends that boundary to every live overflow exposed by
Home Assistant 2026.9: manual Agile runtime states, update-runtime state, update
status, and forecast-validation status. The rich live attributes remain intact;
Recorder stores the compact state and standard metadata only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .agile_slots_state import _attributes as agile_slot_attributes
from .energy_bill_presentation import _payload as energy_bill_payload
from .entity import KEMSEntity
from .sensor import KEMSSensor

RECORDER_ATTRIBUTE_LIMIT_BYTES = 16_384
RECORDER_LIVE_ONLY_ATTRIBUTES = frozenset({MATCH_ALL})
RECORDER_LIVE_ONLY_STATE_INFO = {
    "unrecorded_attributes": RECORDER_LIVE_ONLY_ATTRIBUTES,
}

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


def _async_set_live_only_attributes(
    hass: HomeAssistant,
    entity_id: str,
    value: Any,
    attributes: Mapping[str, Any],
) -> None:
    """Publish rich live attributes while excluding them from Recorder history."""
    hass.states.async_set(
        entity_id,
        str(value),
        attributes,
        state_info=RECORDER_LIVE_ONLY_STATE_INFO,
    )


def _install_manual_state_hygiene() -> None:
    """Make manual Agile and updater runtime publishers Recorder-safe."""
    from . import agile_smart_export as agile
    from . import update_orchestrator as updater

    agile_set = agile.AgileSmartExportManager._set
    if not getattr(agile_set, "_kems_alpha917_recorder_hygiene", False):

        def recorder_safe_agile_set(
            self,
            entity_id: str,
            value: Any,
            attributes: dict[str, Any],
        ) -> None:
            _async_set_live_only_attributes(
                self._hass,
                entity_id,
                value,
                attributes,
            )

        recorder_safe_agile_set._kems_alpha917_recorder_hygiene = True
        agile.AgileSmartExportManager._set = recorder_safe_agile_set

    write_legacy = updater.KEMSUpdateOrchestrator._write_legacy_states
    if not getattr(write_legacy, "_kems_alpha917_recorder_hygiene", False):

        def recorder_safe_legacy_states(self) -> None:
            snapshot = self.snapshot()
            _async_set_live_only_attributes(
                self.hass,
                "sensor.kems_update_orchestrator_runtime",
                snapshot["status"],
                {
                    "friendly_name": "KEMS update orchestrator runtime",
                    **snapshot,
                },
            )
            maintenance = snapshot.get("maintenance") or {"status": "none"}
            _async_set_live_only_attributes(
                self.hass,
                "sensor.kems_maintenance_runtime",
                maintenance.get("status", "none"),
                {
                    "friendly_name": "KEMS maintenance runtime",
                    **maintenance,
                },
            )

        recorder_safe_legacy_states._kems_alpha917_recorder_hygiene = True
        updater.KEMSUpdateOrchestrator._write_legacy_states = (
            recorder_safe_legacy_states
        )


def _install_updater_io_hygiene() -> None:
    """Keep updater filesystem verification off Home Assistant's event loop."""
    from . import update_orchestrator_convergent as convergent
    from . import update_orchestrator_reliable as reliable

    orchestrator_class = convergent.ConvergentKEMSUpdateOrchestrator
    if getattr(orchestrator_class, "_kems_alpha917_io_hygiene", False):
        return

    raw_disk_version_reader = reliable._read_integration_version_from_disk
    files_version_cache = {"value": reliable._RUNNING_INTEGRATION_VERSION}

    def cached_files_version() -> str:
        return files_version_cache["value"]

    reliable._read_integration_version_from_disk = cached_files_version

    async def refresh_files_version(self) -> None:
        files_version_cache["value"] = await self.hass.async_add_executor_job(
            raw_disk_version_reader
        )

    original_start = orchestrator_class.async_start
    original_verify = orchestrator_class.async_verify_pending
    original_check = orchestrator_class.async_check
    original_maybe_run_pending = orchestrator_class._maybe_run_pending

    async def recorder_safe_start(self) -> None:
        await refresh_files_version(self)
        verification = await convergent._async_converge_dashboard(
            self.hass,
            strict=False,
        )
        if verification is not None:
            self._remember_dashboard_verification(verification)
        await original_start(self)

    async def recorder_safe_verify(self, *, save: bool = True) -> None:
        await refresh_files_version(self)
        await original_verify(self, save=save)

    async def recorder_safe_check(self, *, force: bool = False) -> dict[str, Any]:
        await refresh_files_version(self)
        return await original_check(self, force=force)

    async def recorder_safe_maybe_run_pending(self) -> None:
        await original_maybe_run_pending(self)
        await refresh_files_version(self)

    def cached_dashboard_current(self) -> bool | None:
        expected = self._dashboard_expected_sha256
        installed = self._dashboard_installed_sha256
        if expected is None or installed is None:
            return None
        return expected == installed

    orchestrator_class.async_start = recorder_safe_start
    orchestrator_class.async_verify_pending = recorder_safe_verify
    orchestrator_class.async_check = recorder_safe_check
    orchestrator_class._maybe_run_pending = recorder_safe_maybe_run_pending
    orchestrator_class._dashboard_current = cached_dashboard_current
    orchestrator_class._kems_alpha917_io_hygiene = True


def install_alpha917_recorder_hygiene() -> None:
    """Apply the integration-wide Alpha9.17 Recorder and event-loop boundary."""
    from . import sensor as sensor_platform
    from . import update_orchestrator as updater

    _install_manual_state_hygiene()
    _install_updater_io_hygiene()

    setup = sensor_platform.async_setup_entry
    if getattr(setup, "_kems_alpha917_recorder_hygiene", False):
        return

    original_setup = setup

    class RecorderSafeForecastValidationSensor(
        sensor_platform.KEMSForecastValidationSensor
    ):
        _unrecorded_attributes = RECORDER_LIVE_ONLY_ATTRIBUTES

    class RecorderSafeUpdateStatusSensor(updater.KEMSUpdateStatusSensor):
        _unrecorded_attributes = RECORDER_LIVE_ONLY_ATTRIBUTES

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
                elif (
                    isinstance(entity, sensor_platform.KEMSForecastValidationSensor)
                    and entity.entity_description.key == "forecast_validation_status"
                ):
                    repaired.append(
                        RecorderSafeForecastValidationSensor(
                            entity.coordinator,
                            entity.entity_description,
                        )
                    )
                elif isinstance(entity, updater.KEMSUpdateStatusSensor):
                    repaired.append(
                        RecorderSafeUpdateStatusSensor(
                            entity.coordinator,
                            entity.orchestrator,
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

    setup_with_recorder_hygiene._kems_alpha917_recorder_hygiene = True
    sensor_platform.async_setup_entry = setup_with_recorder_hygiene


def install_alpha916_recorder_hygiene() -> None:
    """Compatibility alias retained for older import sites and tests."""
    install_alpha917_recorder_hygiene()
