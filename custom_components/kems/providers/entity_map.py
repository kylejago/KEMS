"""Known Home Assistant entity IDs."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OctopusEntities:
    """Default Octopus Intelligent entity IDs."""

    current_rate: str = (
        "sensor.octopus_energy_electricity_20e5126162_2200019564326_current_rate"
    )

    next_rate: str = (
        "sensor.octopus_energy_electricity_20e5126162_2200019564326_next_rate"
    )

    off_peak: str = (
        "binary_sensor.octopus_energy_electricity_20e5126162_2200019564326_off_peak"
    )

    intelligent_slot: str = (
        "binary_sensor.octopus_intelligent_tariff_octopus_intelligent_slot"
    )

    planned_dispatch: str = (
        "binary_sensor.octopus_intelligent_tariff_octopus_intelligent_planned_dispatch_slot"
    )

    next_offpeak_start: str = (
        "sensor.octopus_intelligent_tariff_octopus_intelligent_next_offpeak_start"
    )

    offpeak_end: str = (
        "sensor.octopus_intelligent_tariff_octopus_intelligent_offpeak_end"
    )
