"""Home Assistant-independent KEMS Observe/Learn/Advise/Simulate core."""

from .advice import AdviceEngine
from .foxess import calculate_battery_power_kw
from .gas import GasEngine
from .learning import LearningEngine
from .models import (
    AdviceItem,
    AdviceState,
    DataQuality,
    GasSummary,
    KEMSData,
    LearnedState,
    SimulationConfig,
    SimulationState,
    Snapshot,
    WholeHomeSummary,
)
from .ohme import interpret_charger_status
from .quality import assess_quality
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
    "KEMSData",
    "LearnedState",
    "LearningEngine",
    "ProposalSystemProfile",
    "SimulationConfig",
    "SimulationEngine",
    "SimulationState",
    "Snapshot",
    "SolarArray",
    "WholeHomeEngine",
    "WholeHomeSummary",
    "assess_quality",
    "calculate_battery_power_kw",
    "interpret_charger_status",
]
