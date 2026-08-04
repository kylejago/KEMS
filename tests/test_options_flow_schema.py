"""Regression tests for the Home Assistant options-flow schema."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
CONFIG_FLOW = ROOT / "custom_components" / "kems" / "config_flow.py"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"


def test_options_flow_uses_serializable_date_selector() -> None:
    """The UI schema must use a selector rather than an unsupported regex."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")

    assert "DateSelector" in source
    assert "vol.Match" not in source
    assert "vol.Optional(CONF_COMMISSIONING_DATE): DateSelector()" in source


def test_manifest_stays_a_hub() -> None:
    """KEMS must remain listed under Integrations rather than Helpers."""
    source = MANIFEST.read_text(encoding="utf-8")

    assert '"integration_type": "hub"' in source
    assert '"version": "0.6.0-beta1"' in source


def test_options_flow_includes_kh7_inverter_limit_and_paced_strategy() -> None:
    """The settings form must expose the physical and strategy assumptions."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    assert "CONF_INVERTER_LIMIT" in source
    assert '"paced_export"' in source
    assert "VERSION = 9" in source


def test_options_flow_includes_power_down_sources_and_toggle() -> None:
    """Power Down sources and planning toggle must be configurable."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    assert "CONF_SAVING_SESSION_EVENTS" in source
    assert "CONF_SAVING_SESSION_IMPORT_BASELINE" in source
    assert "CONF_SAVING_SESSION_EXPORT_BASELINE" in source
    assert "CONF_SAVING_SESSION_ENABLED" in source
    assert "EVENT_SELECTOR" in source
