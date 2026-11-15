"""Alpha9.206: test runtime Compare after the legacy Alpha9.5 card rewrite."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
MASTER = KEMS / "kems_master_dashboard.yaml"


def _repair_module():
    spec = importlib.util.spec_from_file_location(
        "alpha9206_runtime_bill", KEMS / "alpha937_dashboard_contract.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_compare_live_card() -> str:
    """Extract the real Alpha9.5 override without importing HA runtime modules."""
    syntax = ast.parse((KEMS / "alpha95_presentation.py").read_text())
    for node in syntax.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "_COMPARE_LIVE_NEW"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("Alpha9.5 Compare Live override has disappeared")


def _runtime_dashboard():
    """Reproduce the ordering: packaged YAML -> Alpha9.5 -> Alpha9.37."""
    module = _repair_module()
    packaged = MASTER.read_text()
    compare_start = packaged.index("  - title: Compare\n")
    prefix, compare = packaged[:compare_start], packaged[compare_start:]
    compare = module._replace_between(
        compare,
        "          - type: markdown\n            title: Live\n",
        "          - type: markdown\n            title: KEMS\n",
        _legacy_compare_live_card(),
    )
    after_alpha95 = prefix + compare
    assert "sensor.kems_whole_home_observed_cost_today" in after_alpha95
    final = module.repair_dashboard_contract(after_alpha95.encode()).decode()
    return yaml.safe_load(final), module, final


def _cards(data):
    view = next(view for view in data["views"] if view.get("path") == "compare")
    grid = next(card for card in view["cards"] if card.get("type") == "grid")
    live = next(card for card in grid["cards"] if card.get("title") == "Live")
    comparison = next(
        card for card in view["cards"] if card.get("title") == "Today — side by side"
    )
    return live["content"], comparison["content"]


def _render(template: str):
    bill = {
        "today": {
            "live_data": {
                "total_energy_cost_pence": 374.01,
                "electricity_total_cost_pence": 254.01,
                "total_energy_effective_cost_pence": -100.038,
                "electricity_effective_total_cost_pence": -220.038,
                "happy_hour_estimated_credit_pence": 474.048,
                "gas_total_cost_pence": 120.0,
                "grid_import_kwh": 80.5,
                "grid_export_kwh": 30.9,
            }
        }
    }
    values = {
        "sensor.kems_compare_no_system_cost_today": "1092.17",
        "sensor.kems_gas_cost_today": "120.0",
        "sensor.kems_whole_home_observed_cost_today": "374.01",
        "sensor.kems_whole_home_simulated_cost_today": "-148.36",
        "sensor.kems_simulated_grid_import_today": "74.012",
        "sensor.kems_simulated_grid_export_today": "35.528",
    }

    def state_attr(entity, attribute):
        if entity == "sensor.kems_energy_cost_comparison" and attribute == "periods":
            return bill
        if entity == "sensor.kems_compare_no_system_cost_today":
            if attribute == "grid_import_kwh":
                return 59.908
            if attribute == "grid_export_kwh":
                return 0.0
        return None

    return (
        Environment(autoescape=False)
        .from_string(template)
        .render(
            state_attr=state_attr,
            states=lambda entity: values.get(entity, "unknown"),
        )
    )


def test_final_managed_compare_matches_home_after_legacy_rewriter() -> None:
    dashboard, _, final = _runtime_dashboard()
    live, side_by_side = _cards(dashboard)
    assert "sensor.kems_whole_home_observed_cost_today" not in live
    assert "total_energy_effective_cost_pence" in live
    assert "total_energy_effective_cost_pence" in side_by_side
    assert "electricity_effective_total_cost_pence" in side_by_side
    assert "Happy Hour refund (pending)" in side_by_side
    assert "total_energy_cost_pence" not in live.replace(
        "total_energy_effective_cost_pence", ""
    )
    rendered_live = _render(live)
    assert "# £-1.00" in rendered_live
    assert "Electricity: £-2.20" in rendered_live
    assert "Est. Happy Hour refund (pending): −£4.74" in rendered_live
    assert "# £3.74" not in rendered_live
    rendered_table = _render(side_by_side)
    assert "£-1.00" in rendered_table
    assert "£-2.20" in rendered_table
    assert "Est. Happy Hour refund (pending)" in rendered_table
    assert "£3.74" not in rendered_table
    assert "Live system value vs no system: £13.12" in rendered_table
    assert "Measured property data after estimated" in final


def test_compare_final_contract_is_idempotent_and_does_not_edit_control() -> None:
    dashboard, module, final = _runtime_dashboard()
    assert module.repair_dashboard_contract(final.encode()).decode() == final
    live, side = _cards(dashboard)
    assert "sensor.kems_whole_home_observed_cost_today" not in live + side


def test_missing_verified_estimate_is_not_filled_in_using_gross() -> None:
    dashboard, _, _ = _runtime_dashboard()
    live, _ = _cards(dashboard)
    # An unknown effective cost is absent, not replaced by misleading gross.
    missing = _render(
        live.replace(
            "live.get('total_energy_effective_cost_pence')",
            "live.get('absent_effective_total')",
        )
    )
    assert "# —" in missing
    assert "# £3.74" not in missing
