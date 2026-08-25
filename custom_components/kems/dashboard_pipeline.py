"""Fresh managed-dashboard pipeline shared by sync and exact verification."""

from __future__ import annotations


def _plan_table_card(*, title: str, attribute: str, empty_message: str) -> str:
    """Return one readable full-card-width chronological KEMS plan table."""
    return f"""      - type: markdown
        title: {title}
        content: |
          {{% set slots = state_attr('sensor.kems_agile_slots', '{attribute}') or [] %}}
          {{% if slots %}}
          | Time | Rate | KEMS plan and energy |
          |---|---:|---|
          {{% for p in slots %}}
          {{% set raw = (p.get('actions') or ['—']) | join(', ') %}}
          {{% set a = raw | lower %}}
          {{% set plan = 'Cheap charge' if 'cheap charge' in a else 'Max discharge' if 'maximum discharge' in a else 'Deadline export' if 'deadline' in a else 'Battery export' if 'export battery' in a else 'Store solar' if 'store solar' in a else 'Battery → home' if 'battery to home' in a else raw[:36] %}}
          {{% set gi = p.get('grid_import_kwh') %}}
          {{% set ge = p.get('grid_export_kwh') %}}
          {{% set bo = p.get('battery_export_kwh') %}}
          {{% set soc = p.get('ending_soc_percent') %}}
          | {{{{ p.get('label', '—') }}}} | {{{{ ('%.2f' | format(p.get('rate_pence') | float(0))) ~ 'p' if p.get('rate_pence') is not none else '—' }}}} | **{{{{ plan }}}}** · Grid in/out {{{{ ('%.2f' | format(gi | float(0))) if gi is not none else '—' }}}}/{{{{ ('%.2f' | format(ge | float(0))) if ge is not none else '—' }}}} · Batt out {{{{ ('%.2f' | format(bo | float(0))) if bo is not none else '—' }}}} · SOC {{{{ ('%.1f%%' | format(soc | float(0))) if soc is not none else '—' }}}} |
          {{% endfor %}}
          {{% else %}}
          {empty_message}
          {{% endif %}}
"""


def _replace_split_plan_cards(
    text: str,
    *,
    first_title: str,
    next_view_title: str,
    replacement: str,
) -> str:
    """Replace three narrow period cards with one wide chronological list."""
    start_marker = f"      - type: markdown\n        title: {first_title}\n"
    end_marker = f"\n  - title: {next_view_title}\n"
    start = text.find(start_marker)
    if start < 0:
        return text
    end = text.find(end_marker, start)
    if end < 0:
        raise ValueError(
            f"Could not find {next_view_title!r} after managed plan {first_title!r}"
        )
    return f"{text[:start]}{replacement.rstrip()}{text[end:]}"


def _finalise_dashboard_bytes(payload: bytes) -> bytes:
    """Apply deterministic layout/safety fixes shared by sync and verification."""
    text = payload.decode("utf-8")

    # A normal Lovelace masonry column is wide enough for one readable table, but
    # not for three six-column tables nested side-by-side. Replace the three period
    # cards with one chronological list for each day.
    text = _replace_split_plan_cards(
        text,
        first_title="Today — 00:00 to 07:30",
        next_view_title="Compare",
        replacement=_plan_table_card(
            title="Today's KEMS plan — 00:00 to 23:30",
            attribute="today_slots",
            empty_message="Today's plan is not available yet.",
        ),
    )
    text = _replace_split_plan_cards(
        text,
        first_title="Tomorrow — 00:00 to 07:30",
        next_view_title="History",
        replacement=_plan_table_card(
            title="Tomorrow's KEMS plan — 00:00 to 23:30",
            attribute="tomorrow_slots",
            empty_message="Tomorrow's slots have not been published yet.",
        ),
    )

    # Aggregate Tomorrow values must tolerate partial/progressive publication and
    # current slots whose execution fields are intentionally not populated yet.
    for field in (
        "grid_import_kwh",
        "grid_export_kwh",
        "battery_export_kwh",
        "rate_pence",
    ):
        text = text.replace(
            f"p.get('{field}', 0) | float",
            f"p.get('{field}') | float(0)",
        )

    publication_row = "          | Published slots | {{ slots | count }}/48 |\n"
    missing_row = (
        "          | Awaiting publication | {{ (s.attributes.tomorrow_missing_labels "
        "| join(', ')) if s and s.attributes.tomorrow_missing_labels else 'None' }} |\n"
    )
    if publication_row in text and missing_row not in text:
        text = text.replace(publication_row, publication_row + missing_row, 1)

    return text.encode("utf-8")


def _fresh_dashboard_bytes() -> bytes:
    """Return the authoritative customer dashboard after deterministic finalisation."""
    from . import dashboard

    return _finalise_dashboard_bytes(dashboard.PACKAGED_DASHBOARD_PATH.read_bytes())


def install_dashboard_pipeline() -> None:
    """Make one final dashboard payload authoritative for sync and verification."""
    from . import dashboard
    from . import update_orchestrator_convergent as convergent

    # The packaged Alpha8 dashboard stays the source of truth. The deterministic
    # finaliser turns dense split plan cards into readable single lists; normal sync
    # and exact updater verification still consume the identical bytes.
    dashboard._combined_master_dashboard_bytes = _fresh_dashboard_bytes
    convergent._managed_dashboard_bytes = _fresh_dashboard_bytes
