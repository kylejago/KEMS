"""Regression coverage for alpha7.16 rolling Agile export replanning."""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def _string_constant(path: Path, name: str) -> str:
    """Read one literal module constant without importing Home Assistant."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, str)
            return value
    raise AssertionError(f"{name} was not found in {path}")


def test_rolling_replan_runs_on_every_coordinator_scan_without_extra_storage() -> None:
    """Live analysis must see every scan while persistence keeps its normal cadence."""
    source = (INTEGRATION / "agile_rolling_replan.py").read_text(encoding="utf-8")
    assert "runtime.ANALYSIS_REFRESH = timedelta(0)" in source
    assert 'self._kems_live_snapshot = snapshot' in source
    assert "_ORIGINAL_HISTORY_RECORD(self, snapshot)" in source
    assert "live.timestamp > records[-1].timestamp" in source


def test_rolling_replan_reallocates_currently_exportable_energy() -> None:
    """The planner must rebuild remaining slot allocations from current SOC."""
    source = (INTEGRATION / "agile_rolling_replan.py").read_text(encoding="utf-8")
    assert "_current_agile_soc(state)" in source
    assert "predicted_energy_until_offpeak_kwh" in source
    assert "protected_house_ac / efficiency" in source
    assert "exportable_ac = max(battery_kwh - protected_stored_kwh, 0.0)" in source
    assert '"rolling_planned_battery_export_kwh"' in source
    assert '"hold — re-evaluate next KEMS scan"' in source
    assert '"planned battery export — rolling replan"' in source


def test_rolling_replan_keeps_best_prices_until_capacity_pressure() -> None:
    """Price ranking stays primary until the remaining discharge path gets tight."""
    source = (INTEGRATION / "agile_rolling_replan.py").read_text(encoding="utf-8")
    assert "PRESSURE_THRESHOLD = 0.75" in source
    assert 'key=lambda value: value["rate"], reverse=True' in source
    assert "if utilisation >= PRESSURE_THRESHOLD" in source
    assert "SAFETY_HEADROOM_MINUTES = 30" in source
    assert "required_now = max(" in source


def test_runtime_installs_rolling_replan_before_live_reporting() -> None:
    """Rolling allocation must exist before the live dashboard consumes the state."""
    source = (INTEGRATION / "agile_smart_export_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "install_rolling_replan_patch()" in source
    assert "install_alpha716_dashboard_patch()" in source
    assert source.index("install_rolling_replan_patch()") < source.index(
        "install_live_scenario_patch()"
    )
    assert source.index("install_alpha715_dashboard_patch()") < source.index(
        "install_alpha716_dashboard_patch()"
    )


def test_alpha716_dashboard_card_remains_valid_yaml() -> None:
    """The rolling-plan card must stay inside the Agile dashboard view."""
    dashboard_path = INTEGRATION / "agile_alpha716_dashboard.py"
    card = _string_constant(dashboard_path, "_ROLLING_CARD")
    assert "Rolling Agile battery export plan" in card
    assert "sensor.kems_agile_rolling_export_plan" in card
    assert "sensor.kems_agile_rolling_next_export_slot" in card

    sample = (
        "title: KEMS Master Dashboard\n"
        "views:\n"
        "  - title: Agile Smart Export\n"
        "    path: agile-smart-export\n"
        "    cards:\n"
        f"{card}"
        "      - type: history-graph\n"
        "        title: Agile scenario economics — 24 hours\n"
        "        entities: []\n"
    )
    parsed = yaml.safe_load(sample)
    assert parsed["views"][0]["path"] == "agile-smart-export"
    titles = [item.get("title") for item in parsed["views"][0]["cards"]]
    assert "Rolling Agile battery export plan" in titles
