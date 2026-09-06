"""Alpha9.10 current-day presentation regression contracts."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
DASHBOARD = ROOT / "dashboards" / "kems_master_dashboard.yaml"
SOURCE = KEMS / "alpha95_presentation.py"


def _presentation_helpers() -> dict[str, Any]:
    """Load only Home Assistant-independent presentation code from source."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    assignments = {
        "_LIVE_DAILY_OLD",
        "_LIVE_DAILY_NEW",
        "_KEMS_DAILY_OLD",
        "_KEMS_DAILY_NEW",
        "_KEMS_HOME_ENERGY_OLD",
        "_KEMS_HOME_ENERGY_NEW",
        "_HOME_RECONCILED_OLD",
        "_HOME_RECONCILED_NEW",
        "_KEMS_DAILY_CARD_NEW",
        "_COMPARE_WITHOUT_KEMS_NEW",
        "_COMPARE_LIVE_NEW",
        "_COMPARE_KEMS_NEW",
        "_COMPARE_SIDE_BY_SIDE_NEW",
    }
    functions = {
        "_replace_between",
        "_improve_alpha910_today_presentation",
        "improve_alpha95_dashboard",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if names & assignments:
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in functions:
            body.append(node)

    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    namespace: dict[str, Any] = {}
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


def _post_pipeline_fixture() -> str:
    """Reproduce the row mutation that made the Alpha9.5 whole-block match miss."""
    text = DASHBOARD.read_text(encoding="utf-8")
    return text.replace(
        "| Supplier credits | {{ ('−£%.2f' | "
        "format((kems.get('supplier_energy_credit_pence') | float) / 100)) "
        "if kems.get('supplier_energy_credit_pence') is not none else '—' }} |",
        "| Supplier rewards & credits | {{ ('−£%.2f' | "
        "format((kems.get('power_down_reward_pence') | float) / 100)) "
        "if kems.get('power_down_reward_pence') is not none else '—' }} |",
    )


def test_alpha910_post_pipeline_kems_daily_uses_canonical_flat_totals() -> None:
    improve = _presentation_helpers()["improve_alpha95_dashboard"]
    content = improve(_post_pipeline_fixture())
    kems_start = content.index("\n  - title: KEMS\n")
    compare_start = content.index("\n  - title: Compare\n", kems_start)
    kems = content[kems_start:compare_start]

    assert "states('sensor.kems_simulated_kems_cost_today')" in kems
    assert "states('sensor.kems_whole_home_simulated_cost_today')" in kems
    assert "states('sensor.kems_simulated_export_income_today')" in kems
    assert "states('sensor.kems_simulated_power_down_session_bonus_today')" in kems
    assert "states('sensor.kems_whole_home_energy_today')" in kems
    assert "p.get('kems', {})" not in kems


def test_alpha910_compare_today_uses_current_scenario_and_flat_live_totals() -> None:
    improve = _presentation_helpers()["improve_alpha95_dashboard"]
    content = improve(_post_pipeline_fixture())
    compare_start = content.index("\n  - title: Compare\n")
    next_view = content.find("\n  - title:", compare_start + 20)
    compare = (
        content[compare_start:]
        if next_view < 0
        else content[compare_start:next_view]
    )

    assert "sensor.kems_compare_no_system_cost_today" in compare
    assert "sensor.kems_compare_full_kems_cost_today" in compare
    assert "sensor.kems_whole_home_observed_cost_today" in compare
    assert "sensor.kems_observed_grid_import_today" in compare
    assert "sensor.kems_observed_grid_export_today" in compare
    assert "sensor.kems_energy_cost_comparison" not in compare
    assert "p.get('kems', {})" not in compare
    assert "p.get('live_data', {})" not in compare


def test_alpha910_does_not_fabricate_historical_slot_data_or_replace_period_engine() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")

    assert "NO DATA" not in source
    assert "historical" not in source.lower()
    assert "sensor.kems_energy_cost_comparison" in dashboard
    assert "sensor.kems_agile_slots" in dashboard


def test_alpha910_presentation_repair_cannot_write_hardware() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        ".services.async_call(",
        "async_select_option(",
        "async_set_native_value(",
        "write_register(",
        "write_registers(",
        "ModbusClient",
        "commands_permitted = True",
        "safe_to_write_hardware = True",
    ):
        assert forbidden not in source
