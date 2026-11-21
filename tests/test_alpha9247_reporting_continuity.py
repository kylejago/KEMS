"""Alpha9.247: advisory solar continuity and raw FoxESS provenance.

No test here changes site limits, physical write authority, tariff authority
or the commissioning/EV safety gates.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _load_pure(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manager_state_getter():
    module = ast.parse((KEMS / "agile_smart_export.py").read_text())
    manager_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "AgileSmartExportManager"
    )
    method = next(
        node
        for node in manager_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "state"
    )
    method.decorator_list = []
    namespace: dict[str, Any] = {}
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), "<manager_state>", "exec"),
        {"Any": Any},
        namespace,
    )
    return namespace["state"]


def test_solar_shadow_survives_replacing_agile_state():
    module = _load_pure(KEMS / "solar_routing_shadow.py", "solar_shadow_9247")

    class Manager:
        def __init__(self):
            self._state = {"ready": True}
            self._solar_routing_shadow_latest = {"status": "awaiting_first_evaluation"}
            self.published = []

        def _set(self, entity_id, value, attributes):
            self.published.append((entity_id, value, attributes))

    manager = Manager()
    initial = _manager_state_getter()(manager)
    assert initial["solar_routing_shadow"]["status"] == "awaiting_first_evaluation"
    result = {
        "status": "higher_priority",
        "reason": "Scheduled Force Discharge already active",
        "reporting_only": True,
        "hardware_writes": "forbidden",
        "generated_at": "2026-11-21T15:24:00+00:00",
    }
    module.publish_solar_routing_shadow(manager, result)
    assert manager.published[-1][0] == "sensor.kems_solar_routing_shadow"
    manager._state = {"ready": True, "current_action": "Force Discharge"}
    restored = _manager_state_getter()(manager)
    assert restored["solar_routing_shadow"] == result
    assert restored["current_action"] == "Force Discharge"
    assert restored["ready"] is True
    assert restored["solar_routing_shadow"]["hardware_writes"] == "forbidden"


def test_explicit_solar_failure_is_advisory_and_exposed():
    coordinator = (KEMS / "coordinator.py").read_text()
    diagnostics = (KEMS / "diagnostics.py").read_text()
    assert '"status": "evaluation_failed"' in coordinator
    assert '"error_type": type(exc).__name__' in coordinator
    assert '"hardware_writes": "forbidden"' in coordinator
    assert '"solar_routing_shadow_continuity": {' in diagnostics
    assert '"ha_state_matches_cached_status": (' in diagnostics
    assert '"source_freshness": {' in diagnostics


def test_raw_old_unchanged_sources_are_not_claimed_as_remeasured():
    module = _load_pure(
        KEMS / "kems_core" / "diagnostic_evidence.py",
        "diagnostic_evidence_9247",
    )
    result = module.corroborated_unchanged_sources(
        {
            "battery_power_kw": 12.3,
            "battery_soc": 112.3,
            "grid_export_kw": 12.3,
            "grid_import_kw": 1362.3,
            "house_load_kw": 12.3,
            "solar_power_kw": 1212.3,
        },
        (),
        180,
    )
    assert result["raw_age_over_timeout_accepted_by_device_cohort"] == [
        "grid_import_kw",
        "solar_power_kw",
    ]
    quality = result["raw_report_provenance"]
    assert quality["status"] == "unchanged_source_timestamps_old_but_cohort_accepted"
    for key in ("grid_import_kw", "solar_power_kw"):
        assert quality["fields"][key]["status"] == (
            "accepted_unchanged_by_device_cohort_not_remeasured"
        )
        assert quality["fields"][key]["physical_remeasurement_proven"] is False
    assert quality["fields"]["battery_power_kw"]["status"] == (
        "raw_timestamp_within_limit"
    )
    assert quality["reconfirmed_independent_physical_measurement_for_old_values"] is False
    assert quality["changes_control_freshness_or_foxess_commands"] is False


def test_stale_or_unknown_raw_sources_are_not_relabeled_corroborated():
    module = _load_pure(
        KEMS / "kems_core" / "diagnostic_evidence.py",
        "diagnostic_evidence_9247_stale",
    )
    result = module.corroborated_unchanged_sources(
        {"solar_power_kw": 800.0, "grid_import_kw": None},
        ("solar_power_kw",),
        180,
    )
    quality = result["raw_report_provenance"]
    assert quality["status"] == "one_or_more_sources_rejected_stale"
    assert result["raw_age_over_timeout_accepted_by_device_cohort"] == []
    assert quality["fields"]["solar_power_kw"]["status"] == "rejected_as_stale"
    assert quality["fields"]["grid_import_kw"]["status"] == "raw_timestamp_missing"


def test_advisory_bundle_does_not_promote_solar_pilot():
    source = (KEMS / "solar_routing_shadow.py").read_text()
    pilot = (KEMS / "solar_routing_pilot.py").read_text()
    assert 'manager._solar_routing_shadow_latest = dict(payload)' in source
    assert '"hardware_writes": "forbidden"' in source
    assert "independent" in pilot.lower()
    assert "work_mode" in pilot
