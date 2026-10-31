"""Alpha9.165 attribution must not suppress or reorder settlement writes."""

from pathlib import Path

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"


def test_flow_publication_counts_observe_without_short_circuiting():
    source = (KEMS / "agile_flow_presentation.py").read_text(encoding="utf-8")
    start = source.index("    def reconcile_current_day_settlements(")
    source = source[start:]
    assert 'base_writes_before = getattr(scope, "written", 0)' in source
    assert '"base_publication_writes": base_writes' in source
    assert '"publication_actual_writes": final_writes' in source
    assert '"publication_identical_suppressed": final_skipped' in source
    assert source.index("super().reconcile_current_day_settlements(") < source.index(
        "self._publish(self._state)"
    )
    assert "if final_writes" not in source
    assert "if base_writes" not in source


def test_coalescing_keeps_exact_change_authority():
    source = (
        KEMS / "kems_core" / "settlement_publication_coalescing.py"
    ).read_text(encoding="utf-8")
    assert "No time-based cache" in source
    assert "finally:" in source
