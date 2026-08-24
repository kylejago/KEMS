"""Alpha8.9 decision-evidence contracts retained by later Alpha8 releases."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"
NOTES = ROOT / "docs" / "alpha8.9-release-notes.md"
EVIDENCE = ROOT / "custom_components" / "kems" / "agile_decision_evidence.py"


def test_alpha8_9_truth_contract_survives_later_alpha8_releases() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))

    assert str(manifest["version"]).startswith("0.8.0-alpha8.")
    assert int(str(manifest["version"]).rsplit(".", 1)[1]) >= 9
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    web_versions = {
        bundle["components"]["property_web"]["version"],
        bundle["components"]["pi_agent"]["version"],
        bundle["components"]["public_web"]["version"],
    }
    assert len(web_versions) == 1
    assert next(iter(web_versions)).startswith("0.8.0-alpha8-web.")


def test_alpha8_9_notes_lock_truth_and_shadow_scope() -> None:
    text = NOTES.read_text(encoding="utf-8")
    source = EVIDENCE.read_text(encoding="utf-8")

    assert "0.8.0-alpha8.9" in text
    assert "No KEMS decision recorded — runtime/data gap" in text
    assert "No retained KEMS sample" in text
    assert "Recorded simulation" in text
    assert "Live rolling plan" in text
    assert "23 August 2026" in text
    assert "0.8.0-alpha8-web.2` (unchanged)" in text
    assert "0.8.0-alpha8-panel.1` (unchanged)" in text
    assert "Real hardware writes remain blocked" in text
    assert "No KEMS decision recorded — runtime/data gap" in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
