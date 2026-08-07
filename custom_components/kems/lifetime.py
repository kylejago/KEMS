"""Persistent all-time energy and financial ledger for KEMS."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, SIMULATION_LEDGER_VERSION, STORAGE_NAMESPACE
from .kems_core import (
    PERIOD_DATA_COMPLETE_KEY,
    GasEngine,
    GasSummary,
    LifetimeLedger,
    PeriodTotals,
    ROIConfig,
    SimulationConfig,
    SimulationEngine,
    SimulationState,
    Snapshot,
    period_value_keys,
    period_value_kwargs,
    reconciled_simulated_lifetime_values,
    summarise_period_records,
)
from .kems_core.lifetime_accounting import (
    SIGNED_LIFETIME_KEYS,
    should_accumulate_lifetime_value,
)

STORAGE_VERSION = 1
LEDGER_SCHEMA_VERSION = 2
SAVE_EVERY_UPDATES = 5
SIGNED_VALUE_KEYS = SIGNED_LIFETIME_KEYS


class LifetimeLedgerRecorder:
    """Accumulate all-time totals without relying on Recorder retention."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialise the lifetime ledger store."""
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.lifetime",
        )
        self._ledger = LifetimeLedger()
        self._tracking_date: date | None = None
        self._tracking_values: dict[str, float] = {}
        self._daily_records: dict[str, dict[str, float]] = {}
        self._maintenance_date: date | None = None
        self._updates_since_save = 0
        self._loaded_existing = False
        self._repair_required = False
        self._ledger_schema_version = LEDGER_SCHEMA_VERSION
        self._simulation_ledger_version = SIMULATION_LEDGER_VERSION

    @property
    def ledger(self) -> LifetimeLedger:
        """Return the current mutable ledger object."""
        return self._ledger

    @property
    def loaded_existing(self) -> bool:
        """Return whether a stored ledger was restored."""
        return self._loaded_existing

    async def async_load(self) -> None:
        """Load all-time totals and current-day tracking metadata."""
        data = await self._store.async_load()
        if not data:
            return
        self._loaded_existing = True
        self._ledger = LifetimeLedger.from_dict(data.get("ledger", {}))
        stored_ledger_version = int(data.get("ledger_schema_version", 1))
        self._repair_required = stored_ledger_version < LEDGER_SCHEMA_VERSION
        self._ledger.historical_repair_required = self._repair_required
        self._ledger_schema_version = LEDGER_SCHEMA_VERSION
        tracking_date = data.get("tracking_date")
        if isinstance(tracking_date, str):
            self._tracking_date = date.fromisoformat(tracking_date)
        self._tracking_values = {
            key: float(value)
            for key, value in data.get("tracking_values", {}).items()
            if isinstance(value, (int, float))
        }
        self._daily_records = {
            str(day): {
                key: float(value)
                for key, value in values.items()
                if isinstance(value, (int, float))
            }
            for day, values in data.get("daily_records", {}).items()
            if isinstance(values, dict)
        }
        stored_simulation_version = int(data.get("simulation_ledger_version", 1))
        if stored_simulation_version < SIMULATION_LEDGER_VERSION:
            # Keep all observed history and actual post-install totals, but
            # discard simulated financial value produced by the superseded
            # alpha2 reserve calculation. The current day is recalculated with
            # the protected home-reserve fallback on the first refresh.
            self._ledger.simulated_system_value_pence = 0.0
            self._tracking_values["simulated_system_value_pence"] = 0.0
        self._simulation_ledger_version = SIMULATION_LEDGER_VERSION
        if not self._repair_required:
            self._reconcile_simulated_totals()
        maintenance_date = data.get("maintenance_date")
        if isinstance(maintenance_date, str):
            self._maintenance_date = date.fromisoformat(maintenance_date)

    async def async_bootstrap(
        self,
        records: list[Snapshot],
        simulation_engine: SimulationEngine,
        gas_engine: GasEngine,
        simulation_config: SimulationConfig,
        roi_config: ROIConfig,
    ) -> None:
        """Build a first ledger from retained KEMS observations."""
        if not records:
            return
        if self._loaded_existing and not self._repair_required:
            return

        rebuilding_existing_ledger = self._loaded_existing and self._repair_required
        if self._repair_required:
            self._reset_rebuildable_totals()

        history_first = min(
            records,
            key=lambda item: item.timestamp,
        ).timestamp
        if self._ledger.first_observation is None:
            self._ledger.first_observation = history_first
        else:
            self._ledger.first_observation = min(
                self._ledger.first_observation,
                history_first,
            )
        by_day: dict[date, list[Snapshot]] = defaultdict(list)
        for record in sorted(records, key=lambda item: item.timestamp):
            by_day[record.timestamp.date()].append(record)

        cumulative_records: list[Snapshot] = []
        for day in sorted(by_day):
            day_records = by_day[day]
            cumulative_records.extend(day_records)
            if len(day_records) < 2:
                self._daily_records[day.isoformat()] = {}
                self._ledger.accumulation_days_incomplete += 1
                continue
            now = day_records[-1].timestamp
            simulation = simulation_engine.simulate_today(
                cumulative_records,
                now,
                simulation_config,
            )
            gas = gas_engine.summarise(cumulative_records, now)
            self._apply_cumulative_day(
                now,
                simulation,
                gas,
                roi_config,
                include_commissioned_value=not rebuilding_existing_ledger,
            )
            self._record_maintenance(day, roi_config)
            self._check_payback(day, roi_config)

        self._repair_required = False
        self._ledger.historical_repair_required = False
        self._ledger.accumulator_status = "healthy"
        await self.async_save()

    async def async_update(
        self,
        simulation: SimulationState,
        gas: GasSummary,
        now: datetime,
        config: ROIConfig,
    ) -> LifetimeLedger:
        """Apply changes in current-day cumulative metrics to the ledger."""
        if (
            self._ledger.commissioning_date is None
            and config.commissioning_date is not None
            and now.date() >= config.commissioning_date
            and self._tracking_date == now.date()
        ):
            # Keep the pre-installation consumption and billing baseline, but
            # start commissioned-only value counters from this refresh. This
            # prevents a mid-day commissioning date from claiming value that
            # was modelled before the physical system became operational.
            self._tracking_values["actual_avoided_import_value_pence"] = (
                simulation.actual_avoided_import_value_pence or 0.0
            )
            self._tracking_values["actual_system_value_pence"] = (
                simulation.actual_system_value_pence or 0.0
            )
        self._apply_cumulative_day(now, simulation, gas, config)
        self._ledger.last_updated = now
        self._ledger.commissioning_date = config.commissioning_date
        self._ledger.observed_days = self._inclusive_days(
            self._ledger.first_observation,
            now,
        )
        self._ledger.last_successful_accumulation = now
        self._ledger.accumulator_status = "healthy"
        self._ledger.historical_repair_required = self._repair_required
        self._ledger.system_operating_days = self._operating_days(
            config.commissioning_date,
            now.date(),
        )
        self._record_maintenance(now.date(), config)
        self._check_payback(now.date(), config)

        self._updates_since_save += 1
        if self._updates_since_save >= SAVE_EVERY_UPDATES:
            await self.async_save()
        return self._ledger

    async def async_save(self) -> None:
        """Persist totals and the latest daily cumulative values."""
        if self._tracking_date is not None:
            self._finalise_best_day(self._tracking_date, self._tracking_values)
        await self._store.async_save(
            {
                "ledger": self._ledger.to_dict(),
                "tracking_date": (
                    self._tracking_date.isoformat() if self._tracking_date else None
                ),
                "tracking_values": self._tracking_values,
                "daily_records": self._daily_records,
                "maintenance_date": (
                    self._maintenance_date.isoformat()
                    if self._maintenance_date
                    else None
                ),
                "simulation_ledger_version": self._simulation_ledger_version,
                "ledger_schema_version": self._ledger_schema_version,
            }
        )
        self._updates_since_save = 0

    def _apply_cumulative_day(
        self,
        now: datetime,
        simulation: SimulationState,
        gas: GasSummary,
        config: ROIConfig,
        *,
        include_commissioned_value: bool = True,
    ) -> None:
        """Apply one day's current cumulative values using delta accounting."""
        current_date = now.date()
        values = self._current_values(simulation, gas)

        if self._ledger.first_observation is None:
            self._ledger.first_observation = now

        if self._tracking_date is not None and self._tracking_date != current_date:
            self._finalise_best_day(self._tracking_date, self._tracking_values)
            self._daily_records[self._tracking_date.isoformat()] = dict(
                self._tracking_values
            )
            self._ledger.last_daily_rollover = self._tracking_date
            previous_complete = bool(self._tracking_values) and (
                self._tracking_values.get(PERIOD_DATA_COMPLETE_KEY, 1.0) >= 0.5
            )
            if previous_complete:
                self._ledger.accumulation_days_complete += 1
            else:
                self._ledger.accumulation_days_incomplete += 1
            previous_values: dict[str, float] = {}
        else:
            previous_values = self._tracking_values

        installed = (
            config.commissioning_date is not None
            and current_date >= config.commissioning_date
        )
        for key, current in values.items():
            if key == PERIOD_DATA_COMPLETE_KEY:
                continue
            previous = previous_values.get(key, 0.0)
            delta = current - previous
            if key not in SIGNED_VALUE_KEYS:
                delta = max(delta, 0.0)
            self._add_delta(
                key,
                delta,
                installed and include_commissioned_value,
            )

        self._tracking_date = current_date
        self._tracking_values = values
        self._reconcile_simulated_totals()
        self._ledger.last_updated = now

    @staticmethod
    def _current_values(
        simulation: SimulationState,
        gas: GasSummary,
    ) -> dict[str, float]:
        """Return current-day cumulative values with missing data as zero."""
        return {
            PERIOD_DATA_COMPLETE_KEY: (
                1.0 if simulation.data_coverage >= 99.9 else 0.0
            ),
            "house_consumption_kwh": simulation.actual_house_consumption_kwh or 0.0,
            "ev_energy_kwh": simulation.actual_ev_energy_kwh or 0.0,
            "grid_import_kwh": simulation.actual_grid_import_kwh or 0.0,
            "grid_export_kwh": simulation.actual_grid_export_kwh or 0.0,
            "solar_generation_kwh": simulation.actual_solar_generation_kwh or 0.0,
            "battery_charge_kwh": simulation.actual_battery_charge_kwh or 0.0,
            "battery_discharge_kwh": simulation.actual_battery_discharge_kwh or 0.0,
            "gas_consumption_kwh": gas.usage_today_kwh or 0.0,
            "import_cost_pence": simulation.actual_import_cost_pence or 0.0,
            "export_income_pence": simulation.actual_export_income_pence or 0.0,
            "gas_cost_pence": gas.cost_today_pence or 0.0,
            "simulated_grid_import_kwh": (simulation.simulated_grid_import_kwh or 0.0),
            "simulated_grid_export_kwh": (simulation.simulated_grid_export_kwh or 0.0),
            "simulated_solar_generation_kwh": (
                simulation.simulated_solar_generation_kwh or 0.0
            ),
            "simulated_battery_charge_kwh": (
                simulation.simulated_battery_charge_kwh or 0.0
            ),
            "simulated_battery_to_home_kwh": (
                simulation.simulated_battery_to_home_kwh or 0.0
            ),
            "simulated_battery_export_kwh": (
                simulation.simulated_battery_export_kwh or 0.0
            ),
            "simulated_avoided_day_rate_import_kwh": (
                simulation.avoided_day_rate_import_kwh or 0.0
            ),
            "simulated_import_cost_pence": (
                simulation.simulated_import_cost_pence or 0.0
            ),
            "simulated_export_income_pence": (
                simulation.simulated_export_income_pence or 0.0
            ),
            "simulated_net_cost_pence": simulation.simulated_cost_pence or 0.0,
            "simulated_avoided_import_value_pence": (
                simulation.simulated_avoided_import_value_pence or 0.0
            ),
            "actual_avoided_import_value_pence": (
                simulation.actual_avoided_import_value_pence or 0.0
            ),
            "actual_system_value_pence": simulation.actual_system_value_pence or 0.0,
            "simulated_system_value_pence": (
                simulation.simulated_system_value_pence or 0.0
            ),
        }

    def _add_delta(self, key: str, delta: float, installed: bool) -> None:
        """Add a delta to the correct lifetime total."""
        if not delta:
            return

        # Observed consumption and bill evidence exists before installation and
        # is required for learning, reporting and the financial baseline. Only
        # value created by the physical system is commissioning-gated.
        if should_accumulate_lifetime_value(key, installed):
            setattr(self._ledger, key, getattr(self._ledger, key) + delta)

    def _reconcile_simulated_totals(self) -> None:
        """Make simulated lifetime totals match the persisted daily ledger."""
        values = reconciled_simulated_lifetime_values(
            self._daily_records.values(),
            self._tracking_values if self._tracking_date is not None else None,
        )
        for key, value in values.items():
            setattr(self._ledger, key, value)

    def _reset_rebuildable_totals(self) -> None:
        """Reset alpha2 totals that can be deterministically rebuilt from history."""
        for key in (
            "house_consumption_kwh",
            "ev_energy_kwh",
            "grid_import_kwh",
            "grid_export_kwh",
            "solar_generation_kwh",
            "battery_charge_kwh",
            "battery_discharge_kwh",
            "gas_consumption_kwh",
            "import_cost_pence",
            "export_income_pence",
            "gas_cost_pence",
            "simulated_grid_import_kwh",
            "simulated_grid_export_kwh",
            "simulated_solar_generation_kwh",
            "simulated_battery_charge_kwh",
            "simulated_battery_to_home_kwh",
            "simulated_battery_export_kwh",
            "simulated_avoided_day_rate_import_kwh",
            "simulated_import_cost_pence",
            "simulated_export_income_pence",
            "simulated_net_cost_pence",
            "simulated_avoided_import_value_pence",
            "simulated_system_value_pence",
        ):
            setattr(self._ledger, key, 0.0)
        self._tracking_date = None
        self._tracking_values = {}
        self._daily_records = {}
        self._ledger.last_daily_rollover = None
        self._ledger.last_successful_accumulation = None
        self._ledger.accumulation_days_complete = 0
        self._ledger.accumulation_days_incomplete = 0
        self._ledger.best_system_value_day = None
        self._ledger.best_system_value_day_pence = 0.0
        self._ledger.best_solar_day = None
        self._ledger.best_solar_day_kwh = 0.0
        self._ledger.best_export_day = None
        self._ledger.best_export_day_kwh = 0.0
        self._ledger.accumulator_status = "repairing_history"
        self._ledger.historical_repair_required = True

    def period_summaries(self, now: datetime) -> dict[str, PeriodTotals]:
        """Return today, week, month, year, and all-time reporting totals."""
        today = now.date()
        records = dict(self._daily_records)
        if self._tracking_date == today:
            records[today.isoformat()] = dict(self._tracking_values)

        week_start = date.fromordinal(today.toordinal() - today.weekday())
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)
        return {
            "today": summarise_period_records(
                records,
                today,
                today,
                current_day=today,
            ),
            "week": summarise_period_records(
                records,
                week_start,
                today,
                current_day=today,
            ),
            "month": summarise_period_records(
                records,
                month_start,
                today,
                current_day=today,
            ),
            "year": summarise_period_records(
                records,
                year_start,
                today,
                current_day=today,
            ),
            "all_time": self._all_time_summary(today),
        }

    def _all_time_summary(self, today: date) -> PeriodTotals:
        values = {
            key: float(getattr(self._ledger, key, 0.0)) for key in period_value_keys()
        }
        return PeriodTotals(
            start_date=(
                self._ledger.first_observation.date()
                if self._ledger.first_observation
                else None
            ),
            end_date=today,
            days_included=self._ledger.observed_days,
            complete_days=self._ledger.accumulation_days_complete,
            incomplete_days=self._ledger.accumulation_days_incomplete,
            data_complete=(
                not self._ledger.historical_repair_required
                and self._ledger.accumulation_days_incomplete == 0
            ),
            **period_value_kwargs(values),
        )

    def _record_maintenance(self, current_date: date, config: ROIConfig) -> None:
        """Accrue the configured annual maintenance allowance once per day."""
        if (
            config.commissioning_date is None
            or current_date < config.commissioning_date
            or self._maintenance_date == current_date
        ):
            return
        self._ledger.system_operating_cost_pence += (
            max(config.annual_maintenance_gbp, 0.0) * 100 / 365.25
        )
        self._maintenance_date = current_date

    def _check_payback(self, current_date: date, config: ROIConfig) -> None:
        """Permanently record the first date actual value repays the investment."""
        if self._ledger.paid_back_date is not None:
            return
        investment_pence = config.net_investment_gbp * 100
        costs = self._ledger.system_operating_cost_pence
        costs += max(config.manual_system_costs_gbp, 0.0) * 100
        recovered = self._ledger.actual_system_value_pence - costs
        if investment_pence > 0 and recovered >= investment_pence:
            self._ledger.paid_back_date = current_date

    def _finalise_best_day(self, day: date, values: dict[str, float]) -> None:
        """Update best-day lifetime records from the completed day."""
        system_value = values.get("actual_system_value_pence", 0.0)
        if system_value > self._ledger.best_system_value_day_pence:
            self._ledger.best_system_value_day = day
            self._ledger.best_system_value_day_pence = system_value

        solar = values.get("solar_generation_kwh", 0.0)
        if solar > self._ledger.best_solar_day_kwh:
            self._ledger.best_solar_day = day
            self._ledger.best_solar_day_kwh = solar

        exported = values.get("grid_export_kwh", 0.0)
        if exported > self._ledger.best_export_day_kwh:
            self._ledger.best_export_day = day
            self._ledger.best_export_day_kwh = exported

    @staticmethod
    def _inclusive_days(first: datetime | None, now: datetime) -> int:
        """Return inclusive observed days."""
        if first is None:
            return 0
        return max((now.date() - first.date()).days + 1, 1)

    @staticmethod
    def _operating_days(commissioning: date | None, current: date) -> int:
        """Return inclusive operating days since commissioning."""
        if commissioning is None or current < commissioning:
            return 0
        return (current - commissioning).days + 1
