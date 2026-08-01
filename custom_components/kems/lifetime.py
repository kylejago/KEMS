"""Persistent all-time energy and financial ledger for KEMS."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core import (
    GasEngine,
    GasSummary,
    LifetimeLedger,
    ROIConfig,
    SimulationConfig,
    SimulationEngine,
    SimulationState,
    Snapshot,
)

STORAGE_VERSION = 1
SAVE_EVERY_UPDATES = 5
SIGNED_VALUE_KEYS = {
    "actual_avoided_import_value_pence",
    "actual_system_value_pence",
    "simulated_system_value_pence",
}


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
        self._maintenance_date: date | None = None
        self._updates_since_save = 0
        self._loaded_existing = False

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
        tracking_date = data.get("tracking_date")
        if isinstance(tracking_date, str):
            self._tracking_date = date.fromisoformat(tracking_date)
        self._tracking_values = {
            key: float(value)
            for key, value in data.get("tracking_values", {}).items()
            if isinstance(value, (int, float))
        }
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
        if self._loaded_existing or not records:
            return

        self._ledger.first_observation = min(
            records,
            key=lambda item: item.timestamp,
        ).timestamp
        by_day: dict[date, list[Snapshot]] = defaultdict(list)
        for record in sorted(records, key=lambda item: item.timestamp):
            by_day[record.timestamp.date()].append(record)

        cumulative_records: list[Snapshot] = []
        for day in sorted(by_day):
            day_records = by_day[day]
            cumulative_records.extend(day_records)
            if len(day_records) < 2:
                continue
            now = day_records[-1].timestamp
            simulation = simulation_engine.simulate_today(
                cumulative_records,
                now,
                simulation_config,
            )
            gas = gas_engine.summarise(cumulative_records, now)
            self._apply_cumulative_day(now, simulation, gas, roi_config)
            self._record_maintenance(day, roi_config)
            self._check_payback(day, roi_config)

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
            simulated_value = self._tracking_values.get(
                "simulated_system_value_pence",
                0.0,
            )
            self._tracking_values = {
                "simulated_system_value_pence": simulated_value,
            }
        self._apply_cumulative_day(now, simulation, gas, config)
        self._ledger.last_updated = now
        self._ledger.commissioning_date = config.commissioning_date
        self._ledger.observed_days = self._inclusive_days(
            self._ledger.first_observation,
            now,
        )
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
                "maintenance_date": (
                    self._maintenance_date.isoformat()
                    if self._maintenance_date
                    else None
                ),
            }
        )
        self._updates_since_save = 0

    def _apply_cumulative_day(
        self,
        now: datetime,
        simulation: SimulationState,
        gas: GasSummary,
        config: ROIConfig,
    ) -> None:
        """Apply one day's current cumulative values using delta accounting."""
        current_date = now.date()
        values = self._current_values(simulation, gas)

        if self._ledger.first_observation is None:
            self._ledger.first_observation = now

        if self._tracking_date is not None and self._tracking_date != current_date:
            self._finalise_best_day(self._tracking_date, self._tracking_values)
            previous_values: dict[str, float] = {}
        else:
            previous_values = self._tracking_values

        installed = (
            config.commissioning_date is not None
            and current_date >= config.commissioning_date
        )
        for key, current in values.items():
            previous = previous_values.get(key, 0.0)
            delta = current - previous
            if key not in SIGNED_VALUE_KEYS:
                delta = max(delta, 0.0)
            self._add_delta(key, delta, installed)

        self._tracking_date = current_date
        self._tracking_values = values
        self._ledger.last_updated = now

    @staticmethod
    def _current_values(
        simulation: SimulationState,
        gas: GasSummary,
    ) -> dict[str, float]:
        """Return current-day cumulative values with missing data as zero."""
        return {
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

        always_recorded = {"simulated_system_value_pence"}
        installed_only = {
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
            "actual_avoided_import_value_pence",
            "actual_system_value_pence",
        }
        if key in always_recorded or (installed and key in installed_only):
            setattr(self._ledger, key, getattr(self._ledger, key) + delta)

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
