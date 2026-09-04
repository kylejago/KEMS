from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alpha732_platform_contract_is_retained_in_alpha8() -> None:
    manifest = json.loads((ROOT / "custom_components/kems/manifest.json").read_text())
    template = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    assert str(manifest["version"]).startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))

    property_web = str(template["components"]["property_web"]["version"])
    pi_agent = str(template["components"]["pi_agent"]["version"])
    public_web = str(template["components"]["public_web"]["version"])
    assert property_web == pi_agent
    assert public_web == property_web or public_web.startswith("0.9.0-alpha9-public.")
    assert property_web.startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-web.", "0.9.0-alpha9-public.")
    )
    assert (
        property_web.startswith("0.9.0-alpha9-web.")
        or int(property_web.rsplit(".", 1)[1]) >= 2
    )
    assert template["components"]["public_web"]["required"] is False
    assert template["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"


def test_alpha732_is_behaviour_freeze_not_another_agile_patch() -> None:
    runtime = (
        ROOT / "custom_components/kems/agile_smart_export_runtime.py"
    ).read_text()
    assert "install_alpha731_solar_headroom_patch()" in runtime
    assert "alpha732" not in runtime.lower()


def test_stale_root_build_artifacts_are_removed() -> None:
    for name in (
        "CLEAN_BUILD.md",
        "CORRECTED_BUILD.md",
        "DEVELOPMENT_STEPS.md",
        "FILE_MANIFEST.sha256",
    ):
        assert not (ROOT / name).exists(), name


def test_current_entry_docs_are_alpha8() -> None:
    start = (ROOT / "START_HERE.md").read_text()
    validation = (ROOT / "VALIDATION_REPORT.md").read_text()
    agile = (ROOT / "docs/agile-smart-export.md").read_text()
    assert "0.8.0-alpha8.0" in start
    assert "0.8.0-alpha8-web.0" in start
    assert "0.8.0-alpha8-panel.0" in start
    assert "0.8.0-alpha8.0" in validation
    assert "Alpha7.52" in agile
    assert "verified publication gap" in agile.lower()
    assert "13/13" in agile
