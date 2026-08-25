"""Regression contract for the Alpha8.14 Live Data vs KEMS dashboard hotfix."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
PRESENTATION = ROOT / "custom_components" / "kems" / "energy_bill_presentation.py"


def test_managed_dashboard_uses_live_data_and_kems_as_product_views() -> None:
    """The managed HA navigation must expose Live Data and KEMS, not old products."""
    content = PRESENTATION.read_text(encoding="utf-8")
    assert '"  - title: Live Data\\n    path: live-data\\n"' in content
    assert '"  - title: KEMS\\n    path: kems\\n"' in content
    assert '"Full KEMS Forecast"' in content
    assert '"Battery & Solar"' in content
    assert "_remove_view(content, legacy_title)" in content
    assert "KEMS has two user-facing views: **Live Data**" in content


def test_legacy_strategy_views_remain_internal_but_leave_managed_navigation() -> None:
    """Legacy engines may remain for evidence but must not be separate product tabs."""
    content = PRESENTATION.read_text(encoding="utf-8")
    for legacy_title in (
        "Full KEMS Forecast",
        "Forecast vs Agile",
        "Agile Price Plan",
        "Agile History",
        "Agile Assumptions",
        "Battery & Solar",
    ):
        assert f'"{legacy_title}"' in content
    assert "These engines remain in code and standalone evidence dashboards" in content


def test_post_restart_verification_resyncs_dashboard_before_exact_check() -> None:
    """A missing/stale managed file must be repaired before pending verification."""
    content = PRESENTATION.read_text(encoding="utf-8")
    assert "verify_with_dashboard_resync" in content
    assert "if self.pending and self.latest_bundle is not None:" in content
    assert "await reliable._async_sync_update_dashboard(self.hass)" in content
    assert "await original_verify(self, save=save)" in content
    assert "dashboard=waiting / stage=verifying" in content


def test_alpha814_does_not_change_bill_or_hardware_control_engines() -> None:
    """The hotfix must stay presentation/update scoped."""
    content = PRESENTATION.read_text(encoding="utf-8")
    assert "build_energy_cost_comparison" in content
    assert "Battery wear is deliberately excluded" in content
    assert "control" not in " ".join(
        line.strip()
        for line in content.splitlines()
        if "async_verify_pending" in line or "_align_live_kems_navigation" in line
    )
