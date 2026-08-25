"""Regression contract for Alpha8.14 dashboard recovery and product presentation."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
RELIABLE = ROOT / "custom_components" / "kems" / "update_orchestrator_reliable.py"
PRESENTATION = ROOT / "custom_components" / "kems" / "energy_bill_presentation.py"


def test_post_restart_verification_repairs_managed_dashboard_before_completion() -> (
    None
):
    """A missing/stale managed dashboard must self-heal before base verification."""
    content = RELIABLE.read_text(encoding="utf-8")
    assert "async def _async_repair_dashboard_verification" in content
    assert '"restart_requested",' in content
    assert '"verifying",' in content
    assert 'base._component_target(self.latest_bundle, "dashboard")' in content
    assert "await _async_sync_update_dashboard(self.hass)" in content
    assert "await self._async_repair_dashboard_verification()" in content
    repair = content.index("await self._async_repair_dashboard_verification()")
    verify = content.index("await super().async_verify_pending(save=save)", repair)
    assert repair < verify


def test_dashboard_verifier_uses_the_exact_rendered_managed_payload() -> None:
    """Verification must compare the installed file with the same rendered bytes."""
    content = RELIABLE.read_text(encoding="utf-8")
    assert "_combined_dashboard_with_update_button_bytes" in content
    assert 'self.hass.config.path("kems_master_dashboard.yaml")' in content
    assert (
        "installed.read_bytes() == _combined_dashboard_with_update_button_bytes()"
        in content
    )


def test_normal_dashboard_journey_is_live_data_then_kems_then_compare() -> None:
    """The managed UI must expose the unified product model ahead of engineering views."""
    content = PRESENTATION.read_text(encoding="utf-8")
    live_vs = content.index("  - title: Live Data vs KEMS")
    live = content.index("  - title: Live Data\n", live_vs)
    kems = content.index("  - title: KEMS\n", live)
    compare = content.index("  - title: Compare\n")
    assert live_vs < live < kems
    assert compare > kems
    assert "path: overview" in content
    assert "path: live-data" in content
    assert "path: kems" in content
    assert "path: compare" in content


def test_legacy_scenarios_are_relabelled_as_engineering_evidence() -> None:
    """Legacy strategy engines remain available without looking like products."""
    content = PRESENTATION.read_text(encoding="utf-8")
    assert "Engineering Simulation" in content
    assert "Advanced KEMS Strategy" in content
    assert "Scenario Evidence" in content
    assert "Advanced Strategy Validation" in content
    assert "Advanced Price Plan" in content
    assert "Advanced Strategy History" in content
    assert "Advanced Assumptions" in content
    assert "old Battery & Solar / Full KEMS / Full KEMS Agile names" in content


def test_live_and_kems_views_share_the_canonical_bill_entity() -> None:
    """Both product views must read the single Alpha8 bill contract."""
    content = PRESENTATION.read_text(encoding="utf-8")
    assert content.count("sensor.kems_energy_cost_comparison") >= 8
    assert "selected_kems_strategy_label" in content
    assert "TOTAL ENERGY COST" in content
    assert "Saving vs Live Data" in content
