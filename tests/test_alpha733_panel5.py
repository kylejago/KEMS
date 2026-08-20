"""Release regression coverage for Alpha7.33 / managed Panel5 and later."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_alpha733_versions_and_bundle_remain_panel5_or_later_aligned() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    panel = (KEMS / "panel.py").read_text(encoding="utf-8")
    yaml = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")
    dashboard = (KEMS / "dashboard.py").read_text(encoding="utf-8")

    version = str(manifest["version"])
    assert version.startswith("0.7.0-alpha7.")
    assert int(version.rsplit(".", 1)[1]) >= 33

    bundle_version = str(bundle["components"]["panel"]["version"])
    panel_match = re.search(r'PANEL_CONFIG_VERSION = "([^"]+)"', panel)
    yaml_match = re.search(r'panel_config_version: "([^"]+)"', yaml)
    assert panel_match is not None
    assert yaml_match is not None
    assert bundle_version == panel_match.group(1) == "0.7.0-alpha7-panel7"
    assert yaml_match.group(1) == "0.7.0-alpha7-panel6"
    assert (
        "PANEL7_VERSION_LINE = b'panel_config_version: \"0.7.0-alpha7-panel7\"'"
        in dashboard
    )
    assert "source.replace(PANEL6_VERSION_LINE, PANEL7_VERSION_LINE, 1)" in dashboard
    assert bundle_version.startswith("0.7.0-alpha7-panel")
    assert int(bundle_version.rsplit("panel", 1)[1]) >= 5
    assert bundle["components"]["panel"]["delivery"] == "kems_core"
    assert bundle["components"]["panel"]["required"] is False


def test_alpha733_preserves_alpha731_as_agile_runtime_baseline() -> None:
    runtime = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")
    assert "install_alpha731_solar_headroom_patch()" in runtime
    assert "alpha733" not in runtime.lower()


def test_alpha733_automatic_panel_delivery_path_is_still_armed() -> None:
    dashboard = (KEMS / "dashboard.py").read_text(encoding="utf-8")
    assert "panel_changed and panel_was_managed" in dashboard
    assert "async_auto_install_managed_panel" in dashboard
    assert '"command": "firmware/install"' in dashboard
    assert '"port": "OTA"' in dashboard
    assert "async_verify_panel_firmware" in dashboard


def test_alpha733_public_web_delivery_matches_live_ionos_route() -> None:
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    public_web = bundle["components"]["public_web"]
    assert public_web["version"] == "0.7.0-alpha7-web.14"
    assert public_web["delivery"] == "ionos-sftp"
