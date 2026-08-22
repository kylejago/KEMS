"""Release-note guards for the current KEMS HA maintenance release."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
NOTES = ROOT / "docs" / "alpha8.1-release-notes.md"


def test_alpha8_1_notes_keep_web_and_panel_versions_unchanged() -> None:
    text = NOTES.read_text(encoding="utf-8")

    assert "0.8.0-alpha8.1" in text
    assert "0.8.0-alpha8-web.0` (unchanged)" in text
    assert "0.8.0-alpha8-panel.0` (unchanged)" in text
    assert "Hardware writes remain" in text
