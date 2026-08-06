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
    assert '"version": "0.7.0-alpha3"' in source


def test_options_flow_includes_kh7_inverter_limit_and_paced_strategy() -> None:
    """The settings form must expose the physical and strategy assumptions."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    assert "CONF_INVERTER_LIMIT" in source
    assert "CONF_SITE_IMPORT_LIMIT" in source
    assert '"paced_export"' in source
    assert "VERSION = 11" in source


def test_options_flow_includes_power_down_sources_and_toggle() -> None:
    """Power Down sources and planning toggle must be configurable."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    assert "CONF_SAVING_SESSION_EVENTS" in source
    assert "CONF_SAVING_SESSION_IMPORT_BASELINE" in source
    assert "CONF_SAVING_SESSION_EXPORT_BASELINE" in source
    assert "CONF_SAVING_SESSION_ENABLED" in source
    assert "EVENT_SELECTOR" in source


def test_options_flow_includes_control_lab_and_island_safety_settings() -> None:
    """The pre-installation lab must expose modes, scenarios, and safeguards."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    for token in (
        "CONF_OPERATING_MODE",
        "CONF_VIRTUAL_SCENARIO",
        "CONF_CONTROL_ENABLED",
        "CONF_SYSTEM_COMMISSIONED",
        "CONF_EMERGENCY_STOP",
        "CONF_GRID_STABILITY_SECONDS",
        "CONF_EPS_LIMIT",
        "CONF_ISLAND_RESERVE_PERCENT",
        '"grid_outage_daylight"',
        '"grid_outage_night"',
        '"grid_outage_high_load"',
    ):
        assert token in source


def test_site_import_limit_is_an_option_not_a_source_mapping() -> None:
    """The fuse/gateway limit must not be counted as a discovered entity."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    provider_block = source[
        source.index("provider_counts = {") : source.index(
            "return self.async_show_form",
            source.index("provider_counts = {"),
        )
    ]

    assert "CONF_SITE_IMPORT_LIMIT" not in provider_block
