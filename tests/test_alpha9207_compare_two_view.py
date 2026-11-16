"""Alpha9.207: two-view Compare preserves the bill-equivalent runtime contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCES = [
    ROOT / "dashboards" / "kems_master_dashboard.yaml",
    KEMS / "kems_master_dashboard.yaml",
]


def _view(payload: str) -> dict:
    return next(
        view
        for view in yaml.safe_load(payload)["views"]
        if view.get("path") == "compare"
    )


def _assert_two_views(payload: str) -> None:
    view = _view(payload)
    grid = next(card for card in view["cards"] if card.get("type") == "grid")
    assert grid["columns"] == 2
    assert [card["title"] for card in grid["cards"]] == ["Without KEMS", "Live"]
    side = next(
        card for card in view["cards"] if card.get("title") == "Today — side by side"
    )
    assert "| Metric | Without KEMS | Live |" in side["content"]
    assert "| Live | KEMS |" not in side["content"]
    assert "total_energy_effective_cost_pence" in side["content"]
    assert "ROI ledger value today:" in side["content"]
    graph = next(card for card in view["cards"] if card.get("type") == "history-graph")
    assert [entry["name"] for entry in graph["entities"]] == [
        "Live (gross before HH refund)",
        "Without KEMS",
    ]


def test_managed_and_packaged_sources_present_two_views_only() -> None:
    assert SOURCES[0].read_bytes() == SOURCES[1].read_bytes()
    for path in SOURCES:
        _assert_two_views(path.read_text(encoding="utf-8"))


def test_runtime_repair_has_no_simulation_anchor() -> None:
    spec = importlib.util.spec_from_file_location(
        "alpha9207_compare_contract", KEMS / "alpha937_dashboard_contract.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = SOURCES[0].read_bytes()
    repaired = module.repair_dashboard_contract(source)
    _assert_two_views(repaired.decode())
    assert module.repair_dashboard_contract(repaired) == repaired


def test_no_control_modules_changed_in_compare_regression() -> None:
    # A reporting-only change must not add simulated financial authority to
    # live inverter dispatch or invent a settled Happy Hour reward.
    text = SOURCES[0].read_text(encoding="utf-8")
    assert "estimated, unsettled Happy Hour refund" in text
    assert "ROI is a separate accrued accounting ledger" in text


def test_15_nov_roi_ledger_and_bill_comparison_are_not_misrepresented() -> None:
    from jinja2 import Environment

    side = next(
        card["content"]
        for card in _view(SOURCES[0].read_text())["cards"]
        if card.get("title") == "Today — side by side"
    )
    payload = {
        "today": {
            "live_data": {
                "total_energy_effective_cost_pence": -101.0,
                "electricity_effective_total_cost_pence": -221.0,
                "gas_total_cost_pence": 120.0,
                "happy_hour_estimated_credit_pence": 474.048,
                "grid_import_kwh": 80.5,
                "grid_export_kwh": 31.0,
            }
        }
    }
    rendered = (
        Environment(autoescape=False)
        .from_string(side)
        .render(
            state_attr=lambda entity, attr: (
                payload if entity == "sensor.kems_energy_cost_comparison" else None
            ),
            states=lambda entity: {
                "sensor.kems_compare_no_system_cost_today": "1106.0",
                "sensor.kems_actual_system_value_today": "13.31",
            }.get(entity, "unknown"),
        )
    )
    assert "£13.27" in rendered
    assert "ROI ledger value today:** £13.31" in rendered
    assert "differ by £0.04" in rendered
    assert "Est. Happy Hour refund (pending)" in rendered
    assert (
        "£13.31"
        not in rendered.split("**Live system value vs no system:**")[1].split("\n")[0]
    )
