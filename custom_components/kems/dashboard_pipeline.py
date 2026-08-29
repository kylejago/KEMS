"""Fresh managed-dashboard pipeline shared by sync and exact verification."""

from __future__ import annotations

_ROUTE_LABEL_DISPLAY_MAP = (
    "{'EXPO': 'EXPORT', "
    "'IMPORT/EXPO': 'IMPORT/EXPORT', "
    "'HOME/EXPO': 'HOME/EXPORT', "
    "'BATT/EXPO': 'BATT/EXPORT', "
    "'HOME/BATT/EXPO': 'HOME/BATT/EXPORT', "
    "'EXPO/CHARGE': 'EXPORT/CHARGE', "
    "'HOME/EXPO/CHARGE': 'HOME/EXPORT/CHARGE'}"
)


def _route_template_line(
    *,
    indent: str,
    variable: str,
    field: str,
    trim_left: bool = False,
) -> str:
    """Return one canonical route-label Jinja assignment."""
    opener = "{%-" if trim_left else "{%"
    return (
        f"{indent}{opener} set {variable} = "
        f"{_ROUTE_LABEL_DISPLAY_MAP}.get("
        f"(p.get('{field}') or 'IDLE'), "
        f"(p.get('{field}') or 'IDLE')) %}\n"
    )


def _plan_table_card(
    *,
    title: str,
    attribute: str,
    empty_message: str,
    indent: str = "          ",
) -> str:
    """Return one chronological Grid/Solar/Battery plan table."""
    card = indent
    field = f"{indent}  "
    content = f"{indent}    "
    return (
        f"{card}- type: markdown\n"
        f"{field}title: {title}\n"
        f"{field}content: |\n"
        f"{content}{{%- set slots = state_attr('sensor.kems_agile_slots', "
        f"'{attribute}') or [] %}}\n"
        f"{content}{{%- if slots %}}\n"
        f"{content}Future rows show the **current KEMS plan snapshot** and are "
        "recalculated continuously. Energy is the estimated activity within that "
        "half-hour (or the remaining part of the active half-hour).\n\n"
        f"{content}| Time | Price | Est. SOC | Grid | Solar | Battery |\n"
        f"{content}|---|---:|---:|---|---|---|\n"
        f"{content}{{%- for p in slots %}}\n"
        f"{content}{{%- set price = p.get('rate_pence') %}}\n"
        f"{content}{{%- set soc = p.get('flow_estimated_soc_percent') %}}\n"
        + _route_template_line(
            indent=content,
            variable="ga",
            field="flow_grid_action",
            trim_left=True,
        )
        + f"{content}{{%- set gk = p.get('flow_grid_kwh') %}}\n"
        + _route_template_line(
            indent=content,
            variable="sa",
            field="flow_solar_action",
            trim_left=True,
        )
        + f"{content}{{%- set sk = p.get('flow_solar_kwh') %}}\n"
        + _route_template_line(
            indent=content,
            variable="ba",
            field="flow_battery_action",
            trim_left=True,
        )
        + f"{content}{{%- set bk = p.get('flow_battery_kwh') %}}\n"
        f"{content}| {{{{ p.get('label', '—') }}}} | "
        "{{ ('%.2f' | format(price | float(0))) ~ 'p' if price is not none "
        "else '—' }} | "
        "{{ ('%.1f%%' | format(soc | float(0))) if soc is not none "
        "else '—' }} | "
        "**{{ ga }}** · {{ ('%.2f kWh' | format(gk | float(0))) if "
        "gk is not none else '—' }} | "
        "**{{ sa }}** · {{ ('%.2f kWh' | format(sk | float(0))) if "
        "sk is not none else '—' }} | "
        "**{{ ba }}** · {{ ('%.2f kWh' | format(bk | float(0))) if "
        "bk is not none else '—' }} |\n"
        f"{content}{{%- endfor %}}\n"
        f"{content}{{%- else %}}\n"
        f"{content}{empty_message}\n"
        f"{content}{{%- endif %}}\n"
    )


def _compact_plan_summary_card() -> str:
    """Return a narrow-card-friendly NOW/NEXT Agile flow summary."""
    indent = "          "
    return (
        "      - type: markdown\n"
        "        title: Current and next Agile slots\n"
        "        content: |\n"
        "          {% set today = state_attr("
        "'sensor.kems_agile_slots', 'today_slots') or [] %}\n"
        "          {% set tomorrow = state_attr("
        "'sensor.kems_agile_slots', 'tomorrow_slots') or [] %}\n"
        "          {% set slots = today + tomorrow %}\n"
        "          {% set minute = 0 if now().minute < 30 else 30 %}\n"
        "          {% set current_label = "
        "'%02d:%02d' | format(now().hour, minute) %}\n"
        "          {% set ns = "
        "namespace(current=none, next=none, seen=false) %}\n"
        "          {% for p in slots %}\n"
        "            {% if ns.current is none and "
        "p.get('label') == current_label %}\n"
        "              {% set ns.current = p %}\n"
        "              {% set ns.seen = true %}\n"
        "            {% elif ns.seen and ns.next is none %}\n"
        "              {% set ns.next = p %}\n"
        "              {% set ns.seen = false %}\n"
        "            {% endif %}\n"
        "          {% endfor %}\n"
        "          {% for p in [ns.current, ns.next] %}\n"
        "          {% if p %}\n"
        "          {% set price = p.get('rate_pence') %}\n"
        "          {% set soc = p.get('flow_estimated_soc_percent') %}\n"
        + _route_template_line(
            indent=indent,
            variable="ga",
            field="flow_grid_action",
        )
        + "          {% set gk = p.get('flow_grid_kwh') %}\n"
        + _route_template_line(
            indent=indent,
            variable="sa",
            field="flow_solar_action",
        )
        + "          {% set sk = p.get('flow_solar_kwh') %}\n"
        + _route_template_line(
            indent=indent,
            variable="ba",
            field="flow_battery_action",
        )
        + "          {% set bk = p.get('flow_battery_kwh') %}\n"
        "          **{{ 'NOW' if loop.index0 == 0 else 'NEXT' }} — "
        "{{ p.get('label', '—') }} · "
        "{{ ('%.2f' | format(price | float(0))) ~ 'p' "
        "if price is not none else '—' }} · est. SOC "
        "{{ ('%.1f%%' | format(soc | float(0))) "
        "if soc is not none else '—' }}**  \n"
        "          Grid **{{ ga }} · "
        "{{ ('%.2f kWh' | format(gk | float(0))) "
        "if gk is not none else '—' }}** · Solar **{{ sa }} · "
        "{{ ('%.2f kWh' | format(sk | float(0))) "
        "if sk is not none else '—' }}** · Battery **{{ ba }} · "
        "{{ ('%.2f kWh' | format(bk | float(0))) "
        "if bk is not none else '—' }}**\n\n"
        "          {% endif %}\n"
        "          {% endfor %}\n"
        "          {% if ns.current is none %}\n"
        "          Current slot summary is not available yet.\n\n"
        "          {% endif %}\n"
        "          Use the **Agile Plan** tab for the full-width Today and "
        "Tomorrow half-hour schedule.\n"
    )


def _tomorrow_plan_pointer_card() -> str:
    """Keep Tomorrow concise while pointing to the full-width plan view."""
    return (
        "      - type: markdown\n"
        "        title: Agile half-hour plan\n"
        "        content: |\n"
        "          The full 48-slot Today and Tomorrow flow schedule is now on "
        "the **Agile Plan** tab, where Home Assistant can give the table the "
        "full dashboard width.\n"
    )


def _agile_plan_view() -> str:
    """Return one native full-width panel view containing both Agile tables."""
    return (
        "\n  - title: Agile Plan\n"
        "    path: agile-plan\n"
        "    icon: mdi:table-large\n"
        "    type: panel\n"
        "    cards:\n"
        "      - type: vertical-stack\n"
        "        cards:\n"
        "          - type: markdown\n"
        "            content: |\n"
        "              # Agile Plan\n"
        "              Full-width KEMS half-hour plan. Each source/grid cell "
        "shows the planned route and its total estimated energy for that slot.\n\n"
        "              The active half-hour shows the remaining-slot estimate; "
        "future rows show the current continuously recalculated KEMS plan "
        "snapshot.\n"
        + _plan_table_card(
            title="Today's KEMS plan — 00:00 to 23:30",
            attribute="today_slots",
            empty_message="Today's plan is not available yet.",
        )
        + _plan_table_card(
            title="Tomorrow's KEMS plan — 00:00 to 23:30",
            attribute="tomorrow_slots",
            empty_message="Tomorrow's slots have not been published yet.",
        )
    )


def _replace_split_plan_cards(
    text: str,
    *,
    first_title: str,
    next_view_title: str,
    replacement: str,
) -> str:
    """Replace three narrow period cards with a deterministic replacement."""
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

    # Alpha8.52: keep the normal KEMS/Tomorrow masonry pages compact and move the
    # canonical Alpha8.48+ slot-flow tables onto one native full-width panel view.
    old_plan_note = (
        "          The plan is split into three readable sections below instead "
        "of one 48-row table.\n"
    )
    new_plan_note = (
        "          Current and next slots are summarised below. Use the "
        "**Agile Plan** tab for the full-width Today and Tomorrow schedule.\n"
    )
    text = text.replace(old_plan_note, new_plan_note, 1)
    text = _replace_split_plan_cards(
        text,
        first_title="Today — 00:00 to 07:30",
        next_view_title="Compare",
        replacement=_compact_plan_summary_card() + _agile_plan_view(),
    )
    text = _replace_split_plan_cards(
        text,
        first_title="Tomorrow — 00:00 to 07:30",
        next_view_title="History",
        replacement=_tomorrow_plan_pointer_card(),
    )

    # The customer Energy today card must use the registered cumulative charge entity.
    text = text.replace(
        "sensor.kems_simulated_battery_charge_today",
        "sensor.kems_simulated_battery_charged_today",
    )

    # Alpha8.41: the Home summary keeps its explicit electricity-net row on the
    # stable net-energy sensors, but its all-in total and saving come from the
    # canonical bill-equivalent comparison. This includes electricity standing
    # charge and supplier/account credits instead of silently labelling net + gas
    # as Total energy cost.
    home_summary_setup = (
        "          {% set live_e = states("
        "'sensor.kems_observed_cost_today') | float(0) %}\n"
        "          {% set kems_e = states("
        "'sensor.kems_simulated_kems_cost_today') | float(0) %}\n"
        "          {% set gas = states("
        "'sensor.kems_gas_cost_today') | float(0) %}\n"
        "          {% set saving = live_e - kems_e %}\n"
    )
    home_summary_reconciled_setup = (
        "          {% set live_e = states("
        "'sensor.kems_observed_cost_today') | float(0) %}\n"
        "          {% set kems_e = states("
        "'sensor.kems_simulated_kems_cost_today') | float(0) %}\n"
        "          {% set gas = states("
        "'sensor.kems_gas_cost_today') | float(0) %}\n"
        "          {% set bill_periods = state_attr("
        "'sensor.kems_energy_cost_comparison', 'periods') or {} %}\n"
        "          {% set bill = bill_periods.get('today', {}) or {} %}\n"
        "          {% set live_bill = bill.get('live_data', {}) or {} %}\n"
        "          {% set kems_bill = bill.get('kems', {}) or {} %}\n"
        "          {% set live_total = live_bill.get('total_energy_cost_pence') %}\n"
        "          {% set kems_total = kems_bill.get('total_energy_cost_pence') %}\n"
        "          {% set saving = bill.get('saving_pence') %}\n"
    )
    text = text.replace(home_summary_setup, home_summary_reconciled_setup, 1)
    old_total_row = (
        "          | **Total energy cost** | **£{{ '%.2f' | "
        "format((live_e + gas) / 100) }}** | **£{{ '%.2f' | "
        "format((kems_e + gas) / 100) }}** |\n"
    )
    new_total_row = (
        "          | **Total energy cost** | **{{ ('£%.2f' | "
        "format((live_total | float) / 100)) if live_total is not none "
        "else '—' }}** | **{{ ('£%.2f' | "
        "format((kems_total | float) / 100)) if kems_total is not none "
        "else '—' }}** |\n"
    )
    text = text.replace(old_total_row, new_total_row, 1)
    old_saving_line = (
        "          **KEMS saving today:** £{{ '%.2f' | format(saving / 100) }}\n"
    )
    new_saving_line = (
        "          **KEMS saving today:** {{ ('£%.2f' | "
        "format((saving | float) / 100)) if saving is not none "
        "else '—' }}\n\n"
        "          Total energy cost includes electricity standing charge, "
        "export income, supplier/account credits and gas.\n"
    )
    text = text.replace(old_saving_line, new_saving_line, 1)

    # The final managed dashboard, not the legacy readability compositor, is the
    # authoritative customer path. Keep normal export income on its own row and
    # expose the explicit settled Power Down reward as the separate account credit.
    supplier_credit_row = (
        "| Supplier credits | {{ ('−£%.2f' | "
        "format((kems.get('supplier_energy_credit_pence') | float) / 100)) "
        "if kems.get('supplier_energy_credit_pence') is not none else '—' }} |"
    )
    power_down_reward_row = (
        "| Supplier rewards & credits | {{ ('−£%.2f' | "
        "format((kems.get('power_down_reward_pence') | float) / 100)) "
        "if kems.get('power_down_reward_pence') is not none else '—' }} |"
    )
    text = text.replace(supplier_credit_row, power_down_reward_row)

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
    # finaliser exposes canonical flow presentation on the native full-width Agile
    # Plan view; normal sync and exact updater verification consume identical bytes.
    dashboard._combined_master_dashboard_bytes = _fresh_dashboard_bytes
    convergent._managed_dashboard_bytes = _fresh_dashboard_bytes
