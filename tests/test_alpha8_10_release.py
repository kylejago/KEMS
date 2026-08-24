"""Coordinated release contract for KEMS Alpha8.10 / Web.3."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"
NOTES = ROOT / "docs" / "alpha8.10-release-notes.md"
RECONCILIATION = ROOT / "custom_components" / "kems" / "agile_runtime_reconciliation.py"
POWER_DOWN = ROOT / "custom_components" / "kems" / "power_down.py"


def test_alpha8_10_release_identity_and_coordinated_versions() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))

    assert manifest["version"] == "0.8.0-alpha8.10"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.3"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.3"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.3"
    assert bundle["maintenance"]["affected_components"] == [
        "kems_core",
        "dashboard",
        "panel",
        "property_web",
        "pi_agent",
        "public_web",
    ]
    reason = bundle["maintenance"]["reason"]
    assert "Power Down shadow accounting" in reason
    assert "automatic Octopus Weekend Happy Hour discovery" in reason
    assert "selectable shadow EV charging policy" in reason


def test_alpha8_10_notes_lock_reconciliation_and_shadow_scope() -> None:
    notes = NOTES.read_text(encoding="utf-8")
    runtime = RECONCILIATION.read_text(encoding="utf-8")
    power_down = POWER_DOWN.read_text(encoding="utf-8")

    assert "0.8.0-alpha8.10" in notes
    assert "0.8.0-alpha8-web.3" in notes
    assert "0.8.0-alpha8-panel.1" in notes
    assert "missing future Agile price" in notes
    assert "current_routing_snapshot" in notes
    assert "planned net site energy" in notes
    assert "import cost minus export income" in notes
    assert "Real hardware writes remain blocked" in notes
    assert ".services.async_call(" not in runtime + power_down
    assert "providers.foxess" not in runtime + power_down
    assert "commands_permitted = True" not in runtime + power_down
