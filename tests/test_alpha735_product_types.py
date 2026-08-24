"""Regression guards for Alpha7.35 simplified products and cheap handover."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
MANIFEST = KEMS / "manifest.json"
PATCH = KEMS / "agile_alpha735_cheap_handover.py"
RUNTIME = KEMS / "agile_smart_export_runtime.py"
SELECT = KEMS / "select.py"
CONST = KEMS / "const.py"
PRODUCT_TYPES = KEMS / "product_types.py"
TARIFF = KEMS / "tariff.py"
LONDON = ZoneInfo("Europe/London")


def _load_pure_module(name: str, path: Path):
    """Load one pure helper without importing the Home Assistant package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


product_types = _load_pure_module("kems_alpha735_product_types_test", PRODUCT_TYPES)
tariff = _load_pure_module("kems_alpha735_tariff_test", TARIFF)

SYSTEM_TYPE_BATTERY_SOLAR = product_types.SYSTEM_TYPE_BATTERY_SOLAR
SYSTEM_TYPE_FULL_KEMS = product_types.SYSTEM_TYPE_FULL_KEMS
SYSTEM_TYPE_FULL_KEMS_AGILE = product_types.SYSTEM_TYPE_FULL_KEMS_AGILE
SYSTEM_TYPE_KEMS = product_types.SYSTEM_TYPE_KEMS
SYSTEM_TYPE_LIVE_DATA = product_types.SYSTEM_TYPE_LIVE_DATA
SYSTEM_TYPES = product_types.SYSTEM_TYPES
effective_operating_mode = product_types.effective_operating_mode
internal_mode_from_user = product_types.internal_mode_from_user
normalise_system_type = product_types.normalise_system_type
user_mode_from_internal = product_types.user_mode_from_internal
manual_schedule = tariff.manual_schedule


def test_alpha735_capability_levels_survive_unified_kems_product() -> None:
    """Retired Alpha7 product keys remain compatible behind Live Data / KEMS."""
    assert SYSTEM_TYPES == (SYSTEM_TYPE_LIVE_DATA, SYSTEM_TYPE_KEMS)
    for legacy in (
        SYSTEM_TYPE_BATTERY_SOLAR,
        SYSTEM_TYPE_FULL_KEMS,
        SYSTEM_TYPE_FULL_KEMS_AGILE,
    ):
        assert normalise_system_type(legacy) == SYSTEM_TYPE_KEMS


def test_live_data_can_never_escalate_to_simulation_or_control() -> None:
    """The monitoring-only product must fail closed regardless of stored mode."""
    for requested in ("observe", "simulate", "shadow", "control"):
        assert effective_operating_mode(SYSTEM_TYPE_LIVE_DATA, requested) == "observe"
    assert effective_operating_mode(SYSTEM_TYPE_FULL_KEMS_AGILE, "control") == "control"


def test_user_modes_hide_shadow_but_keep_internal_mapping() -> None:
    """Users see Live/Simulate/Control while commissioning may retain Shadow."""
    assert internal_mode_from_user("Live") == "observe"
    assert internal_mode_from_user("Simulate") == "simulate"
    assert internal_mode_from_user("Control") == "control"
    assert user_mode_from_internal("observe") == "Live"
    assert user_mode_from_internal("simulate") == "Simulate"
    assert user_mode_from_internal("shadow") == "Simulate"
    assert user_mode_from_internal("control") == "Control"


def test_virtual_scenario_selector_is_advanced_and_disabled_by_default() -> None:
    """Engineering scenarios must remain available without cluttering normal UX."""
    source = SELECT.read_text(encoding="utf-8")
    assert "KEMSVirtualScenarioSelect" in source
    assert "EntityCategory.DIAGNOSTIC" in source
    assert "_attr_entity_registry_enabled_default = False" in source
    assert '_attr_name = "Advanced test scenario"' in source


def test_legacy_intelligent_slot_option_is_not_a_default_user_capability() -> None:
    """Stored compatibility data stays inert under the new product model."""
    source = CONST.read_text(encoding="utf-8")
    assert 'CONF_SYSTEM_TYPE = "system_type"' in source
    assert 'CONF_SYSTEM_TYPE: "full_kems_agile"' in source
    assert "CONF_INTELLIGENT_SLOTS_ENABLED: False" in source


def test_2330_handover_uses_the_same_configured_overnight_window() -> None:
    """23:30 must immediately be cheap, while 23:29 remains outside."""
    before = datetime(2026, 8, 19, 23, 29, tzinfo=LONDON)
    after = datetime(2026, 8, 19, 23, 31, tzinfo=LONDON)
    assert manual_schedule(before, time(23, 30), time(5, 30))[0] is False
    assert manual_schedule(after, time(23, 30), time(5, 30))[0] is True


def test_alpha735_handover_is_reporting_only_and_blocks_display_export() -> None:
    """The fix must not change hardware or the proven Agile optimiser."""
    source = PATCH.read_text(encoding="utf-8")
    ast.parse(source)
    assert "battery_export = 0.0" in source
    assert '"dispatch_mode": "cheap_charge"' in source
    assert '"cheap overnight import / charge"' in source
    assert "rolling export candidate suppressed" in source
    assert '"hardware_writes": "blocked"' in source
    assert "safe_to_write_hardware = True" not in source
    assert ".services.async_call(" not in source


def test_alpha735_installs_after_alpha734_and_before_later_reporting_patches() -> None:
    """Alpha7.35 remains after the deadline guard without changing optimiser policy."""
    runtime = RUNTIME.read_text(encoding="utf-8")
    assert runtime.rindex("install_alpha735_cheap_handover_patch()") > runtime.rindex(
        "install_alpha734_deadline_guard_patch()"
    )
    assert "alpha735_optimizer" not in runtime


def test_alpha735_release_identity_is_preserved_in_alpha8() -> None:
    """Alpha8 keeps the Alpha7.35 product/handover contract as parity baseline."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert str(manifest["version"]).startswith("0.8.0-alpha8.")
    assert PATCH.exists()
