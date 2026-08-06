"""Pure lifetime-ledger classification used by Home Assistant persistence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

OBSERVED_LIFETIME_KEYS = frozenset(
    {
        "house_consumption_kwh",
        "ev_energy_kwh",
        "grid_import_kwh",
        "grid_export_kwh",
        "solar_generation_kwh",
        "battery_charge_kwh",
        "battery_discharge_kwh",
        "gas_consumption_kwh",
        "import_cost_pence",
        "export_income_pence",
        "gas_cost_pence",
        "simulated_grid_import_kwh",
        "simulated_grid_export_kwh",
        "simulated_solar_generation_kwh",
        "simulated_battery_charge_kwh",
        "simulated_battery_to_home_kwh",
        "simulated_battery_export_kwh",
        "simulated_avoided_day_rate_import_kwh",
        "simulated_import_cost_pence",
        "simulated_export_income_pence",
        "simulated_net_cost_pence",
        "simulated_avoided_import_value_pence",
        "simulated_system_value_pence",
    }
)


SIMULATED_LIFETIME_KEYS = frozenset(
    {
        "simulated_grid_import_kwh",
        "simulated_grid_export_kwh",
        "simulated_solar_generation_kwh",
        "simulated_battery_charge_kwh",
        "simulated_battery_to_home_kwh",
        "simulated_battery_export_kwh",
        "simulated_avoided_day_rate_import_kwh",
        "simulated_import_cost_pence",
        "simulated_export_income_pence",
        "simulated_net_cost_pence",
        "simulated_avoided_import_value_pence",
        "simulated_system_value_pence",
    }
)


def reconciled_simulated_lifetime_values(
    daily_records: Iterable[Mapping[str, float]],
    tracking_values: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Sum simulated lifetime values from the authoritative daily ledger.

    Simulated day totals can legitimately move down as forecasts and export
    pacing are recalculated. Rebuilding from stored day values avoids keeping
    a stale intraday high-water mark in the lifetime ledger.
    """
    totals = {key: 0.0 for key in SIMULATED_LIFETIME_KEYS}
    records = list(daily_records)
    if tracking_values is not None:
        records.append(tracking_values)
    for values in records:
        for key in SIMULATED_LIFETIME_KEYS:
            value = values.get(key)
            if isinstance(value, (int, float)):
                totals[key] += float(value)
    return totals


COMMISSIONED_VALUE_KEYS = frozenset(
    {
        "actual_avoided_import_value_pence",
        "actual_system_value_pence",
    }
)

SIGNED_LIFETIME_KEYS = frozenset(
    {
        "actual_avoided_import_value_pence",
        "actual_system_value_pence",
        "simulated_net_cost_pence",
        "simulated_avoided_import_value_pence",
        "simulated_system_value_pence",
    }
)


def should_accumulate_lifetime_value(key: str, installed: bool) -> bool:
    """Return whether a delta belongs in the lifetime ledger."""
    return key in OBSERVED_LIFETIME_KEYS or (
        installed and key in COMMISSIONED_VALUE_KEYS
    )
