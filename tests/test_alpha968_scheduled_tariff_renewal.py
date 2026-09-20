"""Alpha9.68 scheduled tariff renewal regressions."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
CONST = KEMS / "const.py"
SETTINGS = KEMS / "settings.py"
FLOW = KEMS / "config_flow.py"
TARIFF = KEMS / "tariff.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def test_october_tariff_changes_are_staged_not_immediate_defaults() -> None:
    source = CONST.read_text(encoding="utf-8")

    assert 'CONF_MANUAL_DAY_RATE: 28.3036' in source
    assert 'CONF_MANUAL_OFFPEAK_RATE: 3.4933' in source
    assert 'CONF_MANUAL_STANDING_CHARGE: 53.70435' in source

    assert 'CONF_TARIFF_CHANGE_1_DATE: "2026-10-01"' in source
    assert "CONF_TARIFF_CHANGE_1_DAY_RATE: 26.9558095238" in source
    assert "CONF_TARIFF_CHANGE_1_OFFPEAK_RATE: 3.326952381" in source
    assert "CONF_TARIFF_CHANGE_1_STANDING_CHARGE: 51.147" in source

    assert 'CONF_TARIFF_CHANGE_2_DATE: "2026-10-04"' in source
    assert "CONF_TARIFF_CHANGE_2_DAY_RATE: 37.17" in source
    assert "CONF_TARIFF_CHANGE_2_OFFPEAK_RATE: 8.0" in source
    assert "CONF_TARIFF_CHANGE_2_STANDING_CHARGE: 55.52" in source


def test_runtime_settings_build_both_optional_scheduled_changes() -> None:
    source = SETTINGS.read_text(encoding="utf-8")

    assert "ScheduledTariffChange" in source
    assert "scheduled_changes=tuple(" in source
    assert "CONF_TARIFF_CHANGE_1_DATE" in source
    assert "CONF_TARIFF_CHANGE_2_DATE" in source
    assert "if change is not None" in source


def test_tariff_options_expose_and_can_clear_effective_dates() -> None:
    source = FLOW.read_text(encoding="utf-8")

    assert "SCHEDULED_TARIFF_FIELDS" in source
    assert "vol.Optional(CONF_TARIFF_CHANGE_1_DATE): DateSelector()" in source
    assert "vol.Optional(CONF_TARIFF_CHANGE_2_DATE): DateSelector()" in source
    assert "CONF_TARIFF_CHANGE_1_OFFPEAK_RATE" in source
    assert "CONF_TARIFF_CHANGE_2_OFFPEAK_RATE" in source
    assert "if key not in cleaned:" in source
    assert 'cleaned[key] = ""' in source


def test_resolver_uses_effective_rate_for_intelligent_price_corroboration() -> None:
    source = TARIFF.read_text(encoding="utf-8")

    assert "effective = effective_tariff_rates(settings, now)" in source
    assert "cheap_rate_pence=effective.offpeak_rate_pence" in source
    assert "current_import_rate=effective.offpeak_rate_pence" in source
    assert '"effective_fallback_offpeak_rate_pence"' in source
    assert '"next_scheduled_change"' in source


def test_alpha968_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.68"
    assert reason.startswith("Alpha9.68 adds date-aware electricity tariff fallbacks")
    assert "1 October 2026" in reason
    assert "4 October 2026" in reason
    assert "37.17p/kWh" in reason
    assert "8.00p/kWh" in reason
    assert "55.52p/day" in reason
    assert "Automatic mode continues to prefer live Home Assistant Octopus values" in reason
