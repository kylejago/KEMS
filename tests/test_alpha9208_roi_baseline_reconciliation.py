"""Alpha9.208: source-consistent no-system baseline for live ROI parity."""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
HELPER = KEMS / "kems_core" / "compare_roi_baseline.py"


def _comparison():
    spec = importlib.util.spec_from_file_location("roi_compare_helper", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compare_no_system_cost_today


def _data(**changes):
    day = date(2026, 11, 16)
    scenario = SimpleNamespace(
        ready=True,
        total_cost_pence=341.51,
        import_cost_pence=285.99,
        standing_charge_pence=55.52,
    )
    default = {
        "scenarios": SimpleNamespace(
            scenario=lambda name: scenario if name == "no_system" else None
        ),
        "simulation": SimpleNamespace(
            ready=True,
            baseline_no_system_cost_pence=290.15,
            actual_import_cost_pence=303.13,
            actual_export_income_pence=0.08,
        ),
        "periods": {
            "today": SimpleNamespace(
                start_date=day,
                end_date=day,
                days_included=1,
                import_cost_pence=303.13,
                export_income_pence=0.08,
                actual_avoided_import_value_pence=-12.98,
                actual_system_value_pence=-12.90,
            )
        },
        "snapshot": SimpleNamespace(timestamp=datetime(2026, 11, 16, 8, 51, tzinfo=UTC)),
    }
    default.update(changes)
    return SimpleNamespace(**default)


def test_diagnostic_reconciles_actual_4p_baseline_gap_without_rewriting_live() -> None:
    compare = _comparison()
    data = _data()
    result = compare(data)
    assert result["total_cost_pence"] == pytest.approx(345.67)
    assert result["scenario_replay_cost_pence"] == pytest.approx(341.51)
    assert result["roi_vs_replay_difference_pence"] == pytest.approx(4.16)
    assert result["comparison_cost_basis"] == "roi_meter_sampled_baseline"
    # Gross import 303.13p, export 0.08p, electricity standing 55.52p,
    # gas 72p. Counterfactual minus live exactly matches accrued ROI today.
    live_bill = 303.13 - 0.08 + 55.52 + 72.0
    no_system_bill = result["total_cost_pence"] + 72.0
    assert no_system_bill - live_bill == pytest.approx(-12.90)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"simulation": SimpleNamespace(ready=False)}, "roi_daily_evidence_unavailable"),
        ({"periods": {}}, "roi_daily_evidence_unavailable"),
        (
            {"snapshot": SimpleNamespace(timestamp=datetime(2026, 11, 17, 0, 0, tzinfo=UTC))},
            "daily_rollover_or_period_mismatch",
        ),
    ],
)
def test_incomplete_or_cross_day_evidence_falls_back_without_fake_parity(
    mutation, expected
) -> None:
    result = _comparison()(_data(**mutation))
    assert result["total_cost_pence"] == 341.51
    assert result["comparison_cost_basis"] == "scenario_replay_unreconciled"
    assert result["comparison_basis_reason"] == expected


def test_mismatched_live_import_does_not_get_silently_adjusted() -> None:
    data = _data()
    data.simulation.actual_import_cost_pence = 321.12
    result = _comparison()(data)
    assert result["total_cost_pence"] == 341.51
    assert result["comparison_basis_reason"] == "roi_and_live_ledger_not_synchronised"


def test_nonfinite_baseline_and_missing_scenario_are_not_invented() -> None:
    data = _data()
    data.simulation.baseline_no_system_cost_pence = float("nan")
    assert _comparison()(data)["comparison_basis_reason"] == "nonfinite_or_missing_financial_evidence"
    data.scenarios.scenario = lambda key: None
    assert _comparison()(data)["total_cost_pence"] is None


def test_happy_hour_credit_does_not_get_copied_into_baseline() -> None:
    data = _data()
    data.periods["today"].happy_hour_estimated_credit_pence = 474.048
    result = _comparison()(data)
    assert result["total_cost_pence"] == 345.67
    assert "reward" not in result["comparison_cost_basis"]


def test_dashboard_sources_and_final_compatibility_card_share_source_authority() -> None:
    master = (ROOT / "dashboards" / "kems_master_dashboard.yaml").read_text()
    packaged = (KEMS / "kems_master_dashboard.yaml").read_text()
    repair = (KEMS / "alpha937_dashboard_contract.py").read_text()
    sensor = (KEMS / "sensor.py").read_text()
    assert master == packaged
    assert "roi_meter_sampled_baseline" in master
    assert "compare_no_system_cost_today(data)" in sensor
    assert "No-system uses the same measured-history baseline" not in master
    assert "same measured-history baseline as ROI when source evidence matches" in repair
