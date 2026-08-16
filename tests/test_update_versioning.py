"""Regression tests for KEMS coordinated-update release ordering."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
VERSIONING = ROOT / "custom_components" / "kems" / "versioning.py"
ORCHESTRATOR = ROOT / "custom_components" / "kems" / "update_orchestrator.py"

spec = importlib.util.spec_from_file_location("kems_update_versioning", VERSIONING)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_kems_release_order_handles_alpha_progression() -> None:
    """Alpha releases and alpha point releases must order numerically."""
    assert module.version_relation("0.7.0-alpha7", "0.7.0-alpha6") == 1
    assert module.version_relation("0.7.0-alpha6", "0.7.0-alpha7") == -1
    assert module.version_relation("0.7.0-alpha7.1", "0.7.0-alpha7") == 1
    assert module.version_relation("v0.7.0-alpha8", "0.7.0-alpha7.9") == 1


def test_kems_release_order_handles_promotion_to_stable() -> None:
    """beta, rc and stable releases must sort after earlier prerelease stages."""
    assert module.version_relation("0.7.0-beta1", "0.7.0-alpha99") == 1
    assert module.version_relation("0.7.0-rc1", "0.7.0-beta9") == 1
    assert module.version_relation("0.7.0", "0.7.0-rc99") == 1


def test_unknown_versions_are_not_guessed() -> None:
    """Commit SHAs or unknown labels must not be ordered as software releases."""
    assert module.version_relation("adf5893835", "0.7.0-alpha7") is None
    assert not module.version_is_newer("adf5893835", "0.7.0-alpha7")


def test_orchestrator_uses_running_version_and_downgrade_guards() -> None:
    """Fallback discovery and persisted pending work must never cause a downgrade."""
    content = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "version_is_newer(latest, running)" in content
    assert "Ignoring older KEMS bundle target" in content
    assert "Clearing stale KEMS update target" in content
    assert '"ahead-of-target"' in content
