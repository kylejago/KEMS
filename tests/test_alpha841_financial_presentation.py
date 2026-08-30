"""Regression coverage for Alpha8.41 current-day financial presentation parity."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha841_financial_presentation_test"


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
product_types = _load(f"{PACKAGE}.product_types", KEMS_ROOT / "product_types.py")
presentation = _load(
    f"{PACKAGE}.agile_simulation_presentation",
    KEMS_ROOT / "agile_simulation_presentation.py",
)
dashboard_pipeline = _load(
    f"{PACKAGE}.dashboard_pipeline",
    KEMS_ROOT / "dashboard_pipeline.py",
)


def _coordinator():
    return SimpleNamespace(
        entry=SimpleNamespace(
            options={
                "system_type": "kems",
                "export_tariff_type": product_types.EXPORT_TARIFF_TYPE_AGILE,
            }
        ),
        agile_smart_export_state={
            "periods": {
                "today": {
                    "agile_smart_export": {
                        # Alpha8.40 diagnostic: this settled Agile ledger field
                        # includes the 53.70p electricity standing component.
                        "energy_net_cost_pence": 85.27,
                        "import_cost_pence": 159.13,
                        "export_income_pence": 127.56,
                    }
                }
            }
        },
        data=SimpleNamespace(
            simulation=SimpleNamespace(
                # Reconciled KEMSData keeps the headline electricity comparison
                # on the like-for-like net-energy basis.
                simulated_cost_pence=31.57,
                saving_pence=364.18,
                actual_cost_pence=395.75,
            ),
            whole_home=SimpleNamespace(
                observed_total_cost_pence=482.45,
                simulated_total_cost_pence=118.27,
                simulated_saving_pence=364.18,
            ),
        ),
    )


def test_alpha841_cost_projection_uses_reconciled_kemsdata_net_basis() -> None:
    coordinator = _coordinator()

    projected = presentation._projected_value(coordinator, "simulated_cost_today")

    assert projected == 31.57
    assert projected != 85.27
    assert round(coordinator.data.simulation.actual_cost_pence - projected, 2) == 364.18
    assert coordinator.data.simulation.saving_pence == 364.18


def test_alpha841_whole_home_totals_remain_like_for_like() -> None:
    coordinator = _coordinator()
    whole_home = coordinator.data.whole_home

    assert whole_home.observed_total_cost_pence == 482.45
    assert whole_home.simulated_total_cost_pence == 118.27
    assert (
        round(
            whole_home.observed_total_cost_pence
            - whole_home.simulated_total_cost_pence,
            2,
        )
        == 364.18
    )
    assert whole_home.simulated_saving_pence == 364.18


def test_alpha841_home_summary_uses_bill_totals_for_all_in_rows() -> None:
    payload = (KEMS_ROOT / "kems_master_dashboard.yaml").read_bytes()
    rendered = dashboard_pipeline._finalise_dashboard_bytes(payload).decode("utf-8")

    assert "{% set live_total = live_bill.get('total_energy_cost_pence') %}" in rendered
    assert "{% set kems_total = kems_bill.get('total_energy_cost_pence') %}" in rendered
    assert "{% set saving = bill.get('saving_pence') %}" in rendered
    assert "format((live_e + gas) / 100)" not in rendered
    assert "format((kems_e + gas) / 100)" not in rendered
    assert (
        "Total energy cost includes electricity standing charge, export income, "
        "supplier/account credits and gas."
    ) in rendered


def test_alpha841_does_not_override_the_saving_sensor_or_hardware() -> None:
    coordinator = _coordinator()

    assert (
        presentation._projected_value(coordinator, "simulated_saving_today")
        is presentation._MISSING
    )
    source = Path(presentation.__file__).read_text(encoding="utf-8")
    assert 'hardware_writes": "blocked' in source
    assert ".services.async_call(" not in source
    assert "safe_to_write_hardware = True" not in source


def test_alpha841_release_scope() -> None:
    manifest = json.loads((KEMS_ROOT / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    version = manifest["version"]

    assert version.startswith("0.8.0-alpha8.")
    assert int(version.rsplit(".", 1)[1]) >= 41
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
