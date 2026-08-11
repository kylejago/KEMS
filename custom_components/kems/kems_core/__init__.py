"""Home Assistant-independent KEMS Observe/Learn/Advise/Simulate core."""

from .advice import AdviceEngine
from .control import (
    OPERATING_MODES,
    VIRTUAL_SCENARIOS,
    ControlEngine,
    run_preflight_suite,
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
    WholeHomeSummary,
)
from .ohme import interpret_charger_status
from .periods import (
    PERIOD_DATA_COMPLETE_KEY,
    period_value_keys,
    period_value_kwargs,
    summarise_period_records,
)
from .quality import assess_quality
from .roi import ROIEngine
from .scenario_comparison import (
    SCENARIO_KEYS,
    ScenarioComparisonEngine,
)
from .simulation import SimulationEngine
from .system_profile import FOXHOLE_PROPOSAL_PROFILE, ProposalSystemProfile, SolarArray
from .whole_home import WholeHomeEngine

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
    "ControlConfig",
    "ControlEngine",
    "ControlState",
    "DataQuality",
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
    "SolarArray",
    "WholeHomeEngine",
    "VIRTUAL_SCENARIOS",
    "WholeHomeSummary",
    "assess_quality",
    "calculate_battery_power_kw",
    "normalise_grid_power",
    "run_preflight_suite",
    "period_value_keys",
    "period_value_kwargs",
    "summarise_period_records",
    "interpret_charger_status",
]
