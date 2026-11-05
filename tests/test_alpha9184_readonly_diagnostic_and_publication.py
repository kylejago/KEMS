"""Regressions for alpha9.184 read-only performance and evidence changes."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import pytest

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"


def _evidence_module():
    source = KEMS / "kems_core" / "diagnostic_evidence.py"
    spec = importlib.util.spec_from_file_location(
        "kems_diagnostic_evidence_test", source
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_method_owner():
    source = ast.parse((KEMS / "agile_smart_export.py").read_text(encoding="utf-8"))
    owner = next(
        node
        for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "AgileSmartExportManager"
    )
    method = next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == "_set"
    )
    wrapper = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            ast.ClassDef(
                name="Manager",
                bases=[],
                keywords=[],
                body=[method],
                decorator_list=[],
            ),
        ],
        type_ignores=[],
    )
    namespace = {"perf_counter": perf_counter}
    exec(compile(ast.fix_missing_locations(wrapper), "<kems-set>", "exec"), namespace)
    return namespace["Manager"]


class FakeStates:
    def __init__(self):
        self.values = {}
        self.writes = 0
        self.raise_on_get = False

    def get(self, entity_id):
        if self.raise_on_get:
            raise RuntimeError("lookup temporarily failed")
        return self.values.get(entity_id)

    def async_set(self, entity_id, state, attributes):
        self.writes += 1
        self.values[entity_id] = SimpleNamespace(
            state=state, attributes=dict(attributes)
        )


@pytest.mark.parametrize(
    ("energy", "income", "expected"),
    [
        (0.0, 2.64, "positive_income_without_reported_export_energy"),
        (0.2, 0.0, "export_energy_without_reported_income"),
        (0.2, 3.1, "not_flagged"),
        (None, 3.1, "insufficient_observation"),
    ],
)
def test_export_reconciliation_never_invents_energy(energy, income, expected):
    evidence = _evidence_module()
    result = evidence.actual_export_evidence(energy, income)
    assert result["status"] == expected
    assert result["reported_actual_grid_export_kwh"] == energy
    assert result["reporting_only"] is True


def test_old_foxess_timestamps_are_labeled_only_when_accepted():
    evidence = _evidence_module()
    result = evidence.corroborated_unchanged_sources(
        {"battery_soc": 1956.4, "solar_power_kw": 1956.3, "grid_export_kw": 362.7},
        ("solar_power_kw",),
        180,
    )
    assert result["raw_age_over_timeout_accepted_by_device_cohort"] == [
        "battery_soc",
        "grid_export_kw",
    ]


def test_unsettled_reward_is_never_presented_as_supplier_paid():
    evidence = _evidence_module()
    result = evidence.reward_settlement_evidence(
        {
            "included_total_pence": 588.833934,
            "provisional_partial_pence": 270.624791,
            "meter_supported_estimate_pence": 318.209143,
            "supplier_settlement_available": False,
        }
    )
    assert result["status"] == "estimates_awaiting_supplier"
    assert result["supplier_settled_pence"] is None
    assert result["roi_included_estimate_pence"] == pytest.approx(588.833934)


def test_initial_comparison_skips_only_identical_read_only_state():
    Manager = _set_method_owner()
    manager = Manager()
    states = FakeStates()
    manager._hass = SimpleNamespace(states=states)
    manager._kems_suppress_identical_base_publication = True
    manager._kems_base_publication_stats = {"written": 0, "skipped_identical": 0}
    entity = "sensor.kems_agile_price_data_quality"

    manager._set(entity, "46/48", {"generated_at": "09:18"})
    manager._set(entity, "46/48", {"generated_at": "09:18"})
    assert states.writes == 1
    assert manager._kems_base_publication_stats == {
        "written": 1,
        "skipped_identical": 1,
    }

    # A changed timestamp, price, or SOC must still appear in this scan.
    manager._set(entity, "46/48", {"generated_at": "09:19"})
    assert states.writes == 2
    assert manager._kems_base_publication_stats["written"] == 2


def test_settlement_scope_and_direct_publisher_remain_unchanged():
    Manager = _set_method_owner()
    manager = Manager()
    states = FakeStates()
    manager._hass = SimpleNamespace(states=states)
    entity = "sensor.kems_agile_price_data_quality"
    manager._set(entity, "Ready", {})
    manager._set(entity, "Ready", {})
    assert states.writes == 2

    manager._kems_settlement_publication_scope = {
        "attempted": 0,
        "comparison_seconds": 0.0,
        "compared": 0,
        "skipped_identical": 0,
        "skipped_existing_identical": 0,
        "seen": set(),
        "written": 0,
    }
    manager._set(entity, "Ready", {})
    assert states.writes == 2
    assert manager._kems_settlement_publication_scope["skipped_identical"] == 1


def test_initial_comparison_fails_open_on_lookup_error():
    Manager = _set_method_owner()
    manager = Manager()
    states = FakeStates()
    states.raise_on_get = True
    manager._hass = SimpleNamespace(states=states)
    manager._kems_suppress_identical_base_publication = True
    manager._kems_base_publication_stats = {"written": 0, "skipped_identical": 0}
    manager._set("sensor.kems_agile_export_rate_now", 18.13, {"unit": "p/kWh"})
    assert states.writes == 1
    assert manager._kems_base_publication_stats["written"] == 1
