from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alpha738_coordinates_web18_and_approved_brand() -> None:
    manifest = json.loads((ROOT / "custom_components/kems/manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    branding = (ROOT / "docs/branding.md").read_text()

    assert manifest["version"] == "0.7.0-alpha7.38"
    assert bundle["components"]["property_web"]["version"] == "0.7.0-alpha7-web.18"
    assert bundle["components"]["pi_agent"]["version"] == "0.7.0-alpha7-web.18"
    assert bundle["components"]["public_web"]["version"] == "0.7.0-alpha7-web.18"
    assert "Web.14" not in bundle["maintenance"]["reason"]
    assert "exact approved KEMS branding" in bundle["maintenance"]["reason"]

    approved = ROOT / "docs/assets/kems_full_brand_concept.png"
    assert approved.stat().st_size == 2_156_120
    assert (
        "67ad8c3ee349a35de23f5a9040ce27c18b5cf347454f777cf1f55a6f905eb01f"
        in branding
    )
    assert "not an approved master" in branding
