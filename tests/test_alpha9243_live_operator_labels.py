"""Operator labels distinguish commissioned live control from read-only plans."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_managed_dashboard_readiness_is_not_misleading_shadow_label() -> None:
    source = (ROOT / "dashboards" / "kems_master_dashboard.yaml").read_text()
    packaged = (KEMS / "kems_master_dashboard.yaml").read_text()
    assert source == packaged
    assert "Ready for Control" in source
    assert "binary_sensor.kems_system_commissioned_for_control" in source
    assert "| Commissioning | {{ states(" not in source


def test_historic_optional_dashboard_uses_same_readiness_distinction() -> None:
    old_layout = (KEMS / "dashboard_consolidation.py").read_text()
    assert "Ready for Control" in old_layout
    assert "binary_sensor.kems_system_commissioned_for_control" in old_layout


def test_agile_manager_keeps_compat_mode_but_labels_its_scope() -> None:
    source = (KEMS / "agile_smart_export.py").read_text()
    flow = (KEMS / "agile_smart_export_runtime_base.py").read_text()
    for text in (source, flow):
        assert '"mode": "simulation_only"' in text
        assert '"mode_scope": "read_only_agile_planning_and_comparison"' in text
        assert '"physical_dispatch_owner": "foxess_control_backend"' in text
    assert '"does_not_authorise_hardware_writes": True' in source


def test_commissioning_safety_decision_unchanged() -> None:
    source = (KEMS / "commissioning.py").read_text()
    assert 'state == "Ready for Shadow"' in source
    assert '"ready_for_control": ready_for_control' in source
