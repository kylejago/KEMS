from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_coordinated_release_keeps_web_panel_and_brand_contract() -> None:
    manifest = json.loads((ROOT / "custom_components/kems/manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    branding = (ROOT / "docs/branding.md").read_text()

    version = str(manifest["version"])
    assert version.startswith("0.8.0-alpha8.")
    assert bundle["bundle"] == "__RELEASE_VERSION__"
    assert bundle["components"]["kems_core"]["version"] == "__RELEASE_VERSION__"
    assert bundle["components"]["dashboard"]["version"] == "__RELEASE_VERSION__"

    web_versions = {
        str(bundle["components"]["property_web"]["version"]),
        str(bundle["components"]["pi_agent"]["version"]),
        str(bundle["components"]["public_web"]["version"]),
    }
    assert web_versions == {"0.8.0-alpha8-web.1"}
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.0"

    assert "docs/assets/kems-logo-master.svg" in branding
    assert "single source of truth" in branding
