"""Known Home Assistant entity IDs."""

CURRENT_RATE = "sensor.octopus_energy_electricity_20e5126162_2200019564326_current_rate"

NEXT_RATE = "sensor.octopus_energy_electricity_20e5126162_2200019564326_next_rate"

OFF_PEAK = "binary_sensor.octopus_energy_electricity_20e5126162_2200019564326_off_peak"

INTELLIGENT_SLOT = "binary_sensor.octopus_intelligent_tariff_octopus_intelligent_slot"

PLANNED_DISPATCH = (
    "binary_sensor.octopus_intelligent_tariff_octopus_intelligent_planned_dispatch_slot"
)

NEXT_OFFPEAK_START = (
    "sensor.octopus_intelligent_tariff_octopus_intelligent_next_offpeak_start"
)

OFFPEAK_END = "sensor.octopus_intelligent_tariff_octopus_intelligent_offpeak_end"
