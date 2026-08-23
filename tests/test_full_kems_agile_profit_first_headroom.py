"""Regression contracts for profit-first forecast solar-headroom allocation."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
MODULE = KEMS / "agile_profit_first_headroom.py"
COMPAT = KEMS / "agile_alpha7_compat.py"


def _load_pure_helpers() -> dict[str, Any]:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    body = []
    wanted = {"_candidate_is_economic", "_rank_candidates"}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_EPSILON"
            for target in node.targets
        ):
            body.append(node)
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            body.append(node)
    namespace: dict[str, Any] = {
        "Any": Any,
        "datetime": datetime,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
            str(MODULE),
            "exec",
        ),
        namespace,
    )
    return namespace


def test_replacement_cost_is_the_headroom_candidate_floor() -> None:
    helpers = _load_pure_helpers()
    economic = helpers["_candidate_is_economic"]

    assert not economic(3.49, 3.50)
    assert economic(3.50, 3.50)
    assert economic(4.00, 3.50)
    assert economic(31.00, 3.50)


def test_pre_headroom_candidates_are_ranked_highest_price_first() -> None:
    helpers = _load_pure_helpers()
    rank = helpers["_rank_candidates"]
    candidates = [
        (12.0, datetime(2026, 8, 23, 7, 0, tzinfo=UTC), "12p", 2.0),
        (31.0, datetime(2026, 8, 23, 8, 0, tzinfo=UTC), "31p", 2.0),
        (24.0, datetime(2026, 8, 23, 6, 0, tzinfo=UTC), "24p", 2.0),
    ]

    assert [item[2] for item in rank(candidates)] == ["31p", "24p", "12p"]


def test_solar_forecast_is_timing_constraint_not_spill_price_threshold() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "Solar forecast is a timing constraint" in source
    assert "spill-period export price is retained as evidence" in source
    assert '"spill_price_is_candidate_threshold"] = False' in source
    assert "HEADROOM_MIN_PRICE_ADVANTAGE_PENCE" not in source
    assert "_candidate_is_economic(rate, floor_pence)" in source


def test_headroom_moves_existing_export_without_increasing_daily_export() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "Only re-time energy that was already due to be exported later" in source
    assert '"total_planned_battery_export_increased": False' in source
    assert "later planned export" in source
    assert "lowest-value" in source
    assert "sorted(\n        donors," in source


def test_profit_first_headroom_is_functionally_named_and_ordered() -> None:
    source = COMPAT.read_text(encoding="utf-8")
    forecast = '("agile_forecast_arbitrage", "install_forecast_arbitrage")'
    profit = '("agile_profit_first_headroom", "install_profit_first_headroom")'
    publication = '("agile_price_publication", "install_price_publication")'

    assert forecast in source
    assert profit in source
    assert publication in source
    assert source.index(forecast) < source.index(profit) < source.index(publication)
    assert "alpha8" not in MODULE.name


def test_profit_first_headroom_cannot_enable_hardware_writes() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "writes remain blocked" in source
