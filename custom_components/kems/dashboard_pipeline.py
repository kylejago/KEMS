"""Final managed-dashboard pipeline shared by normal sync and update verification."""

# ruff: noqa: E501

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

_KEMS_PREFIX = r"""      - type: markdown
        content: |
          # KEMS
          KEMS is one user-facing product. It automatically uses the strategy selected for the configured system and export tariff; the legacy replay engines remain internal validation evidence.

          **Selected strategy:** {{ state_attr('sensor.kems_energy_cost_comparison', 'selected_kems_strategy_label') or '—' }}
      - type: markdown
        title: KEMS power now
        content: |
          {% set c = 'sensor.kems_energy_cost_comparison' %}
          {% set strategy = state_attr(c, 'selected_kems_strategy') or 'fixed' %}
          {% if strategy == 'none' %}
            {% set e = 'sensor.kems_compare_kems_no_export_cost_today' %}
          {% elif strategy == 'agile' %}
            {% set e = 'sensor.kems_agile_live_scenario' %}
          {% else %}
            {% set e = 'sensor.kems_compare_full_kems_forecast_cost_today' %}
          {% endif %}
          {% set soc = state_attr(e, 'current_battery_soc_percent') %}
          {% if soc is none %}{% set soc = state_attr(e, 'simulated_soc_percent') %}{% endif %}
          | Flow | KEMS |
          |---|---:|
          | House load | {{ state_attr(e, 'current_house_load_kw') if state_attr(e, 'current_house_load_kw') is not none else '—' }} kW |
          | Solar | {{ state_attr(e, 'current_solar_power_kw') if state_attr(e, 'current_solar_power_kw') is not none else '—' }} kW |
          | Grid import | {{ state_attr(e, 'current_grid_import_kw') if state_attr(e, 'current_grid_import_kw') is not none else '—' }} kW |
          | Grid export | {{ state_attr(e, 'current_grid_export_kw') if state_attr(e, 'current_grid_export_kw') is not none else '—' }} kW |
          | Grid → battery | {{ state_attr(e, 'current_grid_to_battery_kw') if state_attr(e, 'current_grid_to_battery_kw') is not none else '—' }} kW |
          | Battery → home | {{ state_attr(e, 'current_battery_to_home_kw') if state_attr(e, 'current_battery_to_home_kw') is not none else '—' }} kW |
          | Battery → export | {{ state_attr(e, 'current_battery_export_kw') if state_attr(e, 'current_battery_export_kw') is not none else '—' }} kW |
          | Battery SOC | {{ soc if soc is not none else '—' }}% |
      - type: markdown
        title: Today — KEMS energy cost
        content: |
          {% set p = ((state_attr('sensor.kems_energy_cost_comparison', 'periods') or {}).get('today', {}) or {}) %}
          {% set k = p.get('kems', {}) or {} %}
          | Metric | KEMS |
          |---|---:|
          | Total energy cost | {{ ('£%.2f' | format((k.get('total_energy_cost_pence') | float) / 100)) if k.get('total_energy_cost_pence') is not none else '—' }} |
          | Electricity | {{ ('£%.2f' | format((k.get('electricity_total_cost_pence') | float) / 100)) if k.get('electricity_total_cost_pence') is not none else '—' }} |
          | Gas | {{ ('£%.2f' | format((k.get('gas_total_cost_pence') | float) / 100)) if k.get('gas_total_cost_pence') is not none else '—' }} |
          | Home energy | {{ k.get('home_energy_kwh', '—') }} kWh |
          | Grid import | {{ k.get('grid_import_kwh', '—') }} kWh |
          | Grid export | {{ k.get('grid_export_kwh', '—') }} kWh |
      - type: entities
        title: Tariff & strategy inputs
        show_header_toggle: false
        entities:
          - entity: select.kems_export_tariff
            name: Export tariff
          - entity: sensor.kems_current_import_rate
            name: Import rate now
          - entity: binary_sensor.kems_cheap_period_confirmed
            name: Cheap period
          - entity: sensor.kems_agile_export_rate_now
            name: Agile export rate now
          - entity: sensor.kems_agile_price_data_quality
            name: Agile price coverage
"""

_COMPARE_VIEW = r"""  - title: Compare
    path: compare
    icon: mdi:compare-horizontal
    cards:
      - type: markdown
        content: |
          # Live Data vs KEMS
          This is the only user-facing comparison. **Live Data** is what the property actually did; **KEMS** is what KEMS would have done using the strategy selected for the configured tariff and system.

          **KEMS strategy:** {{ state_attr('sensor.kems_energy_cost_comparison', 'selected_kems_strategy_label') or '—' }}
      - type: markdown
        title: Right now — power
        content: |
          {% set c = 'sensor.kems_energy_cost_comparison' %}
          {% set strategy = state_attr(c, 'selected_kems_strategy') or 'fixed' %}
          {% if strategy == 'none' %}
            {% set e = 'sensor.kems_compare_kems_no_export_cost_today' %}
          {% elif strategy == 'agile' %}
            {% set e = 'sensor.kems_agile_live_scenario' %}
          {% else %}
            {% set e = 'sensor.kems_compare_full_kems_forecast_cost_today' %}
          {% endif %}
          {% set soc = state_attr(e, 'current_battery_soc_percent') %}
          {% if soc is none %}{% set soc = state_attr(e, 'simulated_soc_percent') %}{% endif %}
          | Metric | Live Data | KEMS |
          |---|---:|---:|
          | House load kW | {{ states('sensor.kems_house_load') }} | {{ state_attr(e, 'current_house_load_kw') if state_attr(e, 'current_house_load_kw') is not none else '—' }} |
          | Solar kW | {{ states('sensor.kems_solar_power') }} | {{ state_attr(e, 'current_solar_power_kw') if state_attr(e, 'current_solar_power_kw') is not none else '—' }} |
          | Grid import kW | {{ states('sensor.kems_grid_import') }} | {{ state_attr(e, 'current_grid_import_kw') if state_attr(e, 'current_grid_import_kw') is not none else '—' }} |
          | Grid export kW | {{ states('sensor.kems_grid_export') }} | {{ state_attr(e, 'current_grid_export_kw') if state_attr(e, 'current_grid_export_kw') is not none else '—' }} |
          | Battery SOC % | {{ states('sensor.kems_battery_state_of_charge') }} | {{ soc if soc is not none else '—' }} |
      - type: markdown
        title: Today — total energy cost & energy
        content: |
          {% set p = ((state_attr('sensor.kems_energy_cost_comparison', 'periods') or {}).get('today', {}) or {}) %}
          {% set live = p.get('live_data', {}) or {} %}
          {% set kems = p.get('kems', {}) or {} %}
          | Metric | Live Data | KEMS |
          |---|---:|---:|
          | Total energy cost | {{ ('£%.2f' | format((live.get('total_energy_cost_pence') | float) / 100)) if live.get('total_energy_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('total_energy_cost_pence') | float) / 100)) if kems.get('total_energy_cost_pence') is not none else '—' }} |
          | Electricity | {{ ('£%.2f' | format((live.get('electricity_total_cost_pence') | float) / 100)) if live.get('electricity_total_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('electricity_total_cost_pence') | float) / 100)) if kems.get('electricity_total_cost_pence') is not none else '—' }} |
          | Gas | {{ ('£%.2f' | format((live.get('gas_total_cost_pence') | float) / 100)) if live.get('gas_total_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('gas_total_cost_pence') | float) / 100)) if kems.get('gas_total_cost_pence') is not none else '—' }} |
          | Home energy kWh | {{ live.get('home_energy_kwh', '—') }} | {{ kems.get('home_energy_kwh', '—') }} |
          | Grid import kWh | {{ live.get('grid_import_kwh', '—') }} | {{ kems.get('grid_import_kwh', '—') }} |
          | Grid export kWh | {{ live.get('grid_export_kwh', '—') }} | {{ kems.get('grid_export_kwh', '—') }} |

          **Saving today:** {{ ('£%.2f' | format((p.get('saving_pence') | float) / 100)) if p.get('saving_pence') is not none else '—' }}
"""

_AGILE_SLOTS_HEADER = r"""  - title: Agile Slots
    path: agile-slots
    icon: mdi:chart-timeline-variant
    cards:
      - type: markdown
        content: |
          # Agile Slots
          These are the half-hour Agile Outgoing prices and the KEMS plan that uses them. **Agile Slots is tariff/plan information, not a separate KEMS product.**
"""


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


def _view_span(content: str, title: str) -> tuple[int, int] | None:
    """Return the exact top-level view span without consuming the next view."""
    marker = f"  - title: {title}\n"
    if content.startswith(marker):
        start = 0
    else:
        found = content.find(f"\n{marker}")
        if found < 0:
            return None
        start = found + 1
    next_view = content.find("\n  - title:", start + len(marker))
    end = len(content) if next_view < 0 else next_view + 1
    return start, end


def _remove_top_level_view(content: str, title: str) -> str:
    """Remove one top-level dashboard view while retaining embedded evidence."""
    span = _view_span(content, title)
    if span is None:
        return content
    start, end = span
    return content[:start] + content[end:]


def _replace_top_level_view(content: str, title: str, replacement: str) -> str:
    """Replace one top-level view with a deterministic final presentation."""
    span = _view_span(content, title)
    if span is None:
        return content
    start, end = span
    return content[:start] + replacement.rstrip() + "\n" + content[end:]


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


def _section_span(
    content: str,
    *,
    view_title: str,
    section_title: str,
) -> tuple[int, int] | None:
    """Return one consolidation section inside a top-level view."""
    view = _view_span(content, view_title)
    if view is None:
        return None
    view_start, view_end = view
    marker = (
        "      - type: markdown\n"
        "        content: |\n"
        f"          ## {section_title}\n"
    )
    start = content.find(marker, view_start, view_end)
    if start < 0:
        return None
    next_section = content.find(
        "      - type: markdown\n        content: |\n          ## ",
        start + len(marker),
        view_end,
    )
    end = view_end if next_section < 0 else next_section
    return start, end


def _extract_section_cards(
    content: str,
    *,
    view_title: str,
    section_title: str,
) -> str | None:
    """Extract the cards belonging to one consolidation section."""
    span = _section_span(
        content,
        view_title=view_title,
        section_title=section_title,
    )
    if span is None:
        return None
    start, end = span
    marker = (
        "      - type: markdown\n"
        "        content: |\n"
        f"          ## {section_title}\n"
    )
    return content[start + len(marker) : end].rstrip() + "\n"


def _remove_section(
    content: str,
    *,
    view_title: str,
    section_title: str,
) -> str:
    """Remove one embedded consolidation section from a final view."""
    span = _section_span(
        content,
        view_title=view_title,
        section_title=section_title,
    )
    if span is None:
        return content
    start, end = span
    return content[:start] + content[end:]


def _replace_view_prefix(content: str, *, title: str, replacement: str) -> str:
    """Replace cards before the first consolidation section in one view."""
    span = _view_span(content, title)
    if span is None:
        return content
    start, end = span
    cards_marker = "    cards:\n"
    cards_at = content.find(cards_marker, start, end)
    if cards_at < 0:
        return content
    body_start = cards_at + len(cards_marker)
    first_section = content.find(
        "      - type: markdown\n        content: |\n          ## ",
        body_start,
        end,
    )
    body_end = end if first_section < 0 else first_section
    return content[:body_start] + replacement.rstrip() + "\n" + content[body_end:]


def _ensure_agile_slots_view(content: str) -> str:
    """Preserve the Agile price-plan cards as tariff information."""
    if _view_span(content, "Agile Slots") is not None:
        return content
    cards = _extract_section_cards(
        content,
        view_title="Full KEMS Agile",
        section_title="Agile Price Plan",
    )
    if not cards:
        return content
    agile_view = _AGILE_SLOTS_HEADER.rstrip() + "\n" + cards
    history = _view_span(content, "History")
    insert_at = len(content) if history is None else history[0]
    return content[:insert_at] + agile_view.rstrip() + "\n" + content[insert_at:]


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
        "              **Battery & Solar** — tariff-aware battery/solar "
        "optimisation.  \n"
        "              **Full KEMS** — forecasts + smart import tariffs.  \n"
        "              **Full KEMS Agile** — Full KEMS + dynamic smart export.\n"
    )
    new_types = (
        "              **Live Data** — what the property actually did.  \n"
        "              **KEMS** — what KEMS would have done using the strategy "
        "selected for the configured tariff and system.  \n"
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
    """Expose two products while preserving tariff/plan information."""
    content = _ensure_agile_slots_view(content)
    content = _rename_top_level_view(
        content,
        old_title="Full KEMS",
        old_path="full-kems",
        new_title="KEMS",
        new_path="kems",
    )
    content = _replace_view_prefix(content, title="KEMS", replacement=_KEMS_PREFIX)
    content = _remove_section(
        content,
        view_title="KEMS",
        section_title="Full KEMS Forecast",
    )
    content = _replace_top_level_view(content, "Compare", _COMPARE_VIEW)
    content = _remove_section(
        content,
        view_title="History",
        section_title="Agile History",
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

    # Product presentation must run only after the legacy source contract has been
    # consolidated. Earlier presentation patches are reset to the original
    # readability behavior at the source stage.
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
