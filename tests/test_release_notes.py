"""Release-note guards for KEMS HA maintenance releases."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
ALPHA8_1_NOTES = ROOT / "docs" / "alpha8.1-release-notes.md"
ALPHA8_2_NOTES = ROOT / "docs" / "alpha8.2-release-notes.md"
ALPHA8_3_NOTES = ROOT / "docs" / "alpha8.3-release-notes.md"


def test_alpha8_1_notes_remain_historical_release_evidence() -> None:
    text = ALPHA8_1_NOTES.read_text(encoding="utf-8")

    assert "0.8.0-alpha8.1" in text
    assert "0.8.0-alpha8-web.0` (unchanged)" in text
    assert "0.8.0-alpha8-panel.0` (unchanged)" in text
    assert "Hardware writes remain" in text


def test_alpha8_2_notes_describe_coordination_only_web_update() -> None:
    text = ALPHA8_2_NOTES.read_text(encoding="utf-8")

    assert "0.8.0-alpha8.2" in text
    assert "coordination-only maintenance release" in text
    assert "0.8.0-alpha8-web.1" in text
    assert "0.8.0-alpha8-panel.0` (unchanged)" in text
    assert "does not add a new Home Assistant runtime behaviour" in text
    assert "Hardware writes remain blocked" in text


def test_alpha8_3_notes_lock_agile_policy_and_reconciliation_scope() -> None:
    text = ALPHA8_3_NOTES.read_text(encoding="utf-8")

    assert "0.8.0-alpha8.3" in text
    assert "100%" in text
    assert "10%" in text
    assert "23:30–05:30" in text
    assert "automatically turns off" in text
    assert "0.8.0-alpha8-web.1` (unchanged)" in text
    assert "0.8.0-alpha8-panel.0` (unchanged)" in text
    assert "Real FoxESS hardware writes remain blocked" in text
