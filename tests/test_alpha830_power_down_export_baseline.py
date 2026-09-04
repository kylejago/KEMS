"""Regression coverage for Alpha8.30 Power Down export baseline handling."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_mapped_export_baseline_is_fail_closed_for_reward_accounting() -> None:
    """A mapped-but-unavailable export baseline must never become implicit zero."""
    provider = (
        ROOT / "custom_components" / "kems" / "providers" / "octoplus.py"
    ).read_text()

    assert "def _reward_baselines(" in provider
    assert "export_configured: bool" in provider
    assert "if export_period is None:" in provider
    assert "import_period = None" in provider
    assert "if export_total is None:" in provider
    assert "import_total = None" in provider
    assert "only reward accounting is" in provider
    assert "withheld until the matching export baseline becomes usable" in provider


def test_export_baseline_discovery_and_mapping_remain_supported() -> None:
    """KEMS must keep the dedicated Octopus export-baseline discovery path."""
    constants = (ROOT / "custom_components" / "kems" / "const.py").read_text()
    discovery = (
        ROOT / "custom_components" / "kems" / "entity_discovery.py"
    ).read_text()
    mapping = (
        ROOT / "custom_components" / "kems" / "providers" / "entity_map.py"
    ).read_text()

    assert (
        'CONF_SAVING_SESSION_EXPORT_BASELINE = "saving_session_export_baseline"'
        in constants
    )
    assert "CONF_SAVING_SESSION_EXPORT_BASELINE," in discovery
    assert "is_export=True" in discovery
    assert "saving_session_export_baseline" in mapping


def test_power_down_reporting_exposes_baseline_readiness_without_old_claim() -> None:
    """Alpha8.30 reports export-baseline mapping and readiness."""
    source = (ROOT / "custom_components" / "kems" / "binary_sensor.py").read_text()

    assert '"export_baseline_mapped": export_baseline_mapped' in source
    assert '"export_baseline_entity_id": export_baseline_entity' in source
    assert '"reward_baseline_ready": reward_baseline_ready' in source
    assert "Export baseline mapped but unavailable" in source
    assert "reward estimate withheld" in source
    assert '"export_baseline_required": False' not in source
    assert "export baseline not required" not in source


def test_alpha830_release_contract_is_successor_safe() -> None:
    """Later Alpha8 releases retain the Alpha8.30 coordinated release boundary."""
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())

    prefix = "0.9.0-alpha9."
    assert manifest["version"].startswith(prefix)
    assert (
        str(manifest["version"]).startswith("0.9.0-alpha9")
        or int(manifest["version"].removeprefix(prefix)) >= 30
    )
    assert bundle["maintenance"]["affected_components"] in (
        ["kems_core", "dashboard"],
        ["kems_core", "dashboard", "panel", "property_web", "pi_agent", "public_web"],
    )
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
