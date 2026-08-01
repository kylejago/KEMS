"""Home Assistant-independent KEMS domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(UTC)


@dataclass(slots=True)
class Snapshot:
    """One read-only observation of the whole-home energy system."""

    timestamp: datetime = field(default_factory=utc_now)

    current_import_rate: float | None = None
    next_import_rate: float | None = None
    current_export_rate: float | None = None
    electricity_standing_charge: float | None = None
    off_peak: bool | None = None
    intelligent_slot: bool | None = None
    next_offpeak_start: datetime | None = None
    offpeak_end: datetime | None = None

    gas_current_rate: float | None = None
    gas_standing_charge: float | None = None
    gas_meter_total_kwh: float | None = None
    gas_usage_today_kwh: float | None = None
    gas_cost_today_pence: float | None = None

    ev_connected: bool | None = None
    ev_charging: bool | None = None
    ev_power_kw: float | None = None
    ev_soc: float | None = None

    house_load_kw: float | None = None
    battery_soc: float | None = None
    battery_power_kw: float | None = None
    solar_power_kw: float | None = None
    grid_import_kw: float | None = None
    grid_export_kw: float | None = None
    raw_grid_import_kw: float | None = None
    raw_grid_export_kw: float | None = None
    grid_flow_mode: str = "no_grid_source"

    @property
    def cheap_period_confirmed(self) -> bool:
        """Return whether a usable cheap period is confirmed."""
        return self.off_peak is True or (
            self.intelligent_slot is True and self.ev_charging is True
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        for key in ("next_offpeak_start", "offpeak_end"):
            value = data[key]
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        """Restore a snapshot from JSON-compatible data."""
        values = dict(data)
        for key in ("timestamp", "next_offpeak_start", "offpeak_end"):
            value = values.get(key)
            if isinstance(value, str):
                values[key] = datetime.fromisoformat(value)
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in known})


@dataclass(frozen=True, slots=True)
class LearnedState:
    """What KEMS has learned from recorded observations."""

    days_observed: int = 0
    samples: int = 0
    confidence: float = 0.0
    ready: bool = False
    typical_house_load_kw: float | None = None
    typical_solar_power_kw: float | None = None
    typical_grid_import_kw: float | None = None
    predicted_energy_until_offpeak_kwh: float | None = None
    average_import_rate_pence: float | None = None
    profile_slots: int = 0


@dataclass(frozen=True, slots=True)
class GasSummary:
    """Observed gas consumption and cost summary."""

    available: bool = False
    usage_today_kwh: float | None = None
    cost_today_pence: float | None = None
    usage_month_kwh: float | None = None
    cost_month_pence: float | None = None
    typical_daily_usage_kwh: float | None = None
    current_rate_pence: float | None = None
    standing_charge_pence: float | None = None
    days_observed: int = 0
    data_coverage: float = 0.0


@dataclass(frozen=True, slots=True)
class AdviceItem:
    """One explainable, read-only KEMS recommendation."""

    code: str
    title: str
    message: str
    priority: int
    confidence: float
    estimated_saving_pence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible advice data."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AdviceState:
    """Current ordered set of KEMS recommendations."""

    primary: AdviceItem
    items: tuple[AdviceItem, ...] = ()


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Read-only proposal-system and tariff simulation settings."""

    battery_capacity_kwh: float = 56.42
    battery_reserve_percent: float = 10.0
    battery_initial_percent: float = 10.0
    max_charge_kw: float = 10.0
    max_discharge_kw: float = 10.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    export_rate_pence: float = 12.0
    export_limit_kw: float = 10.0
    battery_export_enabled: bool = True
    proposal_solar_enabled: bool = True
    proposal_solar_factor: float = 1.0
    battery_power_positive_is_discharge: bool = True
    strategy: str = "export_first"


@dataclass(frozen=True, slots=True)
class SimulationState:
    """Comparison of observed operation with the KEMS proposal simulation."""

    ready: bool = False
    samples: int = 0
    actual_cost_pence: float | None = None
    simulated_cost_pence: float | None = None
    saving_pence: float | None = None
    actual_import_cost_pence: float | None = None
    actual_export_income_pence: float | None = None
    simulated_import_cost_pence: float | None = None
    simulated_export_income_pence: float | None = None
    actual_house_consumption_kwh: float | None = None
    actual_ev_energy_kwh: float | None = None
    actual_solar_generation_kwh: float | None = None
    actual_battery_charge_kwh: float | None = None
    actual_battery_discharge_kwh: float | None = None
    actual_grid_import_kwh: float | None = None
    actual_grid_export_kwh: float | None = None
    simulated_grid_import_kwh: float | None = None
    simulated_grid_export_kwh: float | None = None
    simulated_solar_generation_kwh: float | None = None
    simulated_solar_curtailed_kwh: float | None = None
    simulated_battery_charge_kwh: float | None = None
    simulated_battery_to_home_kwh: float | None = None
    simulated_battery_export_kwh: float | None = None
    simulated_battery_soc: float | None = None
    avoided_day_rate_import_kwh: float | None = None
    baseline_no_system_cost_pence: float | None = None
    actual_avoided_import_value_pence: float | None = None
    simulated_avoided_import_value_pence: float | None = None
    actual_system_value_pence: float | None = None
    simulated_system_value_pence: float | None = None
    current_simulated_house_load_kw: float | None = None
    current_simulated_solar_power_kw: float | None = None
    current_simulated_grid_import_kw: float | None = None
    current_simulated_grid_export_kw: float | None = None
    current_simulated_battery_power_kw: float | None = None
    effective_export_rate_pence: float | None = None
    export_limit_kw: float | None = None
    proposal_solar_active: bool = False
    battery_export_enabled: bool = False
    data_coverage: float = 0.0


@dataclass(frozen=True, slots=True)
class WholeHomeSummary:
    """Combined electricity and gas energy/cost summary."""

    observed_electricity_cost_pence: float | None = None
    simulated_electricity_cost_pence: float | None = None
    observed_gas_cost_pence: float | None = None
    observed_total_cost_pence: float | None = None
    simulated_total_cost_pence: float | None = None
    simulated_saving_pence: float | None = None
    observed_electricity_kwh: float | None = None
    observed_gas_kwh: float | None = None
    observed_total_energy_kwh: float | None = None
    gas_energy_share_percent: float | None = None


@dataclass(frozen=True, slots=True)
class ROIConfig:
    """Financial assumptions for predicted and actual ROI tracking."""

    system_cost_gbp: float = 20995.0
    additional_costs_gbp: float = 0.0
    grants_rebates_gbp: float = 0.0
    commissioning_date: date | None = None
    annual_maintenance_gbp: float = 0.0
    manual_system_costs_gbp: float = 0.0
    electricity_inflation_percent: float = 3.0
    battery_degradation_percent: float = 2.0
    discount_rate_percent: float = 6.75
    forecast_years: int = 20

    @property
    def net_investment_gbp(self) -> float:
        """Return the investment KEMS must recover."""
        return max(
            self.system_cost_gbp + self.additional_costs_gbp - self.grants_rebates_gbp,
            0.0,
        )


@dataclass(slots=True)
class LifetimeLedger:
    """Persistent all-time energy, cost, earnings, and value totals."""

    first_observation: datetime | None = None
    last_updated: datetime | None = None
    commissioning_date: date | None = None
    paid_back_date: date | None = None
    observed_days: int = 0
    system_operating_days: int = 0

    house_consumption_kwh: float = 0.0
    ev_energy_kwh: float = 0.0
    grid_import_kwh: float = 0.0
    grid_export_kwh: float = 0.0
    solar_generation_kwh: float = 0.0
    battery_charge_kwh: float = 0.0
    battery_discharge_kwh: float = 0.0
    gas_consumption_kwh: float = 0.0

    import_cost_pence: float = 0.0
    export_income_pence: float = 0.0
    gas_cost_pence: float = 0.0
    actual_avoided_import_value_pence: float = 0.0
    actual_system_value_pence: float = 0.0
    simulated_system_value_pence: float = 0.0
    system_operating_cost_pence: float = 0.0

    best_system_value_day: date | None = None
    best_system_value_day_pence: float = 0.0
    best_solar_day: date | None = None
    best_solar_day_kwh: float = 0.0
    best_export_day: date | None = None
    best_export_day_kwh: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        data = asdict(self)
        for key in ("first_observation", "last_updated"):
            value = data[key]
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        for key in (
            "commissioning_date",
            "paid_back_date",
            "best_system_value_day",
            "best_solar_day",
            "best_export_day",
        ):
            value = data[key]
            if isinstance(value, date):
                data[key] = value.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifetimeLedger:
        """Restore ledger totals from storage."""
        values = dict(data)
        for key in ("first_observation", "last_updated"):
            value = values.get(key)
            if isinstance(value, str):
                values[key] = datetime.fromisoformat(value)
        for key in (
            "commissioning_date",
            "paid_back_date",
            "best_system_value_day",
            "best_solar_day",
            "best_export_day",
        ):
            value = values.get(key)
            if isinstance(value, str):
                values[key] = date.fromisoformat(value)
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in known})


@dataclass(frozen=True, slots=True)
class ROIState:
    """Predicted ROI, actual payback, and post-payback profit state."""

    ready: bool = False
    status: str = "Learning financial baseline"
    system_installed: bool = False
    system_paid_back: bool = False
    net_investment_gbp: float = 0.0
    predicted_annual_saving_gbp: float | None = None
    predicted_payback_years: float | None = None
    predicted_payback_date: datetime | None = None
    predicted_net_value_gbp: float | None = None
    proposal_annual_saving_gbp: float = 1856.0
    proposal_payback_years: float = 9.75
    proposal_lifetime_savings_gbp: float = 55128.0
    proposal_net_savings_gbp: float = 34133.0
    actual_value_created_today_gbp: float | None = None
    actual_value_created_total_gbp: float | None = None
    actual_roi_percent: float | None = None
    actual_payback_remaining_gbp: float | None = None
    actual_payback_date: datetime | None = None
    actual_net_profit_gbp: float | None = None
    operating_costs_gbp: float = 0.0
    confidence: float = 0.0
    observed_days: int = 0
    operating_days: int = 0


@dataclass(frozen=True, slots=True)
class DataQuality:
    """Coverage and health of the configured observations."""

    score: float
    configured: int
    available: int
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KEMSData:
    """Complete coordinator payload exposed to KEMS entities."""

    snapshot: Snapshot
    learned: LearnedState
    gas: GasSummary
    advice: AdviceState
    simulation: SimulationState
    whole_home: WholeHomeSummary
    lifetime: LifetimeLedger
    roi: ROIState
    quality: DataQuality
    history_samples: int
    phase: str
