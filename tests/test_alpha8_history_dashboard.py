"""Alpha8 contracts for canonical Alpha7.14/7.15 dashboard ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_history_dashboard.py"
DEADLINE_RUNTIME = KEMS / "agile_deadline_history_dashboard_runtime.py"
DIAGNOSTICS_RUNTIME = KEMS / "agile_history_diagnostics_dashboard_runtime.py"
HISTORICAL_714 = KEMS / "agile_alpha714_dashboard.py"
HISTORICAL_715 = KEMS / "agile_alpha715_dashboard.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-history-dashboard-canonicalisation.md"


def _post_specs() -> list[tuple[str, str]]:
    tree = ast.parse(COMPAT.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "POST_BASE_PATCHES":
            continue
        assert isinstance(node.value, ast.Tuple)
        return [
            (ast.literal_eval(item.elts[0]), ast.literal_eval(item.elts[1]))
            for item in node.value.elts
            if isinstance(item, ast.Tuple) and len(item.elts) == 2
        ]
    raise AssertionError("POST_BASE_PATCHES was not found")


def test_history_dashboard_retires_714_and_715_from_live_registry() -> None:
    specs = _post_specs()
    dispatch = ("agile_settlement_dispatch", "install_settlement_dispatch")
    first = ("agile_history_dashboard", "install_deadline_history_dashboard")
    second = ("agile_history_dashboard", "install_history_diagnostics_dashboard")
    alpha716 = ("agile_rolling_planning", "install_rolling_dashboard")

    assert specs.index(first) == specs.index(dispatch) + 1
    assert specs.index(second) == specs.index(first) + 1
    assert specs.index(alpha716) == specs.index(second) + 1
    retired = {"agile_alpha714_dashboard", "agile_alpha715_dashboard"}
    assert not any(module in retired for module, _ in specs)


def test_dashboard_runtimes_are_byte_identical() -> None:
    assert DEADLINE_RUNTIME.read_bytes() == HISTORICAL_714.read_bytes()
    assert DIAGNOSTICS_RUNTIME.read_bytes() == HISTORICAL_715.read_bytes()


def test_facade_binds_714_before_loading_frozen_715() -> None:
    source = FACADE.read_text(encoding="utf-8")
    bind = '_bind_legacy_name("agile_alpha714_dashboard", deadline_history_runtime)'
    loaded = "diagnostics_runtime = import_module("

    assert source.index(bind) < source.index(loaded)
    assert '".agile_history_diagnostics_dashboard_runtime"' in source
    assert '_bind_legacy_name("agile_alpha715_dashboard"' not in source


def test_frozen_715_still_consumes_exact_714_module_object() -> None:
    source = DIAGNOSTICS_RUNTIME.read_text(encoding="utf-8")

    assert "from . import agile_alpha714_dashboard as alpha714" in source
    assert "alpha714._BACKFILL_DIAGNOSTICS_CARD" in source


def test_deadline_history_presentation_contract_is_preserved() -> None:
    source = DEADLINE_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "10% battery target — cheap-window deadline",
        "Replay coverage including today",
        "sensor.kems_agile_live_hardware_battery_soc",
        "actual Home Assistant battery SOC, never simulated",
        "Historical backfill diagnostics",
    ):
        assert token in source


def test_sensor_backed_diagnostics_presentation_is_preserved() -> None:
    source = DIAGNOSTICS_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "sensor.kems_agile_backfill_method",
        "sensor.kems_agile_backfill_reason",
        "sensor.kems_agile_backfill_grid_import",
        "sensor.kems_agile_backfill_grid_export",
        "sensor.kems_agile_backfill_battery_soc",
    ):
        assert token in source


def test_history_dashboard_cannot_enable_hardware_writes() -> None:
    source = "\n".join(
        (
            FACADE.read_text(encoding="utf-8"),
            DEADLINE_RUNTIME.read_text(encoding="utf-8"),
            DIAGNOSTICS_RUNTIME.read_text(encoding="utf-8"),
        )
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source


def test_version_and_historical_evidence_remain_unchanged() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert HISTORICAL_714.is_file()
    assert HISTORICAL_715.is_file()
    assert '"version": "0.8.0-alpha8.0"' in manifest


def test_history_dashboard_docs_record_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "ownership migration only" in source
    assert "d17ca7fb46162058d3b376e2f7d61a3a9325f122" in source
    assert "dceecc3e7bea567033ba1d8fbac429621c8275e9" in source
    assert "real hardware writes remain blocked" in source
