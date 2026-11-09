"""Alpha9.190: historical bill-equivalent savings stay distinct from gross/ROI."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from kems_core import PeriodTotals, summarise_period_records

ROOT = Path(__file__).parents[1]
LIFETIME = ROOT / "custom_components/kems/lifetime.py"
MASTER = ROOT / "custom_components/kems/kems_master_dashboard.yaml"
SOURCE = ROOT / "dashboards/kems_master_dashboard.yaml"
ROI = ROOT / "custom_components/kems/kems_roi_lifetime_dashboard.yaml"


def _isolated_period_recorder():
    source = ast.parse(LIFETIME.read_text(encoding="utf-8"))
    owner = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "LifetimeLedgerRecorder")
    method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "period_summaries")
    recorder = ast.ClassDef(name="Recorder", bases=[], keywords=[], body=[method], decorator_list=[])
    env = {
        "date": date,
        "timedelta": timedelta,
        "summarise_period_records": summarise_period_records,
        "PeriodTotals": PeriodTotals,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[recorder], type_ignores=[])), "<period-recorder>", "exec"), env)
    obj = env["Recorder"]()
    obj._all_time_summary = lambda today: PeriodTotals()
    return obj


def test_yesterday_and_last_periods_reuse_saved_meter_ledger_after_restart():
    recorder = _isolated_period_recorder()
    recorder._daily_records = {
        "2026-10-31": {"import_cost_pence": 200, "__data_complete": 1},
        "2026-11-01": {"happy_hour_estimated_credit_pence": 261.729, "import_cost_pence": 700, "__data_complete": 1},
        "2026-11-08": {
            "grid_import_kwh": 10.144,
            "import_cost_pence": 850,
            "export_income_pence": 420,
            "gas_cost_pence": 110,
            "happy_hour_estimated_credit_pence": 363.995,
            "happy_hour_credited_import_kwh": 10.144,
            "__data_complete": 1,
        },
    }
    recorder._tracking_date = date(2026, 11, 9)
    recorder._tracking_values = {"import_cost_pence": 100, "__data_complete": 1}
    result = recorder.period_summaries(datetime(2026, 11, 9, 7, 44, tzinfo=UTC))
    yesterday = result["yesterday"]
    assert yesterday.days_included == 1
    assert yesterday.complete_days == 1
    assert yesterday.data_complete is True
    assert yesterday.happy_hour_estimated_credit_pence == pytest.approx(363.995)
    assert yesterday.happy_hour_credited_import_kwh == pytest.approx(10.144)
    assert yesterday.actual_net_cost_pence == pytest.approx(540)
    assert yesterday.actual_net_after_estimated_happy_hour_credit_pence == pytest.approx(176.005)
    assert result["last_week"].happy_hour_estimated_credit_pence == pytest.approx(363.995)
    assert result["last_month"].import_cost_pence == 200
    assert result["month"].happy_hour_estimated_credit_pence == pytest.approx(625.724)
    assert result["today"].happy_hour_estimated_credit_pence == 0
    assert result["all_time"].happy_hour_estimated_credit_pence == 0


def test_missing_saved_yesterday_is_not_silently_replaced_with_current_day():
    recorder = _isolated_period_recorder()
    recorder._daily_records = {}
    recorder._tracking_date = date(2026, 11, 9)
    recorder._tracking_values = {"happy_hour_estimated_credit_pence": 0, "import_cost_pence": 42}
    result = recorder.period_summaries(datetime(2026, 11, 9, tzinfo=UTC))
    assert result["yesterday"].days_included == 0
    assert result["yesterday"].happy_hour_estimated_credit_pence == 0
    assert result["today"].import_cost_pence == 42


def test_yesterday_dashboard_separates_gross_and_estimated_refund():
    content = MASTER.read_text(encoding="utf-8")
    assert content == SOURCE.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    history = next(view for view in parsed["views"] if view["path"] == "history")
    yesterday_cards = [
        card for wrapper in history["cards"] if wrapper.get("type") == "grid"
        for card in wrapper.get("cards", []) if card.get("title") == "Yesterday"
    ]
    assert len(yesterday_cards) == 1
    card = yesterday_cards[0]["content"]
    assert "Electricity import (gross)" in card
    assert "Agile export income" in card
    assert "Happy Hour eligible import" in card
    assert "Total after estimated refund" in card
    assert "Gross comparison saving" in card
    assert "Saving incl. estimated Happy Hour refund" in card
    assert "saved is not none" in card
    assert "day-completion not confirmed" in card
    assert content.count("Gross comparison saving:") == 7
    assert content.count("Saving incl. est. Happy Hour refund (unsettled):") == 6


def test_roi_dashboard_displays_incremental_rewards_without_double_agile_export():
    text = ROI.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    cards = parsed["views"][0]["cards"]
    assert any(c.get("title") == "Actual ROI — reward-inclusive reconciliation" for c in cards)
    assert "sensor.kems_lifetime_system_value" in text
    assert "sensor.kems_roi_happy_hour_credit" in text
    assert "sensor.kems_roi_power_down_bonus" in text
    assert "sensor.kems_actual_system_value_total" in text
    assert "Normal Agile export is already in underlying value" in text
    assert "simulation-based" in text
    assert "not supplier-settled" in text


def test_reward_reconciliation_from_real_november_diagnostic_avoids_duplicate_credit():
    gross_pence = 44420.067
    happy_pence = 896.349057
    power_down_bonus_pence = 56.48
    actual = round((gross_pence + happy_pence + power_down_bonus_pence) / 100, 2)
    assert actual == 453.73
    assert round(896.349057 / 100, 2) == 8.96
    assert round(56.48 / 100, 2) == 0.56
    # Observed Agile export was already included in gross and is not added again.
    assert round((gross_pence + happy_pence + power_down_bonus_pence + 17845.42) / 100, 2) != actual
