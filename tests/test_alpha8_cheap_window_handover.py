"""Alpha8 contracts for canonical Alpha7.35 cheap-window handover ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_cheap_window_handover.py"
RUNTIME = KEMS / "agile_cheap_window_handover_runtime.py"
HISTORICAL = KEMS / "agile_alpha735_cheap_handover.py"


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


def test_cheap_window_handover_retires_alpha735_from_execution() -> None:
    specs = _compat_specs()
    previous = ("agile_deadline_guard", "install_deadline_guard")
    canonical = ("agile_cheap_window_handover", "install_cheap_window_handover")
    following = ("agile_product_presentation", "install_product_presentation")

    assert specs.index(canonical) > specs.index(previous)
    assert specs.index(canonical) < specs.index(following)
    assert not any(
        module_name == "agile_alpha735_cheap_handover" for module_name, _ in specs
    )
    assert HISTORICAL.is_file()


def test_cheap_window_handover_runtime_is_byte_identical_to_alpha735() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL.read_bytes()


def test_cheap_window_handover_facade_owns_only_installation() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    assert "agile_cheap_window_handover_runtime" in source
    assert "handover_runtime.install_alpha735_cheap_handover_patch()" in source
    assert "agile_alpha735_cheap_handover" not in source
    assert "Alpha7.34 deadline/dispatch policy remains authoritative" in source


def test_cheap_handover_preserves_manual_schedule_and_publish_order() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert "manual_schedule(now, tariff.offpeak_start, tariff.offpeak_end)" in source
    assert "alpha735_original_publish(self, state)" in source
    assert source.index("alpha735_original_publish(self, state)") < source.index(
        "snapshot = _cheap_snapshot(self, state)"
    )
    assert (
        '"routing_basis": "current routing snapshot — overnight cheap handover"'
        in source
    )
    assert '"reporting_only": True' in source
    assert '"hardware_writes": "blocked"' in source


def test_cheap_handover_blocks_display_export_without_replanning() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert "battery_export = 0.0" in source
    assert '"dispatch_mode": "cheap_charge"' in source
    assert 'slot["rolling_planned_battery_export_kwh"] = 0.0' in source
    assert 'slot["rolling_target_battery_export_kw"] = 0.0' in source
    assert 'plan["current_battery_export_target_kw"] = 0.0' in source
    assert '"cheap_period_handover_applied": True' in source
    assert "rolling export candidate suppressed" in source

    assert "def _dispatch_targets" not in source
    assert "def _rolling_plan" not in source
    assert "alpha717._dispatch_targets =" not in source
    assert "rolling._rolling_plan =" not in source


def test_cheap_handover_cannot_enable_real_hardware_writes() -> None:
    source = (
        FACADE.read_text(encoding="utf-8") + "\n" + RUNTIME.read_text(encoding="utf-8")
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "real FoxESS hardware writes remain blocked" in source
