"""Regression guards for release identity and canonical Alpha8 source names."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
MANIFEST = INTEGRATION / "manifest.json"
CONST = INTEGRATION / "const.py"
ENTITY = INTEGRATION / "entity.py"


def test_manifest_is_the_only_literal_runtime_release_identity() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    version = str(manifest["version"])
    const_lines = CONST.read_text(encoding="utf-8").splitlines()

    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert not any(line.startswith("VERSION =") for line in const_lines)
    entity = ENTITY.read_text(encoding="utf-8")
    assert 'with_name("manifest.json")' in entity
    assert "sw_version=INTEGRATION_VERSION" in entity


def test_new_alpha8_runtime_files_are_functionally_named() -> None:
    version_named = sorted(path.name for path in INTEGRATION.glob("*alpha8*.py"))
    assert version_named == []

    assert (INTEGRATION / "agile_forecast_arbitrage.py").is_file()
    assert (INTEGRATION / "agile_simulation_presentation.py").is_file()
