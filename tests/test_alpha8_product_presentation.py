"""Alpha8 contracts for canonical Alpha7.36 product-presentation ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_product_presentation.py"
PANEL_RUNTIME = KEMS / "agile_panel_presentation_runtime.py"
DASHBOARD_RUNTIME = KEMS / "dashboard_product_finance_runtime.py"
HISTORICAL_PANEL = KEMS / "agile_alpha736_panel_flow.py"
HISTORICAL_DASHBOARD = KEMS / "dashboard_alpha736_finance.py"


def _compat_specs() -> list[tuple[str, str]]:
    tree = ast.parse(COMPAT.read_text(encoding="utf-8"))
    specs: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id not in {"PRE_BASE_PATCHES", "POST_BASE_PATCHES"}:
            continue
        assert isinstance(node.value, ast.Tuple)
        for item in node.value.elts:
            assert isinstance(item, ast.Tuple) and len(item.elts) == 2
            specs.append(
                (ast.literal_eval(item.elts[0]), ast.literal_eval(item.elts[1]))
            )
    return specs


def test_product_presentation_retires_both_alpha736_modules_from_execution() -> None:
    specs = _compat_specs()
    previous = (
        "agile_alpha735_cheap_handover",
        "install_alpha735_cheap_handover_patch",
    )
    canonical = ("agile_product_presentation", "install_product_presentation")
    following = ("agile_economic_opportunity", "install_economic_opportunity")

    assert specs.index(canonical) > specs.index(previous)
    assert specs.index(canonical) < specs.index(following)
    assert not any(
        module_name in {"agile_alpha736_panel_flow", "dashboard_alpha736_finance"}
        for module_name, _ in specs
    )
    assert HISTORICAL_PANEL.is_file()
    assert HISTORICAL_DASHBOARD.is_file()


def test_product_presentation_runtime_owners_are_byte_identical_to_alpha736() -> None:
    assert PANEL_RUNTIME.read_bytes() == HISTORICAL_PANEL.read_bytes()
    assert DASHBOARD_RUNTIME.read_bytes() == HISTORICAL_DASHBOARD.read_bytes()


def test_product_presentation_facade_preserves_panel_then_dashboard_order() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    panel_call = "panel_runtime.install_alpha736_panel_flow_patch()"
    dashboard_call = "dashboard_runtime.install_alpha736_finance_dashboard_patch()"
    assert panel_call in source
    assert dashboard_call in source
    assert source.index(panel_call) < source.index(dashboard_call)
    assert "agile_alpha736_panel_flow" not in source
    assert "dashboard_alpha736_finance" not in source


def test_panel_projection_keeps_compact_protocol_and_unavailable_sentinel() -> None:
    source = PANEL_RUNTIME.read_text(encoding="utf-8")

    assert 'state.get("current_routing_snapshot")' in source
    assert '"sensor.kems_panel_full_kems_agile_flow_now"' in source
    assert '"sensor.kems_agile_smart_export_flow_now"' in source
    assert "H=-1,S=-1,GI=-1,GE=-1,SH=-1,SB=-1,SE=-1,GB=-1,BH=-1,BE=-1,SOC=-1" in source
    assert '"source": "current_routing_snapshot"' in source
    assert '"reporting_only": True' in source
    assert 'live_attributes["simulated_soc_percent"]' in source
    assert 'live_attributes["panel_flow_state"]' in source
    assert 'live_attributes["panel_flow_source"]' in source


def test_product_finance_dashboard_keeps_comparison_and_roi_contract() -> None:
    source = DASHBOARD_RUNTIME.read_text(encoding="utf-8")

    assert "Winner by period" in source
    assert "Last 7 days" in source
    assert "Last 30 days" in source
    assert "Rolling 365 evidence" in source
    assert "All tracked Agile evidence" in source
    assert "Awaiting battery data" in source
    assert "Awaiting solar data" in source
    assert "title: Cost & ROI" in source
    assert "Actual vs core KEMS simulation" in source
    assert "sensor.kems_actual_roi" in source
    assert "sensor.kems_actual_system_value_total" in source
    assert "sensor.kems_lifetime_simulated_system_value" in source


def test_product_presentation_cannot_change_planning_or_enable_hardware_writes() -> (
    None
):
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (FACADE, PANEL_RUNTIME, DASHBOARD_RUNTIME)
    )

    assert "_dispatch_targets" not in source
    assert "_rolling_plan" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "does not alter planning" in FACADE.read_text(encoding="utf-8")
