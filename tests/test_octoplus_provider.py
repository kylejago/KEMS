"""Tests for BottlecapDave Power Down / Saving Session parsing."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "kems"


def _load_octoplus():
    """Load the provider with minimal Home Assistant module stubs."""
    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    const = ModuleType("homeassistant.const")
    util = ModuleType("homeassistant.util")
    dt = ModuleType("homeassistant.util.dt")

    class State:
        def __init__(self, state: str, attributes: dict | None = None) -> None:
            self.state = state
            self.attributes = attributes or {}

    core.HomeAssistant = object
    core.State = State
    const.ATTR_UNIT_OF_MEASUREMENT = "unit_of_measurement"
    const.STATE_OFF = "off"
    const.STATE_ON = "on"
    const.STATE_UNAVAILABLE = "unavailable"
    const.STATE_UNKNOWN = "unknown"
    dt.now = lambda: datetime.now(UTC)
    dt.parse_datetime = lambda value: datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    util.dt = dt
    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.core": core,
            "homeassistant.const": const,
            "homeassistant.util": util,
            "homeassistant.util.dt": dt,
        }
    )

    package_name = "kems_octoplus_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    providers = ModuleType(f"{package_name}.providers")
    providers.__path__ = [str(INTEGRATION / "providers")]
    sys.modules[package_name] = package
    sys.modules[f"{package_name}.providers"] = providers

    loaded = {}
    for module_name, path in (
        ("const", INTEGRATION / "const.py"),
        ("providers.entity_map", INTEGRATION / "providers" / "entity_map.py"),
        ("providers.base", INTEGRATION / "providers" / "base.py"),
        ("providers.octoplus", INTEGRATION / "providers" / "octoplus.py"),
    ):
        qualified = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(qualified, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified] = module
        spec.loader.exec_module(module)
        loaded[module_name] = module
    return loaded["providers.octoplus"], State


def test_active_joined_event_is_preferred_over_later_event() -> None:
    """The provider should expose the active joined event, otherwise the next one."""
    octoplus, State = _load_octoplus()
    now = datetime(2026, 11, 1, 17, 15, tzinfo=UTC)
    active_start = now - timedelta(minutes=15)
    active_end = now + timedelta(minutes=15)
    later_start = now + timedelta(days=1)
    state = State(
        "2026-11-01T17:00:00+00:00",
        {
            "joined_events": [
                {
                    "id": 1,
                    "start": (now - timedelta(days=1)).isoformat(),
                    "end": (now - timedelta(hours=23)).isoformat(),
                },
                {
                    "id": 3,
                    "start": later_start.isoformat(),
                    "end": (later_start + timedelta(hours=1)).isoformat(),
                },
                {
                    "id": 2,
                    "start": active_start.isoformat(),
                    "end": active_end.isoformat(),
                    "octopoints_per_kwh": 800,
                },
            ]
        },
    )

    selected = octoplus.OctoplusProvider._select_joined_event(state, now)

    assert selected is not None
    assert selected["id"] == 2


def test_baseline_parser_sums_periods_when_total_is_missing() -> None:
    """The optional baseline can be restored from its per-period list."""
    octoplus, State = _load_octoplus()
    start = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)
    state = State(
        "0.4",
        {
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=30)).isoformat(),
            "is_incomplete_calculation": True,
            "baselines": [
                {"baseline": 0.4},
                {"baseline": 0.6},
            ],
        },
    )

    period, total, parsed_start, parsed_end, incomplete = (
        octoplus.OctoplusProvider._baseline(state)
    )

    assert period == 0.4
    assert total == 1.0
    assert parsed_start == start
    assert parsed_end == start + timedelta(minutes=30)
    assert incomplete is True


def test_missing_export_baseline_does_not_create_incomplete_state() -> None:
    """An absent optional export baseline must not be treated as incomplete."""
    octoplus, _ = _load_octoplus()

    assert octoplus.OctoplusProvider._combine_incomplete(False, None) is False
    assert octoplus.OctoplusProvider._combine_incomplete(True, None) is True
    assert octoplus.OctoplusProvider._combine_incomplete(None, None) is None


def test_mapped_export_baseline_fails_reward_accounting_closed_until_available() -> None:
    """Never substitute zero export when an export baseline source is mapped."""
    octoplus, _ = _load_octoplus()
    start = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)
    imported = (0.4, 1.0, start, start + timedelta(minutes=30), False)
    missing_export = (None, None, None, None, None)

    safe_import, safe_export = octoplus.OctoplusProvider._reward_baselines(
        imported,
        missing_export,
        export_configured=True,
    )

    assert safe_import[0] is None
    assert safe_import[1] is None
    assert safe_import[2:] == imported[2:]
    assert safe_export == missing_export


def test_unmapped_export_baseline_keeps_import_only_reward_baseline_available() -> None:
    """Sites without a mapped export baseline retain the import-only baseline."""
    octoplus, _ = _load_octoplus()
    start = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)
    imported = (0.4, 1.0, start, start + timedelta(minutes=30), False)
    no_export = (None, None, None, None, None)

    safe_import, safe_export = octoplus.OctoplusProvider._reward_baselines(
        imported,
        no_export,
        export_configured=False,
    )

    assert safe_import == imported
    assert safe_export == no_export


def test_mapped_export_baseline_combines_with_import_when_available() -> None:
    """Usable import/export baseline values must both reach net reward accounting."""
    octoplus, _ = _load_octoplus()
    start = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)
    imported = (0.4, 1.0, start, start + timedelta(minutes=30), False)
    exported = (0.1, 0.25, start, start + timedelta(minutes=30), False)

    safe_import, safe_export = octoplus.OctoplusProvider._reward_baselines(
        imported,
        exported,
        export_configured=True,
    )

    assert safe_import == imported
    assert safe_export == exported
