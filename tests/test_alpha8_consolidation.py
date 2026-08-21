"""Alpha8 coordinated consolidation contracts.

These tests make Alpha8.0 a refactor/parity release: the proven Alpha7.52
behaviour is kept behind one frozen boundary while new version-named runtime
patches are prohibited.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _compat_specs() -> list[tuple[str, str]]:
    source = (KEMS / "agile_alpha7_compat.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    specs: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id not in {"PRE_BASE_PATCHES", "POST_BASE_PATCHES"}:
            continue
        assert isinstance(node.value, ast.Tuple)
        for item in node.value.elts:
            assert isinstance(item, ast.Tuple) and len(item.elts) == 2
            module = ast.literal_eval(item.elts[0])
            installer = ast.literal_eval(item.elts[1])
            specs.append((module, installer))
    return specs


def test_alpha8_release_family_is_coordinated() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release/kems-bundle.template.json").read_text(encoding="utf-8")
    )
    panel_manager = (KEMS / "panel.py").read_text(encoding="utf-8")
    panel_yaml = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")

    assert manifest["version"] == "0.8.0-alpha8.0"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.0"
    assert {
        bundle["components"]["property_web"]["version"],
        bundle["components"]["pi_agent"]["version"],
        bundle["components"]["public_web"]["version"],
    } == {"0.8.0-alpha8-web.0"}
    assert 'PANEL_CONFIG_VERSION = "0.8.0-alpha8-panel.0"' in panel_manager
    assert 'panel_config_version: "0.8.0-alpha8-panel.0"' in panel_yaml


def test_runtime_entrypoint_has_one_alpha7_compatibility_boundary() -> None:
    runtime = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")
    assert "install_alpha7_compatibility" in runtime
    assert "agile_alpha7_compat" in runtime
    assert not re.search(r"from \.agile_alpha7\d+", runtime)
    assert not re.search(r"install_alpha7\d+", runtime)


def test_frozen_alpha7_compatibility_registry_is_complete_and_resolvable() -> None:
    specs = _compat_specs()
    assert specs
    assert len(specs) == len(
        set(specs)
    ), "Alpha7 compatibility installers must be unique"
    assert specs[0] == ("agile_smart_export_reporting", "install_reporting_patch")
    assert specs[-1] == (
        "agile_alpha752_tomorrow_no_reserve_rounding",
        "install_alpha752_tomorrow_no_reserve_rounding_patch",
    )

    for module_name, installer_name in specs:
        path = KEMS / f"{module_name}.py"
        assert path.is_file(), f"Missing frozen compatibility module {module_name}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert installer_name in functions, f"{module_name} is missing {installer_name}"


def test_alpha8_does_not_restart_version_named_patch_debt() -> None:
    offenders = sorted(path.name for path in KEMS.glob("agile_alpha8*.py"))
    assert offenders == [], (
        "Alpha8 behaviour belongs in canonical Agile modules, not another "
        f"version-named patch chain: {offenders}"
    )


def test_alpha8_is_newer_than_the_frozen_alpha7_baseline() -> None:
    source = (KEMS / "versioning.py").read_text(encoding="utf-8")
    namespace: dict[str, object] = {}
    exec(compile(source, "versioning.py", "exec"), namespace)
    relation = namespace["version_relation"]
    assert callable(relation)
    assert relation("0.8.0-alpha8.0", "0.7.0-alpha7.52") == 1
