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

    saving_session_joined: bool = False
    saving_session_active: bool = False
    saving_session_id: str | None = None
    saving_session_start: datetime | None = None
    saving_session_end: datetime | None = None
    saving_session_octopoints_per_kwh: float | None = None
    saving_session_import_baseline_period_kwh: float | None = None
    saving_session_export_baseline_period_kwh: float | None = None
    saving_session_import_baseline_total_kwh: float | None = None
    saving_session_export_baseline_total_kwh: float | None = None
    saving_session_baseline_period_start: datetime | None = None
    saving_session_baseline_period_end: datetime | None = None
    saving_session_baseline_incomplete: bool | None = None

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

    # Freshness metadata is recorded alongside the observation so that stale
    # live power sources cannot silently become valid-looking history.
    source_age_seconds: dict[str, float] = field(default_factory=dict)
    stale_fields: tuple[str, ...] = ()
    source_data_age_seconds: float | None = None

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
        data["stale_fields"] = list(self.stale_fields)
        for key in (
            "next_offpeak_start",
            "offpeak_end",
            "saving_session_start",
            "saving_session_end",
            "saving_session_baseline_period_start",
            "saving_session_baseline_period_end",
        ):
            value = data[key]
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        """Restore a snapshot from JSON-compatible data."""
        values = dict(data)
        for key in (
            "timestamp",
            "next_offpeak_start",
            "offpeak_end",
            "saving_session_start",
            "saving_session_end",
            "saving_session_baseline_period_start",
            "saving_session_baseline_period_end",
        ):
            value = values.get(key)
            if isinstance(value, str):
                values[key] = datetime.fromisoformat(value)
        stale_fields = values.get("stale_fields")
        if isinstance(stale_fields, list):
            values["stale_fields"] = tuple(str(item) for item in stale_fields)
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in known})


@dataclass(frozen=True, slots=True)
class LearnedState:
    """What KEMS has learned from recorded observations."""

    days_observed: int = 0
    elapsed_observation_days: float = 0.0
    samples: int = 0
    data_coverage: float = 0.0
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
    max_charge_kw: float = 7.0
    max_discharge_kw: float = 7.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    export_rate_pence: float = 12.0
    export_tariff_status: str = "active"
    inverter_limit_kw: float = 7.0
    export_limit_kw: float = 7.0
    eps_output_limit_kw: float = 7.0
    site_import_limit_kw: float | None = None
    battery_export_enabled: bool = True
    proposal_solar_enabled: bool = True
    proposal_solar_factor: float = 1.0
    battery_power_positive_is_discharge: bool = True
    strategy: str = "paced_export"
    saving_session_enabled: bool = True
    island_reserve_percent: float = 20.0


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
    simulated_cheap_import_cost_pence: float | None = None
    simulated_day_import_cost_pence: float | None = None
    simulated_export_income_pence: float | None = None
    actual_house_consumption_kwh: float | None = None
    actual_ev_energy_kwh: float | None = None
    actual_solar_generation_kwh: float | None = None
    actual_battery_charge_kwh: float | None = None
    actual_battery_discharge_kwh: float | None = None
    actual_grid_import_kwh: float | None = None
    actual_grid_export_kwh: float | None = None
    simulated_grid_import_kwh: float | None = None
    simulated_cheap_import_kwh: float | None = None
    simulated_day_import_kwh: float | None = None
    simulated_grid_export_kwh: float | None = None
    simulated_solar_generation_kwh: float | None = None
    simulated_solar_to_home_kwh: float | None = None
    simulated_solar_to_battery_kwh: float | None = None
    simulated_solar_export_kwh: float | None = None
    simulated_grid_to_battery_kwh: float | None = None
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
    current_simulated_battery_charge_power_kw: float | None = None
    current_simulated_solar_to_battery_power_kw: float | None = None
    current_simulated_battery_to_home_power_kw: float | None = None
    current_simulated_battery_export_power_kw: float | None = None
    current_simulated_total_kh7_output_kw: float | None = None
    current_simulated_grid_bypass_power_kw: float | None = None
    current_simulated_total_site_import_kw: float | None = None
    target_battery_export_power_kw: float | None = None
    exportable_battery_energy_kwh: float | None = None
    reserved_for_home_kwh: float | None = None
    hours_until_next_cheap_period: float | None = None
    projected_soc_at_cheap_period_percent: float | None = None
    home_reserve_forecast_source: str = "unavailable"
    projected_grid_import_before_cheap_kwh: float | None = None
    battery_export_paused_for_home_reserve: bool = False
    saving_session_joined: bool = False
    saving_session_active: bool = False
    saving_session_start: datetime | None = None
    saving_session_end: datetime | None = None
    saving_session_duration_minutes: float | None = None
    saving_session_octopoints_per_kwh: float | None = None
    saving_session_bonus_rate_pence: float | None = None
    saving_session_baseline_net_kwh: float | None = None
    saving_session_baseline_source: str = "unavailable"
    saving_session_baseline_incomplete: bool | None = None
    saving_session_battery_reserve_kwh: float | None = None
    saving_session_export_target_kw: float | None = None
    estimated_saving_session_export_kwh: float | None = None
    estimated_saving_session_rewardable_reduction_kwh: float | None = None
    estimated_saving_session_bonus_pence: float | None = None
    estimated_saving_session_export_income_pence: float | None = None
    estimated_saving_session_total_income_pence: float | None = None
    simulated_saving_session_bonus_pence: float | None = None
    battery_reserved_for_saving_session: bool = False
    battery_export_reduced_for_saving_session: bool = False
    effective_export_rate_pence: float | None = None
    export_tariff_status: str = "active"
    export_tariff_active: bool = True
    no_export_mode_active: bool = False
    overnight_charge_target_percent: float | None = None
    overnight_charge_target_kwh: float | None = None
    forecast_home_until_next_cheap_kwh: float | None = None
    forecast_solar_until_next_cheap_kwh: float | None = None
    forecast_solar_credit_kwh: float | None = None
    inverter_limit_kw: float | None = None
    export_limit_kw: float | None = None
    battery_charge_limit_kw: float | None = None
    battery_discharge_limit_kw: float | None = None
    eps_output_limit_kw: float | None = None
    site_import_limit_kw: float | None = None
    site_import_headroom_kw: float | None = None
    site_import_limit_exceeded: bool = False
    strategy: str = "paced_export"
    proposal_solar_active: bool = False
    battery_export_enabled: bool = False
    data_coverage: float = 0.0


@dataclass(frozen=True, slots=True)
class ScenarioSummary:
    """One what-if financial or resilience result for a system design."""

    key: str
    label: str
    description: str = ""
    ready: bool = False
    samples: int = 0
    data_coverage: float = 0.0
    import_cost_pence: float = 0.0
    cheap_import_cost_pence: float = 0.0
    day_import_cost_pence: float = 0.0
    export_income_pence: float = 0.0
    power_down_income_pence: float = 0.0
    standing_charge_pence: float = 0.0
    energy_net_cost_pence: float = 0.0
    total_cost_pence: float = 0.0
    saving_vs_no_system_pence: float = 0.0
    day_rate_import_reduction_pence: float = 0.0
    cheap_rate_import_change_pence: float = 0.0
    house_consumption_kwh: float = 0.0
    grid_import_kwh: float = 0.0
    cheap_grid_import_kwh: float = 0.0
    day_grid_import_kwh: float = 0.0
    grid_export_kwh: float = 0.0
    solar_generation_kwh: float = 0.0
    solar_to_home_kwh: float = 0.0
    solar_to_battery_kwh: float = 0.0
    solar_export_kwh: float = 0.0
    solar_curtailed_kwh: float = 0.0
    battery_charge_kwh: float = 0.0
    battery_grid_charge_kwh: float = 0.0
    battery_solar_charge_kwh: float = 0.0
    battery_to_home_kwh: float = 0.0
    battery_export_kwh: float = 0.0
    ending_soc_percent: float | None = None
    financially_comparable: bool = True
    grid_available: bool = True
    outage_survived: bool | None = None
    outage_status: str | None = None
    outage_duration_hours: float = 0.0
    load_served_kwh: float = 0.0
    unserved_load_kwh: float = 0.0
    load_served_percent: float | None = None
    starting_soc_percent: float | None = None
    minimum_soc_percent: float | None = None
    conservation_threshold_percent: float | None = None
    emergency_floor_percent: float | None = None
    eps_limited_unserved_kwh: float = 0.0
    energy_limited_unserved_kwh: float = 0.0
    first_shortfall_at: str | None = None
    estimated_remaining_runtime_hours: float | None = None
    battery_energy_above_floor_kwh: float | None = None

    # Prepared-outage resilience. This is the same solar/battery/EPS system,
    # but KEMS is assumed to have advance notice and may pre-charge before the
    # replay starts. It remains non-financial and separate from cheapest ranking.
    required_starting_soc_percent: float | None = None
    required_starting_soc_status: str | None = None
    recommended_prepared_soc_percent: float | None = None
    prepared_starting_soc_percent: float | None = None
    prepared_soc_margin_percent: float | None = None
    prepared_outage_survived: bool | None = None
    prepared_outage_status: str | None = None
    prepared_load_served_kwh: float | None = None
    prepared_unserved_load_kwh: float | None = None
    prepared_load_served_percent: float | None = None
    prepared_ending_soc_percent: float | None = None
    prepared_minimum_soc_percent: float | None = None
    prepared_eps_limited_unserved_kwh: float | None = None
    prepared_energy_limited_unserved_kwh: float | None = None
    prepared_first_shortfall_at: str | None = None

    # Current/recent power routing for live visualisations such as the
    # 16x16 KEMS panel. These are instantaneous kW values from the latest
    # replay snapshot, not period totals.
    current_house_load_kw: float | None = None
    current_solar_power_kw: float | None = None
    current_grid_import_kw: float | None = None
    current_grid_export_kw: float | None = None
    current_solar_to_home_kw: float | None = None
    current_solar_to_battery_kw: float | None = None
    current_solar_export_kw: float | None = None
    current_grid_to_battery_kw: float | None = None
    current_battery_to_home_kw: float | None = None
    current_battery_export_kw: float | None = None
    current_battery_soc_percent: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible summary."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScenarioPeriodComparison:
    """Scenario results aggregated across one reporting period."""

    key: str
    label: str
    start_date: date
    end_date: date
    days_included: int
    scenarios: tuple[ScenarioSummary, ...] = ()

    def scenario(self, key: str) -> ScenarioSummary | None:
        """Return one named scenario from the period."""
        return next((item for item in self.scenarios if item.key == key), None)

    @property
    def cheapest(self) -> ScenarioSummary | None:
        """Return the cheapest ready scenario in the period."""
        ready = [
            item
            for item in self.scenarios
            if item.ready and item.financially_comparable
        ]
        return min(ready, key=lambda item: item.total_cost_pence) if ready else None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible period comparison data."""
        return {
            "key": self.key,
            "label": self.label,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "days_included": self.days_included,
            "cheapest_scenario": self.cheapest.key if self.cheapest else None,
            "scenarios": [item.to_dict() for item in self.scenarios],
        }


@dataclass(frozen=True, slots=True)
class ScenarioTimelinePoint:
    """One today replay point for financial-cost and island-resilience charts."""

    timestamp: datetime
    no_system_cost_pence: float
    solar_only_cost_pence: float
    solar_battery_cost_pence: float
    kems_no_export_cost_pence: float
    kems_full_cost_pence: float
    island_load_served_percent: float | None = None
    island_unserved_load_kwh: float | None = None
    island_soc_percent: float | None = None
    island_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible chart data."""
        values = asdict(self)
        values["timestamp"] = self.timestamp.isoformat()
        return values


@dataclass(frozen=True, slots=True)
class ScenarioComparisonState:
    """Complete parallel what-if comparison payload."""

    generated_at: datetime
    periods: dict[str, ScenarioPeriodComparison] = field(default_factory=dict)
    timeline: tuple[ScenarioTimelinePoint, ...] = ()

    def period(self, key: str = "today") -> ScenarioPeriodComparison | None:
        """Return one reporting period."""
        return self.periods.get(key)

    def scenario(
        self,
        scenario_key: str,
        period_key: str = "today",
    ) -> ScenarioSummary | None:
        """Return one scenario from one period."""
        period = self.period(period_key)
        return period.scenario(scenario_key) if period else None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible scenario data for diagnostics and web use."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "periods": {key: value.to_dict() for key, value in self.periods.items()},
            "timeline": [item.to_dict() for item in self.timeline],
        }


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
    accumulator_status: str = "initialising"
    last_daily_rollover: date | None = None
    last_successful_accumulation: datetime | None = None
    accumulation_days_complete: int = 0
    accumulation_days_incomplete: int = 0
    historical_repair_required: bool = False

    house_consumption_kwh: float = 0.0
    ev_energy_kwh: float = 0.0
    grid_import_kwh: float = 0.0
    grid_export_kwh: float = 0.0
    solar_generation_kwh: float = 0.0
    battery_charge_kwh: float = 0.0
    battery_discharge_kwh: float = 0.0
    gas_consumption_kwh: float = 0.0

    simulated_grid_import_kwh: float = 0.0
    simulated_grid_export_kwh: float = 0.0
    simulated_solar_generation_kwh: float = 0.0
    simulated_battery_charge_kwh: float = 0.0
    simulated_battery_to_home_kwh: float = 0.0
    simulated_battery_export_kwh: float = 0.0
    simulated_avoided_day_rate_import_kwh: float = 0.0

    import_cost_pence: float = 0.0
    export_income_pence: float = 0.0
    gas_cost_pence: float = 0.0
    simulated_import_cost_pence: float = 0.0
    simulated_export_income_pence: float = 0.0
    simulated_net_cost_pence: float = 0.0
    simulated_avoided_import_value_pence: float = 0.0
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
        for key in (
            "first_observation",
            "last_updated",
            "last_successful_accumulation",
        ):
            value = data[key]
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        for key in (
            "commissioning_date",
            "paid_back_date",
            "last_daily_rollover",
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
        for key in (
            "first_observation",
            "last_updated",
            "last_successful_accumulation",
        ):
            value = values.get(key)
            if isinstance(value, str):
                values[key] = datetime.fromisoformat(value)
        for key in (
            "commissioning_date",
            "paid_back_date",
            "last_daily_rollover",
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
class PeriodTotals:
    """Persisted actual and simulated totals for a reporting period."""

    start_date: date | None = None
    end_date: date | None = None
    days_included: int = 0
    complete_days: int = 0
    incomplete_days: int = 0
    data_complete: bool = True

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

    simulated_grid_import_kwh: float = 0.0
    simulated_grid_export_kwh: float = 0.0
    simulated_solar_generation_kwh: float = 0.0
    simulated_battery_charge_kwh: float = 0.0
    simulated_battery_to_home_kwh: float = 0.0
    simulated_battery_export_kwh: float = 0.0
    simulated_avoided_day_rate_import_kwh: float = 0.0
    simulated_import_cost_pence: float = 0.0
    simulated_export_income_pence: float = 0.0
    simulated_net_cost_pence: float = 0.0
    simulated_avoided_import_value_pence: float = 0.0
    simulated_system_value_pence: float = 0.0

    @property
    def actual_net_cost_pence(self) -> float:
        """Return electricity and gas cost after export income."""
        return self.import_cost_pence + self.gas_cost_pence - self.export_income_pence

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible reporting payload."""
        data = asdict(self)
        for key in ("start_date", "end_date"):
            value = data[key]
            if isinstance(value, date):
                data[key] = value.isoformat()
        data["actual_net_cost_pence"] = round(self.actual_net_cost_pence, 2)
        return data


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
class ControlConfig:
    """Safety and commissioning settings for the control planner."""

    operating_mode: str = "simulate"
    virtual_scenario: str = "normal"
    control_enabled: bool = False
    commissioned: bool = False
    emergency_stop: bool = False
    stale_data_seconds: int = 180
    grid_stability_seconds: int = 300
    eps_limit_kw: float = 7.0
    eps_warning_percent: float = 70.0
    eps_critical_percent: float = 90.0
    island_reserve_percent: float = 20.0
    normal_reserve_percent: float = 10.0
    battery_capacity_kwh: float = 56.42
    discharge_efficiency: float = 0.95
    max_charge_kw: float = 7.0
    max_discharge_kw: float = 7.0
    export_limit_kw: float = 7.0
    inverter_limit_kw: float = 7.0
    site_import_limit_kw: float | None = None


@dataclass(frozen=True, slots=True)
class ControlState:
    """One explainable desired-control plan."""

    operating_mode: str = "simulate"
    virtual_scenario: str = "normal"
    operating_reason: str = "observe_only"
    desired_work_mode: str = "No change"
    desired_charge_power_kw: float = 0.0
    desired_battery_to_home_power_kw: float = 0.0
    desired_battery_export_power_kw: float = 0.0
    desired_total_discharge_power_kw: float = 0.0
    desired_min_soc_percent: float = 10.0
    desired_ev_charging_allowed: bool = True
    desired_grid_export_allowed: bool = True
    grid_available: bool = True
    island_mode_active: bool = False
    whole_house_eps_load_kw: float = 0.0
    virtual_scenario_house_load_kw: float = 0.0
    virtual_scenario_solar_power_kw: float = 0.0
    eps_headroom_kw: float = 7.0
    eps_utilisation_percent: float = 0.0
    eps_warning: bool = False
    eps_critical: bool = False
    eps_status: str = "not_active"
    eps_load_reduction_required_kw: float = 0.0
    total_kh7_ac_output_kw: float = 0.0
    kh7_output_headroom_kw: float = 7.0
    grid_bypass_power_kw: float = 0.0
    total_site_import_kw: float = 0.0
    site_import_limit_kw: float | None = None
    site_import_headroom_kw: float | None = None
    site_import_limit_exceeded: bool = False
    solar_to_house_kw: float = 0.0
    solar_to_battery_kw: float = 0.0
    battery_to_house_kw: float = 0.0
    island_conservation_threshold_percent: float = 20.0
    island_emergency_floor_percent: float = 10.0
    island_battery_status: str = "not_active"
    estimated_outage_runtime_hours: float | None = None
    data_age_seconds: float = 0.0
    data_fresh: bool = True
    plan_safe: bool = True
    control_enabled: bool = False
    commissioned: bool = False
    real_backend_available: bool = False
    commands_permitted: bool = False
    blocked_reason: str = "Simulation/shadow only"
    next_action: str = "Continue observing"
    preflight_passed: int = 0
    preflight_total: int = 0
    preflight_status: str = "Not run"


@dataclass(frozen=True, slots=True)
class PowerDownResult:
    """Persisted summary of the last completed Power Down event."""

    available: bool = False
    session_id: str | None = None
    session_start: datetime | None = None
    session_end: datetime | None = None
    starting_simulated_soc_percent: float | None = None
    finishing_simulated_soc_percent: float | None = None
    planned_battery_to_home_kwh: float | None = None
    planned_export_kwh: float | None = None
    maximum_inverter_output_kw: float | None = None
    rewardable_reduction_kwh: float | None = None
    bonus_pence: float | None = None
    fixed_export_income_pence: float | None = None
    combined_income_pence: float | None = None
    ev_successfully_blocked: bool = False
    active_samples_observed: int = 0
    plan_safe_throughout: bool | None = None
    island_override_observed: bool | None = None
    completed_successfully: bool = False
    completion_reason: str = "unavailable"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("session_start", "session_end"):
            value = data[key]
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PowerDownResult:
        values = dict(data)
        for key in ("session_start", "session_end"):
            value = values.get(key)
            if isinstance(value, str):
                values[key] = datetime.fromisoformat(value)
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in known})


@dataclass(frozen=True, slots=True)
class DataQuality:
    """Coverage and health of the configured observations."""

    score: float
    configured: int
    available: int
    missing_fields: tuple[str, ...] = ()
    stale_fields: tuple[str, ...] = ()
    max_source_age_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class KEMSData:
    """Complete coordinator payload exposed to KEMS entities."""

    snapshot: Snapshot
    learned: LearnedState
    gas: GasSummary
    advice: AdviceState
    simulation: SimulationState
    scenarios: ScenarioComparisonState
    whole_home: WholeHomeSummary
    lifetime: LifetimeLedger
    roi: ROIState
    quality: DataQuality
    control: ControlState
    history_samples: int
    phase: str
    last_power_down: PowerDownResult = field(default_factory=PowerDownResult)
    periods: dict[str, PeriodTotals] = field(default_factory=dict)
