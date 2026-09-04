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


def test_release_bundle_renders_exact_coordinated_alpha9_targets() -> None:
    """The current template must render the exact four-track Alpha9 baseline."""
    bundle = module.render_bundle(TEMPLATE, "v0.9.0-alpha9.0")
    assert bundle["bundle"] == "0.9.0-alpha9.0"
    assert bundle["components"]["kems_core"]["version"] == "0.9.0-alpha9.0"
    assert bundle["components"]["dashboard"]["version"] == "0.9.0-alpha9.0"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert bundle["components"]["property_web"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["pi_agent"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["public_web"]["version"] == "0.9.0-alpha9-public.0"
    assert bundle["components"]["property_web"]["required"] is True
    assert bundle["components"]["pi_agent"]["required"] is True
    assert bundle["components"]["public_web"]["required"] is False
    assert bundle["components"]["public_web"]["delivery"] == "ionos-sftp"

    affected = bundle["maintenance"]["affected_components"]
    assert affected == [
        "kems_core",
        "dashboard",
        "panel",
        "property_web",
        "pi_agent",
        "public_web",
    ]
    assert bundle["maintenance"]["reboot_required"] is False
    reason = bundle["maintenance"]["reason"]
    assert "Alpha9 coordinated parity baseline" in reason
    assert "0.9.0-alpha9-web.0" in reason
    assert "0.9.0-alpha9-public.0" in reason
    assert "0.9.0-alpha9-panel.0" in reason
    assert "hardware writes hard-blocked" in reason


def test_bundle_contract_rejects_mismatched_appliance_versions() -> None:
    """Property web and its Pi agent must be published as one appliance release."""
    raw = json.loads(
        TEMPLATE.read_text(encoding="utf-8").replace(
            "__RELEASE_VERSION__", "0.8.0-alpha8.7"
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
            "__RELEASE_VERSION__", "0.8.0-alpha8.7"
        )
    )
    raw["maintenance"]["affected_components"].append("not_a_component")
    try:
        module.validate_bundle(raw)
    except ValueError as error:
        assert "unknown component" in str(error)
    else:
        raise AssertionError("Unknown maintenance component was accepted")
