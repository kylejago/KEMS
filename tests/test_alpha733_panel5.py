"""Release regression coverage for Alpha7.33 / managed Panel5 and later."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_alpha733_versions_and_bundle_remain_aligned_in_alpha8() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    panel = (KEMS / "panel.py").read_text(encoding="utf-8")
    yaml = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")
    transform = (KEMS / "panel_ev_policy.py").read_text(encoding="utf-8")
    dashboard = (KEMS / "dashboard.py").read_text(encoding="utf-8")

    assert str(manifest["version"]).startswith("0.8.0-alpha8.")
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert 'PANEL_EV_POLICY_VERSION = "0.8.0-alpha8-panel.1"' in transform
    # Alpha8.5 intentionally keeps the proven panel.0 source template intact;
    # panel.1 is the runtime-managed transform that HA validates and OTA-delivers.
    assert 'PANEL_CONFIG_VERSION = "0.8.0-alpha8-panel.0"' in panel
    assert 'panel_config_version: "0.8.0-alpha8-panel.0"' in yaml
    assert "PANEL6_VERSION_LINE" not in dashboard
    assert "PANEL7_VERSION_LINE" not in dashboard
    assert "return PACKAGED_PANEL_PATH.read_bytes()" in dashboard
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


def test_alpha733_public_web_delivery_matches_alpha8_route() -> None:
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    public_web = bundle["components"]["public_web"]
    assert public_web["version"] == "0.8.0-alpha8-web.2"
    assert public_web["delivery"] == "ionos-sftp"
