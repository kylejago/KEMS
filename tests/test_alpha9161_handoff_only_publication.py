"""Avoid one needless full settlement republish on metadata-only handoff edits.

Reproduce Alpha9.160's 30 Oct 07:38 profile: Tomorrow SOC handoff alone
changed after the first publication, so a second full publication consumed
~1.07s CPU, despite no Tomorrow slot/price/period/quality change.
"""

from __future__ import annotations

from pathlib import Path

from kems_core.settlement_reconciliation_cadence import (
    needs_full_tomorrow_republication,
)

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"


def test_only_handoff_metadata_does_not_republish_all_agile_entities() -> None:
    assert needs_full_tomorrow_republication([]) is False
    assert needs_full_tomorrow_republication(["tomorrow_soc_handoff"]) is False


def test_any_actual_tomorrow_change_still_triggers_same_scan_republish() -> None:
    for kind in (
        "tomorrow_slots",
        "price_quality",
        "tomorrow_period",
        "future_unknown_new_field",
    ):
        assert needs_full_tomorrow_republication([kind]) is True
        assert needs_full_tomorrow_republication(["tomorrow_soc_handoff", kind]) is True


def test_handoff_state_written_even_when_second_publish_is_skipped() -> None:
    source = (KEMS / "agile_settled_soc_handoff.py").read_text()
    assert 'state["tomorrow_soc_handoff"] = {' in source
    assert 'state["settled_soc_handoff_reconciliation"] = diagnostic' in source
    assert "manager._state = state" in source
    assert "if second_publication_needed:" in source
    assert "manager._publish(manager._state)" in source
    assert "needs_full_tomorrow_republication(" in source


def test_full_synchronous_settlement_chain_and_live_writer_preserved() -> None:
    # Even if a handoff-only intermediate publication is suppressed, the
    # current synchronous owner publishes after flow and deadline overlays.
    deadline = (KEMS / "agile_deadline_settlement_consistency.py").read_text()
    assert "super().reconcile_current_day_settlements(" in deadline
    assert "rebase_day_summary_deadline_from_rolling(" in deadline
    assert "self._publish(self._state)" in deadline
    coord = (KEMS / "coordinator.py").read_text()
    assert "if post_shadow_settlement_changed:" in coord
    assert "self._agile_smart_export.reconcile_current_day_settlements(" in coord
    assert "self._foxess_control.async_update(" in coord


def test_snapshot_cadence_and_physical_guards_unchanged() -> None:
    helper = (KEMS / "kems_core/settlement_reconciliation_cadence.py").read_text()
    assert "deepcopy(settled)" in helper
    assert "return previous != current" in helper
    handoff = (KEMS / "agile_settled_soc_handoff.py").read_text()
    assert 'prior_tomorrow_slots != state["tomorrow_slots"]' in handoff
    assert "prior_tomorrow_period" in handoff
    assert "prior_quality != state" in handoff
