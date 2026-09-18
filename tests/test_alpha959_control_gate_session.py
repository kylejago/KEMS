"""Alpha9.59 control-gate persistence and commissioning-session regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.kems.const import (
    CONF_CONTROL_ENABLED,
    CONF_SYSTEM_COMMISSIONED,
)
from custom_components.kems.runtime_options import async_set_control_gate_option
from custom_components.kems.settings import KEMSSettings

ROOT = Path(__file__).resolve().parents[1]
SWITCH = ROOT / "custom_components" / "kems" / "switch.py"
RUNTIME_OPTIONS = ROOT / "custom_components" / "kems" / "runtime_options.py"


class _ConfigEntries:
    def __init__(self) -> None:
        self.updated_options: dict[str, object] | None = None
        self.reload_calls = 0

    def async_update_entry(self, entry, *, options) -> None:
        self.updated_options = dict(options)
        entry.options = dict(options)

    async def async_reload(self, entry_id: str) -> None:
        self.reload_calls += 1
        raise AssertionError(f"control-gate update must not reload {entry_id}")


class _Coordinator:
    def __init__(self) -> None:
        self.entry = SimpleNamespace(entry_id="test-entry", options={})
        self.settings = KEMSSettings.from_options({})
        self.refresh_calls = 0

    async def async_request_refresh(self) -> None:
        self.refresh_calls += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "attribute"),
    (
        (CONF_SYSTEM_COMMISSIONED, "commissioned"),
        (CONF_CONTROL_ENABLED, "control_enabled"),
    ),
)
async def test_control_gate_persists_in_place_without_reload(
    key: str,
    attribute: str,
) -> None:
    config_entries = _ConfigEntries()
    hass = SimpleNamespace(config_entries=config_entries)
    coordinator = _Coordinator()

    await async_set_control_gate_option(hass, coordinator, key, True)

    assert config_entries.updated_options is not None
    assert config_entries.updated_options[key] is True
    assert getattr(coordinator.settings.control, attribute) is True
    assert coordinator.refresh_calls == 1
    assert config_entries.reload_calls == 0


@pytest.mark.asyncio
async def test_control_gate_helper_rejects_non_gate_option() -> None:
    config_entries = _ConfigEntries()
    hass = SimpleNamespace(config_entries=config_entries)
    coordinator = _Coordinator()

    with pytest.raises(ValueError):
        await async_set_control_gate_option(
            hass,
            coordinator,
            "operating_mode",
            True,
        )

    assert config_entries.updated_options is None
    assert coordinator.refresh_calls == 0


def test_control_opt_in_switches_preserve_session_evidence_on_enable() -> None:
    source = SWITCH.read_text(encoding="utf-8")
    commissioned = source.split(
        "class KEMSCommissionedForControlSwitch", 1
    )[1].split("class KEMSMasterControlEnableSwitch", 1)[0]
    master = source.split("class KEMSMasterControlEnableSwitch", 1)[1].split(
        "class KEMSWeekendHappyHourPlanningSwitch", 1
    )[0]

    assert "async_set_control_gate_option" in commissioned
    assert "async_set_control_gate_option" in master
    assert "async_set_runtime_option" in commissioned
    assert "async_set_runtime_option" in master
    assert "KEMS control-critical commissioning evidence is not ready" in master
    assert "commissioned for control before Master control" in master
    assert "Mode must be Control before Master control" in master


def test_control_gate_helper_is_narrow_and_does_not_reload() -> None:
    source = RUNTIME_OPTIONS.read_text(encoding="utf-8")
    helper = source.split("async def async_set_control_gate_option", 1)[1]

    assert "_CONTROL_GATE_KEYS" in source
    assert "CONF_CONTROL_ENABLED" in source
    assert "CONF_SYSTEM_COMMISSIONED" in source
    assert "async_update_entry" in helper
    assert "async_request_refresh" in helper
    assert "async_reload" not in helper
