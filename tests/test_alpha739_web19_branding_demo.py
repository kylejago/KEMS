from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_alpha8_keeps_web19_plus_branding_contract_and_exact_svg_brand() -> None:
    manifest = json.loads((ROOT / "custom_components/kems/manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    branding = (ROOT / "docs/branding.md").read_text()

    assert str(manifest["version"]).startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    web_versions = {
        str(bundle["components"][component]["version"])
        for component in ("property_web", "pi_agent", "public_web")
    }
    assert len(web_versions) == 1
    web_version = web_versions.pop()
    assert web_version.startswith("0.8.0-alpha8-web.")
    assert int(web_version.rsplit(".", 1)[1]) >= 2

    reason = bundle["maintenance"]["reason"]
    assert "Web.18" not in reason
    assert "Web.14" not in reason

    master = ROOT / "docs/assets/kems-logo-master.svg"
    icon = ROOT / "custom_components/kems/brand/icon.png"
    logo = ROOT / "custom_components/kems/brand/logo.png"
    assert master.stat().st_size == 877
    assert (
        _sha256(master)
        == "ef53e22bdff4e4ebd81007c3a6d5f28da0384f547e9036a7be7e3bf2d420b464"
    )
    assert (
        _sha256(icon)
        == "fe743d5275610376e49a28fed0e1d5c4d536c6809c9c2f5f4ffb87842408b059"
    )
    assert (
        _sha256(logo)
        == "b5283d7901b9e277f6854bc9a4b11ca209f93547533682f94d96d54a496d3198"
    )

    assert "exact supplied SVG" in branding
    assert "kems_full_brand_concept.png" in branding
