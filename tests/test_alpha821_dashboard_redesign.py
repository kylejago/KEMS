"""Alpha8.21 managed-dashboard redesign regressions."""

from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"
ENERGY_BILL = ROOT / "custom_components" / "kems" / "energy_bill.py"


def _view(title: str) -> dict:
    parsed = yaml.safe_load(PACKAGED.read_text(encoding="utf-8"))
    return next(view for view in parsed["views"] if view["title"] == title)


def _bounds_function():
    tree = ast.parse(ENERGY_BILL.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_bounds"
    )
    namespace = {"date": date, "timedelta": timedelta}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
            str(ENERGY_BILL),
            "exec",
        ),
        namespace,
    )
    return namespace["_bounds"]


def test_dashboard_has_requested_customer_navigation_and_exact_packaging() -> None:
    assert SOURCE.read_bytes() == PACKAGED.read_bytes()
    parsed = yaml.safe_load(PACKAGED.read_text(encoding="utf-8"))
    assert [view["path"] for view in parsed["views"]] == [
        "home",
        "live-data",
        "kems",
        "compare",
        "tomorrow",
        "history",
        "system",
    ]
    assert "path: agile-slots" not in PACKAGED.read_text(encoding="utf-8")


def test_live_and_kems_pages_have_matching_core_graphs() -> None:
    live = _view("Live Data")
    kems = _view("KEMS")

    def graph_titles(view: dict) -> set[str]:
        titles: set[str] = set()

        def walk(value) -> None:
            if isinstance(value, dict):
                if value.get("type") == "history-graph":
                    titles.add(str(value.get("title")))
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(view)
        return titles

    expected = {
        "House demand",
        "Grid import",
        "Grid export",
        "Solar",
        "Battery power",
        "Battery SOC",
        "Energy cost",
    }
    assert expected <= graph_titles(live)
    assert expected <= graph_titles(kems)


def test_today_slots_live_on_kems_and_tomorrow_slots_live_on_tomorrow() -> None:
    kems = yaml.safe_dump(_view("KEMS"), sort_keys=False)
    tomorrow = yaml.safe_dump(_view("Tomorrow"), sort_keys=False)
    assert "today_slots" in kems
    assert "tomorrow_slots" not in kems
    assert "tomorrow_slots" in tomorrow
    assert "today_slots" not in tomorrow
    for label in ("00:00 to 07:30", "08:00 to 15:30", "16:00 to 23:30"):
        assert label in kems
        assert label in tomorrow


def test_compare_is_three_column_no_system_live_kems_view() -> None:
    compare = _view("Compare")
    content = yaml.safe_dump(compare, sort_keys=False)
    assert "columns: 3" in content
    for title in ("Without KEMS", "Live", "KEMS"):
        assert f"title: {title}" in content
    assert "sensor.kems_compare_no_system_cost_today" in content
    assert "Live system value vs no system" in content
    assert "KEMS potential value vs no system" in content


def test_history_has_requested_calendar_periods() -> None:
    history = yaml.safe_dump(_view("History"), sort_keys=False)
    for title in (
        "Yesterday",
        "This Week",
        "Last Week",
        "This Month",
        "Last Month",
        "This Year",
        "All time",
    ):
        assert f"title: {title}" in history
    for key in ("this_week", "last_week", "this_month", "last_month"):
        assert key in history

    bounds = _bounds_function()
    today = date(2026, 8, 25)
    assert bounds("this_week", today, set()) == (date(2026, 8, 24), today)
    assert bounds("last_week", today, set()) == (
        date(2026, 8, 17),
        date(2026, 8, 23),
    )
    assert bounds("this_month", today, set()) == (date(2026, 8, 1), today)
    assert bounds("last_month", today, set()) == (
        date(2026, 7, 1),
        date(2026, 7, 31),
    )


def test_system_page_is_compact_and_update_history_is_bounded() -> None:
    system = yaml.safe_dump(_view("System"), sort_keys=False)
    assert "title: Health" in system
    assert "title: Control safety" in system
    assert "title: Update" in system
    assert "Recent updates — latest 5" in system
    assert "[0:5]" in system
    assert "Real inverter writes remain blocked" not in system
    assert "Physical control remains locked" in system
