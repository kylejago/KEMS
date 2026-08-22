"""Alpha8 contracts for canonical Agile live-scenario ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_live_scenario.py"
LIVE_RUNTIME = KEMS / "agile_live_scenario_runtime.py"
GUARD_RUNTIME = KEMS / "agile_live_scenario_yaml_guard_runtime.py"
HISTORICAL_LIVE = KEMS / "agile_smart_export_live.py"
HISTORICAL_GUARD = KEMS / "agile_dashboard_yaml_guard.py"
HISTORICAL_LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-live-scenario-canonicalisation.md"


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


def test_live_scenario_retires_historical_live_seams_from_registry() -> None:
    specs = _post_specs()
    rolling = ("agile_rolling_planning", "install_rolling_replan")
    live = ("agile_live_scenario", "install_live_scenario")
    guard = ("agile_live_scenario", "install_live_scenario_yaml_guard")
    dispatch = ("agile_settlement_dispatch", "install_settlement_dispatch")

    assert specs.index(live) == specs.index(rolling) + 1
    assert specs.index(guard) == specs.index(live) + 1
    assert specs.index(dispatch) == specs.index(guard) + 1
    retired = {"agile_smart_export_live", "agile_dashboard_yaml_guard"}
    assert not any(module in retired for module, _ in specs)


def test_live_scenario_runtimes_are_byte_identical() -> None:
    assert LIVE_RUNTIME.read_bytes() == HISTORICAL_LIVE.read_bytes()
    assert GUARD_RUNTIME.read_bytes() == HISTORICAL_GUARD.read_bytes()


def test_facade_preserves_split_install_positions_without_legacy_alias() -> None:
    source = FACADE.read_text(encoding="utf-8")

    assert "live_runtime.install_live_scenario_patch()" in source
    assert '".agile_live_scenario_yaml_guard_runtime"' in source
    assert "guard_runtime.install_dashboard_yaml_guard()" in source
    assert "sys.modules" not in source
    assert "_bind_legacy_name" not in source


def test_historical_live_names_have_no_executable_import_consumers() -> None:
    legacy = {"agile_smart_export_live", "agile_dashboard_yaml_guard"}
    offenders: list[tuple[str, str]] = []

    for path in sorted(KEMS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module in legacy:
                offenders.append((path.name, str(node.module)))
            for alias in node.names:
                if alias.name in legacy:
                    offenders.append((path.name, alias.name))

    assert offenders == []


def test_live_scenario_reporting_contract_is_preserved() -> None:
    source = LIVE_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "sensor.kems_agile_live_scenario",
        "sensor.kems_agile_simulated_battery_soc_now",
        'today.get("agile_smart_export")',
        'return slot, "current simulated half-hour"',
        'return latest[1], "latest completed simulated half-hour"',
        "complete = all(",
        '"mode": "simulation_only"',
        '"waiting for first complete simulated half-hour"',
    ):
        assert token in source


def test_live_scenario_dashboard_contract_is_preserved() -> None:
    source = LIVE_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "title: Agile Smart Export",
        "path: agile-smart-export",
        "Agile Smart Export — Live Scenario",
        "Current Agile Smart Export power routing",
        "Current and upcoming Agile plan",
        "Live hardware battery SOC",
        "Agile simulated SOC now",
        "_AGILE_LIVE_VIEW.lstrip()",
    ):
        assert token in source


def test_yaml_guard_contract_is_preserved() -> None:
    source = GUARD_RUNTIME.read_text(encoding="utf-8")

    for token in (
        '_BAD_AGILE_VIEW_ROOT = "\\n\\n- title: Agile Smart Export\\n"',
        '_GOOD_AGILE_VIEW_ROOT = "\\n\\n  - title: Agile Smart Export\\n"',
        "repair_agile_live_view_indentation(original())",
        "_kems_agile_yaml_guard",
    ):
        assert token in source


def test_live_scenario_ownership_cannot_enable_hardware_writes() -> None:
    source = "\n".join(
        (
            FACADE.read_text(encoding="utf-8"),
            LIVE_RUNTIME.read_text(encoding="utf-8"),
            GUARD_RUNTIME.read_text(encoding="utf-8"),
        )
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source


def test_historical_install_order_remains_evidence() -> None:
    source = HISTORICAL_LOADER.read_text(encoding="utf-8")

    assert "install_live_scenario_patch()" in source
    assert "install_dashboard_yaml_guard()" in source
    assert source.index("install_live_scenario_patch()") < source.index(
        "install_dashboard_yaml_guard()"
    )
    assert source.index("install_dashboard_yaml_guard()") < source.index(
        "install_alpha717_dispatch_patch()"
    )


def test_version_and_historical_live_sources_remain_unchanged() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert HISTORICAL_LIVE.is_file()
    assert HISTORICAL_GUARD.is_file()
    assert '"version": "0.8.0-alpha8.0"' in manifest


def test_live_scenario_docs_record_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "ownership migration only" in source
    assert "38dea9f6d3adb8bbccbbfb935403d514895a052c" in source
    assert "d87dc4c1246a24df22148fd5e4630f8268afd350" in source
    assert "No runtime body is rewritten" in source
    assert "real hardware writes remain blocked" in source
