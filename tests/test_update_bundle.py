"""Tests for the portable coordinated-release bundle."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "render_update_bundle.py"
TEMPLATE = ROOT / "release" / "kems-bundle.template.json"

spec = importlib.util.spec_from_file_location("render_update_bundle", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_release_bundle_renders_exact_coordinated_alpha8_targets() -> None:
    """A release should carry exact Alpha8 targets for every participating component."""
    bundle = module.render_bundle(TEMPLATE, "v0.8.0-alpha8.4")
    assert bundle["bundle"] == "0.8.0-alpha8.4"
    assert bundle["components"]["kems_core"]["version"] == "0.8.0-alpha8.4"
    assert bundle["components"]["dashboard"]["version"] == "0.8.0-alpha8.4"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.0"

    property_web = str(bundle["components"]["property_web"]["version"])
    pi_agent = str(bundle["components"]["pi_agent"]["version"])
    public_web = str(bundle["components"]["public_web"]["version"])
    assert property_web == pi_agent == public_web == "0.8.0-alpha8-web.1"
    assert bundle["components"]["property_web"]["required"] is True
    assert bundle["components"]["pi_agent"]["required"] is True
    assert bundle["components"]["public_web"]["required"] is False
    assert bundle["components"]["public_web"]["delivery"] == "ionos-sftp"
    assert bundle["maintenance"]["affected_components"] == [
        "kems_core",
        "dashboard",
    ]
    assert bundle["maintenance"]["reboot_required"] is False
    assert "Recover proven completed Happy Hour" in bundle["maintenance"]["reason"]


def test_bundle_contract_rejects_mismatched_appliance_versions() -> None:
    """Property web and its Pi agent must be published as one appliance release."""
    raw = json.loads(
        TEMPLATE.read_text(encoding="utf-8").replace(
            "__RELEASE_VERSION__", "0.8.0-alpha8.4"
        )
    )
    raw["components"]["pi_agent"]["version"] = "different"
    try:
        module.validate_bundle(raw)
    except ValueError as error:
        assert "must share one appliance release version" in str(error)
    else:
        raise AssertionError("Mismatched property_web/pi_agent versions were accepted")


def test_bundle_maintenance_only_names_known_components() -> None:
    """A typo in a maintenance scope must fail release validation."""
    raw = json.loads(
        TEMPLATE.read_text(encoding="utf-8").replace(
            "__RELEASE_VERSION__", "0.8.0-alpha8.4"
        )
    )
    raw["maintenance"]["affected_components"].append("not_a_component")
    try:
        module.validate_bundle(raw)
    except ValueError as error:
        assert "unknown components" in str(error)
    else:
        raise AssertionError("Unknown maintenance component was accepted")
