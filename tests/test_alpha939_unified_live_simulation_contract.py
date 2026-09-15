"""Alpha9.39 unified Live/KEMS presentation authority regressions."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha939_unified_simulation_test"


@dataclass(frozen=True)
class _SimulationState:
    simulated_cost_pence: float | None = None
    saving_pence: float | None = None
    simulated_import_cost_pence: float | None = None
    simulated_export_income_pence: float | None = None
    simulated_grid_import_kwh: float | None = None
    simulated_grid_export_kwh: float | None = None
    simulated_solar_generation_kwh: float | None = None
    simulated_solar_to_home_kwh: float | None = None
    simulated_solar_to_battery_kwh: float | None = None
    simulated_solar_export_kwh: float | None = None
    simulated_grid_to_battery_kwh: float | None = None
    simulated_battery_charge_kwh: float | None = None
    simulated_battery_to_home_kwh: float | None = None
    simulated_battery_export_kwh: float | None = None
    simulated_battery_soc: float | None = None
    avoided_day_rate_import_kwh: float | None = None
    simulated_avoided_import_value_pence: float | None = None
    simulated_system_value_pence: float | None = None
    effective_export_rate_pence: float | None = None
    exportable_battery_energy_kwh: float | None = None
    reserved_for_home_kwh: float | None = None
    projected_soc_at_cheap_period_percent: float | None = None
    simulated_saving_session_bonus_pence: float | None = 0.0
    actual_cost_pence: float | None = None
    baseline_no_system_cost_pence: float | None = None
    current_simulated_house_load_kw: float | None = None
    current_simulated_solar_power_kw: float | None = None
    current_simulated_grid_import_kw: float | None = None
    current_simulated_grid_export_kw: float | None = None
    current_simulated_battery_power_kw: float | None = None
    current_simulated_battery_charge_power_kw: float | None = None
    current_simulated_solar_to_battery_power_kw: float | None = None
    current_simulated_battery_to_home_power_kw: float | None = None
    current_simulated_battery_export_power_kw: float | None = None
    current_simulated_total_kh7_output_kw: float | None = None
    current_simulated_grid_bypass_power_kw: float | None = None
    current_simulated_total_site_import_kw: float | None = None
    target_battery_export_power_kw: float | None = None


def _load_presentation():
    package = ModuleType(PACKAGE)
    package.__path__ = [str(KEMS_ROOT)]
    sys.modules[PACKAGE] = package

    core = ModuleType(f"{PACKAGE}.kems_core")
    core.SimulationState = _SimulationState
    sys.modules[f"{PACKAGE}.kems_core"] = core

    name = f"{PACKAGE}.agile_current_day_presentation"
    spec = importlib.util.spec_from_file_location(
        name,
        KEMS_ROOT / "agile_current_day_presentation.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


presentation = _load_presentation()


def _midnight_agile_state() -> dict:
    return {
        # Just after midnight there may be no completed settlement yet.  That must
        # not make the legacy proposal replay authoritative for the KEMS tab.
        "current_day_settlement_reconciliation": {
            "applied": False,
            "all_accounting_checks_passed": False,
        },
        "periods": {
            "today": {
                "agile_smart_export": {
                    "ready": True,
                    "import_cost_pence": 8.2,
                    "export_income_pence": 0.0,
                    "grid_import_kwh": 2.348,
                    "grid_export_kwh": 0.0,
                    "solar_generation_kwh": 0.0,
                    "solar_to_home_kwh": 0.0,
                    "solar_to_battery_kwh": 0.0,
                    "solar_export_kwh": 0.0,
                    "grid_to_battery_kwh": 2.065,
                    "battery_to_home_kwh": 0.0,
                    "battery_export_kwh": 0.0,
                    "ending_soc_percent": 26.6,
                    "weighted_achieved_export_rate_pence": None,
                }
            }
        },
        "current_routing_snapshot": {
            "available": True,
            "simulated_house_load_kw": 0.559,
            "solar_power_kw": 0.0,
            "grid_import_kw": 7.559,
            "grid_export_kw": 0.0,
            "solar_to_battery_kw": 0.0,
            "grid_to_battery_kw": 7.0,
            "battery_to_home_kw": 0.0,
            "battery_export_kw": 0.0,
            "total_discharge_kw": 0.0,
            "normalised_kh7_ac_output_kw": 0.0,
        },
    }


def test_alpha939_ready_full_kems_period_is_authority_before_first_settlement() -> None:
    """SOC, accumulated energy and current power must all describe Full KEMS."""
    legacy = _SimulationState(
        simulated_grid_import_kwh=0.174,
        simulated_grid_to_battery_kwh=0.0,
        simulated_battery_charge_kwh=0.0,
        simulated_battery_soc=80.2,
        actual_cost_pence=0.61,
        baseline_no_system_cost_pence=0.61,
        current_simulated_grid_import_kw=0.559,
    )

    result = presentation.reconciled_current_day_simulation(
        legacy,
        _midnight_agile_state(),
    )

    assert result.simulated_battery_soc == 26.6
    assert result.simulated_grid_import_kwh == 2.348
    assert result.simulated_grid_to_battery_kwh == 2.065
    assert result.simulated_battery_charge_kwh == 2.065
    assert result.current_simulated_house_load_kw == 0.559
    assert result.current_simulated_grid_import_kw == 7.559
    assert result.current_simulated_battery_charge_power_kw == 7.0
    assert result.current_simulated_battery_power_kw == -7.0


def test_alpha939_unavailable_full_kems_period_preserves_generic_fallback() -> None:
    """The generic simulation remains the fallback only when Full KEMS is not ready."""
    legacy = _SimulationState(simulated_battery_soc=80.2)
    state = {
        "periods": {"today": {"agile_smart_export": {"ready": False}}},
    }

    result = presentation.reconciled_current_day_simulation(legacy, state)

    assert result is legacy
