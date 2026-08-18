"""Regression tests for the Agile Smart Export read-only strategy helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def _load_agile_module():
    """Load the HA-layer module with tiny Home Assistant/aiohttp test stubs."""
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientError = type("ClientError", (Exception,), {})
    sys.modules.setdefault("aiohttp", aiohttp)

    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        """Enough generic-looking Store API for module import."""

        def __class_getitem__(cls, item):
            return cls

    storage.Store = Store
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)
    sys.modules.setdefault("homeassistant.helpers.storage", storage)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType("custom_components.kems")
    package.__path__ = [str(INTEGRATION)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.kems", package)

    name = "custom_components.kems.agile_smart_export"
    spec = importlib.util.spec_from_file_location(
        name,
        INTEGRATION / "agile_smart_export.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_region_and_fixed_benchmark_are_explicit() -> None:
    """The requested Region L and 12p benchmark must not drift silently."""
    agile = _load_agile_module()
    assert agile.REGION == "L"
    assert agile.FIXED_EXPORT_PENCE == 12.0
    assert agile.BATTERY_WEAR_PENCE_PER_KWH == 2.0


def test_expected_slot_count_handles_both_uk_dst_transitions() -> None:
    """Price completeness must allow 46/48/50-slot local days."""
    agile = _load_agile_module()
    assert agile._expected_slots(date(2026, 3, 28)) == 48
    assert agile._expected_slots(date(2026, 3, 29)) == 46
    assert agile._expected_slots(date(2026, 10, 25)) == 50
    assert agile._expected_slots(date(2026, 10, 26)) == 48


def test_export_threshold_reserves_energy_for_highest_value_slots() -> None:
    """Two hours of exportable energy should select only the four best slots."""
    agile = _load_agile_module()
    start = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    prices = [5.0, 20.0, 8.0, 24.0, 10.0, 18.0]
    rates = [
        agile.AgileRate(
            "AGILE-OUTGOING-TEST",
            "E-1R-AGILE-OUTGOING-TEST-L",
            value,
            start + timedelta(minutes=30 * index),
            start + timedelta(minutes=30 * (index + 1)),
        )
        for index, value in enumerate(prices)
    ]
    # 7kW x 0.5h = 3.5kWh per slot. 7kWh therefore needs the two
    # highest-value remaining slots: 24p and 20p.
    threshold = agile._threshold(
        rates,
        start,
        start + timedelta(hours=3),
        energy=7.0,
        max_kw=7.0,
    )
    assert threshold == 20.0


def test_price_quality_uses_publication_window_without_inventing_rates() -> None:
    """Missing tomorrow prices are labelled rather than backfilled with guesses."""
    agile = _load_agile_module()
    london = ZoneInfo("Europe/London")
    now = datetime(2026, 8, 18, 15, 0, tzinfo=london)
    today = [{}] * 48
    quality = agile._quality(now, today, [])
    assert quality["today_complete"] is True
    assert quality["tomorrow_complete"] is False
    assert quality["tomorrow_status"] == "awaiting Octopus publication"


def test_comparison_names_the_lower_economic_cost_strategy() -> None:
    """Positive Agile advantage means Agile has the lower economic cost."""
    agile = _load_agile_module()
    assert agile._comparison(125.4)["winner"] == "Agile Smart Export"
    assert agile._comparison(-12.0)["winner"] == "Full KEMS Forecast"
    assert agile._comparison(0.0)["winner"] == "Tie"


def test_agile_feature_does_not_import_control_or_foxess_write_code() -> None:
    """The new strategy must stay outside the commissioned write boundary."""
    source = (INTEGRATION / "agile_smart_export.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "agile_smart_export_runtime.py").read_text(
        encoding="utf-8"
    )
    combined = source + runtime
    assert "ControlEngine" not in combined
    assert "battery_manager" not in combined
    assert "foxess" not in combined.lower()
    assert '"mode": "simulation_only"' in source
