"""Home Assistant-independent KEMS domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(UTC)


@dataclass(slots=True)
class Snapshot:
    """One read-only observation of the home energy system."""

    timestamp: datetime = field(default_factory=utc_now)

    current_import_rate: float | None = None
    next_import_rate: float | None = None
    current_export_rate: float | None = None
    off_peak: bool | None = None
    intelligent_slot: bool | None = None
    next_offpeak_start: datetime | None = None
    offpeak_end: datetime | None = None

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
        return cls(**values)


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
    """Read-only battery and tariff simulation settings."""

    battery_capacity_kwh: float = 56.42
    battery_reserve_percent: float = 10.0
    battery_initial_percent: float = 10.0
    max_charge_kw: float = 10.0
    max_discharge_kw: float = 10.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    export_rate_pence: float = 0.0
    strategy: str = "export_first"


@dataclass(frozen=True, slots=True)
class SimulationState:
    """Comparison of observed cost with the KEMS simulated strategy."""

    ready: bool = False
    samples: int = 0
    actual_cost_pence: float | None = None
    simulated_cost_pence: float | None = None
    saving_pence: float | None = None
    actual_grid_import_kwh: float | None = None
    simulated_grid_import_kwh: float | None = None
    simulated_grid_export_kwh: float | None = None
    simulated_battery_soc: float | None = None
    avoided_day_rate_import_kwh: float | None = None
    data_coverage: float = 0.0


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
    advice: AdviceState
    simulation: SimulationState
    quality: DataQuality
    history_samples: int
    phase: str
