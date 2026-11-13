"""Alpha9.173: reward credit presentation is a read-only bill estimate."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha9173_test"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = ModuleType(PACKAGE)
package.__path__ = [str(KEMS_ROOT)]
sys.modules[PACKAGE] = package
_load(f"{PACKAGE}.product_types", KEMS_ROOT / "product_types.py")
models = _load(f"{PACKAGE}.kems_core.models", KEMS_ROOT / "kems_core" / "models.py")
core = ModuleType(f"{PACKAGE}.kems_core")
core.__path__ = [str(KEMS_ROOT / "kems_core")]
core.KEMSData = models.KEMSData
core.ScenarioSummary = models.ScenarioSummary
core.Snapshot = models.Snapshot
sys.modules[f"{PACKAGE}.kems_core"] = core
bill = _load(f"{PACKAGE}.energy_bill", KEMS_ROOT / "energy_bill.py")
audit = _load(
    f"{PACKAGE}.happy_hour_accounting_diagnostics",
    KEMS_ROOT / "happy_hour_accounting_diagnostics.py",
)


def _live(rows):
    stub = SimpleNamespace(
        snapshot=SimpleNamespace(electricity_standing_charge=40.0),
        gas=SimpleNamespace(standing_charge_pence=0.0),
    )
    return bill._live(rows, {date(2026, 11, 1)}, {}, {}, stub, True)


def test_verified_day_rate_import_is_effectively_free_but_gross_remains() -> None:
    row = {
        "import_cost_pence": 358.8,
        "happy_hour_estimated_credit_pence": 358.8,
        "happy_hour_credited_import_kwh": 10.0,
        "export_income_pence": 0,
        "grid_import_kwh": 10.0,
    }
    result = _live([row])
    assert result["electricity_import_cost_pence"] == 358.8
    assert result["happy_hour_estimated_credit_pence"] == 358.8
    assert result["happy_hour_credited_import_kwh"] == 10.0
    assert result["electricity_effective_import_cost_pence"] == 0.0
    assert result["electricity_standing_charge_pence"] == 40.0
    assert result["electricity_total_cost_pence"] == 398.8
    assert result["electricity_effective_total_cost_pence"] == 40.0
    assert result["total_energy_effective_cost_pence"] == 40.0
    assert result["happy_hour_supplier_settled"] is False


def test_partial_refund_keeps_non_reward_import_and_export_earnings() -> None:
    result = _live(
        [
            {
                "import_cost_pence": 600.0,
                "happy_hour_estimated_credit_pence": 261.729,
                "happy_hour_credited_import_kwh": 7.294,
                "export_income_pence": 100.0,
            }
        ]
    )
    assert result["electricity_import_cost_pence"] == 600.0
    assert result["electricity_effective_import_cost_pence"] == 338.27
    assert result["electricity_effective_total_cost_pence"] == 278.27
    assert result["electricity_total_cost_pence"] == 540.0


def test_period_aggregate_sums_daily_receipts_without_double_credit() -> None:
    result = _live(
        [
            {
                "import_cost_pence": 200,
                "happy_hour_estimated_credit_pence": 120,
                "happy_hour_credited_import_kwh": 5.0,
            },
            {
                "import_cost_pence": 300,
                "happy_hour_estimated_credit_pence": 150,
                "happy_hour_credited_import_kwh": 6.0,
            },
        ]
    )
    assert result["happy_hour_estimated_credit_pence"] == 270.0
    assert result["happy_hour_credited_import_kwh"] == 11.0
    assert result["electricity_effective_import_cost_pence"] == 230.0


def test_bad_or_excess_credit_cannot_make_import_negative() -> None:
    result = _live(
        [
            {
                "import_cost_pence": 100.0,
                "happy_hour_estimated_credit_pence": 999.0,
            }
        ]
    )
    assert result["electricity_effective_import_cost_pence"] == 0.0
    assert result["happy_hour_estimated_credit_pence"] == 100.0


def test_no_reward_never_changes_regular_bill() -> None:
    result = _live([{"import_cost_pence": 100.0, "export_income_pence": 50.0}])
    assert result["happy_hour_estimated_credit_pence"] == 0.0
    assert result["electricity_effective_import_cost_pence"] == 100.0
    assert (
        result["electricity_effective_total_cost_pence"]
        == result["electricity_total_cost_pence"]
    )


def test_evidence_audit_exposes_merges_and_missing_physical_proof() -> None:
    start = datetime(2026, 11, 1, 12, tzinfo=UTC)
    second = start + timedelta(hours=1)
    end = second + timedelta(hours=1)
    status = {
        "last_sample": (second + timedelta(minutes=48)).isoformat(),
        "persisted_reward_windows": [
            {
                "start": start.isoformat(),
                "end": second.isoformat(),
                "event_id": "first",
            },
            {"start": second.isoformat(), "end": end.isoformat(), "event_id": "second"},
            {"start": start.isoformat(), "end": end.isoformat()},
        ],
    }
    saved = [
        {
            "start": start.isoformat(),
            "end": second.isoformat(),
            "import_kwh": 7.294,
            "credit_pence": 261.729,
            "completed": True,
        }
    ]
    result = audit.build_happy_hour_accounting_audit(status, saved)
    states = {item["status"] for item in result["hour_evidence"]}
    assert states == {
        "verified_saved_receipt",
        "booking_verified_but_meter_or_tariff_proof_incomplete",
        "grouped_window_not_independent_reward_proof",
    }
    assert result["completed_verified_receipts"] == 1
    assert result["recorded_unverified_windows"] == 2
    assert result["supplier_credit_settled"] is False
    assert result["physical_meter_last_saved_sample"] == status["last_sample"]
    assert (
        sum(item["saved_credit_pence"] or 0 for item in result["hour_evidence"])
        == 261.729
    )


def test_dashboard_and_bill_views_use_shared_effective_cost_without_repricing() -> None:
    dash = (KEMS_ROOT / "kems_master_dashboard.yaml").read_text()
    presentation = (KEMS_ROOT / "energy_bill_presentation.py").read_text()
    diagnostics = (KEMS_ROOT / "diagnostics.py").read_text()
    assert "live.get('total_energy_effective_cost_pence')" in dash
    assert "live.get('happy_hour_estimated_credit_pence')" in dash
    assert "live.get('total_energy_effective_cost_pence')" in presentation
    assert "happy_hour_accounting_audit" in diagnostics
    assert "sensor.kems_happy_hour_estimated_import_credit_today')" not in dash
    assert "0.9.0-alpha9.202" in (KEMS_ROOT / "manifest.json").read_text()
