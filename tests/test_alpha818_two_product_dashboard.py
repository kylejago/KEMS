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

    assert paths == ["home", "live-data", "kems", "compare", "agile-slots", "history", "system"]
    assert "Battery & Solar" not in content
    assert "Full KEMS Agile" not in content
    assert "Compare every KEMS type" not in content


def test_compare_page_is_live_data_vs_kems_only() -> None:
    parsed, _ = _dashboard()
    views = {view["path"]: str(view) for view in parsed["views"]}
    compare = views["compare"]

    assert "Live Data" in compare
    assert "KEMS" in compare
    assert "Battery & Solar" not in compare
    assert "Full KEMS Agile" not in compare


def test_agile_slots_is_tariff_information_not_a_product() -> None:
    parsed, content = _dashboard()
    views = {view["path"]: str(view) for view in parsed["views"]}
    slots = views["agile-slots"]

    assert "not another KEMS product" in slots
    assert "sensor.kems_agile_slots" in content
    assert "today_slots" in slots
    assert "tomorrow_slots" in slots


def test_alpha818_release_boundary_survives_successors() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))

    assert manifest["version"].startswith("0.8.0-alpha8.")
    assert int(manifest["version"].rsplit(".", 1)[-1]) >= 19
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.4"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.4"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.4"
