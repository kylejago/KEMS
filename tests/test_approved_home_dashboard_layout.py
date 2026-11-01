"""Regression checks for the user-approved KEMS Home dashboard layout."""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"


def test_approved_home_layout_is_packaged_without_losing_other_views() -> None:
    """The next release retains the full master, with the approved Home view."""
    source = SOURCE.read_bytes()
    assert PACKAGED.read_bytes() == source
    views = yaml.safe_load(source)["views"]
    assert [view["path"] for view in views] == [
        "home",
        "live-data",
        "kems",
        "compare",
        "tomorrow",
        "history",
        "system",
    ]

    home_cards = views[0]["cards"]
    assert [card.get("title", "<energy-grid>") for card in home_cards] == [
        "Live KEMS — at a glance",
        "Today's actual costs",
        "Tariffs & battery now",
        "<energy-grid>",
        "Today's Agile plan — now and next",
        "Top 5 Agile export prices today",
        "Power Down — session & preparation",
        "EV — status & charging plan",
        "Happy Hour — booking & charging plan",
    ]
    assert "Control plan safe:" in home_cards[0]["content"]
    assert "Intelligent status fresh:" in home_cards[0]["content"]
    assert "KEMS update status:" in home_cards[0]["content"]

    energy = home_cards[3]
    assert energy["type"] == "grid"
    assert energy["columns"] == 1
    assert len(energy["cards"]) == 2
    left, right = energy["cards"]
    assert left["cards"][0]["type"] == "custom:power-flow-card-plus"
    assert left["cards"][1]["type"] == "grid"
    assert left["cards"][1]["columns"] == 6
    assert right["cards"][1]["columns"] == 6
    assert "sensor.kh7_battery_charge_today" in str(right)
    assert "sensor.kh7_battery_discharge_today" in str(right)

    assert "sensor.kems_agile_slots" in home_cards[5]["content"]
    assert "sensor.ohme_epod_status" in home_cards[7]["content"]

    def check_templates(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                check_templates(item)
        elif isinstance(node, dict):
            if node.get("type") == "markdown":
                Environment().parse(node["content"])
            for child in node.values():
                if isinstance(child, (dict, list)):
                    check_templates(child)

    check_templates(home_cards)
