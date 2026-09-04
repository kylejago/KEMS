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


def test_alpha8_10_release_identity_and_coordinated_versions_survive_later_alpha8() -> (
    None
):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))

    assert str(manifest["version"]).startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert int(str(manifest["version"]).rsplit(".", 1)[1]) >= 10
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    web_versions = {
        str(bundle["components"][key]["version"])
        for key in ("property_web", "pi_agent", "public_web")
    }
    assert len(web_versions) == 1
    web_version = web_versions.pop()
    assert web_version.startswith("0.8.0-alpha8-web.")
    assert int(web_version.rsplit(".", 1)[1]) >= 3


def test_alpha8_10_notes_lock_reconciliation_and_shadow_scope() -> None:
    notes = NOTES.read_text(encoding="utf-8")
    runtime = RECONCILIATION.read_text(encoding="utf-8")
    power_down = POWER_DOWN.read_text(encoding="utf-8")

    assert "0.8.0-alpha8.10" in notes
    assert "0.8.0-alpha8-web.3" in notes
    assert "0.9.0-alpha9-panel.0" in notes
    assert "missing future Agile price" in notes
    assert "current_routing_snapshot" in notes
    assert "planned net site energy" in notes
    assert "import cost minus export income" in notes
    assert "Real hardware writes remain blocked" in notes
    assert ".services.async_call(" not in runtime + power_down
    assert "providers.foxess" not in runtime + power_down
    assert "commands_permitted = True" not in runtime + power_down
