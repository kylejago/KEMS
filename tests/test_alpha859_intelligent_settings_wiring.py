"""Alpha8.59 production-path regressions for Intelligent slot option wiring."""

from __future__ import annotations

import importlib
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "kems"
PACKAGE_NAME = "kems_alpha859"
LONDON = ZoneInfo("Europe/London")


def _load_runtime_modules():
    """Load the integration package without importing Home Assistant entrypoints."""
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(INTEGRATION_DIR)]
    sys.modules.setdefault(PACKAGE_NAME, package)
    settings = importlib.import_module(f"{PACKAGE_NAME}.settings")
    tariff = importlib.import_module(f"{PACKAGE_NAME}.tariff")
    const = importlib.import_module(f"{PACKAGE_NAME}.const")
    return settings, tariff, const


def _resolve_with_option(enabled: bool):
    settings_module, tariff_module, const = _load_runtime_modules()
    runtime = settings_module.KEMSSettings.from_options(
        {const.CONF_INTELLIGENT_SLOTS_ENABLED: enabled}
    )
    resolved = tariff_module.resolve_tariff(
        settings=runtime.tariff,
        now=datetime(2026, 8, 30, 17, 51, tzinfo=LONDON),
        live_current_import_rate=28.3036,
        live_next_import_rate=3.4933,
        live_current_export_rate=12.0,
        live_standing_charge=53.70435,
        live_off_peak=False,
        live_intelligent_slot=True,
        live_next_offpeak_start=datetime(2026, 8, 30, 16, 33, tzinfo=UTC),
        live_offpeak_end=datetime(2026, 8, 30, 17, 0, tzinfo=UTC),
        ev_charging=True,
        fallback_export_rate=12.0,
        ev_connected=True,
        ev_power_kw=7.326,
        ev_soc=56.0,
        live_current_demand_kw=8.682,
    )
    return runtime, resolved


def test_persisted_true_reaches_runtime_tariff_settings() -> None:
    runtime, _ = _resolve_with_option(True)
    assert runtime.tariff.intelligent_slots_enabled is True


def test_persisted_false_keeps_runtime_tariff_settings_disabled() -> None:
    runtime, _ = _resolve_with_option(False)
    assert runtime.tariff.intelligent_slots_enabled is False


def test_omitted_legacy_option_defaults_safely_to_disabled() -> None:
    settings_module, _, _ = _load_runtime_modules()
    runtime = settings_module.KEMSSettings.from_options({})
    assert runtime.tariff.intelligent_slots_enabled is False


def test_enabled_option_reaches_confirmation_gate_and_permits_large_import() -> None:
    _, resolved = _resolve_with_option(True)
    assert resolved.intelligent_slot is True
    assert resolved.intelligent_slot_confirmation == "confirmed"
    assert resolved.intelligent_slot_evidence["enabled"] is True
    assert resolved.intelligent_slot_evidence["confirmed"] is True
    assert resolved.intelligent_slot_evidence["reason"] == "confirmed"
    assert resolved.intelligent_slot_evidence["large_import_permitted"] is True


def test_disabled_option_with_identical_evidence_fails_closed() -> None:
    _, resolved = _resolve_with_option(False)
    assert resolved.intelligent_slot is False
    assert resolved.intelligent_slot_evidence["enabled"] is False
    assert resolved.intelligent_slot_evidence["confirmed"] is False
    assert resolved.intelligent_slot_evidence["reason"] == "disabled"
    assert resolved.intelligent_slot_evidence["large_import_permitted"] is False
