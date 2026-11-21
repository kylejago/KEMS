"""Alpha9.245 cleanup: no loss of live No-KEMS comparison or authority."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _retirement():
    spec = importlib.util.spec_from_file_location(
        "kems_retired_scenarios_test", KEMS / "retired_scenario_sensors.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Registry:
    def __init__(self, entities):
        self.entities = dict(entities)
        self.removed = []

    def async_get_entity_id(self, domain, platform, unique_id):
        assert (domain, platform) == ("sensor", "kems")
        return next(
            (
                key
                for key, value in self.entities.items()
                if value.unique_id == unique_id
            ),
            None,
        )

    def async_remove(self, entity_id):
        self.removed.append(entity_id)
        self.entities.pop(entity_id)


class _States:
    def __init__(self, states):
        self.states = states

    def get(self, entity_id):
        state = self.states.get(entity_id)
        return None if state is None else SimpleNamespace(state=state)


def _entity(entry, key, platform="kems"):
    return SimpleNamespace(
        config_entry_id=entry,
        unique_id=f"{entry}_{key}",
        platform=platform,
    )


def test_legacy_scenario_surface_retired_but_no_kems_costs_retained():
    module = _retirement()
    assert len(module.RETIRED_SCENARIO_SENSOR_KEYS) == 23
    source = ast.parse((KEMS / "sensor.py").read_text())
    keys = {
        node.value.value
        for node in ast.walk(source)
        if isinstance(node, ast.keyword)
        and node.arg == "key"
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    assert not (set(module.RETIRED_SCENARIO_SENSOR_KEYS) & keys)
    assert "compare_no_system_cost_today" in keys
    assert "compare_no_system_net_electricity_cost_today" in keys
    assert "scenario_comparison_today" in keys
    assert "simulated_cost_today" in keys
    dashboard = (KEMS / "kems_master_dashboard.yaml").read_text()
    assert "sensor.kems_compare_no_system_cost_today" in dashboard
    for key in module.RETIRED_SCENARIO_SENSOR_KEYS:
        assert f"sensor.kems_{key}" not in dashboard


def test_registry_removes_only_exact_owned_inactive_scenarios():
    module = _retirement()
    inactive = "sensor.kems_compare_solar_only_cost_today"
    sentinel = "sensor.kems_compare_solar_only_flow_now"
    active = "sensor.kems_compare_kems_full_cost_today"
    foreign = "sensor.foreign_compare_solar_battery_cost_today"
    no_kems = "sensor.kems_compare_no_system_cost_today"
    registry = _Registry(
        {
            inactive: _entity("entry-1", "compare_solar_only_cost_today"),
            sentinel: _entity("entry-1", "compare_solar_only_flow_now"),
            active: _entity("entry-1", "compare_kems_full_cost_today"),
            foreign: _entity("entry-2", "compare_solar_battery_cost_today", "other"),
            no_kems: _entity("entry-1", "compare_no_system_cost_today"),
        }
    )
    states = _States(
        {
            inactive: "unknown",
            sentinel: ",".join(
                f"{key}=-1"
                for key in [
                    "H",
                    "S",
                    "GI",
                    "GE",
                    "SH",
                    "SB",
                    "SE",
                    "GB",
                    "BH",
                    "BE",
                    "SOC",
                ]
            ),
            active: "12.4",
            foreign: "unavailable",
            no_kems: "138.5",
        }
    )
    removed = module.retire_inactive_scenario_sensors(
        registry, states, entry_id="entry-1"
    )
    assert set(removed) == {inactive, sentinel}
    assert set(registry.entities) == {active, foreign, no_kems}
    assert (
        module.retire_inactive_scenario_sensors(registry, states, entry_id="entry-1")
        == ()
    )


def test_registry_never_removes_another_entry_or_live_legacy_sensor():
    module = _retirement()
    candidate = "sensor.kems_compare_full_island_mode_today"
    entity = _entity("another-entry", "compare_full_island_mode_today")
    registry = _Registry({candidate: entity})
    assert not module.retire_inactive_scenario_sensors(
        registry, _States({candidate: "Unavailable"}), entry_id="entry-1"
    )
    entity.config_entry_id = "entry-1"
    entity.unique_id = "entry-1_compare_full_island_mode_today"
    assert not module.retire_inactive_scenario_sensors(
        registry, _States({candidate: "Survived"}), entry_id="entry-1"
    )


def test_commissioning_display_does_not_change_underlying_safety_gate():
    source = (KEMS / "commissioning.py").read_text()
    assert 'state == "Ready for Shadow"' in source
    assert '"ready_for_control": ready_for_control' in source
    assert "commissioning_operator_state(" in source
    assert 'return "Ready for Control"' in source
    assert 'return state' in source
    init = (KEMS / "__init__.py").read_text()
    assert "retire_inactive_scenario_sensors(" in init
    entity = (KEMS / "entity.py").read_text()
    assert 'model="Whole-home energy management"' in entity
    assert 'model="Whole-home proposal simulation"' not in entity


def test_active_release_note_is_compact_and_history_remains_auditable():
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    current = bundle["maintenance"]["reason"]
    archive = (ROOT / "docs/archived-release-notes-through-alpha9244.md").read_text()
    assert manifest["version"] == "0.9.0-alpha9.246"
    assert current.startswith("Alpha9.246:")
    assert len(current.encode("utf-8")) < 2000
    assert "No new FoxESS/Ohme commands" in current
    assert "15% deliberate export floor / 10% household floor" in current
    assert "06:00-06:30 safe-first" in current
    assert archive.startswith("# KEMS release-note history through Alpha9.244")
    assert "Alpha9.244: Reduce confirmed-cheap FoxESS Force Charge demand" in archive
    assert "Alpha9.243: Complete original-scope solar-only progress" in archive


def test_legacy_simulation_dashboard_is_archived_not_installed():
    old = (KEMS / "dashboard_consolidation.py").read_text()
    setup = (KEMS / "__init__.py").read_text()
    current = (KEMS / "kems_master_dashboard.yaml").read_text()
    assert "Archived Alpha7 product dashboard" in old
    assert "install_dashboard_consolidation()" not in setup
    assert "install_dashboard_pipeline()" in setup
    assert "sensor.kems_compare_solar_and_battery_cost_today" not in current
    assert "sensor.kems_compare_full_kems_forecast_cost_today" not in current
