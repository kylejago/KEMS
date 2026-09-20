"""Alpha9.59 control-gate persistence and commissioning-session regressions."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
SWITCH = KEMS / "switch.py"
RUNTIME_OPTIONS = KEMS / "runtime_options.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def test_control_opt_in_switches_preserve_session_evidence_on_enable() -> None:
    source = SWITCH.read_text(encoding="utf-8")
    commissioned = source.split("class KEMSCommissionedForControlSwitch", 1)[1].split(
        "class KEMSMasterControlEnableSwitch", 1
    )[0]
    master = source.split("class KEMSMasterControlEnableSwitch", 1)[1].split(
        "class KEMSWeekendHappyHourPlanningSwitch", 1
    )[0]

    assert "async_set_control_gate_option" in commissioned
    assert "async_set_control_gate_option" in master

    # Disable paths deliberately retain the reload helper so integration unload
    # continues to restore any KEMS-owned FoxESS state fail-closed.
    assert "async_set_runtime_option" in commissioned
    assert "async_set_runtime_option" in master

    assert "KEMS control-critical commissioning evidence is not ready" in master
    assert "commissioned for control before Master control" in master
    assert "Mode must be Control before Master control" in master


def test_control_gate_helper_is_narrow_persistent_and_reload_free() -> None:
    source = RUNTIME_OPTIONS.read_text(encoding="utf-8")
    helper = source.split("async def async_set_control_gate_option", 1)[1]

    assert "_CONTROL_GATE_KEYS" in source
    assert "CONF_CONTROL_ENABLED" in source
    assert "CONF_SYSTEM_COMMISSIONED" in source
    assert "async_update_entry" in helper
    assert "KEMSSettings.from_options" in helper
    assert "replace(" in helper
    assert "async_request_refresh" in helper
    assert "async_reload" not in helper


def test_legacy_runtime_options_still_reload_for_non_gate_settings() -> None:
    source = RUNTIME_OPTIONS.read_text(encoding="utf-8")
    legacy = source.split("async def async_set_runtime_options", 1)[1].split(
        "async def async_set_runtime_option", 1
    )[0]

    assert "async_update_entry" in legacy
    assert "async_reload" in legacy


def test_alpha959_release_identity_and_safety_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.67"
    assert reason.startswith("Alpha9.67")
    assert "Alpha9.59 fixes the final opt-in reload loop" in reason
    assert "Commissioned for control ON" in reason
    assert "Master control enable ON" in reason
    assert "request a normal coordinator refresh instead of reloading" in reason
    assert "OFF paths keep the existing reload/shutdown behaviour" in reason
    assert "does not broaden FoxESS write authority" in reason
    assert "Force Discharge" in reason
    assert "Export Power Limit writes" in reason
    assert "10 W grid-import-prevention bias Shadow-only" in reason
