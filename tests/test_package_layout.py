"""Regression tests for the HACS package layout."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def test_all_runtime_code_is_inside_integration_directory() -> None:
    """HACS only installs the integration directory."""
    assert not (ROOT / "kems_core").exists()
    assert (INTEGRATION / "kems_core" / "models.py").is_file()
    assert (INTEGRATION / "providers" / "foxess.py").is_file()
    assert (INTEGRATION / "entity_discovery.py").is_file()


def test_no_absolute_kems_core_imports_in_runtime_code() -> None:
    """Runtime modules must use package-relative imports."""
    offenders: list[str] = []

    for path in INTEGRATION.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "kems_core" for alias in node.names
            ):
                offenders.append(f"{path}: import kems_core")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and (node.module or "").startswith("kems_core")
            ):
                offenders.append(f"{path}: from {node.module} import ...")

    assert offenders == []


def test_repository_contains_no_python_cache_files() -> None:
    """Compiled cache files must never be shipped through HACS."""
    assert list(INTEGRATION.rglob("*.pyc")) == []
    assert [path for path in INTEGRATION.rglob("__pycache__") if path.is_dir()] == []


def test_all_relative_runtime_imports_resolve_to_source_files() -> None:
    """Every package-relative runtime import must point to a shipped module."""
    missing: list[str] = []

    for path in INTEGRATION.rglob("*.py"):
        relative = path.relative_to(INTEGRATION).with_suffix("")
        parts = list(relative.parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()

        module_name = ".".join(["custom_components", "kems", *parts])
        package_name = module_name if is_package else module_name.rpartition(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue

            relative_name = f"{'.' * node.level}{node.module or ''}"
            target = importlib.util.resolve_name(relative_name, package_name)
            prefix = "custom_components.kems"
            if target == prefix:
                continue
            if not target.startswith(f"{prefix}."):
                missing.append(f"{path}:{node.lineno} resolves outside KEMS: {target}")
                continue

            target_parts = target.split(".")[2:]
            module_path = INTEGRATION.joinpath(*target_parts).with_suffix(".py")
            package_path = INTEGRATION.joinpath(*target_parts, "__init__.py")
            if not module_path.is_file() and not package_path.is_file():
                missing.append(f"{path}:{node.lineno} missing target: {target}")

    assert missing == []
