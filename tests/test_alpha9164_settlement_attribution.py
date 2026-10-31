"""Alpha9.164 must observe settlement timing without changing safety or replay."""

from pathlib import Path

COORDINATOR = (
    Path(__file__).parents[1] / "custom_components" / "kems" / "coordinator.py"
)


def test_precontrol_wall_and_thread_cpu_are_independently_measured():
    source = COORDINATOR.read_text(encoding="utf-8")
    assert "pre_settlement_cpu_started = thread_time()" in source
    assert '"precontrol_settlement_thread_cpu_seconds"' in source
    assert '"precontrol_settlement_unattributed_seconds"' in source
    assert "max(pre_settlement_wall_seconds - accounted, 0.0)" in source


def test_settlement_and_physical_control_order_unchanged():
    source = COORDINATOR.read_text(encoding="utf-8")
    pre = source.index("pre_settlement_started = perf_counter()")
    settlement = source.index("self._agile_smart_export.reconcile_current_day_settlements(", pre)
    planning = source.index("control = self._control.plan(", settlement)
    physical_guard = source.index("guard_paid_agile_physical_export(", planning)
    post = source.index("if post_shadow_settlement_changed:", physical_guard)
    assert pre < settlement < planning < physical_guard < post
