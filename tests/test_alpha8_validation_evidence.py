"""Alpha8 contracts for canonical Alpha7.19 validation-evidence ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_validation_evidence.py"
VALIDATION_RUNTIME = KEMS / "agile_validation_evidence_runtime.py"
DASHBOARD_RUNTIME = KEMS / "agile_validation_dashboard_runtime.py"
HISTORICAL_VALIDATION = KEMS / "agile_alpha719_validation.py"
HISTORICAL_DASHBOARD = KEMS / "agile_alpha719_dashboard.py"
PROVISIONAL_RUNTIME = KEMS / "agile_provisional_planning_runtime.py"
HISTORICAL_LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-validation-evidence-canonicalisation.md"


def _compat_specs() -> list[tuple[str, str]]:
    tree = ast.parse(COMPAT.read_text(encoding="utf-8"))
    specs: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
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


def test_validation_evidence_retires_alpha719_from_execution() -> None:
    specs = _compat_specs()
    alpha717 = ("agile_alpha717_dashboard", "install_alpha717_dashboard_patch")
    validation = ("agile_validation_evidence", "install_validation_evidence")
    consolidation = ("dashboard_consolidation", "install_dashboard_consolidation")
    dashboard = ("agile_validation_evidence", "install_validation_dashboard")
    alpha720 = ("agile_preinstall_evidence", "install_preinstall_evidence")

    assert specs.index(alpha717) < specs.index(validation)
    assert specs.index(validation) < specs.index(consolidation)
    assert specs.index(consolidation) < specs.index(dashboard)
    assert specs.index(dashboard) < specs.index(alpha720)

    retired = {"agile_alpha719_validation", "agile_alpha719_dashboard"}
    assert not any(module_name in retired for module_name, _ in specs)
    assert HISTORICAL_VALIDATION.is_file()
    assert HISTORICAL_DASHBOARD.is_file()


def test_validation_evidence_runtimes_are_byte_identical() -> None:
    assert VALIDATION_RUNTIME.read_bytes() == HISTORICAL_VALIDATION.read_bytes()
    assert DASHBOARD_RUNTIME.read_bytes() == HISTORICAL_DASHBOARD.read_bytes()


def test_validation_evidence_facade_bridges_frozen_import_names() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    assert '"agile_alpha719_validation", validation_runtime' in source
    assert '"agile_alpha719_dashboard", dashboard_runtime' in source
    assert "validation_runtime.install_alpha719_validation_patch()" in source
    assert "dashboard_runtime.install_alpha719_dashboard_patch()" in source


def test_frozen_provisional_runtime_mutates_bridged_alpha719_objects() -> None:
    facade = FACADE.read_text(encoding="utf-8")
    provisional = PROVISIONAL_RUNTIME.read_text(encoding="utf-8")

    assert "from . import agile_alpha719_dashboard as alpha719_dashboard" in provisional
    assert (
        "from . import agile_alpha719_validation as alpha719_validation" in provisional
    )
    assert "current_audit = alpha719_validation._decision_audit" in provisional
    assert (
        "alpha719_validation._decision_audit = _decision_audit_with_provisional"
        in provisional
    )
    assert "current_trajectory = alpha719_validation._soc_trajectory" in provisional
    assert (
        "alpha719_validation._soc_trajectory = _soc_trajectory_with_provisional"
        in provisional
    )
    assert "alpha719_dashboard._AGILE_CARDS = _ALPHA726_AGILE_CARDS" in provisional
    assert (
        '_bind_legacy_name("agile_alpha719_validation", validation_runtime)' in facade
    )
    assert '_bind_legacy_name("agile_alpha719_dashboard", dashboard_runtime)' in facade


def test_validation_runtime_preserves_evidence_and_soc_contract() -> None:
    source = VALIDATION_RUNTIME.read_text(encoding="utf-8")

    for token in (
        'for key in ("7_days", "30_days", "365_days")',
        'period["authoritative"] = complete',
        '"agile_advantage_pence": None',
        '"period": "hour"',
        '"direct_path_ready": not missing',
        "sensor.kems_agile_decision_audit",
        "sensor.kems_agile_soc_trajectory",
        '"source": "rolling_replan_conservative"',
        "Future solar is not pre-spent",
        '"mode": "simulation_only"',
    ):
        assert token in source


def test_validation_dashboard_preserves_five_validation_card_groups() -> None:
    source = DASHBOARD_RUNTIME.read_text(encoding="utf-8")

    for token in (
        '_inject_after_cards(content, "live", _LIVE_CARD)',
        '_inject_after_cards(content, "plan", _PLAN_CARD)',
        '_inject_after_cards(content, "agile", _AGILE_CARDS)',
        '_inject_after_cards(content, "history", _HISTORY_CARD)',
        '_inject_after_cards(content, "control", _CONTROL_CARDS)',
        "Actual → Target → Difference readiness",
        "Shadow-control validation",
    ):
        assert token in source


def test_validation_evidence_keeps_hardware_control_blocked() -> None:
    validation = VALIDATION_RUNTIME.read_text(encoding="utf-8").lower()
    dashboard = DASHBOARD_RUNTIME.read_text(encoding="utf-8").lower()
    facade = FACADE.read_text(encoding="utf-8").lower()
    source = "\n".join((validation, dashboard, facade))

    assert '"recorder",\n            "get_statistics"' in validation
    assert "foxess_modbus.write" not in source
    assert 'hass.services.async_call("foxess' not in source
    assert "hass.services.async_call('foxess'" not in source
    assert "commands_permitted = true" not in source
    assert "safe_to_write_hardware = true" not in source
    assert "zero inverter writes" in dashboard


def test_alpha720_canonicalisation_remains_downstream_of_validation() -> None:
    specs = _compat_specs()
    validation_dashboard = (
        "agile_validation_evidence",
        "install_validation_dashboard",
    )
    preinstall = ("agile_preinstall_evidence", "install_preinstall_evidence")
    dashboard = ("agile_preinstall_evidence", "install_preinstall_dashboard")

    assert specs.index(validation_dashboard) < specs.index(preinstall)
    assert specs.index(dashboard) == specs.index(preinstall) + 1


def test_historical_metadata_and_alpha8_version_remain_unchanged() -> None:
    loader = HISTORICAL_LOADER.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert "install_alpha719_validation_patch" in loader
    assert "install_alpha719_dashboard_patch" in loader
    assert "ALPHA7_COMPATIBILITY_ORDER" in loader
    assert '"version": "0.8.0-alpha8.0"' in manifest


def test_validation_evidence_documentation_records_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "ownership migration only" in source
    assert "ed35ca4347d7d02892e31f11821f02678786deb2" in source
    assert "34462b34777116a386d4cc932eed1c0f14c54a93" in source
    assert "No runtime body is rewritten" in source
    assert "Alpha7.20 remains historical live ownership" in source
    assert "real hardware writes remain blocked" in source
