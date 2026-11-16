"""Alpha9.207: two-column Compare stays bill-equivalent through runtime compatibility."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCES = [ROOT / "dashboards" / "kems_master_dashboard.yaml", KEMS / "kems_master_dashboard.yaml"]


def _view(payload: str) -> dict:
    return next(
        view for view in yaml.safe_load(payload)["views"] if view.get("path") == "compare"
    )


def _assert_two_views(payload: str) -> None:
    view = _view(payload)
    grid = next(card for card in view["cards"] if card.get("type") == "grid")
    assert grid["columns"] == 2
    assert [card["title"] for card in grid["cards"]] == ["Without KEMS", "Live"]
    side = next(card for card in view["cards"] if card.get("title") == "Today — side by side")
    assert "| Metric | Without KEMS | Live |" in side["content"]
    assert "| Live | KEMS |" not in side["content"]
    assert "total_energy_effective_cost_pence" in side["content"]
    assert "ROI ledger value today:" in side["content"]
    graph = next(card for card in view["cards"] if card.get("type") == "history-graph")
    assert [entry["name"] for entry in graph["entities"]] == [
        "Live (gross before HH refund)", "Without KEMS"
    ]


def test_managed_and_packaged_sources_present_two_views_only() -> None:
    assert SOURCES[0].read_bytes() == SOURCES[1].read_bytes()
    for path in SOURCES:
        _assert_two_views(path.read_text(encoding="utf-8"))


def test_runtime_repair_preserves_two_view_contract_without_legacy_kems_anchor() -> None:
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
