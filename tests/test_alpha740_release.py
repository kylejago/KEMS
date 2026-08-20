import json
from pathlib import Path

from custom_components.kems.dashboard_alpha740_agile_primary import (
    improve_alpha740_dashboard,
)


ROOT = Path(__file__).resolve().parents[1]


def test_alpha740_manifest_and_bundle_targets_web20() -> None:
    manifest = json.loads((ROOT / "custom_components/kems/manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.7.0-alpha7.40"
    assert bundle["components"]["property_web"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["pi_agent"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["public_web"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["panel"]["version"] == "0.7.0-alpha7-panel7"


def test_alpha740_dashboard_inserts_agile_and_compare_command_cards() -> None:
    source = (
        "title: KEMS Master Dashboard\n\nviews:\n"
        "  - title: Full KEMS Agile\n"
        "    path: full-kems-agile\n"
        "    icon: mdi:transmission-tower-export\n"
        "    cards:\n"
        "      - type: markdown\n"
        "        content: old agile\n"
        "  - title: Compare\n"
        "    path: compare\n"
        "    icon: mdi:compare-horizontal\n"
        "    cards:\n"
        "      - type: markdown\n"
        "        content: old compare\n"
    )

    result = improve_alpha740_dashboard(source)

    assert "Full KEMS Agile — command centre" in result
    assert "Economic early-export guard" in result
    assert "Overall strategy comparison — which KEMS type is winning?" in result
    assert "Strategy evidence by period" in result
    assert "Strategy cost — rolling 24 hours" in result
