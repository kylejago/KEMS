"""Fresh managed-dashboard pipeline shared by sync and exact verification."""

from __future__ import annotations


_PLAN_VALUE_EXPRESSIONS = {
    "{{ '%.2f' | format(p.get('grid_import_kwh', 0) | float) }}": (
        "{{ ('%.2f' | format(p.get('grid_import_kwh') | float(0))) if "
        "p.get('grid_import_kwh') is not none else '—' }}"
    ),
    "{{ '%.2f' | format(p.get('grid_export_kwh', 0) | float) }}": (
        "{{ ('%.2f' | format(p.get('grid_export_kwh') | float(0))) if "
        "p.get('grid_export_kwh') is not none else '—' }}"
    ),
    "{{ '%.2f' | format(p.get('battery_export_kwh', 0) | float) }}": (
        "{{ ('%.2f' | format(p.get('battery_export_kwh') | float(0))) if "
        "p.get('battery_export_kwh') is not none else '—' }}"
    ),
}


def _wrap_plan_cards(
    text: str,
    *,
    first_title: str,
    next_view_title: str,
) -> str:
    """Keep a three-card day plan together instead of letting masonry scatter it."""
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

    cards = text[start:end]
    nested_cards = "\n".join(
        f"    {line}" if line else line for line in cards.splitlines()
    )
    grid = (
        "      - type: grid\n"
        "        columns: 3\n"
        "        square: false\n"
        "        cards:\n"
        f"{nested_cards}"
    )
    return f"{text[:start]}{grid}{text[end:]}"


def _finalise_dashboard_bytes(payload: bytes) -> bytes:
    """Apply the small runtime layout/safety fixes shared by sync and verification."""
    text = payload.decode("utf-8")

    # Home Assistant's default masonry view independently places top-level cards in
    # the shortest column. Nest the three chronological plan cards in one grid so
    # 00:00, 08:00 and 16:00 always stay together left-to-right.
    text = _wrap_plan_cards(
        text,
        first_title="Today — 00:00 to 07:30",
        next_view_title="Compare",
    )
    text = _wrap_plan_cards(
        text,
        first_title="Tomorrow — 00:00 to 07:30",
        next_view_title="History",
    )

    # A current/future slot may intentionally have execution fields set to null.
    # Markdown must show an em dash for those values rather than aborting the whole
    # card while trying to format None as a number.
    for unsafe, safe in _PLAN_VALUE_EXPRESSIONS.items():
        text = text.replace(unsafe, safe)

    # Aggregate Tomorrow values should tolerate partial/progressive publication and
    # current slots whose execution fields are not populated yet.
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

    # The packaged Alpha8 dashboard stays the source of truth. A small deterministic
    # finaliser now fixes Lovelace plan-card layout and nullable slot presentation;
    # normal sync and exact updater verification still consume the identical bytes.
    dashboard._combined_master_dashboard_bytes = _fresh_dashboard_bytes
    convergent._managed_dashboard_bytes = _fresh_dashboard_bytes
