"""Regression tests for KH7 runtime option safety."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
SETTINGS = ROOT / "custom_components" / "kems" / "settings.py"
CONST = ROOT / "custom_components" / "kems" / "const.py"


def test_legacy_options_are_clamped_to_kh7_paced_export() -> None:
    """Runtime safety must work even before Home Assistant persists migration."""
    settings_source = SETTINGS.read_text(encoding="utf-8")
    const_source = CONST.read_text(encoding="utf-8")

    assert 'CONF_INVERTER_LIMIT = "inverter_ac_limit_kw"' in const_source
    assert "max_charge_kw=min(" in settings_source
    assert "max_discharge_kw=min(" in settings_source
    assert "export_limit_kw=min(" in settings_source
    assert "eps_output_limit_kw=max(" in settings_source
    assert settings_source.count("max(float(values[CONF_INVERTER_LIMIT]), 0.1)") >= 6
    unsafe_eps_clamp = (
        "max(float(values[CONF_EPS_LIMIT]), 0.1),\n"
        "                ),\n                max_discharge_kw"
    )
    assert unsafe_eps_clamp not in settings_source
    assert 'else "paced_export"' in settings_source
    assert "CONF_EXPORT_RATE: 12.0" in const_source


def test_alpha5_exposes_export_tariff_status_and_safe_default() -> None:
    """Existing users keep paid-export behaviour until they choose awaiting."""
    settings_source = SETTINGS.read_text(encoding="utf-8")
    const_source = CONST.read_text(encoding="utf-8")

    assert 'CONF_EXPORT_TARIFF_STATUS = "export_tariff_status"' in const_source
    assert 'CONF_EXPORT_TARIFF_STATUS: "active"' in const_source
    assert 'if str(values[CONF_EXPORT_TARIFF_STATUS]) == "awaiting"' in settings_source
