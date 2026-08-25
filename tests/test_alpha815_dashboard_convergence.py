"""Executable regression coverage for Alpha8.15 dashboard convergence."""

from __future__ import annotations

from pathlib import Path

import pytest
from dashboard_convergence import (
    DashboardConvergenceError,
    sync_and_verify_managed_dashboard,
    verify_managed_dashboard,
)

ROOT = Path(__file__).parents[1]
CONVERGENT = ROOT / "custom_components" / "kems" / "update_orchestrator_convergent.py"
INIT = ROOT / "custom_components" / "kems" / "__init__.py"
PRESENTATION = ROOT / "custom_components" / "kems" / "energy_bill_presentation.py"

EXPECTED = b"title: KEMS\nviews:\n  - title: Live Data\n  - title: KEMS\n"


def test_missing_dashboard_is_created_and_verified_exactly(tmp_path: Path) -> None:
    target = tmp_path / "kems_master_dashboard.yaml"

    verification = sync_and_verify_managed_dashboard(target, EXPECTED)

    assert verification.current is True
    assert target.read_bytes() == EXPECTED
    assert verification.installed_sha256 == verification.expected_sha256


def test_stale_dashboard_is_replaced_and_verified_exactly(tmp_path: Path) -> None:
    target = tmp_path / "kems_master_dashboard.yaml"
    target.write_bytes(b"stale dashboard")
    before = verify_managed_dashboard(target, EXPECTED)
    assert before.current is False
    assert before.installed_sha256 != before.expected_sha256

    after = sync_and_verify_managed_dashboard(target, EXPECTED)

    assert after.current is True
    assert target.read_bytes() == EXPECTED
    assert after.installed_sha256 == after.expected_sha256


def test_dashboard_write_error_is_explicit_not_waiting_forever(tmp_path: Path) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("file", encoding="utf-8")
    target = blocked_parent / "kems_master_dashboard.yaml"

    with pytest.raises(DashboardConvergenceError, match="repair failed"):
        sync_and_verify_managed_dashboard(target, EXPECTED)


def test_active_updater_owns_convergence_and_hard_fails_pending_error() -> None:
    init = INIT.read_text(encoding="utf-8")
    content = CONVERGENT.read_text(encoding="utf-8")

    assert (
        "from .update_orchestrator_convergent import async_setup_update_orchestrator"
        in init
    )
    assert (
        "verification = await _async_converge_dashboard(self.hass, strict=True)"
        in content
    )
    assert "await self._fail_pending(str(error))" in content
    assert (
        "base.KEMSUpdateOrchestrator.async_verify_pending(self, save=save)" in content
    )
    assert 'snapshot["dashboard_verification"]' in content


def test_managed_payload_anchor_is_updates_view_not_description_copy() -> None:
    content = CONVERGENT.read_text(encoding="utf-8")

    assert '_UPDATE_VIEW = "\\n  - title: Updates\\n    path: updates\\n"' in content
    assert '_UPDATE_CARDS = "    cards:\\n"' in content
    assert "Managed KEMS Updates view marker is missing" not in content
    assert "Automatic updates are opt-in" not in content


def test_alpha815_keeps_live_data_kems_presentation_and_hardware_boundary() -> None:
    presentation = PRESENTATION.read_text(encoding="utf-8")
    content = CONVERGENT.read_text(encoding="utf-8")

    assert "KEMS has two user-facing views: **Live Data**" in presentation
    assert '"  - title: Live Data\\n    path: live-data\\n"' in presentation
    assert '"  - title: KEMS\\n    path: kems\\n"' in presentation
    assert "real_backend" not in content
    assert "commands_permitted" not in content
