from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_alpha739_coordinates_web19_and_exact_svg_brand() -> None:
    manifest = json.loads((ROOT / "custom_components/kems/manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    branding = (ROOT / "docs/branding.md").read_text()

    assert manifest["version"] == "0.7.0-alpha7.39"
    assert bundle["components"]["panel"]["version"] == "0.7.0-alpha7-panel7"
    for component in ("property_web", "pi_agent", "public_web"):
        assert bundle["components"][component]["version"] == "0.7.0-alpha7-web.19"

    reason = bundle["maintenance"]["reason"]
    assert "Web.19" in reason
    assert "Web.18" not in reason
    assert "Web.14" not in reason

    master = ROOT / "docs/assets/kems-logo-master.svg"
    icon = ROOT / "custom_components/kems/brand/icon.png"
    logo = ROOT / "custom_components/kems/brand/logo.png"
    assert master.stat().st_size == 877
    assert _sha256(master) == "ef53e22bdff4e4ebd81007c3a6d5f28da0384f547e9036a7be7e3bf2d420b464"
    assert _sha256(icon) == "f3c68f1a2e73c190b9415bf6abe0a3c590a38b298321af668a5ec3325c7bae90"
    assert _sha256(logo) == "08e45c44b1f509f49256a8378d0680196f89d77b8d19ce74467a00a62ce01d77"

    assert "exact supplied SVG" in branding
    assert "kems_full_brand_concept.png" in branding
