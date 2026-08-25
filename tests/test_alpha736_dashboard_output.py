"""Validate the retained internal Alpha7.36 dashboard-finance transformation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _source_dashboard() -> str:
    """Build legacy engineering source views independently of customer YAML."""
    consolidation = _load(
        "kems_alpha736_source_consolidation_test", KEMS / "dashboard_consolidation.py"
    )
    parts = ["title: KEMS legacy Alpha7.36 fixture\n\nviews:\n"]
    for index, title in enumerate(sorted(consolidation.EXPECTED_SOURCE_TITLES)):
        parts.append(
            f"  - title: {title}\n"
            f"    path: source-{index}\n"
            "    cards:\n"
            "      - type: markdown\n"
            "        content: |\n"
            f"          Internal evidence fixture for {title}.\n"
        )
    return "\n".join(part.rstrip() for part in parts).rstrip() + "\n"


def test_alpha736_internal_dashboard_finance_transform_remains_valid() -> None:
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
