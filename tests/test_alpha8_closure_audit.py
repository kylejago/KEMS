"""Alpha8 closure audit for residual historical Agile imports."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-closure-audit.md"

_VERSIONED = re.compile(r"^agile_alpha7\d.*$")
_BRIDGE_OWNERS = {
    "agile_alpha728_bounded_partial": "agile_bounded_partial_runtime",
    "agile_alpha734_deadline_guard": "agile_deadline_guard_runtime",
    "agile_alpha741_partial_publication": "agile_price_publication_runtime",
}


def _is_historical(path: Path) -> bool:
    return _VERSIONED.fullmatch(path.stem) is not None


def _canonical_python_files() -> list[Path]:
    return sorted(path for path in KEMS.glob("*.py") if not _is_historical(path))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _versioned_imports(path: Path) -> set[str]:
    """Return historical Alpha7 module names imported by one canonical file."""
    result: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                candidate = node.module.rsplit(".", 1)[-1]
                if _VERSIONED.fullmatch(candidate):
                    result.add(candidate)
            for alias in node.names:
                candidate = alias.name.rsplit(".", 1)[-1]
                if _VERSIONED.fullmatch(candidate):
                    result.add(candidate)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                candidate = alias.name.rsplit(".", 1)[-1]
                if _VERSIONED.fullmatch(candidate):
                    result.add(candidate)
    return result


def _module_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        if node.module is not None:
            continue
        for alias in node.names:
            aliases[alias.asname or alias.name] = alias.name
    return aliases


def _versioned_bridges() -> dict[str, tuple[Path, str]]:
    """Map each explicit historical name to its canonical imported runtime."""
    bridges: dict[str, tuple[Path, str]] = {}
    for path in _canonical_python_files():
        tree = _tree(path)
        aliases = _module_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 2:
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr if isinstance(function, ast.Attribute) else None
            )
            if name != "_bind_legacy_name":
                continue
            legacy_arg, runtime_arg = node.args[:2]
            if not isinstance(legacy_arg, ast.Constant) or not isinstance(
                legacy_arg.value, str
            ):
                continue
            legacy = legacy_arg.value
            if _VERSIONED.fullmatch(legacy) is None:
                continue
            assert isinstance(
                runtime_arg, ast.Name
            ), f"{path.name}: versioned bridge target must be an imported module name"
            runtime_module = aliases.get(runtime_arg.id)
            assert (
                runtime_module is not None
            ), f"{path.name}: cannot resolve bridge target {runtime_arg.id}"
            assert legacy not in bridges, f"Duplicate versioned bridge for {legacy}"
            bridges[legacy] = (path, runtime_module)
    return bridges


def _compat_specs() -> list[tuple[str, str]]:
    tree = _tree(COMPAT)
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


def test_every_residual_versioned_import_has_an_explicit_canonical_bridge() -> None:
    bridges = _versioned_bridges()
    references = {
        path.name: sorted(imports)
        for path in _canonical_python_files()
        if (imports := _versioned_imports(path))
    }
    assert references, "Audit should still see frozen historical import references"

    missing = {
        module
        for imports in references.values()
        for module in imports
        if module not in bridges
    }
    assert missing == set(), (
        "Canonical/frozen code imports historical Alpha7 module names that are not "
        f"redirected to canonical runtime objects: {sorted(missing)}; refs={references}"
    )


def test_every_versioned_bridge_points_to_byte_identical_historical_runtime() -> None:
    bridges = _versioned_bridges()
    assert bridges
    for legacy, (owner, runtime_module) in bridges.items():
        historical = KEMS / f"{legacy}.py"
        runtime = KEMS / f"{runtime_module}.py"
        assert historical.is_file(), f"Missing historical evidence for {legacy}"
        assert (
            runtime.is_file()
        ), f"{owner.name} bridge target is missing: {runtime_module}"
        assert runtime.read_bytes() == historical.read_bytes(), (
            f"{owner.name}: {legacy} must resolve to an exact historical runtime copy, "
            f"not a behavioural rewrite ({runtime_module})"
        )


def test_frozen_runtimes_with_versioned_imports_remain_historical_blobs() -> None:
    historical_blobs = {
        path.read_bytes()
        for path in KEMS.glob("agile_alpha7*.py")
        if _is_historical(path)
    }
    audited = []
    for path in _canonical_python_files():
        imports = _versioned_imports(path)
        if not imports or not path.name.endswith("_runtime.py"):
            continue
        audited.append(path.name)
        assert path.read_bytes() in historical_blobs, (
            f"{path.name} imports historical names but is not byte-identical to any "
            "packaged Alpha7 evidence module"
        )
    assert audited


def test_newly_repaired_identity_bridges_are_present_and_ordered() -> None:
    bridges = _versioned_bridges()
    for legacy, runtime in _BRIDGE_OWNERS.items():
        assert legacy in bridges
        assert bridges[legacy][1] == runtime

    specs = _compat_specs()
    bounded = ("agile_bounded_partial", "install_bounded_partial_horizon")
    price_publication = ("agile_price_publication", "install_price_publication")
    deadline_guard = ("agile_deadline_guard", "install_deadline_guard")
    deadline_reconcile = (
        "agile_deadline_plan_reconciliation",
        "install_deadline_plan_coverage",
    )
    reporting = ("agile_publication_reporting", "install_no_reserve_reporting")

    assert specs.index(bounded) < specs.index(price_publication)
    assert specs.index(deadline_guard) < specs.index(deadline_reconcile)
    assert specs.index(price_publication) < specs.index(reporting)


def test_closure_audit_does_not_change_release_or_hardware_write_boundary() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == "0.8.0-alpha8.0"

    for name in (
        "agile_bounded_partial.py",
        "agile_deadline_guard.py",
        "agile_price_publication.py",
    ):
        source = (KEMS / name).read_text(encoding="utf-8")
        assert ".services.async_call(" not in source
        assert "providers.foxess" not in source
        assert "safe_to_write_hardware = True" not in source
        assert "commands_permitted = True" not in source

    assert sorted(path.name for path in KEMS.glob("agile_alpha8*.py")) == []


def test_closure_audit_documentation_records_the_repaired_residuals() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "3cc55f374e03f326211f743ac5b2f2a0eecd09fc" in source
    assert "agile_alpha728_bounded_partial" in source
    assert "agile_alpha734_deadline_guard" in source
    assert "agile_alpha741_partial_publication" in source
    assert "b6b06ecea370050eb663a5bf03baf53d6e4d401c" in source
    assert "e4423b3bf55a64f91baaa07fc72eaa4f54ce38cf" in source
    assert "5321a95a4954a47ba6eb8511c41f44c2aed8fdfd" in source
    assert "zero accidental residual historical dependencies" in source
    assert "real hardware writes remain blocked" in source
