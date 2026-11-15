"""Cross-view bill-equivalent regression for estimated Happy Hour refunds."""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ROOT / "dashboards" / "kems_master_dashboard.yaml",
    ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml",
]


def _cards(path: Path):
    dashboard = yaml.safe_load(path.read_text(encoding="utf-8"))
    compare = next(view for view in dashboard["views"] if view.get("path") == "compare")
    comparison_grid = next(
        card for card in compare["cards"] if card.get("type") == "grid"
    )
    live = next(
        card for card in comparison_grid["cards"] if card.get("title") == "Live"
    )
    side_by_side = next(
        card
        for card in compare["cards"]
        if card.get("title") == "Today — side by side"
    )
    return live["content"], side_by_side["content"]


def _comparison_report():
    return {
        "today": {
            "live_data": {
                "total_energy_cost_pence": 467.9,
                "total_energy_effective_cost_pence": -6.148,
                "electricity_total_cost_pence": 274.9,
                "electricity_effective_total_cost_pence": -199.148,
                "happy_hour_estimated_credit_pence": 474.048,
                "gas_total_cost_pence": 193.0,
                "grid_import_kwh": 80.5,
                "grid_export_kwh": 30.0,
            },
            "kems": {
                "total_energy_cost_pence": -20.86,
                "electricity_total_cost_pence": -213.86,
                "gas_total_cost_pence": 193.0,
                "grid_import_kwh": 74.012,
                "grid_export_kwh": 32.683,
            },
        }
    }


def test_compare_live_card_uses_home_refund_adjusted_total() -> None:
    """15 Nov observed £4.67 gross and £4.74 refund must not show £4.67 Live."""
    periods = _comparison_report()
    env = Environment(autoescape=False)
    for path in SOURCES:
        live, side_by_side = _cards(path)

        def state_attr(entity: str, attribute: str):
            if entity == "sensor.kems_energy_cost_comparison":
                return periods if attribute == "periods" else None
            if entity == "sensor.kems_compare_no_system_cost_today":
                return 57.698 if attribute == "grid_import_kwh" else 0.0
            return None

        rendered = env.from_string(live).render(state_attr=state_attr)
        assert "# £-0.06" in rendered
        assert "Electricity: £-1.99" in rendered
        assert "Est. Happy Hour refund (pending): −£4.74" in rendered
        assert "_Measured property data after estimated, unsettled" in rendered

        rendered_table = env.from_string(side_by_side).render(
            state_attr=state_attr,
            states=lambda entity: "1012.84",
        )
        assert "| Total energy cost |" in rendered_table
        assert "£-0.06" in rendered_table
        assert "Est. Happy Hour refund (pending)" in rendered_table
        assert "£-1.99" in rendered_table
        assert "Live system value vs no system:" in rendered_table


def test_unverified_credit_is_not_silently_filled_with_gross_cost() -> None:
    periods = _comparison_report()
    periods["today"]["live_data"]["total_energy_effective_cost_pence"] = None
    path = SOURCES[0]
    live, _ = _cards(path)
    rendered = Environment(autoescape=False).from_string(live).render(
        state_attr=lambda entity, attr: periods,
    )
    assert "# —" in rendered
    assert "# £4.67" not in rendered


def test_master_dashboard_packaged_copy_matches_source() -> None:
    assert SOURCES[0].read_bytes() == SOURCES[1].read_bytes()
