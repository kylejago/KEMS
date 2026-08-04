"""Home Assistant-independent KEMS Observe/Learn/Advise/Simulate core."""

from .advice import AdviceEngine
from .foxess import GridPower, calculate_battery_power_kw, normalise_grid_power
from .gas import GasEngine
from .learning import LearningEngine
from .models import (
    AdviceItem,
    AdviceState,
    DataQuality,
    GasSummary,
    KEMSData,
    LearnedState,
    LifetimeLedger,
    ROIConfig,
    ROIState,
    SimulationConfig,
    SimulationState,
    Snapshot,
    WholeHomeSummary,
)
from .ohme import interpret_charger_status
from .quality import assess_quality
from .roi import ROIEngine
from .simulation import SimulationEngine
from .system_profile import FOXHOLE_PROPOSAL_PROFILE, ProposalSystemProfile, SolarArray
from .whole_home import WholeHomeEngine

__all__ = [
    "AdviceEngine",
    "AdviceItem",
    "AdviceState",
    "DataQuality",
    "FOXHOLE_PROPOSAL_PROFILE",
    "GasEngine",
    "GasSummary",
    "GridPower",
    "KEMSData",
    "LearnedState",
    "LearningEngine",
    "LifetimeLedger",
    "ProposalSystemProfile",
    "ROIConfig",
    "ROIEngine",
    "ROIState",
    "SimulationConfig",
    "SimulationEngine",
    "SimulationState",
    "Snapshot",
    "SolarArray",
    "WholeHomeEngine",
    "WholeHomeSummary",
    "assess_quality",
    "calculate_battery_power_kw",
    "normalise_grid_power",
    "interpret_charger_status",
]
