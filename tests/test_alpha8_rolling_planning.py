"""Alpha8 contracts for canonical Alpha7.16 rolling planning ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_rolling_planning.py"
ROLLING_RUNTIME = KEMS / "agile_rolling_replan_runtime.py"
DASHBOARD_RUNTIME = KEMS / "agile_rolling_dashboard_runtime.py"
HISTORICAL_ROLLING = KEMS / "agile_rolling_replan.py"
HISTORICAL_DASHBOARD = KEMS / "agile_alpha716_dashboard.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-rolling-planning-canonicalisation.md"


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


def test_rolling_ownership_retires_alpha716_live_entries() -> None:
    specs = _post_specs()
    rolling = ("agile_rolling_planning", "install_rolling_replan")
    live = ("agile_live_scenario", "install_live_scenario")
    history = ("agile_history_dashboard", "install_history_diagnostics_dashboard")
    dashboard = ("agile_rolling_planning", "install_rolling_dashboard")
    alpha717 = (
        "agile_settlement_dispatch",
        "install_settlement_dispatch_dashboard",
    )

    assert specs[0] == rolling
    assert specs.index(live) == specs.index(rolling) + 1
    assert specs.index(dashboard) == specs.index(history) + 1
    assert specs.index(alpha717) == specs.index(dashboard) + 1
    retired = {"agile_rolling_replan", "agile_alpha716_dashboard"}
    assert not any(module in retired for module, _ in specs)


def test_rolling_runtime_has_explicit_successor_delta_only() -> None:
    runtime = ROLLING_RUNTIME.read_text(encoding="utf-8")
    historical = HISTORICAL_ROLLING.read_text(encoding="utf-8")

    assert ROLLING_RUNTIME.read_bytes() != HISTORICAL_ROLLING.read_bytes()
    assert DASHBOARD_RUNTIME.read_bytes() == HISTORICAL_DASHBOARD.read_bytes()
    assert "settled current-day digital-twin SOC" in runtime
    assert '"arrival_reserve_soc_percent"' in runtime
    assert '"arrival_reserve_policy"' in runtime
    assert "settled current-day digital-twin SOC" not in historical
    assert '"arrival_reserve_soc_percent"' not in historical
    assert 'key=lambda value: value["rate"], reverse=True' in runtime
    assert 'key=lambda value: value["rate"], reverse=True' in historical


def test_facade_binds_only_rolling_legacy_name() -> None:
    source = FACADE.read_text(encoding="utf-8")

    assert '_bind_legacy_name("agile_rolling_replan", rolling_runtime)' in source
    assert "sys.modules[qualified] = module" in source
    assert "setattr(_PACKAGE, name, module)" in source
    assert '".agile_rolling_dashboard_runtime"' in source
    assert '_bind_legacy_name("agile_alpha716_dashboard"' not in source


def test_frozen_consumers_keep_shared_rolling_object() -> None:
    consumers = {
        "agile_alpha717_dispatch.py": (
            "rolling._rolling_plan = rolling_plan_with_alpha717"
        ),
        "agile_bounded_partial_runtime.py": (
            "from . import agile_rolling_replan as rolling"
        ),
        "agile_event_priority_runtime.py": (
            "from . import agile_rolling_replan as rolling"
        ),
    }

    for filename, token in consumers.items():
        source = (KEMS / filename).read_text(encoding="utf-8")
        assert "from . import agile_rolling_replan as rolling" in source
        assert token in source


def test_rolling_behavior_contract_is_preserved() -> None:
    source = ROLLING_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "runtime.ANALYSIS_REFRESH = timedelta(0)",
        "self._kems_live_snapshot = snapshot",
        "PRESSURE_THRESHOLD = 0.75",
        "SAFETY_HEADROOM_MINUTES = 30",
        "protected_house_ac / efficiency",
        '"hold — re-evaluate next KEMS scan"',
        '"planned battery export — rolling replan"',
        '"mode": "simulation_only"',
    ):
        assert token in source


def test_rolling_dashboard_contract_is_preserved() -> None:
    source = DASHBOARD_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "Rolling Agile battery export plan",
        "sensor.kems_agile_rolling_export_plan",
        "sensor.kems_agile_rolling_next_export_slot",
        "sensor.kems_agile_rolling_exportable_energy",
        "sensor.kems_agile_rolling_protected_house_energy",
        "sensor.kems_agile_rolling_capacity_margin",
    ):
        assert token in source


def test_rolling_ownership_cannot_enable_hardware_writes() -> None:
    source = "\n".join(
        (
            FACADE.read_text(encoding="utf-8"),
            ROLLING_RUNTIME.read_text(encoding="utf-8"),
            DASHBOARD_RUNTIME.read_text(encoding="utf-8"),
        )
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source


def test_historical_install_order_remains_evidence() -> None:
    source = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")

    assert "install_rolling_replan_patch()" in source
    assert "install_alpha716_dashboard_patch()" in source
    assert source.index("install_rolling_replan_patch()") < source.index(
        "install_alpha717_dispatch_patch()"
    )
    assert source.index("install_alpha715_dashboard_patch()") < source.index(
        "install_alpha716_dashboard_patch()"
    )


def test_version_and_historical_sources_remain_unchanged() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert HISTORICAL_ROLLING.is_file()
    assert HISTORICAL_DASHBOARD.is_file()
    assert any(
        marker in manifest
        for marker in ('"version": "0.8.0-alpha8.', '"version": "0.9.0-alpha9.')
    )


def test_rolling_docs_record_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "ownership migration only" in source
    assert "b5bfcd1f93f6afea29f71155e49d97af4f074232" in source
    assert "d5ef0f9f8871bb76fe6f2966e284d8d2b6ad771f" in source
    assert "real hardware writes remain blocked" in source
