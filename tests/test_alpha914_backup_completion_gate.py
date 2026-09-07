"""Alpha9.14 pre-update backup completion contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
CONVERGENT = KEMS / "update_orchestrator_convergent.py"
BASE = KEMS / "update_orchestrator.py"


def test_pre_update_backup_waits_for_fresh_completed_event() -> None:
    """Starting a backup is not enough; a fresh completed event is required."""
    content = CONVERGENT.read_text(encoding="utf-8")
    assert '_BACKUP_EVENT_ENTITY_ID = "event.backup_automatic_backup"' in content
    assert '_BACKUP_EVENT_TYPES = frozenset({"completed", "failed", "in_progress"})' in content
    assert "before_marker = before.state" in content
    assert "saw_fresh_attempt = False" in content
    assert "state.state != before_marker" in content
    assert 'if event_type == "completed":' in content
    assert 'if event_type == "failed":' in content
    assert "_BACKUP_COMPLETION_TIMEOUT_SECONDS = 3600.0" in content


def test_backup_failure_stops_before_update_install() -> None:
    """Any backup start/failure/timeout error must remain a hard install gate."""
    content = CONVERGENT.read_text(encoding="utf-8")
    backup_call = content.index('"backup",\n                "create_automatic"')
    fail_pending = content.index(
        '"Pre-update backup failed before KEMS installation started: "'
    )
    install_delegate = content.index(
        "await super().async_apply_pending(force=force)", fail_pending
    )
    assert backup_call < fail_pending < install_delegate
    assert "await self._async_require_completed_automatic_backup()" in content
    assert "KEMS will not install without completion evidence" in content


def test_verified_backup_bypass_is_transient_not_persisted_policy() -> None:
    """The base orchestrator must not create a second backup after proof completes."""
    content = CONVERGENT.read_text(encoding="utf-8")
    assert "self._verified_backup_bypass = True" in content
    assert "self.policy.backup_before_update = False" in content
    assert "Never persist the transient post-proof backup bypass" in content
    assert "self.policy.backup_before_update = True" in content
    assert "self._verified_backup_bypass = False" in content


def test_base_updater_still_keeps_backup_as_a_hard_gate() -> None:
    """Alpha9.14 strengthens rather than removes the original fail-closed contract."""
    content = BASE.read_text(encoding="utf-8")
    assert "if self.policy.backup_before_update:" in content
    assert '"backup",\n                            "create_automatic"' in content
    assert "except Exception as error:  # backup must be a hard gate" in content
    assert "Pre-update backup failed" in content


def test_alpha914_does_not_enable_hardware_writes() -> None:
    """Updater repair remains completely outside physical control authority."""
    content = CONVERGENT.read_text(encoding="utf-8")
    assert "commands_permitted" not in content
    assert "real_backend" not in content
    assert "foxess" not in content.lower()
