"""Alpha7.36 comparison completeness, winner history and Cost & ROI view."""

# ruff: noqa: E501

from __future__ import annotations


_WINNER_CARD = r"""      - type: markdown
        title: Winner by period — user-facing KEMS products
        content: |
          {% set std = state_attr('sensor.kems_scenario_comparison_today', 'periods') or {} %}
          {% set agp = state_attr('sensor.kems_agile_smart_export_plan', 'periods') or {} %}

          {% set nt = namespace(b={}, f={}) %}
          {% for x in (std.get('today', {}) or {}).get('scenarios', []) %}{% if x.get('key') == 'solar_battery' %}{% set nt.b = x %}{% elif x.get('key') == 'kems_forecast' %}{% set nt.f = x %}{% endif %}{% endfor %}
          {% set at = (agp.get('today', {}) or {}).get('agile_smart_export', {}) %}
          {% set btc = ((nt.b.get('import_cost_pence', 999999) | float) - (nt.b.get('export_income_pence', 0) | float)) / 100 %}
          {% set ftc = ((nt.f.get('import_cost_pence', 999999) | float) - (nt.f.get('export_income_pence', 0) | float)) / 100 %}
          {% set atc = ((at.get('import_cost_pence', 999999) | float) - (at.get('export_income_pence', 0) | float)) / 100 %}
          {% set tbest = [(btc, 'Battery & Solar'), (ftc, 'Full KEMS'), (atc, 'Full KEMS Agile')] | sort %}

          {% set ny = namespace(b={}, f={}) %}
          {% for x in (std.get('yesterday', {}) or {}).get('scenarios', []) %}{% if x.get('key') == 'solar_battery' %}{% set ny.b = x %}{% elif x.get('key') == 'kems_forecast' %}{% set ny.f = x %}{% endif %}{% endfor %}
          {% set ay = (agp.get('yesterday', {}) or {}).get('agile_smart_export', {}) %}
          {% set byc = ((ny.b.get('import_cost_pence', 999999) | float) - (ny.b.get('export_income_pence', 0) | float)) / 100 %}
          {% set fyc = ((ny.f.get('import_cost_pence', 999999) | float) - (ny.f.get('export_income_pence', 0) | float)) / 100 %}
          {% set ayc = ((ay.get('import_cost_pence', 999999) | float) - (ay.get('export_income_pence', 0) | float)) / 100 %}
          {% set ybest = [(byc, 'Battery & Solar'), (fyc, 'Full KEMS'), (ayc, 'Full KEMS Agile')] | sort %}

          {% set n7 = namespace(b={}, f={}) %}
          {% for x in (std.get('7_days', {}) or {}).get('scenarios', []) %}{% if x.get('key') == 'solar_battery' %}{% set n7.b = x %}{% elif x.get('key') == 'kems_forecast' %}{% set n7.f = x %}{% endif %}{% endfor %}
          {% set a7 = (agp.get('7_days', {}) or {}).get('agile_smart_export', {}) %}
          {% set b7c = ((n7.b.get('import_cost_pence', 999999) | float) - (n7.b.get('export_income_pence', 0) | float)) / 100 %}
          {% set f7c = ((n7.f.get('import_cost_pence', 999999) | float) - (n7.f.get('export_income_pence', 0) | float)) / 100 %}
          {% set a7c = ((a7.get('import_cost_pence', 999999) | float) - (a7.get('export_income_pence', 0) | float)) / 100 %}
          {% set best7 = [(b7c, 'Battery & Solar'), (f7c, 'Full KEMS'), (a7c, 'Full KEMS Agile')] | sort %}

          {% set n30 = namespace(b={}, f={}) %}
          {% for x in (std.get('30_days', {}) or {}).get('scenarios', []) %}{% if x.get('key') == 'solar_battery' %}{% set n30.b = x %}{% elif x.get('key') == 'kems_forecast' %}{% set n30.f = x %}{% endif %}{% endfor %}
          {% set a30 = (agp.get('30_days', {}) or {}).get('agile_smart_export', {}) %}
          {% set b30c = ((n30.b.get('import_cost_pence', 999999) | float) - (n30.b.get('export_income_pence', 0) | float)) / 100 %}
          {% set f30c = ((n30.f.get('import_cost_pence', 999999) | float) - (n30.f.get('export_income_pence', 0) | float)) / 100 %}
          {% set a30c = ((a30.get('import_cost_pence', 999999) | float) - (a30.get('export_income_pence', 0) | float)) / 100 %}
          {% set best30 = [(b30c, 'Battery & Solar'), (f30c, 'Full KEMS'), (a30c, 'Full KEMS Agile')] | sort %}

          {% set p365 = agp.get('365_days', {}) or {} %}
          {% set f365 = p365.get('full_kems_forecast', {}) %}
          {% set a365 = p365.get('agile_smart_export', {}) %}
          {% set f365c = ((f365.get('import_cost_pence', 999999) | float) - (f365.get('export_income_pence', 0) | float)) / 100 %}
          {% set a365c = ((a365.get('import_cost_pence', 999999) | float) - (a365.get('export_income_pence', 0) | float)) / 100 %}
          {% set best365 = [(f365c, 'Full KEMS'), (a365c, 'Full KEMS Agile')] | sort %}

          {% set pall = agp.get('all_time', {}) or {} %}
          {% set fall = pall.get('full_kems_forecast', {}) %}
          {% set aall = pall.get('agile_smart_export', {}) %}
          {% set fallc = ((fall.get('import_cost_pence', 999999) | float) - (fall.get('export_income_pence', 0) | float)) / 100 %}
          {% set aallc = ((aall.get('import_cost_pence', 999999) | float) - (aall.get('export_income_pence', 0) | float)) / 100 %}
          {% set bestall = [(fallc, 'Full KEMS'), (aallc, 'Full KEMS Agile')] | sort %}

          Common basis below is **import cost − export income**, excluding standing charge and battery-wear assumptions so the strategies are compared on the same electricity-bill basis.

          | Period | Battery & Solar | Full KEMS | Full KEMS Agile | Best |
          |---|---:|---:|---:|---|
          | Today | £{{ btc | round(2) }} | £{{ ftc | round(2) }} | £{{ atc | round(2) }} | **{{ tbest[0][1] }}** |
          | Yesterday | £{{ byc | round(2) }} | £{{ fyc | round(2) }} | £{{ ayc | round(2) }} | **{{ ybest[0][1] }}** |
          | Last 7 days | £{{ b7c | round(2) }} | £{{ f7c | round(2) }} | £{{ a7c | round(2) }} | **{{ best7[0][1] }}** |
          | Last 30 days | £{{ b30c | round(2) }} | £{{ f30c | round(2) }} | £{{ a30c | round(2) }} | **{{ best30[0][1] }}** |
          | Rolling 365 evidence | — | £{{ f365c | round(2) }} | £{{ a365c | round(2) }} | **{{ best365[0][1] }}** |
          | All tracked Agile evidence | — | £{{ fallc | round(2) }} | £{{ aallc | round(2) }} | **{{ bestall[0][1] }}** |

          **365-day evidence:** {{ p365.get('evidence_status', 'Building evidence') }}. Battery & Solar does not yet have a matching 365-day replay, so KEMS shows `—` instead of inventing a result.
"""

_COST_ROI_VIEW = r"""  - title: Cost & ROI
    path: cost-roi
    icon: mdi:finance
    cards:
      - type: markdown
        content: |
          # Cost & ROI
          This page separates **money actually observed** from **money modelled by KEMS**. Before commissioning, ROI is predictive. Once the system is installed and operating, the existing actual-value ledger automatically becomes the source for actual savings, ROI and payback.
      - type: markdown
        title: Actual vs core KEMS simulation
        content: |
          {% set periods = [
            ('Today', 'sensor.kems_today_energy_summary'),
            ('This week', 'sensor.kems_week_energy_summary'),
            ('This month', 'sensor.kems_month_energy_summary'),
            ('This year — tracked data', 'sensor.kems_year_energy_summary'),
            ('All tracked', 'sensor.kems_all_time_energy_summary')
          ] %}
          | Period | Days | Actual electricity | Actual whole-home | Core simulation | Modelled value | Complete? |
          |---|---:|---:|---:|---:|---:|---|
          {% for label, e in periods %}
          {% set actual_elec = ((state_attr(e, 'import_cost_pence') or 0) - (state_attr(e, 'export_income_pence') or 0)) / 100 %}
          {% set actual_whole = (states(e) | float(0)) / 100 %}
          {% set sim = (state_attr(e, 'simulated_net_cost_pence') or 0) / 100 %}
          {% set value = (state_attr(e, 'simulated_system_value_pence') or 0) / 100 %}
          | {{ label }} | {{ state_attr(e, 'days_included') or 0 }} | £{{ actual_elec | round(2) }} | £{{ actual_whole | round(2) }} | £{{ sim | round(2) }} | £{{ value | round(2) }} | {{ 'Yes' if state_attr(e, 'data_complete') else 'Partial' }} |
          {% endfor %}

          **Actual electricity** = measured import cost − measured export income. **Actual whole-home** also includes tracked gas. The year/all-tracked rows only cover days KEMS has evidence for; they are not presented as a full calendar year when coverage is partial.
      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Predicted ROI
            show_header_toggle: false
            entities:
              - entity: sensor.kems_roi_status
                name: ROI status
              - entity: sensor.kems_system_investment
                name: System investment
              - entity: sensor.kems_predicted_annual_saving
                name: Predicted annual saving
              - entity: sensor.kems_predicted_payback
                name: Predicted payback
              - entity: sensor.kems_predicted_payback_date
                name: Predicted payback date
              - entity: sensor.kems_predicted_net_value
                name: Predicted net value
              - entity: sensor.kems_roi_confidence
                name: Confidence
          - type: entities
            title: Actual savings & ROI — fills after commissioning
            show_header_toggle: false
            entities:
              - entity: sensor.kems_actual_system_value_today
                name: Actual value today
              - entity: sensor.kems_actual_system_value_total
                name: Actual value total
              - entity: sensor.kems_actual_roi
                name: Actual ROI
              - entity: sensor.kems_actual_payback_remaining
                name: Payback remaining
              - entity: sensor.kems_actual_payback_date
                name: Actual payback date
              - entity: sensor.kems_profit_after_payback
                name: Profit after payback
      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Actual lifetime ledger
            show_header_toggle: false
            entities:
              - sensor.kems_lifetime_observed_days
              - sensor.kems_lifetime_grid_import
              - sensor.kems_lifetime_grid_export
              - sensor.kems_lifetime_import_cost
              - sensor.kems_lifetime_export_income
              - sensor.kems_lifetime_net_energy_cost
              - sensor.kems_lifetime_system_value
          - type: entities
            title: Simulated lifetime evidence
            show_header_toggle: false
            entities:
              - sensor.kems_lifetime_simulated_system_value
              - sensor.kems_simulated_saving_today
              - sensor.kems_whole_home_simulated_cost_today
              - sensor.kems_whole_home_simulated_saving_today
      - type: history-graph
        title: Actual vs simulation — rolling 24 hours
        hours_to_show: 24
        entities:
          - entity: sensor.kems_observed_cost_today
            name: Actual electricity
          - entity: sensor.kems_simulated_kems_cost_today
            name: Core KEMS simulation
          - entity: sensor.kems_agile_smart_export_cost_today
            name: Full KEMS Agile
"""


def improve_alpha736_dashboard(content: str) -> str:
    """Repair comparison wiring and insert winner/finance views."""
    # The live import cost already exists in the native period payload. Alpha7.35
    # rendered a literal dash instead of using it.
    content = content.replace(
        "| Import cost p | — | {{ state_attr(b, 'import_cost_pence') or 0 }} | {{ state_attr(f, 'import_cost_pence') or 0 }} | {{ a.get('import_cost_pence', 0) }} |",
        "| Import cost p | {{ state_attr('sensor.kems_today_energy_summary', 'import_cost_pence') if state_attr('sensor.kems_today_energy_summary', 'import_cost_pence') is not none else '—' }} | {{ state_attr(b, 'import_cost_pence') or 0 }} | {{ state_attr(f, 'import_cost_pence') or 0 }} | {{ a.get('import_cost_pence', 0) }} |",
        1,
    )

    # Use explicit commissioning labels for genuinely unavailable physical data,
    # rather than making an uninstalled battery/solar source look like a broken
    # dashboard calculation.
    content = content.replace(
        "| Solar kW | {{ states('sensor.kems_solar_power') }} | {{ state_attr(b, 'current_solar_power_kw') or 0 }} | {{ state_attr(f, 'current_solar_power_kw') or 0 }} | {{ state_attr(a, 'current_solar_power_kw') or 0 }} |",
        "| Solar kW | {{ states('sensor.kems_solar_power') if states('sensor.kems_solar_power') not in ['unknown', 'unavailable'] else 'Awaiting solar data' }} | {{ state_attr(b, 'current_solar_power_kw') or 0 }} | {{ state_attr(f, 'current_solar_power_kw') or 0 }} | {{ state_attr(a, 'current_solar_power_kw') or 0 }} |",
        1,
    )
    content = content.replace(
        "| Grid export kW | {{ states('sensor.kems_grid_export') }} | {{ state_attr(b, 'current_grid_export_kw') or 0 }} | {{ state_attr(f, 'current_grid_export_kw') or 0 }} | {{ state_attr(a, 'current_grid_export_kw') or 0 }} |",
        "| Grid export kW | {{ states('sensor.kems_grid_export') if states('sensor.kems_grid_export') not in ['unknown', 'unavailable'] else 'Awaiting grid export data' }} | {{ state_attr(b, 'current_grid_export_kw') or 0 }} | {{ state_attr(f, 'current_grid_export_kw') or 0 }} | {{ state_attr(a, 'current_grid_export_kw') or 0 }} |",
        1,
    )
    old_soc = "| Battery SOC % | {{ states('sensor.kems_battery_state_of_charge') }} | {{ state_attr(b, 'current_battery_soc_percent') if state_attr(b, 'current_battery_soc_percent') is not none else '—' }} | {{ state_attr(f, 'current_battery_soc_percent') if state_attr(f, 'current_battery_soc_percent') is not none else '—' }} | {{ state_attr(a, 'simulated_soc_percent') if state_attr(a, 'simulated_soc_percent') is not none else '—' }} |"
    new_soc = "| Battery SOC % | {{ states('sensor.kems_battery_state_of_charge') if states('sensor.kems_battery_state_of_charge') not in ['unknown', 'unavailable'] else 'Awaiting battery data' }} | {{ state_attr(b, 'current_battery_soc_percent') if state_attr(b, 'current_battery_soc_percent') is not none else '—' }} | {{ state_attr(f, 'current_battery_soc_percent') if state_attr(f, 'current_battery_soc_percent') is not none else '—' }} | {{ state_attr(a, 'simulated_soc_percent') if state_attr(a, 'simulated_soc_percent') is not none else (state_attr(a, 'current_routing_snapshot') or {}).get('simulated_soc_percent', '—') }} |"
    content = content.replace(old_soc, new_soc, 1)

    graph_marker = "      - type: history-graph\n        title: Cost comparison — 24 hours\n"
    if graph_marker not in content:
        raise ValueError("Alpha7.36 could not find the Compare cost graph insertion point")
    content = content.replace(graph_marker, _WINNER_CARD + graph_marker, 1)

    history_marker = "  - title: History\n"
    if history_marker not in content:
        raise ValueError("Alpha7.36 could not find the History view insertion point")
    content = content.replace(history_marker, _COST_ROI_VIEW + "\n" + history_marker, 1)
    return content


def install_alpha736_finance_dashboard_patch() -> None:
    """Install the final Alpha7.36 dashboard wrapper exactly once."""
    from . import dashboard as dashboard_module

    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_alpha736_finance", False):
        return

    def combined_alpha736_dashboard() -> bytes:
        content = original().decode("utf-8")
        return improve_alpha736_dashboard(content).encode("utf-8")

    combined_alpha736_dashboard._kems_alpha736_finance = True
    dashboard_module._combined_master_dashboard_bytes = combined_alpha736_dashboard
