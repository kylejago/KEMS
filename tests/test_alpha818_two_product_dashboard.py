"""Successor regression for the Alpha8.18 two-product dashboard contract."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
MASTER = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def _dashboard() -> tuple[dict, str]:
    content = MASTER.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    assert isinstance(parsed, dict)
    return parsed, content


def test_successor_dashboard_keeps_live_data_and_kems_as_only_products() -> None:
    parsed, content = _dashboard()
    paths = [view["path"] for view in parsed["views"]]

    assert paths == [
        "home",
        "live-data",
        "kems",
        "compare",
        "tomorrow",
        "history",
        "system",
    ]
    assert "Battery & Solar" not in content
    assert "Full KEMS Agile" not in content
    assert "Compare every KEMS type" not in content


def test_compare_page_preserves_two_products_and_adds_no_system_counterfactual() -> (
    None
):
    parsed, _ = _dashboard()
    views = {view["path"]: str(view) for view in parsed["views"]}
    compare = views["compare"]

    assert "Without KEMS" in compare
    assert "Live" in compare
    assert "KEMS" in compare
    assert "counterfactual" in compare.lower()
    assert "Battery & Solar" not in compare
    assert "Full KEMS Agile" not in compare


def test_tariff_slots_are_planning_information_not_another_product() -> None:
    parsed, content = _dashboard()
    views = {view["path"]: str(view) for view in parsed["views"]}
    kems = views["kems"]
    tomorrow = views["tomorrow"]

    assert "sensor.kems_agile_slots" in content
    assert "today_slots" in kems
    assert "tomorrow_slots" in tomorrow
    assert "simulated planning" in tomorrow.lower()


def test_alpha818_release_boundary_survives_successors() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))

    assert manifest["version"].startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert (
        str(manifest["version"]).startswith("0.9.0-alpha9")
        or int(manifest["version"].rsplit(".", 1)[-1]) >= 19
    )
    assert bundle["maintenance"]["affected_components"] in (
        ["kems_core", "dashboard"],
        ["kems_core", "dashboard", "panel", "property_web", "pi_agent", "public_web"],
    )
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert str(bundle["components"]["property_web"]["version"]).startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-web.")
    )
    assert str(bundle["components"]["pi_agent"]["version"]).startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-web.")
    )
    assert str(bundle["components"]["public_web"]["version"]).startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-public.")
    )
