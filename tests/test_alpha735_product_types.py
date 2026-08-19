"""Regression guards for Alpha7.35 simplified products and cheap handover."""

from __future__ import annotations

import ast
import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from custom_components.kems.product_types import (
    SYSTEM_TYPE_BATTERY_SOLAR,
    SYSTEM_TYPE_FULL_KEMS,
    SYSTEM_TYPE_FULL_KEMS_AGILE,
    SYSTEM_TYPE_LIVE_DATA,
    SYSTEM_TYPES,
    effective_operating_mode,
    internal_mode_from_user,
    user_mode_from_internal,
)
from custom_components.kems.tariff import manual_schedule

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
MANIFEST = KEMS / "manifest.json"
PATCH = KEMS / "agile_alpha735_cheap_handover.py"
RUNTIME = KEMS / "agile_smart_export_runtime.py"
SELECT = KEMS / "select.py"
CONST = KEMS / "const.py"
LONDON = ZoneInfo("Europe/London")


def test_four_user_facing_product_types_are_stable() -> None:
    """KEMS should expose four capability levels rather than strategy clutter."""
    assert SYSTEM_TYPES == (
        SYSTEM_TYPE_LIVE_DATA,
        SYSTEM_TYPE_BATTERY_SOLAR,
        SYSTEM_TYPE_FULL_KEMS,
        SYSTEM_TYPE_FULL_KEMS_AGILE,
    )


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
    """Stored compatibility data remains inert while the new product default is clear."""
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


def test_alpha735_installs_after_alpha734_without_another_optimizer_patch() -> None:
    """Alpha7.31/34 policy stays intact; Alpha7.35 is the final display wrapper."""
    runtime = RUNTIME.read_text(encoding="utf-8")
    assert runtime.rindex("install_alpha735_cheap_handover_patch()") > runtime.rindex(
        "install_alpha734_deadline_guard_patch()"
    )
    assert "alpha735_optimizer" not in runtime


def test_alpha735_release_identity() -> None:
    """The simplified dashboard ships through the coordinated updater."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == "0.7.0-alpha7.35"
