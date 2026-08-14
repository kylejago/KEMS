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
    assert '"version": "0.7.0-alpha6"' in source


def test_options_flow_includes_kh7_inverter_limit_and_paced_strategy() -> None:
    """The settings form must expose the physical and strategy assumptions."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    assert "CONF_INVERTER_LIMIT" in source
    assert "CONF_SITE_IMPORT_LIMIT" in source
    assert '"paced_export"' in source
    assert "VERSION = 13" in source


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


def test_options_flow_has_friendly_category_menu_and_tariff_editor() -> None:
    """Users should configure KEMS through small named pages, not one huge form."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    for token in (
        "MENU_OPTIONS = {",
        '"tariff"',
        '"battery"',
        '"solar"',
        '"financial"',
        '"monitoring"',
        '"control"',
        "CONF_TARIFF_MODE",
        "CONF_MANUAL_DAY_RATE",
        "CONF_MANUAL_OFFPEAK_RATE",
        "CONF_MANUAL_STANDING_CHARGE",
        "CONF_MANUAL_OFFPEAK_START",
        "CONF_MANUAL_OFFPEAK_END",
        "TIME_SELECTOR",
        "async_show_menu",
    ):
        assert token in source


def test_options_menu_has_explicit_fallback_labels() -> None:
    """Menu labels must not disappear when frontend translations are stale."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")

    for label in (
        "Tariff and prices",
        "Battery, inverter and grid limits",
        "Solar, export and Power Down",
        "System cost and ROI",
        "Monitoring and history",
        "Control Lab and EPS safety",
    ):
        assert label in source

    assert "menu_options=self.MENU_OPTIONS" in source


def test_manual_setup_can_run_without_live_import_rate_entity() -> None:
    """Friends and family must be able to use a fully manual tariff."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    assert 'manual = self._initial_options[CONF_TARIFF_MODE] == "manual"' in source
    assert "require_import_rate=not manual" in source
    assert "MANUAL_TARIFF_SCHEMA" in source
    assert "options=self._initial_options" in source


def test_number_selectors_use_home_assistant_supported_steps() -> None:
    """Number selector steps must be 'any' or at least 0.001 in HA 2026.8."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")

    assert 'step: float | Literal["any"]' in source
    assert "0.0001" not in source
    assert '_number(0, 200, "any", "p/kWh")' in source
    assert '_number(1, 20, "any", "kWh/m³")' in source


def test_alpha5_tariff_page_exposes_export_tariff_status() -> None:
    """The user can switch between awaiting and active export tariff states."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    assert "CONF_EXPORT_TARIFF_STATUS" in source
    assert "Not active / awaiting export tariff" in source
    assert "Active - export is paid" in source
