"""Final YAML guard for the managed Agile Smart Export dashboard view."""

from __future__ import annotations

_BAD_AGILE_VIEW_ROOT = "\n\n- title: Agile Smart Export\n"
_GOOD_AGILE_VIEW_ROOT = "\n\n  - title: Agile Smart Export\n"


def repair_agile_live_view_indentation(content: bytes) -> bytes:
    """Keep the Agile live view inside the dashboard's top-level views list."""
    text = content.decode("utf-8")
    if _BAD_AGILE_VIEW_ROOT in text:
        text = text.replace(_BAD_AGILE_VIEW_ROOT, _GOOD_AGILE_VIEW_ROOT, 1)
    return text.encode("utf-8")


def install_dashboard_yaml_guard() -> None:
    """Install the final dashboard-output guard exactly once."""
    from . import dashboard as dashboard_module

    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_agile_yaml_guard", False):
        return

    def combined_dashboard_with_yaml_guard() -> bytes:
        return repair_agile_live_view_indentation(original())

    combined_dashboard_with_yaml_guard._kems_agile_yaml_guard = True
    dashboard_module._combined_master_dashboard_bytes = combined_dashboard_with_yaml_guard
