"""Tests for the HACS-installed managed KEMS dashboard."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"


def test_packaged_master_dashboard_matches_repository_source() -> None:
    """HACS must receive the same master dashboard that the repo documents."""
    assert PACKAGED.exists()
    assert PACKAGED.read_bytes() == SOURCE.read_bytes()


def test_managed_master_dashboard_is_valid_builtin_yaml() -> None:
    """The managed dashboard should parse and keep the expected master views."""
    content = yaml.safe_load(PACKAGED.read_text(encoding="utf-8"))
    assert content["title"] == "KEMS Master Dashboard"
    paths = {view["path"] for view in content["views"]}
    assert {
        "overview",
        "live-energy",
        "simulation",
        "forecast",
        "full-kems-forecast",
        "compare",
        "battery-solar",
        "tariff-ev",
        "power-down",
        "control-eps",
        "finance-history",
        "learning-health",
        "gas",
        "all-entities",
    } <= paths


def test_kems_setup_syncs_managed_dashboard() -> None:
    """Integration startup must refresh its managed dashboard in /config."""
    setup = (ROOT / "custom_components" / "kems" / "__init__.py").read_text(
        encoding="utf-8"
    )
    sync = (ROOT / "custom_components" / "kems" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    assert "await async_sync_managed_dashboard(hass)" in setup
    assert 'MANAGED_DASHBOARD_FILENAME = "kems_master_dashboard.yaml"' in sync
    assert "hass.config.path(MANAGED_DASHBOARD_FILENAME)" in sync
    assert "os.replace(temporary, target)" in sync
