"""Frozen FoxESS Modbus KH commissioning contract."""

from __future__ import annotations

from typing import Any, Final

FOXESS_MODBUS_REVIEWED_VERSION: Final = "1.15.0"
FOXESS_MODBUS_PLATFORM: Final = "foxess_modbus"
FOXESS_MODBUS_KH_FAMILIES: Final = ("KH_PRE119", "KH_PRE133", "KH_133")

# Stable upstream telemetry keys reviewed against foxess_modbus v1.15.0.
# These are the preferred sources KEMS needs to leave pre-installation fallback mode.
FOXESS_MODBUS_REQUIRED_TELEMETRY: Final = {
    "battery_soc": {
        "key": "battery_soc",
        "name": "Battery SoC",
        "unit": "%",
    },
    "battery_power_kw": {
        "key": "invbatpower",
        "name": "Inverter Battery Power",
        "unit": "kW",
        "sign": "positive discharge; negative charge",
    },
    "solar_power_kw": {
        "key": "pv_power_now",
        "name": "PV Power",
        "unit": "kW",
    },
    "house_load_kw": {
        "key": "load_power",
        "name": "Load Power",
        "unit": "kW",
    },
    "grid_import_kw": {
        "key": "grid_consumption",
        "name": "Grid Consumption",
        "unit": "kW",
        "direction": "import-only normalised from Grid CT",
    },
    "grid_export_kw": {
        "key": "feed_in",
        "name": "Feed-in",
        "unit": "kW",
        "direction": "export-only normalised from Grid CT",
    },
}

# KH exposes inverter-side battery voltage/current across the reviewed families.
# KEMS may derive battery power from this pair only when direct invbatpower is absent.
FOXESS_MODBUS_BATTERY_POWER_FALLBACK: Final = {
    "battery_voltage": {
        "key": "invbatvolt",
        "name": "Inverter Battery Voltage",
        "unit": "V",
    },
    "battery_current": {
        "key": "invbatcurrent",
        "name": "Inverter Battery Current",
        "unit": "A",
    },
}

# Useful read-only evidence for installation-day reconciliation. Some entries are
# model-dependent and are deliberately not commissioning requirements.
FOXESS_MODBUS_OPTIONAL_DIAGNOSTICS: Final = {
    "raw_grid_power": {"key": "grid_ct", "name": "Grid CT"},
    "inverter_power": {"key": "rpower", "name": "Inverter Power"},
    "battery_energy_remaining": {
        "key": "bms_kwh_remaining",
        "name": "BMS kWh Remaining",
        "model_dependent": True,
    },
    "pv1_power": {"key": "pv1_power", "name": "PV1 Power"},
    "pv2_power": {"key": "pv2_power", "name": "PV2 Power"},
    "pv3_power": {"key": "pv3_power", "name": "PV3 Power"},
    "pv4_power": {"key": "pv4_power", "name": "PV4 Power"},
}

# The upstream integration exposes writable configuration entities for KH. KEMS
# records their existence only; Alpha8.60 does not map, call, or write any of them.
FOXESS_MODBUS_KNOWN_WRITABLE_CAPABILITIES: Final = {
    "work_mode": "Work Mode",
    "max_charge_current": "Max Charge Current",
    "max_discharge_current": "Max Discharge Current",
    "min_soc": "Min SoC",
    "max_soc": "Max SoC",
    "min_soc_on_grid": "Min SoC (On Grid)",
    "export_power_limit": "Export Power Limit (KH_133)",
    "import_power_limit": "Import Power Limit (KH_133)",
}


def foxess_modbus_contract_snapshot() -> dict[str, Any]:
    """Return the reviewed read-only commissioning contract for diagnostics."""
    return {
        "platform": FOXESS_MODBUS_PLATFORM,
        "reviewed_upstream_version": FOXESS_MODBUS_REVIEWED_VERSION,
        "kh_families": list(FOXESS_MODBUS_KH_FAMILIES),
        "required_telemetry": {
            key: dict(value)
            for key, value in FOXESS_MODBUS_REQUIRED_TELEMETRY.items()
        },
        "battery_power_fallback": {
            key: dict(value)
            for key, value in FOXESS_MODBUS_BATTERY_POWER_FALLBACK.items()
        },
        "optional_diagnostics": {
            key: dict(value)
            for key, value in FOXESS_MODBUS_OPTIONAL_DIAGNOSTICS.items()
        },
        "known_writable_capabilities": dict(
            FOXESS_MODBUS_KNOWN_WRITABLE_CAPABILITIES
        ),
        "writes_permitted": False,
        "hardware_writes": "blocked",
        "control_scope": "catalogue only; no FoxESS write path is enabled",
    }
