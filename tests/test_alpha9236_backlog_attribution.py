"""Alpha9.236: explain startup cost, unproven gaps and export scope safely."""

from __future__ import annotations

import ast
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "kems_core" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gap_priority_excludes_only_recorded_correspondence() -> None:
    module = _load("kems_alpha9236_gaps", "history_gap_provenance.py")
    start = datetime(2026, 11, 19, 10, tzinfo=UTC)
    snapshots = [
        SimpleNamespace(timestamp=start),
        SimpleNamespace(timestamp=start + timedelta(minutes=20)),
        SimpleNamespace(timestamp=start + timedelta(minutes=35)),
        SimpleNamespace(timestamp=start + timedelta(minutes=40)),
    ]
    recorded_update = [
        {
            "result": "success",
            "target": "0.9.0-alpha9.235",
            "completed_at": (start + timedelta(minutes=34)).isoformat(),
        }
    ]
    result = module.history_gap_provenance(
        records=snapshots,
        update_history=recorded_update,
        ledger_audit={
            "recent_days": [
                {
                    "date": "2026-11-19",
                    "recorded_totals_available": True,
                    "simulation_replay_complete": False,
                }
            ]
        },
        now=start + timedelta(hours=1),
    )
    assert result["days"][0]["gaps_over_10_minutes"] == 2
    assert result["gaps_without_recorded_correspondence"] == 1
    assert result["largest_unattributed_observation_gaps"] == [
        {
            "date": "2026-11-19",
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=20)).isoformat(),
            "gap_seconds": 1200,
            "recorded_restart_correspondence": False,
            "physical_import_export_kwh": None,
        }
    ]
    assert result["largest_unattributed_observation_gaps_omitted"] == 0
    assert result["days"][0]["simulation_replay_complete"] is False
    assert result["restart_cause_proven"] is False


def test_gap_priority_does_not_treat_missing_marker_as_proof_of_no_restart() -> None:
    module = _load("kems_alpha9236_gaps_other", "history_gap_provenance.py")
    start = datetime(2026, 11, 19, 9, tzinfo=UTC)
    result = module.history_gap_provenance(
        records=[
            SimpleNamespace(timestamp=start),
            SimpleNamespace(timestamp=start + timedelta(minutes=15)),
        ],
        update_history=[],
        lifecycle_events=[],
        ledger_audit={"recent_days": []},
        now=start + timedelta(hours=1),
    )
    assert result["gaps_without_recorded_correspondence"] == 1
    assert result["largest_unattributed_observation_gaps"][0][
        "physical_import_export_kwh"
    ] is None
    assert "does not prove no restart" in result["unattributed_gap_note"]


def test_export_triage_separates_ordinary_agile_from_verified_power_down() -> None:
    module = _load("kems_alpha9236_export", "diagnostic_evidence.py")
    start = datetime(2026, 11, 19, 17, tzinfo=UTC)
    slots = [
        {
            "valid_from": (start + timedelta(minutes=30 * index)).isoformat(),
            "valid_to": (start + timedelta(minutes=30 * (index + 1))).isoformat(),
            "grid_export_kwh": shadow,
            "rate_pence": 18.41,
            "settlement_source": "settled shadow digital-twin outcome",
        }
        for index, shadow in enumerate([0.0, 0.0, 0.25])
    ]
    records = [
        SimpleNamespace(
            timestamp=start + timedelta(minutes=30 * index),
            grid_export_kw=power,
            stale_fields=(),
        )
        for index, power in enumerate([2.0, 2.0, 0.0, 0.0])
    ]
    result = module.agile_export_interval_audit(
        now=start + timedelta(minutes=95),
        agile_state={"today_slots": slots},
        records=records,
        reported_grid_export_kwh=2.0,
        reported_income_pence=18.41,
        activation_cutoff="2026-11-19T00:00:00+00:00",
        completed_power_down={
            "completed_successfully": True,
            "physical_export_verified": True,
            "session_start": start.isoformat(),
            "session_end": (start + timedelta(hours=1)).isoformat(),
        },
    )
    assert result["verified_power_down_overlap_settled_slots"] == 2
    assert result["non_power_down_completed_settled_slots"] == 1
    assert result["top_non_power_down_variance_rows_omitted"] == 0
    ordinary = result["top_non_power_down_variance_rows"]
    assert len(ordinary) == 1
    assert ordinary[0]["shadow_minus_snapshot_kwh"] == 0.25
    assert ordinary[0]["independent_supplier_meter_verified"] is False
    assert result["reporting_only"] is True


def test_startup_diagnostics_are_bounded_observation_only() -> None:
    coordinator = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    manager = (ROOT / "agile_smart_export.py").read_text(encoding="utf-8")
    ast.parse(coordinator)
    ast.parse(manager)
    assert "agile_manager_wrapper_thread_cpu_seconds" in coordinator
    assert "agile_manager_wrapper_non_cpu_seconds" in coordinator
    assert "historical_cache_hits_this_pass" in manager
    assert "historical_cache_misses_this_pass" in manager
    assert "historical_cache_fingerprint_seconds_this_pass" in manager
    assert "manager_base_thread_cpu_seconds" in manager
