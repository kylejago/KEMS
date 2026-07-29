"""Configuration models."""

from dataclasses import dataclass


@dataclass(slots=True)
class MonitorConfig:
    """Monitor configuration."""

    scan_interval: int = 300

    record_history: bool = True

    learn_patterns: bool = True

    advisor_enabled: bool = False

    simulation_enabled: bool = False
