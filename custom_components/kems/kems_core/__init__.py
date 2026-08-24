"""Home Assistant-independent KEMS Observe/Learn/Advise/Simulate core."""

from .advice import AdviceEngine
from .control import (
    OPERATING_MODES,
    VIRTUAL_SCENARIOS,
    ControlEngine,
    run_preflight_suite,
)
from .ev_charge_policy import (
    CONF_EV_CHARGING_POLICY,
    DEFAULT_EV_POLICY,
    EV_POLICY_CHEAP_WINDOW,
    EV_POLICY_DISABLED,
    EV_POLICY_KEYS,
    EV_POLICY_LABELS,
    EV_POLICY_SURPLUS,
    configure_ev_charge_policy,
    ev_policy_from_options,
    install_ev_charge_policy,
)
from .forecast import ForecastPlanningEngine, fuse_solar_forecasts
from .forecast_validation import (
    ForecastObservation,
    ForecastValidationDay,
    ForecastValidationEngine,
    ForecastValidationState,
)
from .foxess import GridPower, calculate_battery_power_kw, normalise_grid_power
from .gas import GasEngine
from .learning import LearningEngine
from .lifetime_accounting import (
    COMMISSIONED_VALUE_KEYS,
    OBSERVED_LIFETIME_KEYS,
    SIGNED_LIFETIME_KEYS,
    SIMULATED_LIFETIME_KEYS,
    reconciled_observed_lifetime_values,
    reconciled_simulated_lifetime_values,
    should_accumulate_lifetime_value,
)
from .models import (
    AdviceItem,
    AdviceState,
    ControlConfig,
    ControlState,
    DataQuality,
    ForecastConfig,
    ForecastHour,
    ForecastPlanState,
    GasSummary,
    KEMSData,
    LearnedState,
    LifetimeLedger,
    PeriodTotals,
    PowerDownResult,
    ROIConfig,
    ROIState,
    ScenarioComparisonState,
    ScenarioPeriodComparison,
    ScenarioSummary,
    ScenarioTimelinePoint,
    SimulationConfig,
    SimulationState,
    Snapshot,
    SolarForecastState,
    WholeHomeSummary,
)
from .ohme import interpret_charger_status
from .overnight_cheap_policy import install_overnight_only_cheap_policy
from .periods import (
    PERIOD_DATA_COMPLETE_KEY,
    period_value_keys,
    period_value_kwargs,
    summarise_period_records,
)
from .power_down_audit import (
    PowerDownAccountingState,
    PowerDownAuditState,
    finalise_power_down_audit,
)
from .quality import assess_quality
from .roi import ROIEngine
from .scenario_comparison import SCENARIO_KEYS, ScenarioComparisonEngine
from .simulation import SimulationEngine
from .system_profile import FOXHOLE_PROPOSAL_PROFILE, ProposalSystemProfile, SolarArray
from .whole_home import WholeHomeEngine

# Alpha7.34: make the configured overnight window the sole cheap-period
# authority for both newly collected and previously retained snapshots.
install_overnight_only_cheap_policy()

# EV policy remains a shadow-only desired-command gate. Each coordinator sets
# its own persisted policy on its ControlEngine instance during setup.
install_ev_charge_policy()

__all__ = [
    "should_accumulate_lifetime_value",
    "SIGNED_LIFETIME_KEYS",
    "SIMULATED_LIFETIME_KEYS",
    "reconciled_observed_lifetime_values",
    "reconciled_simulated_lifetime_values",
    "OBSERVED_LIFETIME_KEYS",
    "COMMISSIONED_VALUE_KEYS",
    "AdviceEngine",
    "AdviceItem",
    "AdviceState",
    "CONF_EV_CHARGING_POLICY",
    "ControlConfig",
    "ControlEngine",
    "ControlState",
    "DEFAULT_EV_POLICY",
    "DataQuality",
    "EV_POLICY_CHEAP_WINDOW",
    "EV_POLICY_DISABLED",
    "EV_POLICY_KEYS",
    "EV_POLICY_LABELS",
    "EV_POLICY_SURPLUS",
    "ForecastConfig",
    "ForecastHour",
    "ForecastObservation",
    "ForecastPlanState",
    "ForecastPlanningEngine",
    "ForecastValidationDay",
    "ForecastValidationEngine",
    "ForecastValidationState",
    "FOXHOLE_PROPOSAL_PROFILE",
    "GasEngine",
    "GasSummary",
    "GridPower",
    "OPERATING_MODES",
    "KEMSData",
    "LearnedState",
    "LearningEngine",
    "LifetimeLedger",
    "PeriodTotals",
    "PERIOD_DATA_COMPLETE_KEY",
    "PowerDownAccountingState",
    "PowerDownAuditState",
    "PowerDownResult",
    "ProposalSystemProfile",
    "ROIConfig",
    "ROIEngine",
    "ROIState",
    "SCENARIO_KEYS",
    "ScenarioComparisonEngine",
    "ScenarioComparisonState",
    "ScenarioPeriodComparison",
    "ScenarioSummary",
    "ScenarioTimelinePoint",
    "SimulationConfig",
    "SimulationEngine",
    "SimulationState",
    "Snapshot",
    "SolarForecastState",
    "SolarArray",
    "WholeHomeEngine",
    "VIRTUAL_SCENARIOS",
    "WholeHomeSummary",
    "assess_quality",
    "calculate_battery_power_kw",
    "configure_ev_charge_policy",
    "ev_policy_from_options",
    "normalise_grid_power",
    "run_preflight_suite",
    "period_value_keys",
    "period_value_kwargs",
    "summarise_period_records",
    "interpret_charger_status",
    "finalise_power_down_audit",
    "fuse_solar_forecasts",
]
