"""Fresh managed-dashboard pipeline shared by sync and exact verification."""

from __future__ import annotations


def _fresh_dashboard_bytes() -> bytes:
    """Return the packaged customer dashboard without legacy composition."""
    from . import dashboard

    return dashboard.PACKAGED_DASHBOARD_PATH.read_bytes()


def install_dashboard_pipeline() -> None:
    """Make the rebuilt packaged dashboard the one authoritative payload."""
    from . import dashboard
    from . import update_orchestrator_convergent as convergent

    # Alpha8.19 deliberately bypasses the historical dashboard compositor and all
    # presentation patch chains. The packaged dashboard is now written exactly as
    # shipped, and the updater hashes the exact same bytes.
    dashboard._combined_master_dashboard_bytes = _fresh_dashboard_bytes
    convergent._managed_dashboard_bytes = _fresh_dashboard_bytes
