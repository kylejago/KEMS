"""Final managed-dashboard pipeline shared by normal sync and update verification."""

from __future__ import annotations

_UPDATE_BUTTON = (
    "      - type: button\n"
    "        name: Check for updates\n"
    "        icon: mdi:refresh\n"
    "        show_state: false\n"
    "        tap_action:\n"
    "          action: perform-action\n"
    "          perform_action: kems.check_for_updates\n"
)


def baseline_readability_pass(content: str) -> str:
    """Apply the original non-product-specific dashboard readability fixes."""
    content = content.replace("        columns: 4\n", "        columns: 2\n").replace(
        "        columns: 5\n", "        columns: 3\n"
    )
    unsafe_failure_template = (
        "{% set failure = update.attributes.last_error or "
        "maintenance.attributes.error %}"
    )
    safe_failure_template = (
        "{% set failure = update.attributes.get('last_error') or "
        "maintenance.attributes.get('error') %}"
    )
    return content.replace(unsafe_failure_template, safe_failure_template)


def _remove_top_level_view(content: str, title: str) -> str:
    """Remove one top-level dashboard view while retaining embedded evidence."""
    marker = f"\n  - title: {title}\n"
    start = content.find(marker)
    if start < 0 and content.startswith(f"  - title: {title}\n"):
        start = 0
    if start < 0:
        return content
    search_from = start + len(marker)
    end = content.find("\n  - title:", search_from)
    if end < 0:
        end = len(content)
    return content[:start] + content[end:]


def _rename_top_level_view(
    content: str,
    *,
    old_title: str,
    old_path: str,
    new_title: str,
    new_path: str,
) -> str:
    """Rename one final navigation view without touching card copy."""
    old = f"  - title: {old_title}\n    path: {old_path}\n"
    new = f"  - title: {new_title}\n    path: {new_path}\n"
    return content.replace(old, new, 1)


def _canonical_home_copy(content: str) -> str:
    """Keep the Home page aligned with the two-product Live Data/KEMS contract."""
    content = content.replace(
        "KEMS now has four clear system types. Pick the capability you want, then "
        "choose **Live**, **Simulate** or **Control** where that type supports it.",
        "KEMS has two user-facing products: **Live Data** shows what the property "
        "actually did; **KEMS** shows what KEMS would have done using the strategy "
        "selected for the configured tariff and system.",
    )
    content = content.replace(
        "            title: Four simple types\n",
        "            title: Two user-facing products\n",
    )
    old_types = (
        "              **Live Data** — actual property data only.  \n"
        "              **Battery & Solar** — tariff-aware battery/solar optimisation.  \n"
        "              **Full KEMS** — forecasts + smart import tariffs.  \n"
        "              **Full KEMS Agile** — Full KEMS + dynamic smart export.\n"
    )
    new_types = (
        "              **Live Data** — what the property actually did.  \n"
        "              **KEMS** — what KEMS would have done using the strategy selected "
        "for the configured tariff and system.  \n"
        "              Legacy strategy engines remain internal evidence rather than "
        "separate products.\n"
    )
    return content.replace(old_types, new_types)


def inject_update_button(content: str) -> str:
    """Put the update action into the final System/Updates view deterministically."""
    if _UPDATE_BUTTON in content:
        return content

    for title, path in (("System", "system"), ("Updates", "updates")):
        marker = f"\n  - title: {title}\n    path: {path}\n"
        view_start = content.find(marker)
        if view_start < 0:
            continue
        next_view = content.find("\n  - title:", view_start + len(marker))
        cards_at = content.find("    cards:\n", view_start)
        if cards_at < 0 or (next_view >= 0 and cards_at >= next_view):
            continue
        insert_at = cards_at + len("    cards:\n")
        return content[:insert_at] + _UPDATE_BUTTON + content[insert_at:]

    raise ValueError("Managed KEMS System/Updates view is missing")


def canonicalize_final_dashboard(content: str) -> str:
    """Expose Live Data and KEMS as the only customer-facing product views."""
    content = _rename_top_level_view(
        content,
        old_title="Full KEMS",
        old_path="full-kems",
        new_title="KEMS",
        new_path="kems",
    )
    content = _remove_top_level_view(content, "Battery & Solar")
    content = _remove_top_level_view(content, "Full KEMS Agile")
    content = _canonical_home_copy(content)
    return inject_update_button(content)


def install_dashboard_pipeline() -> None:
    """Run presentation only after legacy source views have been consolidated."""
    from . import dashboard
    from . import update_orchestrator_convergent as convergent
    from .energy_bill_presentation import improve_energy_bill_dashboard

    # Alpha8.14 attached product presentation to the base readability pass, which
    # meant source views were renamed/removed before dashboard_consolidation could
    # consume them. Restore only the original readability behavior at that stage.
    dashboard._dashboard_readability_pass = baseline_readability_pass

    original_builder = dashboard._combined_master_dashboard_bytes
    if not getattr(original_builder, "_kems_final_dashboard_pipeline", False):

        def final_dashboard_bytes() -> bytes:
            content = original_builder().decode("utf-8")
            content = improve_energy_bill_dashboard(content)
            content = canonicalize_final_dashboard(content)
            return content.encode("utf-8")

        final_dashboard_bytes._kems_final_dashboard_pipeline = True
        dashboard._combined_master_dashboard_bytes = final_dashboard_bytes

    # update_orchestrator_convergent imported the builder by value during package
    # import. Point its payload generator at the live final builder so dashboard
    # sync and exact convergence always hash and write identical bytes.
    def managed_dashboard_bytes() -> bytes:
        return dashboard._combined_master_dashboard_bytes()

    managed_dashboard_bytes._kems_final_dashboard_pipeline = True
    convergent._managed_dashboard_bytes = managed_dashboard_bytes
