"""Shared data models for KEMS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class OperatingMode(StrEnum):
    """How KEMS behaves."""

    MONITOR = "monitor"
    ADVISOR = "advisor"
    AUTONOMOUS = "autonomous"


class EnergyProfile(StrEnum):
    """House profile."""

    HOME = "home"
    HOLIDAY = "holiday"


class MissionAction(StrEnum):
    """Mission planner actions."""

    IDLE = "idle"
    CHARGE = "charge"
    DISCHARGE = "discharge"
    EXPORT = "export"
    IMPORT = "import"
    HOLD = "hold"


@dataclass(slots=True)
class BatteryState:
    """Current battery state."""

    soc: float
    capacity_kwh: float
    stored_energy_kwh: float
    charge_power_kw: float
    discharge_power_kw: float
    temperature: float
    health: float


@dataclass(slots=True)
class SolarState:
    """Current solar generation."""

    generation_kw: float
    forecast_today_kwh: float
    forecast_tomorrow_kwh: float


@dataclass(slots=True)
class GridState:
    """Grid import/export."""

    import_power_kw: float
    export_power_kw: float
    import_price: float
    export_price: float
    cheap_rate: bool


@dataclass(slots=True)
class HouseState:
    """House consumption."""

    load_kw: float
    baseload_kw: float


@dataclass(slots=True)
class TariffWindow:
    """Represents one tariff period."""

    start: datetime
    end: datetime
    import_price: float
    export_price: float
    cheap: bool


@dataclass(slots=True)
class MissionStep:
    """One optimisation step."""

    start: datetime
    end: datetime
    action: MissionAction
    target_power_kw: float
    reason: str


@dataclass(slots=True)
class MissionPlan:
    """Complete mission plan."""

    created: datetime
    steps: list[MissionStep] = field(default_factory=list)

    def add_step(self, step: MissionStep) -> None:
        """Add a mission step."""
        self.steps.append(step)


@dataclass(slots=True)
class Confidence:
    """Prediction confidence."""

    battery: float = 100.0
    solar: float = 100.0
    house: float = 100.0
    tariff: float = 100.0

    @property
    def overall(self) -> float:
        """Average confidence."""
        return (self.battery + self.solar + self.house + self.tariff) / 4


@dataclass(slots=True)
class DigitalTwin:
    """Current simulated state."""

    battery: BatteryState
    solar: SolarState
    grid: GridState
    house: HouseState
    mission: MissionPlan
    confidence: Confidence
