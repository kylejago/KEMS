"""Alpha8 contracts for live-registry closure and dashboard ownership."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
DASHBOARD = KEMS / "dashboard_consolidation.py"
HISTORICAL_LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-live-registry-closure.md"


def _registry(name: str) -> list[tuple[str, str]]:
    tree = ast.parse(COMPAT.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != name:
            continue
        assert isinstance(node.value, ast.Tuple)
        return [
            (ast.literal_eval(item.elts[0]), ast.literal_eval(item.elts[1]))
            for item in node.value.elts
            if isinstance(item, ast.Tuple) and len(item.elts) == 2
        ]
    raise AssertionError(f"{name} was not found")


def test_live_registries_have_no_version_named_alpha7_runtime_modules() -> None:
    specs = _registry("PRE_BASE_PATCHES") + _registry("POST_BASE_PATCHES")

    assert specs
    offenders = [
        module
        for module, _ in specs
        if re.fullmatch(r"agile_alpha7\d.*", module) is not None
    ]
    assert offenders == []


def test_dashboard_consolidation_remains_the_existing_functional_owner() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    ast.parse(source)

    assert "def consolidate_dashboard(content: str) -> str:" in source
    assert "def install_dashboard_consolidation() -> None:" in source
    assert "from . import dashboard as dashboard_module" in source
    assert "dashboard_module._combined_master_dashboard_bytes" in source
    assert "_kems_dashboard_consolidated" in source
    assert "sys.modules" not in source
    assert "agile_alpha7" not in source


def test_dashboard_consolidation_keeps_its_exact_registry_position() -> None:
    specs = _registry("POST_BASE_PATCHES")
    evidence = ("agile_validation_evidence", "install_validation_evidence")
    consolidation = ("dashboard_consolidation", "install_dashboard_consolidation")
    dashboard = ("agile_validation_evidence", "install_validation_dashboard")

    assert specs.index(consolidation) == specs.index(evidence) + 1
    assert specs.index(dashboard) == specs.index(consolidation) + 1


def test_registry_closure_preserves_history_version_and_hardware_boundary() -> None:
    loader = HISTORICAL_LOADER.read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert "ALPHA7_COMPATIBILITY_ORDER" in loader
    assert "install_dashboard_consolidation()" in loader
    assert manifest["version"] == "0.8.0-alpha8.0"
    assert list(KEMS.glob("agile_alpha7*.py"))

    assert ".services.async_call(" not in dashboard
    assert "providers.foxess" not in dashboard
    assert "safe_to_write_hardware = True" not in dashboard
    assert "commands_permitted = True" not in dashboard


def test_registry_closure_documentation_records_no_runtime_migration() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "registry closure" in source
    assert "518e45cf6b0a8474f7e5f33eb76a0bf8027104aa" in source
    assert "e17b3d182c43c053a89a27d4812d1b35f2adb50f" in source
    assert "26a965828995598f3965065132041d8452a08ecb" in source
    assert "No dashboard runtime is copied, renamed or wrapped" in source
    assert "real hardware writes remain blocked" in source
