"""Fresh managed-dashboard pipeline shared by sync and exact verification."""

from __future__ import annotations


def _plan_table_card(*, title: str, attribute: str, empty_message: str) -> str:
    """Return one readable chronological KEMS plan table."""
    plan_line = (
        "          {% set rolling = (p.get('rolling_action') or '') | lower %}\n"
        "          {% set planned_export = "
        "p.get('rolling_planned_battery_export_kwh') %}\n"
        "          {% if 'hold' in rolling %}\n"
        "          {% set plan = 'House first — no battery export planned' %}\n"
        "          {% elif 'planned battery export' in rolling %}\n"
        "          {% set plan = 'Battery export' %}\n"
        "          {% elif 'cheap charge' in a %}\n"
        "          {% set plan = 'Cheap charge' %}\n"
        "          {% elif 'maximum discharge' in a %}\n"
        "          {% set plan = 'Maximum discharge' %}\n"
        "          {% elif 'deadline' in a %}\n"
        "          {% set plan = 'Deadline export' %}\n"
        "          {% elif 'store solar' in a %}\n"
        "          {% set plan = 'Store solar' %}\n"
        "          {% elif 'battery to home' in a %}\n"
        "          {% set plan = 'Battery → home' %}\n"
        "          {% else %}\n"
        "          {% set plan = raw[:48] %}\n"
        "          {% endif %}\n"
    )
    detail_line = (
        "          | {{ p.get('label', '—') }} | **{{ plan }}**<br>"
        "{{ ('%.2f' | format(p.get('rate_pence') | float(0))) ~ 'p' if "
        "p.get('rate_pence') is not none else 'Rate —' }}"
        "{% if planned_export is not none and planned_export | float(0) > 0 %}"
        " · Export {{ '%.2f' | format(planned_export | float(0)) }} kWh"
        "{% elif bo is not none and bo | float(0) > 0 %}"
        " · Export {{ '%.2f' | format(bo | float(0)) }} kWh"
        "{% endif %}"
        "{% if gi is not none and gi | float(0) > 0 %}"
        " · Grid in {{ '%.2f' | format(gi | float(0)) }} kWh"
        "{% endif %}"
        "{% if soc is not none %}"
        " · SOC {{ '%.1f%%' | format(soc | float(0)) }}"
        "{% endif %} |\n"
    )
    return (
        "      - type: markdown\n"
        f"        title: {title}\n"
        "        content: |\n"
        f"          {{% set slots = state_attr('sensor.kems_agile_slots', "
        f"'{attribute}') or [] %}}\n"
        "          {% if slots %}\n"
        "          Future rows show the **current plan snapshot**. KEMS recalculates "
        "the plan continuously; **no battery export planned** is a deliberate "
        "decision, not a waiting/error state.\n\n"
        "          | Time | KEMS plan |\n"
        "          |---|---|\n"
        "          {% for p in slots %}\n"
        "          {% set raw = (p.get('actions') or ['—']) | join(', ') %}\n"
        "          {% set a = raw | lower %}\n"
        f"{plan_line}"
        "          {% set gi = p.get('grid_import_kwh') %}\n"
        "          {% set bo = p.get('battery_export_kwh') %}\n"
        "          {% set soc = p.get('ending_soc_percent') %}\n"
        f"{detail_line}"
        "          {% endfor %}\n"
        "          {% else %}\n"
        f"          {empty_message}\n"
        "          {% endif %}\n"
    )


def _replace_split_plan_cards(
    text: str,
    *,
    first_title: str,
    next_view_title: str,
    replacement: str,
) -> str:
    """Replace three narrow period cards with one chronological list."""
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

    # Render one compact two-column table instead of exposing the rolling planner's
    # implementation wording or trying to fit flow details into many narrow columns.
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
    # finaliser turns rolling implementation detail into a readable customer plan;
    # normal sync and exact updater verification consume the identical bytes.
    dashboard._combined_master_dashboard_bytes = _fresh_dashboard_bytes
    convergent._managed_dashboard_bytes = _fresh_dashboard_bytes
