"""Alpha8 contracts for canonical Alpha7.17 settlement dispatch ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_settlement_dispatch.py"
DISPATCH_RUNTIME = KEMS / "agile_settlement_dispatch_runtime.py"
DASHBOARD_RUNTIME = KEMS / "agile_settlement_dispatch_dashboard_runtime.py"
HISTORICAL_DISPATCH = KEMS / "agile_alpha717_dispatch.py"
HISTORICAL_DASHBOARD = KEMS / "agile_alpha717_dashboard.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-settlement-dispatch-canonicalisation.md"


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


def test_settlement_dispatch_retires_alpha717_live_entries() -> None:
    specs = _post_specs()
    yaml_guard = ("agile_live_scenario", "install_live_scenario_yaml_guard")
    dispatch = ("agile_settlement_dispatch", "install_settlement_dispatch")
    history = ("agile_history_dashboard", "install_deadline_history_dashboard")
    rolling_dashboard = ("agile_rolling_planning", "install_rolling_dashboard")
    dashboard = (
        "agile_settlement_dispatch",
        "install_settlement_dispatch_dashboard",
    )
    validation = ("agile_validation_evidence", "install_validation_evidence")

    assert specs.index(dispatch) == specs.index(yaml_guard) + 1
    assert specs.index(history) == specs.index(dispatch) + 1
    assert specs.index(dashboard) == specs.index(rolling_dashboard) + 1
    assert specs.index(validation) == specs.index(dashboard) + 1
    retired = {"agile_alpha717_dispatch", "agile_alpha717_dashboard"}
    assert not any(module in retired for module, _ in specs)


def test_settlement_dispatch_runtimes_are_byte_identical() -> None:
    assert DISPATCH_RUNTIME.read_bytes() == HISTORICAL_DISPATCH.read_bytes()
    assert DASHBOARD_RUNTIME.read_bytes() == HISTORICAL_DASHBOARD.read_bytes()


def test_facade_binds_only_dispatch_legacy_name() -> None:
    source = FACADE.read_text(encoding="utf-8")

    assert '_bind_legacy_name("agile_alpha717_dispatch", dispatch_runtime)' in source
    assert "sys.modules[qualified] = module" in source
    assert "setattr(_PACKAGE, name, module)" in source
    assert '".agile_settlement_dispatch_dashboard_runtime"' in source
    assert '_bind_legacy_name("agile_alpha717_dashboard"' not in source


def test_dispatch_keeps_shared_canonical_rolling_object() -> None:
    source = DISPATCH_RUNTIME.read_text(encoding="utf-8")

    assert "from . import agile_rolling_replan as rolling" in source
    assert "rolling._rolling_plan = rolling_plan_with_alpha717" in source


def test_frozen_consumers_keep_shared_dispatch_object() -> None:
    consumers = (
        "agile_bounded_partial_runtime.py",
        "agile_solar_headroom_runtime.py",
        "agile_deadline_guard_runtime.py",
        "agile_economic_opportunity_runtime.py",
        "agile_event_priority_runtime.py",
        "agile_deadline_plan_reconciliation.py",
    )

    for filename in consumers:
        source = (KEMS / filename).read_text(encoding="utf-8")
        assert "from . import agile_alpha717_dispatch as alpha717" in source


def test_settlement_dispatch_behavior_contract_is_preserved() -> None:
    source = DISPATCH_RUNTIME.read_text(encoding="utf-8")

    for token in (
        'mode = "maximum_discharge"',
        'mode = "deadline_following"',
        "total_target_kw = effective_kw",
        "total_target_kw - house_kw",
        "config.inverter_limit_kw - house_kw",
        "config.max_discharge_kw - house_kw",
        'slot["rolling_target_battery_export_kw"]',
        '"current simulated half-hour — elapsed-slot average"',
        'attrs["routing_basis"] = "rolling target — current coordinator scan"',
        '{"friendly_name": name, "mode": "simulation_only"}',
    ):
        assert token in source


def test_settlement_dispatch_dashboard_contract_is_preserved() -> None:
    source = DASHBOARD_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "sensor.kems_agile_dispatch_mode",
        "sensor.kems_agile_battery_discharge_target_now",
        "sensor.kems_agile_battery_export_target_now",
        "sensor.kems_agile_dispatch_shortfall_now",
        "Rolling target / simulated power",
        "**Power basis:** battery/grid export use the current rolling target",
    ):
        assert token in source


def test_settlement_dispatch_cannot_enable_hardware_writes() -> None:
    source = "\n".join(
        (
            FACADE.read_text(encoding="utf-8"),
            DISPATCH_RUNTIME.read_text(encoding="utf-8"),
            DASHBOARD_RUNTIME.read_text(encoding="utf-8"),
        )
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source


def test_historical_alpha717_install_order_remains_evidence() -> None:
    source = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")

    assert "install_alpha717_dispatch_patch()" in source
    assert "install_alpha717_dashboard_patch()" in source
    assert source.index("install_dashboard_yaml_guard()") < source.index(
        "install_alpha717_dispatch_patch()"
    )
    assert source.index("install_alpha716_dashboard_patch()") < source.index(
        "install_alpha717_dashboard_patch()"
    )


def test_version_and_historical_alpha717_sources_remain_unchanged() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert HISTORICAL_DISPATCH.is_file()
    assert HISTORICAL_DASHBOARD.is_file()
    assert '"version": "0.8.0-alpha8.' in manifest


def test_settlement_dispatch_docs_record_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "ownership migration only" in source
    assert "7417342ecd5a8ba090a78b56283c8e5607e4a924" in source
    assert "984164ced70196357acf6b85a63e63b07af23c60" in source
    assert "real hardware writes remain blocked" in source
