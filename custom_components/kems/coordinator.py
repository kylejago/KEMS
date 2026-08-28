"""Data update coordinator for KEMS."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .agile_control_alignment import (
    align_agile_control_state,
    aligned_agile_control_views,
)
from .agile_current_day_presentation import reconciled_current_day_simulation
from .agile_history_backfill import AgileHistoryBackfill
from .agile_smart_export_runtime import EfficientAgileSmartExportManager
from .collector import Collector
from .const import NAME
from .entity_discovery import SourceValidationResult
from .forecast_validation import ForecastValidationRecorder
from .forecasting import SolarForecastCoordinator
from .history import HistoryRecorder
from .kems_core import (
    AdviceEngine,
    ControlEngine,
    ForecastObservation,
    ForecastPlanningEngine,
    ForecastValidationState,
    GasEngine,
    KEMSData,
    LearningEngine,
    LifetimeLedger,
    ROIEngine,
    ScenarioComparisonEngine,
    SimulationEngine,
    WholeHomeEngine,
    assess_quality,
)
from .lifetime import LifetimeLedgerRecorder
from .power_down import PowerDownHistoryRecorder
from .providers.entity_map import KEMSEntities
from .settings import KEMSSettings
from .shadow_validation import ShadowValidationRecorder

LOGGER = logging.getLogger(__name__)


class KEMSCoordinator(DataUpdateCoordinator[KEMSData]):
    """Coordinate Observe, Learn, Advise, and Simulate stages."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        collector: Collector,
        entities: KEMSEntities,
        settings: KEMSSettings,
        source_validation: SourceValidationResult,
    ) -> None:
        """Initialise the coordinator."""
        self.entry = entry
        self.entities = entities
        self.settings = settings
        self.source_validation = source_validation
        self._collector = collector
        self._history = HistoryRecorder(
            hass,
            entry.entry_id,
            settings.history_days,
        )
        self._learning = LearningEngine()
        self._forecast = SolarForecastCoordinator(hass, settings.forecast)
        self._forecast_planning = ForecastPlanningEngine()
        self._forecast_validation = ForecastValidationRecorder(hass, entry.entry_id)
        self._gas = GasEngine()
        self._advice = AdviceEngine()
        self._simulation = SimulationEngine()
        self._scenarios = ScenarioComparisonEngine()
        self._agile_history_backfill = AgileHistoryBackfill(hass, entities)
        self._agile_smart_export = EfficientAgileSmartExportManager(
            hass,
            entry.entry_id,
            max(settings.history_days, 365),
        )
        self._whole_home = WholeHomeEngine()
        self._control = ControlEngine()
        self._shadow_validation = ShadowValidationRecorder(hass, entry.entry_id)
        self._lifetime = LifetimeLedgerRecorder(hass, entry.entry_id)
        self._power_down = PowerDownHistoryRecorder(hass, entry.entry_id)
        self._roi = ROIEngine()

        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=NAME,
            update_interval=timedelta(seconds=settings.scan_interval_seconds),
            always_update=False,
        )

    @property
    def forecast_validation_state(self) -> ForecastValidationState:
        """Return the latest retained forecast-vs-actual validation state."""
        return self._forecast_validation.state

    @property
    def forecast_validation_observations(self) -> list[ForecastObservation]:
        """Return retained pre-target-day forecast evidence for diagnostics."""
        return self._forecast_validation.forecasts

    @property
    def agile_smart_export_state(self) -> dict:
        """Return live Region L Agile Smart Export comparison diagnostics."""
        return self._agile_smart_export.state

    @property
    def agile_history_backfill_state(self) -> dict:
        """Return Home Assistant statistics backfill diagnostics."""
        return self._agile_history_backfill.state

    async def _async_setup(self) -> None:
        """Load retained learning history and permanent supporting ledgers."""
        await self._history.async_load()
        await self._forecast_validation.async_load()
        await self._lifetime.async_load()
        await self._power_down.async_load()
        await self._agile_smart_export.async_load()
        await self._shadow_validation.async_load()
        await self._lifetime.async_bootstrap(
            self._history.records,
            self._simulation,
            self._gas,
            self.settings.simulation,
            self.settings.roi,
        )

    async def _async_update_data(self) -> KEMSData:
        """Run the complete read-only KEMS analysis pipeline."""
        try:
            snapshot = self._collector.collect()
            now = dt_util.now()

            # Forecast planning is calculated before history recording so the
            # exact decision that KEMS made at this point in time is retained
            # with the observation. That lets Full KEMS Forecast be replayed
            # historically without applying today's forecast to yesterday.
            planning_records = self._history.records
            if (
                not planning_records
                or snapshot.timestamp > planning_records[-1].timestamp
            ):
                planning_records = [*planning_records, snapshot]
            planning_learned = self._learning.analyse(planning_records, now)
            planning_simulation = self._simulation.simulate_today(
                planning_records,
                now,
                self.settings.simulation,
                planning_learned.predicted_energy_until_offpeak_kwh,
                current_snapshot=snapshot,
            )
            forecast = await self._forecast.async_update(now)
            forecast_plan = self._forecast_planning.plan(
                simulation=planning_simulation,
                learned=planning_learned,
                forecast=forecast,
                simulation_config=self.settings.simulation,
                forecast_config=self.settings.forecast,
                cheap_window_hours=self._cheap_window_hours(),
            )
            self._annotate_snapshot_with_forecast(snapshot, forecast_plan)
            captured = await self._forecast_validation.async_capture(
                now,
                forecast,
                forecast_plan,
                planning_learned,
            )
            if captured:
                await self._forecast_validation.async_save()

            await self._history.async_record(snapshot)
            records = self._history.records
            self._forecast_validation.analyse(records, now)
            learned = self._learning.analyse(records, now)
            gas = self._gas.summarise(records, now)
            base_simulation = self._simulation.simulate_today(
                records,
                now,
                self.settings.simulation,
                learned.predicted_energy_until_offpeak_kwh,
                current_snapshot=snapshot,
            )
            scenarios = self._scenarios.compare(
                records,
                now,
                self.settings.simulation,
                learned.predicted_energy_until_offpeak_kwh,
                current_snapshot=snapshot,
            )
            agile_records = await self._agile_history_backfill.async_records(
                native_records=records,
                now=now,
                tariff=self.settings.tariff,
                config=self.settings.simulation,
            )
            await self._agile_smart_export.async_update(
                records=agile_records,
                now=now,
                config=self.settings.simulation,
                learned=learned,
                forecast=forecast,
                forecast_plan=forecast_plan,
                tariff=self.settings.tariff,
            )

            # Settle retained completed outcomes before the rolling target,
            # ControlState and shadow candidate are built. This prevents those
            # layers from validating against the older replay SOC after a real
            # simulated export has already spent that battery energy.
            self._agile_smart_export.reconcile_current_day_settlements(
                settled_half_hours=list(self._shadow_validation._settled),
                now=now,
            )
            agile_state = self._agile_smart_export.state
            simulation = reconciled_current_day_simulation(
                base_simulation,
                agile_state,
            )

            quality = assess_quality(
                snapshot,
                self.entities.configured_snapshot_fields(),
            )
            control_simulation, shadow_simulation, _alignment = (
                aligned_agile_control_views(simulation, agile_state)
            )
            control = self._control.plan(
                snapshot,
                control_simulation,
                now,
                self.settings.control,
            )
            control = align_agile_control_state(
                control,
                simulation,
                agile_state,
                self.settings.control,
            )
            await self._shadow_validation.async_update(
                snapshot=snapshot,
                simulation=shadow_simulation,
                control=control,
                now=now,
                config=self.settings.control,
                agile_state=agile_state,
            )

            # Capture any half-hour that settled during this scan, then rebuild
            # the published headline simulation from the same authoritative
            # current-day ledger. Dashboard, Pi/API consumers and financial
            # summaries therefore all receive one coherent KEMS/Agile basis.
            self._agile_smart_export.reconcile_current_day_settlements(
                settled_half_hours=list(self._shadow_validation._settled),
                now=now,
            )
            agile_state = self._agile_smart_export.state
            simulation = reconciled_current_day_simulation(
                base_simulation,
                agile_state,
            )

            advice = self._advice.evaluate(
                snapshot,
                learned,
                self.settings.simulation,
                gas,
            )
            whole_home = self._whole_home.summarise(snapshot, simulation, gas)
            stored_lifetime = await self._lifetime.async_update(
                simulation,
                gas,
                now,
                self.settings.roi,
            )
            lifetime = LifetimeLedger.from_dict(stored_lifetime.to_dict())
            periods = self._lifetime.period_summaries(now)
            roi = self._roi.evaluate(
                lifetime,
                simulation,
                now,
                self.settings.roi,
            )
            last_power_down = await self._power_down.async_update(
                snapshot,
                simulation,
                control,
                now,
                agile_state=agile_state,
            )
            phase = self._phase(
                learned.ready,
                simulation.ready,
                control.operating_mode,
            )
            return KEMSData(
                snapshot=snapshot,
                learned=learned,
                gas=gas,
                advice=advice,
                simulation=simulation,
                scenarios=scenarios,
                whole_home=whole_home,
                lifetime=lifetime,
                roi=roi,
                quality=quality,
                control=control,
                forecast=forecast,
                forecast_plan=forecast_plan,
                last_power_down=last_power_down,
                periods=periods,
                history_samples=len(records),
                phase=phase,
            )
        except Exception as err:
            raise UpdateFailed(f"KEMS analysis failed: {err}") from err

    def _cheap_window_hours(self) -> float:
        """Return configured normal overnight cheap-window duration."""
        start = self.settings.tariff.offpeak_start
        end = self.settings.tariff.offpeak_end
        start_minutes = start.hour * 60 + start.minute + start.second / 60.0
        end_minutes = end.hour * 60 + end.minute + end.second / 60.0
        minutes = (end_minutes - start_minutes) % (24 * 60)
        return round((minutes or 24 * 60) / 60.0, 3)

    @staticmethod
    def _annotate_snapshot_with_forecast(snapshot, plan) -> None:
        """Persist the current explainable forecast decision on the observation."""
        snapshot.forecast_source = plan.forecast_source
        snapshot.forecast_expected_solar_remaining_today_kwh = (
            plan.expected_solar_remaining_today_kwh
        )
        snapshot.forecast_expected_solar_tomorrow_kwh = plan.expected_solar_tomorrow_kwh
        snapshot.forecast_expected_house_remaining_today_kwh = (
            plan.expected_house_remaining_today_kwh
        )
        snapshot.forecast_expected_house_tomorrow_kwh = plan.expected_house_tomorrow_kwh
        snapshot.forecast_required_morning_soc_percent = (
            plan.required_morning_soc_percent
        )
        snapshot.forecast_minimum_precheap_soc_percent = (
            plan.minimum_precheap_soc_percent
        )
        snapshot.forecast_solar_recovery_target_percent = (
            plan.solar_recovery_target_percent
        )
        snapshot.forecast_maximum_overnight_soc_percent = (
            plan.maximum_overnight_soc_percent
        )
        snapshot.forecast_recharge_shortfall_kwh = plan.recharge_shortfall_kwh
        snapshot.forecast_recharge_target_feasible = plan.recharge_target_feasible
        snapshot.forecast_protection_state = plan.state
        snapshot.forecast_confidence_percent = plan.confidence_percent

    async def async_shutdown(self) -> None:
        """Flush retained KEMS state before unloading."""
        await self._history.async_save()
        await self._forecast_validation.async_save()
        await self._lifetime.async_save()
        await self._power_down.async_save()
        await self._shadow_validation.async_shutdown()
        await self._agile_smart_export.async_shutdown()
        await self._agile_history_backfill.async_shutdown()

    @staticmethod
    def _phase(
        learning_ready: bool,
        simulation_ready: bool,
        operating_mode: str,
    ) -> str:
        """Return the furthest currently active phase."""
        base = (
            "Observe → Learn → Advise → Simulate"
            if (simulation_ready and learning_ready)
            else "Observe → Learn → Advise" if learning_ready else "Observe → Learn"
        )
        if operating_mode == "shadow":
            return f"{base} → Shadow"
        if operating_mode == "control":
            return f"{base} → Control (blocked until commissioning)"
        if operating_mode == "simulate":
            return f"{base} → Control Lab"
        return base
