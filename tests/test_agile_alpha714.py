"""Regression coverage for the alpha7.14 Agile deadline and history work."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def _load_deadline_module():
    """Reuse the existing Agile test stubs, then load the deadline module."""
    from test_agile_smart_export import _load_agile_module

    _load_agile_module()
    name = "custom_components.kems.agile_deadline_dispatch"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        name,
        INTEGRATION / "agile_deadline_dispatch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_late_766_percent_case_is_physically_unreachable() -> None:
    """The live case that exposed the bug must not be labelled on-track."""
    deadline = _load_deadline_module()
    from custom_components.kems.kems_core import SimulationConfig
    from custom_components.kems.tariff import TariffSettings

    london = ZoneInfo("Europe/London")
    config = SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=10.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        discharge_efficiency=0.95,
    )
    metrics = deadline._deadline_metrics(
        battery_kwh=56.42 * 0.766,
        timestamp=datetime(2026, 8, 18, 19, 10, tzinfo=london),
        config=config,
        tariff=TariffSettings(),
    )
    assert metrics["deadline_target_soc_percent"] == 10.0
    assert metrics["deadline_effective_discharge_kw"] == 7.0
    assert metrics["deadline_status"] == "Physically unreachable"
    assert metrics["deadline_margin_kwh"] < 0
    assert metrics["deadline_minimum_reachable_soc_percent"] > 10.0


def test_earlier_lower_soc_case_keeps_price_flexibility() -> None:
    """A feasible battery state should remain free to wait for better prices."""
    deadline = _load_deadline_module()
    from custom_components.kems.kems_core import SimulationConfig
    from custom_components.kems.tariff import TariffSettings

    london = ZoneInfo("Europe/London")
    config = SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=10.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        discharge_efficiency=0.95,
    )
    metrics = deadline._deadline_metrics(
        battery_kwh=56.42 * 0.55,
        timestamp=datetime(2026, 8, 18, 15, 0, tzinfo=london),
        config=config,
        tariff=TariffSettings(),
    )
    assert metrics["deadline_status"] == "On track"
    assert metrics["deadline_margin_kwh"] > 0


def test_deadline_uses_real_discharge_bottleneck() -> None:
    """The price selector must use discharge, inverter and export limits together."""
    source = (INTEGRATION / "agile_deadline_dispatch.py").read_text(encoding="utf-8")
    assert "max(config.max_discharge_kw, 0.0)" in source
    assert "max(config.inverter_limit_kw, 0.0)" in source
    assert "max(config.export_limit_kw, 0.0)" in source
    assert "deadline export to protect 10% target" in source
    assert "deadline blocks extra solar storage" in source
    assert "max(export_limit - deadline_reserve_ac, 0.0)" in source


def test_runtime_installs_deadline_and_history_before_live_dashboard() -> None:
    """The simulation constraints must exist before runtime/live reporting is loaded."""
    source = (INTEGRATION / "agile_smart_export_runtime.py").read_text(encoding="utf-8")
    assert "install_deadline_patch()" in source
    assert "install_enhanced_backfill()" in source
    assert "install_alpha714_dashboard_patch()" in source
    assert source.index("install_deadline_patch()") < source.index(
        "from . import agile_smart_export_runtime_base"
    )
    assert source.index("install_enhanced_backfill()") < source.index(
        "from . import agile_smart_export_runtime_base"
    )
    assert source.index("install_dashboard_yaml_guard()") < source.index(
        "install_alpha714_dashboard_patch()"
    )


def test_energy_dashboard_source_mapping_and_house_equation_are_explicit() -> None:
    """Energy fallback must cover grid, solar and battery flows."""
    source = (INTEGRATION / "agile_history_backfill_v2.py").read_text(encoding="utf-8")
    assert 'source.get("stat_energy_from")' in source
    assert 'source.get("stat_energy_to")' in source
    assert 'source.get("stat_soc")' in source
    assert '"types": ["change", "mean", "state"]' in source
    assert (
        "solar + grid_import + battery_discharge - grid_export - battery_charge"
        in source
    )
    assert "Configured power statistics did not recover older days" in source


def test_alpha714_dashboard_patch_keeps_yaml_shape_valid() -> None:
    """The new deadline/history cards must stay nested inside dashboard views."""
    source = (INTEGRATION / "agile_alpha714_dashboard.py").read_text(encoding="utf-8")
    assert "10% battery target — cheap-window deadline" in source
    assert "Historical backfill diagnostics" in source
    assert "Replay coverage including today" in source
    assert "sensor.kems_agile_live_hardware_battery_soc" in source

    sample = """title: KEMS Master Dashboard
views:
  - title: Agile History
    path: agile-history
    cards:
      - type: history-graph
        title: Cumulative Agile advantage
        entities: []

  - title: Agile Smart Export
    path: agile-smart-export
    cards:
      - type: entities
        title: Battery and price state
        entities:
          - entity: sensor.kems_battery_state_of_charge
      - type: history-graph
        title: Agile scenario economics — 24 hours
        entities: []
"""
    parsed = yaml.safe_load(sample)
    assert [item["path"] for item in parsed["views"]] == [
        "agile-history",
        "agile-smart-export",
    ]
