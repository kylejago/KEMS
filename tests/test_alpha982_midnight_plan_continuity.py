"""Alpha9.82 regression coverage for continuous Today -> Tomorrow SOC flow."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
LONDON = ZoneInfo("Europe/London")


def _load_handoff():
    package_name = "alpha982_midnight_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    sys.modules[package_name] = package

    agile = types.ModuleType(f"{package_name}.agile_smart_export")
    agile.LONDON = LONDON
    agile._aggregate = lambda *args, **kwargs: {}
    agile._quality = lambda *args, **kwargs: {}
    sys.modules[agile.__name__] = agile

    core = types.ModuleType(f"{package_name}.kems_core")
    for name in (
        "ForecastPlanState",
        "LearnedState",
        "SimulationConfig",
        "SolarForecastState",
    ):
        setattr(core, name, type(name, (), {}))
    core.__path__ = []
    sys.modules[core.__name__] = core

    handoff_helpers = types.ModuleType(f"{package_name}.kems_core.tomorrow_soc_handoff")
    handoff_helpers.project_tomorrow_midnight_soc = lambda *args, **kwargs: (0.0, {})
    handoff_helpers.reconcile_precheap_projection = lambda **kwargs: (
        kwargs.get("projected_precheap_soc_percent"),
        {},
    )
    sys.modules[handoff_helpers.__name__] = handoff_helpers

    tariff = types.ModuleType(f"{package_name}.tariff")
    tariff.TariffSettings = type("TariffSettings", (), {})
    sys.modules[tariff.__name__] = tariff

    module_name = f"{package_name}.agile_settled_soc_handoff"
    spec = importlib.util.spec_from_file_location(
        module_name,
        INTEGRATION / "agile_settled_soc_handoff.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_today_final_display_soc_is_exact_tomorrow_boundary_authority() -> None:
    handoff = _load_handoff()
    state = {
        "today_slots": [
            {
                "valid_from": "2026-10-06T22:30:00+00:00",
                "valid_to": "2026-10-06T23:00:00+00:00",
                "flow_estimated_soc_percent": 20.9,
                "ending_soc_percent": 77.4,
            }
        ]
    }

    result = handoff._today_display_midnight_soc(
        state,
        now=datetime(2026, 10, 6, 22, 51, tzinfo=LONDON),
    )

    assert result == (20.9, "flow_estimated_soc_percent")


def test_raw_replay_soc_is_only_fallback_when_flow_soc_missing() -> None:
    handoff = _load_handoff()
    state = {
        "today_slots": [
            {
                "valid_from": "2026-10-06T22:30:00+00:00",
                "valid_to": "2026-10-06T23:00:00+00:00",
                "ending_soc_percent": 20.9,
            }
        ]
    }

    assert handoff._today_display_midnight_soc(
        state,
        now=datetime(2026, 10, 6, 22, 51, tzinfo=LONDON),
    ) == (20.9, "ending_soc_percent")


def test_non_midnight_slot_cannot_seed_tomorrow() -> None:
    handoff = _load_handoff()
    state = {
        "today_slots": [
            {
                "valid_from": "2026-10-06T22:00:00+00:00",
                "valid_to": "2026-10-06T22:30:00+00:00",
                "flow_estimated_soc_percent": 20.9,
            }
        ]
    }

    assert (
        handoff._today_display_midnight_soc(
            state,
            now=datetime(2026, 10, 6, 22, 51, tzinfo=LONDON),
        )
        is None
    )


def test_settlement_flow_refreshes_routing_before_flow_contract() -> None:
    source = (INTEGRATION / "agile_flow_presentation.py").read_text()
    reconcile = source[source.index("def reconcile_current_day_settlements") :]

    enrich = reconcile.index("_enrich_slot_routing(")
    attach = reconcile.index("_attach_flow_contract(")
    publish = reconcile.index("self._publish(self._state)")

    assert enrich < attach < publish
    assert "tomorrow_slots" in reconcile
    assert "hardware writes" not in reconcile.lower()


def test_midnight_handoff_remains_reporting_only() -> None:
    source = (INTEGRATION / "agile_settled_soc_handoff.py").read_text()

    assert "_today_display_midnight_soc" in source
    assert "today_to_tomorrow_continuity_applied" in source
    assert '"hardware_writes": "blocked"' in source
    assert ".services.async_call(" not in source
    assert "safe_to_write_hardware = True" not in source
