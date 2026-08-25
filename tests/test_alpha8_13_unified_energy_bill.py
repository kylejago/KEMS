from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha813_test"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Load the HA-independent modules under a synthetic package so their relative
# imports work without importing custom_components.kems.__init__ (and therefore
# without requiring the full Home Assistant runtime in repository CI).
package = ModuleType(PACKAGE)
package.__path__ = [str(KEMS_ROOT)]
sys.modules[PACKAGE] = package

product_types = _load(f"{PACKAGE}.product_types", KEMS_ROOT / "product_types.py")
models = _load(f"{PACKAGE}.kems_core.models", KEMS_ROOT / "kems_core" / "models.py")
kems_core = ModuleType(f"{PACKAGE}.kems_core")
kems_core.__path__ = [str(KEMS_ROOT / "kems_core")]
kems_core.KEMSData = models.KEMSData
kems_core.ScenarioSummary = models.ScenarioSummary
kems_core.Snapshot = models.Snapshot
sys.modules[f"{PACKAGE}.kems_core"] = kems_core
energy_bill = _load(f"{PACKAGE}.energy_bill", KEMS_ROOT / "energy_bill.py")

_scenario = energy_bill._scenario
_strategy = energy_bill._strategy
ScenarioSummary = models.ScenarioSummary

EXPORT_TARIFF_TYPE_AGILE = product_types.EXPORT_TARIFF_TYPE_AGILE
EXPORT_TARIFF_TYPE_FIXED = product_types.EXPORT_TARIFF_TYPE_FIXED
EXPORT_TARIFF_TYPE_NONE = product_types.EXPORT_TARIFF_TYPE_NONE
SYSTEM_TYPE_KEMS = product_types.SYSTEM_TYPE_KEMS
SYSTEM_TYPE_LIVE_DATA = product_types.SYSTEM_TYPE_LIVE_DATA
SYSTEM_TYPES = product_types.SYSTEM_TYPES
export_tariff_type_from_options = product_types.export_tariff_type_from_options
normalise_system_type = product_types.normalise_system_type


def test_user_facing_products_are_live_data_and_kems_only() -> None:
    assert SYSTEM_TYPES == (SYSTEM_TYPE_LIVE_DATA, SYSTEM_TYPE_KEMS)
    for legacy in ("battery_solar", "full_kems", "full_kems_agile"):
        assert normalise_system_type(legacy) == SYSTEM_TYPE_KEMS


def test_legacy_product_choice_preserves_export_tariff_intent() -> None:
    assert (
        export_tariff_type_from_options({"system_type": "battery_solar"})
        == EXPORT_TARIFF_TYPE_NONE
    )
    assert (
        export_tariff_type_from_options({"system_type": "full_kems"})
        == EXPORT_TARIFF_TYPE_FIXED
    )
    assert (
        export_tariff_type_from_options({"system_type": "full_kems_agile"})
        == EXPORT_TARIFF_TYPE_AGILE
    )
    assert (
        export_tariff_type_from_options({"export_tariff_type": "agile"})
        == EXPORT_TARIFF_TYPE_AGILE
    )


def test_bill_equivalent_scenario_includes_standing_gas_and_supplier_credit() -> None:
    scenario = ScenarioSummary(
        key="kems_forecast",
        label="KEMS",
        ready=True,
        import_cost_pence=300.0,
        export_income_pence=500.0,
        power_down_income_pence=40.0,
        standing_charge_pence=60.0,
        energy_net_cost_pence=-240.0,
        total_cost_pence=-180.0,
        house_consumption_kwh=12.0,
        grid_import_kwh=20.0,
        grid_export_kwh=30.0,
    )
    gas = {
        "gas_available": True,
        "gas_usage_cost_pence": 70.0,
        "gas_standing_charge_pence": 30.0,
        "gas_total_cost_pence": 100.0,
        "gas_usage_kwh": 8.0,
    }
    result = _scenario(scenario, gas)
    assert result["electricity_import_cost_pence"] == 300.0
    assert result["electricity_standing_charge_pence"] == 60.0
    assert result["electricity_export_income_pence"] == 500.0
    assert result["supplier_energy_credit_pence"] == 40.0
    assert result["electricity_total_cost_pence"] == -180.0
    assert result["gas_total_cost_pence"] == 100.0
    assert result["total_energy_cost_pence"] == -80.0
    assert result["battery_wear_included"] is False


def test_agile_bill_reconciliation_uses_producer_bill_not_battery_wear() -> None:
    day = date(2026, 8, 24)
    rows = [
        {
            "import_cost_pence": 144.39,
            "export_income_pence": 814.09,
            "energy_net_cost_pence": -616.0,
            "economic_net_cost_pence": -529.82,
            "grid_import_kwh": 41.335,
            "grid_export_kwh": 45.198,
            "house_load_kwh": 16.19,
        }
    ]
    gas = {
        "gas_available": True,
        "gas_usage_cost_pence": 80.0,
        "gas_standing_charge_pence": 30.0,
        "gas_total_cost_pence": 110.0,
    }
    result = _strategy(
        rows,
        {day},
        gas,
        {day: 53.70},
        53.70,
        "Agile export optimisation",
    )
    assert result["electricity_standing_charge_pence"] == 53.70
    assert result["supplier_energy_credit_pence"] == 0.0
    assert result["electricity_total_cost_pence"] == -616.0
    assert result["total_energy_cost_pence"] == -506.0
    assert result["battery_wear_included"] is False


def test_unified_bill_contract_is_preserved_in_alpha8_14_and_coordinated_web4() -> (
    None
):
    manifest = json.loads((ROOT / "custom_components/kems/manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    assert manifest["version"] == "0.8.0-alpha8.14"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    for key in ("property_web", "pi_agent", "public_web"):
        assert bundle["components"][key]["version"] == "0.8.0-alpha8-web.4"


def test_dashboard_and_web_contract_use_one_canonical_bill_state() -> None:
    presentation = (
        ROOT / "custom_components/kems/energy_bill_presentation.py"
    ).read_text()
    init_source = (ROOT / "custom_components/kems/__init__.py").read_text()
    assert "sensor.kems_energy_cost_comparison" in presentation
    assert "Total energy cost by period — Live Data vs KEMS" in presentation
    assert "Battery wear is deliberately excluded" in presentation
    assert "install_energy_bill_dashboard_patch()" in init_source
    assert "async_setup_energy_bill_state(hass, entry, coordinator)" in init_source
