"""Regression coverage for Alpha8.42 canonical current-routing authority."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha842_current_routing_test"


@dataclass(frozen=True)
class _SimulationState:
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


def _alpha841_routing() -> dict:
    return {
        "current_routing_snapshot": {
            "available": True,
            "simulated_house_load_kw": 0.488,
            "solar_power_kw": 3.439,
            "grid_import_kw": 0.0,
            "grid_export_kw": 2.951,
            "solar_to_battery_kw": 0.0,
            "grid_to_battery_kw": 0.0,
            "battery_to_home_kw": 0.0,
            "battery_export_kw": 0.0,
            "total_discharge_kw": 0.0,
            "normalised_kh7_ac_output_kw": 3.439,
        }
    }


def test_alpha842_exact_alpha841_current_power_conflict_is_removed() -> None:
    """The generic SimulationState must agree with final Agile routing now."""
    base = _SimulationState(
        current_simulated_house_load_kw=0.488,
        current_simulated_solar_power_kw=3.439,
        current_simulated_grid_import_kw=0.0,
        current_simulated_grid_export_kw=4.262,
        current_simulated_battery_power_kw=1.311,
        current_simulated_battery_charge_power_kw=0.0,
        current_simulated_solar_to_battery_power_kw=0.0,
        current_simulated_battery_to_home_power_kw=0.488,
        current_simulated_battery_export_power_kw=0.823,
        current_simulated_total_kh7_output_kw=4.75,
        current_simulated_grid_bypass_power_kw=0.0,
        current_simulated_total_site_import_kw=0.0,
        target_battery_export_power_kw=0.823,
    )

    result = presentation.reconciled_current_day_simulation(
        base,
        _alpha841_routing(),
    )

    assert result.current_simulated_house_load_kw == 0.488
    assert result.current_simulated_solar_power_kw == 3.439
    assert result.current_simulated_grid_import_kw == 0.0
    assert result.current_simulated_grid_export_kw == 2.951
    assert result.current_simulated_battery_power_kw == 0.0
    assert result.current_simulated_battery_charge_power_kw == 0.0
    assert result.current_simulated_solar_to_battery_power_kw == 0.0
    assert result.current_simulated_battery_to_home_power_kw == 0.0
    assert result.current_simulated_battery_export_power_kw == 0.0
    assert result.current_simulated_total_kh7_output_kw == 3.439
    assert result.current_simulated_grid_bypass_power_kw == 0.0
    assert result.current_simulated_total_site_import_kw == 0.0
    assert result.target_battery_export_power_kw == 0.0


def test_alpha842_routing_projection_does_not_require_a_settled_slot() -> None:
    """Current routing stays authoritative even before today's first settlement."""
    base = _SimulationState(current_simulated_grid_export_kw=9.0)

    result = presentation.reconciled_current_day_simulation(
        base,
        _alpha841_routing(),
    )

    assert result.current_simulated_grid_export_kw == 2.951


def test_alpha842_charge_sign_and_grid_bypass_are_coherent() -> None:
    """Charging is negative battery power and grid bypass excludes battery charge."""
    state = {
        "current_routing_snapshot": {
            "available": True,
            "simulated_house_load_kw": 0.5,
            "solar_power_kw": 1.2,
            "grid_import_kw": 2.8,
            "grid_export_kw": 0.0,
            "solar_to_battery_kw": 1.2,
            "grid_to_battery_kw": 2.3,
            "battery_to_home_kw": 0.0,
            "battery_export_kw": 0.0,
            "total_discharge_kw": 0.0,
            "normalised_kh7_ac_output_kw": 0.0,
        }
    }

    projected = presentation._current_routing_replacements(state)

    assert projected["current_simulated_battery_charge_power_kw"] == 3.5
    assert projected["current_simulated_battery_power_kw"] == -3.5
    assert projected["current_simulated_grid_bypass_power_kw"] == 0.5
    assert projected["current_simulated_total_site_import_kw"] == 2.8


def test_alpha842_missing_current_routing_preserves_generic_fallback() -> None:
    """Without final Agile routing the existing SimulationState remains untouched."""
    base = _SimulationState(current_simulated_grid_export_kw=4.262)

    result = presentation.reconciled_current_day_simulation(base, {})

    assert result is base


def test_alpha842_release_scope_and_architecture() -> None:
    manifest = json.loads((KEMS_ROOT / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    source = (KEMS_ROOT / "agile_current_day_presentation.py").read_text()
    version = manifest["version"]

    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert int(version.rsplit(".", 1)[1]) >= 42
    assert bundle["maintenance"]["affected_components"] == [
        "kems_core",
        "dashboard",
    ]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert "current_routing_snapshot" in source
    assert ".services.async_call(" not in source
    assert not (KEMS_ROOT / "agile_alpha842.py").exists()
