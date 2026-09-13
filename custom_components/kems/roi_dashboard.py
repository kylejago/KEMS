"""Managed-dashboard extension for the Alpha9.33 live ROI view."""

from __future__ import annotations

from collections.abc import Callable

DashboardBytesFn = Callable[[], bytes]

_installed = False


def install_roi_dashboard_extension() -> None:
    """Append the packaged ROI view without changing the proven base pipeline."""
    global _installed
    if _installed:
        return

    from . import dashboard, dashboard_pipeline

    base_fresh_dashboard_bytes: DashboardBytesFn = dashboard_pipeline._fresh_dashboard_bytes

    def _fresh_dashboard_bytes_with_roi() -> bytes:
        """Return the normal managed dashboard followed by the live ROI view."""
        master = base_fresh_dashboard_bytes().decode("utf-8").rstrip()
        roi_path = dashboard.PACKAGED_DASHBOARD_PATH.with_name(
            "kems_roi_lifetime_dashboard.yaml"
        )
        roi = roi_path.read_text(encoding="utf-8")
        marker = "\nviews:\n"
        if marker not in roi:
            raise ValueError("Packaged KEMS ROI dashboard has no views section")
        roi_views = roi.split(marker, 1)[1].lstrip("\n")
        return f"{master}\n\n{roi_views}".encode()

    dashboard_pipeline._fresh_dashboard_bytes = _fresh_dashboard_bytes_with_roi
    _installed = True
