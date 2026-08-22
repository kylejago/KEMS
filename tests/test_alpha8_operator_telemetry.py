"""Alpha8 contracts for canonical Full KEMS Agile operator telemetry."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_operator_telemetry.py"
FOCUS_RUNTIME = KEMS / "agile_operator_dashboard_runtime.py"
LIVE_RUNTIME = KEMS / "agile_live_graph_runtime.py"
HISTORICAL_FOCUS = KEMS / "agile_alpha742_dashboard_focus.py"
HISTORICAL_LIVE = KEMS / "agile_alpha742_live_graph_telemetry.py"


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


def test_operator_telemetry_retires_both_alpha742_modules_from_execution() -> None:
    specs = _compat_specs()
    previous = (
        "dashboard_alpha741_partial_publication",
        "install_alpha741_partial_publication_dashboard_patch",
    )
    canonical = ("agile_operator_telemetry", "install_operator_telemetry")
    following = ("agile_event_priority", "install_event_priority")

    assert specs.index(canonical) > specs.index(previous)
    assert specs.index(canonical) < specs.index(following)
    assert not any(
        module_name
        in {
            "agile_alpha742_dashboard_focus",
            "agile_alpha742_live_graph_telemetry",
        }
        for module_name, _ in specs
    )
    assert HISTORICAL_FOCUS.is_file()
    assert HISTORICAL_LIVE.is_file()


def test_canonical_runtime_owners_are_byte_identical_to_alpha742() -> None:
    assert FOCUS_RUNTIME.read_bytes() == HISTORICAL_FOCUS.read_bytes()
    assert LIVE_RUNTIME.read_bytes() == HISTORICAL_LIVE.read_bytes()


def test_canonical_installer_preserves_focus_then_live_graph_order() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    focus_call = "operator_dashboard.install_alpha742_dashboard_focus_patch()"
    live_call = "live_graph.install_alpha742_live_graph_telemetry_patch()"
    assert focus_call in source
    assert live_call in source
    assert source.index(focus_call) < source.index(live_call)
    assert "agile_alpha742_dashboard_focus" not in source
    assert "agile_alpha742_live_graph_telemetry" not in source


def test_operator_telemetry_keeps_reporting_and_missing_data_contracts() -> None:
    focus = FOCUS_RUNTIME.read_text(encoding="utf-8")
    live = LIVE_RUNTIME.read_text(encoding="utf-8")

    assert "Full KEMS Agile — live vs simulation" in focus
    assert '"missing_sources_remain_unavailable": True' in focus
    assert '"missing_physical_data_is_not_zero": True' in live
    assert "sensor.kems_agile_live_today_summary" in focus
    assert "sensor.kems_agile_simulated_battery_net_power" in focus
    assert "sensor.kems_agile_actual_battery_net_power" in live


def test_operator_telemetry_cannot_change_dispatch_or_hardware_writes() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (FACADE, FOCUS_RUNTIME, LIVE_RUNTIME)
    )

    assert "_dispatch_targets" not in source
    assert "_rolling_plan" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"reporting_only": True' in source
    assert '"hardware_writes": "blocked"' in source
    assert "Real FoxESS hardware writes remain blocked" in source
