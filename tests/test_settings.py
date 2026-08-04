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
    assert 'else "paced_export"' in settings_source
    assert "CONF_EXPORT_RATE: 12.0" in const_source
