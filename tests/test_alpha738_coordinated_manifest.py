from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alpha738_or_later_keeps_coordinated_web_and_brand_contract() -> None:
    manifest = json.loads((ROOT / "custom_components/kems/manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    branding = (ROOT / "docs/branding.md").read_text()

    version = str(manifest["version"])
    assert version.startswith("0.7.0-alpha7.")
    assert int(version.rsplit(".", 1)[1]) >= 38

    web_versions = {
        str(bundle["components"]["property_web"]["version"]),
        str(bundle["components"]["pi_agent"]["version"]),
        str(bundle["components"]["public_web"]["version"]),
    }
    assert len(web_versions) == 1
    web_version = web_versions.pop()
    assert web_version.startswith("0.7.0-alpha7-web.")
    assert int(web_version.rsplit(".", 1)[1]) >= 18
    assert bundle["components"]["panel"]["version"] == "0.7.0-alpha7-panel7"

    assert "docs/assets/kems-logo-master.svg" in branding
    assert "single source of truth" in branding
