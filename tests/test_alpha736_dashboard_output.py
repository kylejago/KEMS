"""Validate the fully assembled Alpha7.36 managed dashboard output."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
MASTER = KEMS / "kems_master_dashboard.yaml"
AGILE = KEMS / "kems_agile_smart_export_dashboard.yaml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _source_dashboard() -> str:
    master = MASTER.read_text(encoding="utf-8").rstrip()
    agile = AGILE.read_text(encoding="utf-8")
    marker = "\nviews:\n"
    assert marker in agile
    agile_views = agile.split(marker, 1)[1].lstrip("\n").rstrip()
    live_view = """
  - title: Agile Smart Export
    path: agile-smart-export
    icon: mdi:transmission-tower-export
    cards:
      - type: markdown
        content: Runtime Agile live scenario placeholder.
""".rstrip()
    return f"{master}\n\n{agile_views}\n\n{live_view}\n"


def test_alpha736_final_dashboard_has_ten_valid_views_and_finance_parity() -> None:
    consolidation = _load(
        "kems_alpha736_consolidation_test", KEMS / "dashboard_consolidation.py"
    )
    finance = _load(
        "kems_alpha736_finance_test", KEMS / "dashboard_alpha736_finance.py"
    )

    consolidated = consolidation.consolidate_dashboard(_source_dashboard())
    rendered = finance.improve_alpha736_dashboard(consolidated)
    parsed = yaml.safe_load(rendered)

    paths = [view["path"] for view in parsed["views"]]
    assert paths == [
        "home",
        "live-data",
        "battery-solar",
        "full-kems",
        "full-kems-agile",
        "compare",
        "cost-roi",
        "history",
        "advanced",
        "system",
    ]

    views = {view["path"]: str(view) for view in parsed["views"]}
    compare = views["compare"]
    assert "Winner by period" in compare
    assert "Awaiting battery data" in compare
    assert "sensor.kems_today_energy_summary" in compare
    assert "current_routing_snapshot" in compare

    finance_view = views["cost-roi"]
    assert "Actual vs core KEMS simulation" in finance_view
    assert "sensor.kems_predicted_annual_saving" in finance_view
    assert "sensor.kems_actual_system_value_total" in finance_view
    assert "sensor.kems_lifetime_import_cost" in finance_view
