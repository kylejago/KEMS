"""Regression for settled Power Down rewards in the canonical Alpha8 bill."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha834_test"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = ModuleType(PACKAGE)
package.__path__ = [str(KEMS_ROOT)]
sys.modules[PACKAGE] = package

core = ModuleType(f"{PACKAGE}.kems_core")
core.KEMSData = object
core.ScenarioSummary = object
core.Snapshot = object
sys.modules[f"{PACKAGE}.kems_core"] = core

product_types = ModuleType(f"{PACKAGE}.product_types")
product_types.EXPORT_TARIFF_TYPE_AGILE = "agile"
product_types.EXPORT_TARIFF_TYPE_FIXED = "fixed"
product_types.EXPORT_TARIFF_TYPE_NONE = "none"
product_types.kems_strategy_label = lambda value: value
sys.modules[f"{PACKAGE}.product_types"] = product_types

energy_bill = _load(f"{PACKAGE}.energy_bill", KEMS_ROOT / "energy_bill.py")


def test_settled_power_down_reward_is_separate_from_agile_export_income() -> None:
    day = date(2026, 8, 26)
    now = datetime(2026, 8, 26, 22, 0, tzinfo=UTC)
    data = SimpleNamespace(
        last_power_down=SimpleNamespace(
            available=True,
            completed_successfully=True,
            session_start=datetime(2026, 8, 26, 18, 0, tzinfo=UTC),
            bonus_pence=49.73,
        )
    )

    reward = energy_bill._settled_power_down_reward(data, day, day, now)
    assert reward == 49.73

    result = energy_bill._strategy(
        [
            {
                "import_cost_pence": 166.89,
                "export_income_pence": 732.81,
                "energy_net_cost_pence": -512.21,
                "grid_import_kwh": 47.776,
                "grid_export_kwh": 39.389,
                "house_load_kwh": 28.979,
            }
        ],
        {day},
        {"gas_total_cost_pence": 0.0},
        {day: 53.70},
        53.70,
        "Agile Smart Export",
        reward,
    )

    assert result["electricity_export_income_pence"] == 732.81
    assert result["power_down_reward_pence"] == 49.73
    assert result["supplier_energy_credit_pence"] == 49.73
    assert result["power_down_reward_source"] == "settled_power_down_event"
    assert result["electricity_total_cost_pence"] == -561.95
    assert result["total_energy_cost_pence"] == -561.95
    assert f"−£{result['electricity_export_income_pence'] / 100:.2f}" == "−£7.33"
    assert f"−£{result['power_down_reward_pence'] / 100:.2f}" == "−£0.50"


def test_settled_reward_only_applies_to_period_containing_the_event() -> None:
    data = SimpleNamespace(
        last_power_down=SimpleNamespace(
            available=True,
            completed_successfully=True,
            session_start=datetime(2026, 8, 26, 18, 0, tzinfo=UTC),
            bonus_pence=49.73,
        )
    )
    now = datetime(2026, 8, 26, 22, 0, tzinfo=UTC)

    assert (
        energy_bill._settled_power_down_reward(
            data,
            date(2026, 8, 25),
            date(2026, 8, 25),
            now,
        )
        is None
    )


def test_final_managed_dashboard_uses_explicit_power_down_reward() -> None:
    dashboard = ModuleType(f"{PACKAGE}.dashboard")
    dashboard.PACKAGED_DASHBOARD_PATH = KEMS_ROOT / "kems_master_dashboard.yaml"
    sys.modules[f"{PACKAGE}.dashboard"] = dashboard
    pipeline = _load(
        f"{PACKAGE}.dashboard_pipeline",
        KEMS_ROOT / "dashboard_pipeline.py",
    )

    content = pipeline._fresh_dashboard_bytes().decode("utf-8")

    assert "| Supplier rewards & credits |" in content
    assert "kems.get('power_down_reward_pence')" in content
    assert "| Supplier credits |" not in content
    assert "kems.get('supplier_energy_credit_pence')" not in content
    assert "kems.get('electricity_export_income_pence')" in content
