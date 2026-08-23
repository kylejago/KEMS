"""Alpha8.9 contracts for truthful Agile decision evidence and profit-first ranking."""

from __future__ import annotations

import ast
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
EVIDENCE = KEMS / "agile_decision_evidence.py"
ROLLING = KEMS / "agile_rolling_replan_runtime.py"
HISTORICAL_ROLLING = KEMS / "agile_rolling_replan.py"
COMPAT = KEMS / "agile_alpha7_compat.py"


def _load_functions(path: Path, names: set[str], constants: set[str] | None = None):
    """Execute selected pure helpers without importing Home Assistant."""
    constants = constants or set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            body.append(node)
            continue
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constants
            for target in node.targets
        ):
            body.append(node)
            continue
        if isinstance(node, ast.FunctionDef) and node.name in names:
            body.append(node)
    namespace = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "timedelta": timedelta,
        "math": math,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
            str(path),
            "exec",
        ),
        namespace,
    )
    return namespace


def test_past_future_placeholder_is_reported_as_missing_evidence_not_hold() -> None:
    helpers = _load_functions(
        EVIDENCE,
        {"_actions", "_classify_slot"},
        {"_MISSING_DECISION", "_NO_LIVE_PLAN"},
    )
    classify = helpers["_classify_slot"]

    result = classify(
        {
            "status": "past",
            "decision": "Hold battery / normal solar",
            "valid_from": "2026-08-23T15:00:00+00:00",
        },
        {"actions": ["future slot"], "rate_pence": 21.57},
        rolling_available=True,
    )

    assert result["decision"] == "No KEMS decision recorded — runtime/data gap"
    assert result["decision_source"] == "missing_historical_evidence"
    assert result["evidence_available"] is False
    assert result["evidence_label"] == "No retained KEMS sample"


def test_genuine_recorded_historical_hold_remains_a_recorded_outcome() -> None:
    helpers = _load_functions(
        EVIDENCE,
        {"_actions", "_classify_slot"},
        {"_MISSING_DECISION", "_NO_LIVE_PLAN"},
    )
    classify = helpers["_classify_slot"]

    result = classify(
        {"status": "past", "decision": "Hold battery / normal solar"},
        {"actions": [], "ending_soc_percent": 72.0},
        rolling_available=True,
    )

    assert result["decision"] == "Hold battery / normal solar"
    assert result["decision_source"] == "historical_simulation"
    assert result["evidence_available"] is True
    assert result["evidence_label"] == "Recorded simulation"


def test_known_future_slot_without_live_plan_is_not_presented_as_a_hold() -> None:
    helpers = _load_functions(
        EVIDENCE,
        {"_actions", "_classify_slot"},
        {"_MISSING_DECISION", "_NO_LIVE_PLAN"},
    )
    classify = helpers["_classify_slot"]

    result = classify(
        {"status": "future", "decision": "Hold battery / normal solar routing"},
        {"actions": ["future slot"], "rate_pence": 21.57},
        rolling_available=False,
    )

    assert result["decision"] == "Waiting for live rolling plan — no decision published"
    assert result["decision_source"] == "rolling_plan_unavailable"
    assert result["evidence_available"] is False
    assert result["evidence_label"] == "No live plan"


def _load_rolling_plan(deadline: datetime):
    names = {
        "_number",
        "_datetime",
        "_current_agile_soc",
        "_predicted_house_until_deadline",
        "_current_house_headroom_kw",
        "_rolling_plan",
    }
    namespace = _load_functions(
        ROLLING,
        names,
        {"SAFETY_HEADROOM_MINUTES", "_EPSILON"},
    )
    namespace["agile"] = SimpleNamespace(_next_cheap=lambda now, tariff: deadline)
    namespace["_effective_deadline_kw"] = lambda config: 7.0
    namespace["_target_percent"] = lambda config: 10.0
    namespace["SimulationConfig"] = Any
    namespace["TariffSettings"] = Any
    return namespace["_rolling_plan"]


def _slot(start: datetime, label: str, rate: float) -> dict[str, Any]:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "label": label,
        "rate_pence": rate,
        "actions": ["future slot"],
    }


def test_23_august_prices_prefer_high_feasible_slots() -> None:
    """Regression for the table that exposed the misleading 23 August presentation."""
    now = datetime(2026, 8, 23, 14, 30, tzinfo=UTC)
    deadline = datetime(2026, 8, 23, 22, 30, tzinfo=UTC)
    rolling_plan = _load_rolling_plan(deadline)
    prices = [
        ("15:30", 12.79),
        ("16:00", 21.57),
        ("16:30", 21.08),
        ("17:00", 21.31),
        ("17:30", 22.44),
        ("18:00", 23.30),
        ("18:30", 23.64),
        ("19:00", 16.36),
        ("19:30", 16.36),
        ("20:00", 16.45),
        ("20:30", 16.36),
        ("21:00", 16.45),
        ("21:30", 15.97),
        ("22:00", 15.69),
        ("22:30", 14.59),
        ("23:00", 12.36),
    ]
    slots = [
        _slot(now + timedelta(minutes=30 * index), label, rate)
        for index, (label, rate) in enumerate(prices)
    ]

    capacity_kwh = 56.42
    target_kwh = capacity_kwh * 0.10
    desired_export_kwh = 21.0
    soc_percent = (target_kwh + desired_export_kwh) / capacity_kwh * 100.0
    state = {
        "periods": {
            "today": {
                "agile_smart_export": {"ending_soc_percent": soc_percent},
            }
        },
        "today_slots": slots,
    }
    config = SimpleNamespace(
        battery_capacity_kwh=capacity_kwh,
        discharge_efficiency=1.0,
        max_discharge_kw=7.0,
    )
    manager = SimpleNamespace(
        _rolling_predicted_house_kwh=0.0,
        _panel_today_records=[],
    )

    plan = rolling_plan(manager, state, now=now, config=config, tariff=object())
    selected = [item["label"] for item in plan["selected_slots"]]

    assert plan["required_in_current_slot_kwh"] == 0.0
    assert selected == ["16:00", "16:30", "17:00", "17:30", "18:00", "18:30"]
    assert "15:30" not in selected
    assert "20:30" not in selected
    assert "21:00" not in selected
    assert "23:00" not in selected


def test_decision_evidence_reporting_only_and_rolling_runtime_frozen() -> None:
    evidence = EVIDENCE.read_text(encoding="utf-8")
    compat = COMPAT.read_text(encoding="utf-8")

    assert ROLLING.read_bytes() == HISTORICAL_ROLLING.read_bytes()
    assert 'key=lambda value: value["rate"], reverse=True' in ROLLING.read_text(
        encoding="utf-8"
    )
    assert '("agile_dashboard_parity", "install_dashboard_parity")' in compat
    assert '("agile_decision_evidence", "install_decision_evidence")' in compat
    assert compat.index(
        '("agile_dashboard_parity", "install_dashboard_parity")'
    ) < compat.index('("agile_decision_evidence", "install_decision_evidence")')
    assert "| Evidence |" in evidence
    assert ".services.async_call(" not in evidence
    assert "providers.foxess" not in evidence
    assert "Real hardware writes remain blocked" in evidence
