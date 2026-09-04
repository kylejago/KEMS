import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "custom_components" / "kems" / "dashboard_alpha740_agile_primary.py"


def test_alpha740_bundle_capabilities_continue_in_alpha8() -> None:
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    web_versions = {
        str(bundle["components"][component]["version"])
        for component in ("property_web", "pi_agent", "public_web")
    }
    assert len(web_versions) == 1
    web_version = web_versions.pop()
    assert web_version.startswith("0.8.0-alpha8-web.")
    assert int(web_version.rsplit(".", 1)[1]) >= 2
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"


def test_alpha740_dashboard_inserts_agile_and_compare_command_cards() -> None:
    improve_alpha740_dashboard = runpy.run_path(str(DASHBOARD))[
        "improve_alpha740_dashboard"
    ]
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
