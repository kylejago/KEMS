"""Alpha9.41 no-paid-export simulation-authority regressions."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha941_no_export_authority_test"


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
    no_export_mode_active: bool | None = None


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


def _paid_export_agile_state() -> dict:
    return {
        "periods": {
            "today": {
                "agile_smart_export": {
                    "ready": True,
                    "import_cost_pence": 145.75,
                    "export_income_pence": 121.23,
                    "grid_import_kwh": 41.723,
                    "grid_export_kwh": 10.103,
                    "solar_generation_kwh": 5.049,
                    "solar_to_home_kwh": 0.0,
                    "solar_to_battery_kwh": 0.0,
                    "solar_export_kwh": 5.049,
                    "grid_to_battery_kwh": 36.907,
                    "battery_to_home_kwh": 4.535,
                    "battery_export_kwh": 5.054,
                    "ending_soc_percent": 67.3,
                    "weighted_achieved_export_rate_pence": 17.5414,
                }
            }
        },
        "current_routing_snapshot": {
            "available": True,
            "simulated_house_load_kw": 0.434,
            "solar_power_kw": 1.487,
            "grid_import_kw": 0.0,
            "grid_export_kw": 0.0,
            "solar_to_battery_kw": 1.053,
            "grid_to_battery_kw": 0.0,
            "battery_to_home_kw": 0.0,
            "battery_export_kw": 0.0,
            "total_discharge_kw": 0.0,
            "normalised_kh7_ac_output_kw": 0.434,
        },
    }


def test_alpha941_no_export_keeps_policy_simulation_for_cumulative_values() -> None:
    """Paid-export Agile replay must not overwrite a no-export KEMS digital twin."""
    no_export = _SimulationState(
        simulated_cost_pence=10.04,
        simulated_import_cost_pence=10.04,
        simulated_export_income_pence=0.0,
        simulated_grid_import_kwh=2.873,
        simulated_grid_export_kwh=0.0,
        simulated_solar_generation_kwh=5.049,
        simulated_solar_to_home_kwh=1.52,
        simulated_solar_to_battery_kwh=3.353,
        simulated_solar_export_kwh=0.0,
        simulated_grid_to_battery_kwh=0.0,
        simulated_battery_charge_kwh=3.353,
        simulated_battery_to_home_kwh=3.015,
        simulated_battery_export_kwh=0.0,
        simulated_battery_soc=80.5,
        actual_cost_pence=96.15,
        baseline_no_system_cost_pence=138.39,
        no_export_mode_active=True,
    )

    result = presentation.reconciled_current_day_simulation(
        no_export,
        _paid_export_agile_state(),
    )

    # Cumulative/accounting authority remains the policy-aware no-export replay.
    assert result.simulated_grid_import_kwh == 2.873
    assert result.simulated_grid_export_kwh == 0.0
    assert result.simulated_battery_charge_kwh == 3.353
    assert result.simulated_battery_export_kwh == 0.0
    assert result.simulated_export_income_pence == 0.0
    assert result.simulated_battery_soc == 80.5

    # Instantaneous power still comes from the final canonical routing snapshot.
    assert result.current_simulated_house_load_kw == 0.434
    assert result.current_simulated_solar_power_kw == 1.487
    assert result.current_simulated_grid_import_kw == 0.0
    assert result.current_simulated_grid_export_kw == 0.0
    assert result.current_simulated_battery_charge_power_kw == 1.053
    assert result.current_simulated_battery_power_kw == -1.053


def test_alpha941_paid_export_still_uses_full_agile_cumulative_authority() -> None:
    """The Alpha9.39 Full-KEMS authority remains intact when export is paid."""
    paid_export = _SimulationState(
        simulated_grid_import_kwh=2.873,
        simulated_grid_export_kwh=0.0,
        simulated_battery_export_kwh=0.0,
        simulated_battery_soc=80.5,
        actual_cost_pence=96.15,
        baseline_no_system_cost_pence=138.39,
        no_export_mode_active=False,
    )

    result = presentation.reconciled_current_day_simulation(
        paid_export,
        _paid_export_agile_state(),
    )

    assert result.simulated_grid_import_kwh == 41.723
    assert result.simulated_grid_export_kwh == 10.103
    assert result.simulated_battery_export_kwh == 5.054
    assert result.simulated_export_income_pence == 121.23
    assert result.simulated_battery_soc == 67.3
