"""Release contract for the Alpha8.8 retained Happy Hour evidence release."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"
NOTES = ROOT / "docs" / "alpha8.8-release-notes.md"


def test_alpha8_8_release_identity_and_coordinated_versions() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))

    assert manifest["version"] == "0.8.0-alpha8.8"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.2"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.2"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.2"
    reason = bundle["maintenance"]["reason"]
    assert "automatic Octopus Weekend Happy Hour discovery" in reason
    assert "selectable shadow EV charging policy" in reason


def test_alpha8_8_notes_lock_retention_and_safety_scope() -> None:
    text = NOTES.read_text(encoding="utf-8")

    assert "0.8.0-alpha8.8" in text
    assert "durable storage" in text
    assert "retained_completed" in text
    assert "Ambiguous live Power Up data" in text
    assert "newer current/future manual Happy Hour" in text
    assert "35 days" in text
    assert "0.8.0-alpha8-web.2` (unchanged)" in text
    assert "0.8.0-alpha8-panel.1` (unchanged)" in text
    assert "no Home Assistant service call to Octopus or Ohme" in text
    assert "no FoxESS hardware write" in text
    assert "Real hardware writes remain blocked" in text
