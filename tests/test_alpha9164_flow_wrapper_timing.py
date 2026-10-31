"""Read-only Alpha9.164 flow stage timing contract."""

from pathlib import Path

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"


def test_flow_wrapper_exposes_individual_reporting_stage_timings():
    flow = (KEMS / "agile_flow_presentation.py").read_text(encoding="utf-8")
    for name in (
        "base_seconds",
        "solar_accounting_seconds",
        "future_projection_seconds",
        "panel_routing_seconds",
        "flow_contract_seconds",
        "publication_seconds",
        "total_thread_cpu_seconds",
    ):
        assert f'"{name}"' in flow
    assert "self._kems_flow_settlement_performance" in flow


def test_coordinator_preserves_authoritative_settlement_and_control():
    source = (KEMS / "coordinator.py").read_text(encoding="utf-8")
    assert '"_kems_flow_settlement_performance"' in source
    assert 'detail_seconds[f"precontrol_flow_{name}"]' in source
    assert "if post_shadow_settlement_changed:" in source
    assert "guard_paid_agile_physical_export(" in source
