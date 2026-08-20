"""Alpha7.40 Agile-first dashboard and expanded strategy comparison."""

from __future__ import annotations

_AGILE_MARKER = (
    "  - title: Full KEMS Agile\n"
    "    path: full-kems-agile\n"
    "    icon: mdi:transmission-tower-export\n"
    "    cards:\n"
)

_COMPARE_MARKER = (
    "  - title: Compare\n"
    "    path: compare\n"
    "    icon: mdi:compare-horizontal\n"
    "    cards:\n"
)

_AGILE_PRIMARY_CARDS = r"""      - type: markdown
        title: Full KEMS Agile — command centre
        content: |
          {% set r = state_attr('sensor.kems_agile_rolling_export_plan', 'selected_slots') or [] %}
          {% set g = state_attr('sensor.kems_agile_rolling_export_plan', 'economic_opportunity_guard') or {} %}
          {% set d = state_attr('sensor.kems_agile_rolling_export_plan', 'deadline_guard') or {} %}
          **Primary KEMS strategy:** Full KEMS Agile  
          **Decision now:** {{ state_attr('sensor.kems_agile_live_scenario', 'routing_action') or state_attr('sensor.kems_agile_rolling_export_plan', 'dispatch_action') or 'Building plan' }}  
          **Dispatch mode:** {{ states('sensor.kems_agile_dispatch_mode') }}  
          **Agile export now:** {{ states('sensor.kems_agile_export_rate_now') }} p/kWh  
          **Battery export target now:** {{ states('sensor.kems_agile_battery_export_target_now') }} kW  
          **Exportable battery:** {{ state_attr('sensor.kems_agile_rolling_export_plan', 'exportable_battery_energy_kwh') or 0 }} kWh  
          **Planned battery export:** {{ state_attr('sensor.kems_agile_rolling_export_plan', 'planned_battery_export_kwh') or 0 }} kWh  
          **Target SOC at cheap start:** {{ state_attr('sensor.kems_agile_rolling_export_plan', 'target_soc_percent') or 10 }}%  
          **Latest safe export start:** {{ d.get('latest_safe_export_start') or state_attr('sensor.kems_agile_rolling_export_plan', 'latest_safe_export_start') or 'Building' }}  
          **Economic early-export guard:** {{ 'ACTIVE' if g.get('active') else 'Standby' }}{% if g.get('active') %} — current price is {{ g.get('price_advantage_pence', 0) }}p/kWh above the marginal future slot{% endif %}.  
          **Planned future export slots:** {{ r | count }}
      - type: markdown
        title: Remaining Agile plan
        content: |
          {% set slots = state_attr('sensor.kems_agile_rolling_export_plan', 'selected_slots') or [] %}
          {% if slots %}
          | Slot | Export price | Planned battery export | Deadline forced? |
          |---|---:|---:|---|
          {% for s in slots %}
          | {{ s.get('label') or s.get('valid_from') }} | {{ s.get('rate_pence', 0) | round(2) }}p | {{ s.get('planned_battery_export_kwh', 0) | round(3) }} kWh | {{ 'Yes' if s.get('deadline_forced') else 'No' }} |
          {% endfor %}
          {% else %}
          KEMS has not selected a remaining battery-export slot yet. The plan is rebuilt on every coordinator scan.
          {% endif %}
      - type: markdown
        title: Current routing and today totals
        content: |
          {% set e = 'sensor.kems_agile_live_scenario' %}
          {% set periods = state_attr('sensor.kems_agile_smart_export_plan', 'periods') or {} %}
          {% set today = (periods.get('today', {}) or {}).get('agile_smart_export', {}) %}
          | Route | Now | Today |
          |---|---:|---:|
          | Solar → home | {{ state_attr(e, 'current_solar_to_home_kw') or 0 }} kW | {{ today.get('solar_to_home_kwh', 0) | round(3) }} kWh |
          | Solar → battery | {{ state_attr(e, 'current_solar_to_battery_kw') or 0 }} kW | {{ today.get('solar_to_battery_kwh', 0) | round(3) }} kWh |
          | Solar → export | {{ state_attr(e, 'current_solar_export_kw') or 0 }} kW | {{ today.get('solar_export_kwh', 0) | round(3) }} kWh |
          | Grid → battery | {{ state_attr(e, 'current_grid_to_battery_kw') or 0 }} kW | {{ today.get('grid_to_battery_kwh', 0) | round(3) }} kWh |
          | Battery → home | {{ state_attr(e, 'current_battery_to_home_kw') or 0 }} kW | {{ today.get('battery_to_home_kwh', 0) | round(3) }} kWh |
          | Battery → export | {{ state_attr(e, 'current_battery_export_kw') or 0 }} kW | {{ today.get('battery_export_kwh', 0) | round(3) }} kWh |
          | Grid import | {{ state_attr(e, 'current_grid_import_kw') or 0 }} kW | {{ today.get('grid_import_kwh', 0) | round(3) }} kWh |
          | Grid export | {{ state_attr(e, 'current_grid_export_kw') or 0 }} kW | {{ today.get('grid_export_kwh', 0) | round(3) }} kWh |
          | Solar curtailed / capped | — | {{ today.get('solar_curtailed_kwh', 0) | round(3) }} kWh |
      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Agile accuracy & safety
            show_header_toggle: false
            entities:
              - sensor.kems_agile_price_data_quality
              - sensor.kems_agile_dispatch_mode
              - sensor.kems_agile_rolling_capacity_margin
              - sensor.kems_agile_rolling_exportable_energy
              - sensor.kems_agile_rolling_protected_house_energy
              - sensor.kems_agile_rolling_next_export_slot
          - type: entities
            title: Forecast evidence
            show_header_toggle: false
            entities:
              - sensor.kems_forecast_solar_tomorrow
              - sensor.kems_forecast_house_demand_tomorrow
              - sensor.kems_forecast_required_morning_soc
              - sensor.kems_learning_confidence
              - sensor.kems_data_quality
"""

_COMPARE_PRIMARY_CARDS = r"""      - type: markdown
        title: Overall strategy comparison — which KEMS type is winning?
        content: |
          {% set std = state_attr('sensor.kems_scenario_comparison_today', 'periods') or {} %}
          {% set agp = state_attr('sensor.kems_agile_smart_export_plan', 'periods') or {} %}
          {% set nt = namespace(b={}, f={}) %}
          {% for x in (std.get('today', {}) or {}).get('scenarios', []) %}{% if x.get('key') == 'solar_battery' %}{% set nt.b = x %}{% elif x.get('key') == 'kems_forecast' %}{% set nt.f = x %}{% endif %}{% endfor %}
          {% set at = (agp.get('today', {}) or {}).get('agile_smart_export', {}) %}
          {% set live = ((state_attr('sensor.kems_today_energy_summary', 'import_cost_pence') or 0) - (state_attr('sensor.kems_today_energy_summary', 'export_income_pence') or 0)) / 100 %}
          {% set b = ((nt.b.get('import_cost_pence', 999999) | float) - (nt.b.get('export_income_pence', 0) | float)) / 100 %}
          {% set f = ((nt.f.get('import_cost_pence', 999999) | float) - (nt.f.get('export_income_pence', 0) | float)) / 100 %}
          {% set a = ((at.get('import_cost_pence', 999999) | float) - (at.get('export_income_pence', 0) | float)) / 100 %}
          {% set ranked = [(live, 'Live Data'), (b, 'Battery & Solar'), (f, 'Full KEMS'), (a, 'Full KEMS Agile')] | sort %}
          # {{ ranked[0][1] }} is currently cheapest today
          **Current bill-basis leader:** {{ ranked[0][1] }} at £{{ ranked[0][0] | round(2) }}.  
          **Full KEMS Agile vs Live Data:** £{{ (live - a) | round(2) }} better today when positive.  
          This headline uses the common electricity-bill basis **import cost − export income**. Historical evidence below is shown separately so a short-lived price event cannot hide a weaker long-term strategy.
      - type: markdown
        title: Strategy evidence by period
        content: |
          {% set std = state_attr('sensor.kems_scenario_comparison_today', 'periods') or {} %}
          {% set agp = state_attr('sensor.kems_agile_smart_export_plan', 'periods') or {} %}
          | Period | Battery & Solar | Full KEMS | Full KEMS Agile | Evidence leader |
          |---|---:|---:|---:|---|
          {% for key, label in [('today','Today'), ('yesterday','Yesterday'), ('7_days','Last 7 days'), ('30_days','Last 30 days')] %}
          {% set n = namespace(b={}, f={}) %}
          {% for x in (std.get(key, {}) or {}).get('scenarios', []) %}{% if x.get('key') == 'solar_battery' %}{% set n.b = x %}{% elif x.get('key') == 'kems_forecast' %}{% set n.f = x %}{% endif %}{% endfor %}
          {% set aa = (agp.get(key, {}) or {}).get('agile_smart_export', {}) %}
          {% set bc = ((n.b.get('import_cost_pence', 999999) | float) - (n.b.get('export_income_pence', 0) | float)) / 100 %}
          {% set fc = ((n.f.get('import_cost_pence', 999999) | float) - (n.f.get('export_income_pence', 0) | float)) / 100 %}
          {% set ac = ((aa.get('import_cost_pence', 999999) | float) - (aa.get('export_income_pence', 0) | float)) / 100 %}
          {% set best = [(bc,'Battery & Solar'),(fc,'Full KEMS'),(ac,'Full KEMS Agile')] | sort %}
          | {{ label }} | £{{ bc | round(2) }} | £{{ fc | round(2) }} | £{{ ac | round(2) }} | **{{ best[0][1] }}** |
          {% endfor %}
      - type: markdown
        title: Why the strategies differ today
        content: |
          {% set std = state_attr('sensor.kems_scenario_comparison_today', 'periods') or {} %}
          {% set n = namespace(b={}, f={}) %}
          {% for x in (std.get('today', {}) or {}).get('scenarios', []) %}{% if x.get('key') == 'solar_battery' %}{% set n.b = x %}{% elif x.get('key') == 'kems_forecast' %}{% set n.f = x %}{% endif %}{% endfor %}
          {% set a = ((state_attr('sensor.kems_agile_smart_export_plan', 'periods') or {}).get('today', {}) or {}).get('agile_smart_export', {}) %}
          | Measure | Battery & Solar | Full KEMS | Full KEMS Agile |
          |---|---:|---:|---:|
          | Grid import | {{ n.b.get('grid_import_kwh', 0) | round(2) }} kWh | {{ n.f.get('grid_import_kwh', 0) | round(2) }} kWh | {{ a.get('grid_import_kwh', 0) | round(2) }} kWh |
          | Grid export | {{ n.b.get('grid_export_kwh', 0) | round(2) }} kWh | {{ n.f.get('grid_export_kwh', 0) | round(2) }} kWh | {{ a.get('grid_export_kwh', 0) | round(2) }} kWh |
          | Export income | {{ n.b.get('export_income_pence', 0) | round(1) }}p | {{ n.f.get('export_income_pence', 0) | round(1) }}p | {{ a.get('export_income_pence', 0) | round(1) }}p |
          | Battery → home | {{ n.b.get('battery_to_home_kwh', 0) | round(2) }} kWh | {{ n.f.get('battery_to_home_kwh', 0) | round(2) }} kWh | {{ a.get('battery_to_home_kwh', 0) | round(2) }} kWh |
          | Battery → export | {{ n.b.get('battery_export_kwh', 0) | round(2) }} kWh | {{ n.f.get('battery_export_kwh', 0) | round(2) }} kWh | {{ a.get('battery_export_kwh', 0) | round(2) }} kWh |
          | End SOC | {{ n.b.get('ending_soc_percent', 0) | round(1) }}% | {{ n.f.get('ending_soc_percent', 0) | round(1) }}% | {{ a.get('ending_soc_percent', 0) | round(1) }}% |
      - type: history-graph
        title: Strategy cost — rolling 24 hours
        hours_to_show: 24
        entities:
          - entity: sensor.kems_observed_cost_today
            name: Live Data
          - entity: sensor.kems_compare_solar_and_battery_cost_today
            name: Battery & Solar
          - entity: sensor.kems_compare_full_kems_forecast_cost_today
            name: Full KEMS
          - entity: sensor.kems_agile_smart_export_cost_today
            name: Full KEMS Agile
"""


def improve_alpha740_dashboard(content: str) -> str:
    """Insert Agile-first command and comparison cards into consolidated YAML."""
    if "Full KEMS Agile — command centre" not in content:
        if _AGILE_MARKER not in content:
            raise ValueError("Alpha7.40 Full KEMS Agile dashboard marker missing")
        content = content.replace(
            _AGILE_MARKER,
            _AGILE_MARKER + _AGILE_PRIMARY_CARDS,
            1,
        )
    if "Overall strategy comparison — which KEMS type is winning?" not in content:
        if _COMPARE_MARKER not in content:
            raise ValueError("Alpha7.40 Compare dashboard marker missing")
        content = content.replace(
            _COMPARE_MARKER,
            _COMPARE_MARKER + _COMPARE_PRIMARY_CARDS,
            1,
        )
    return content


def install_alpha740_agile_primary_dashboard_patch() -> None:
    """Install Alpha7.40 cards after consolidation and finance patches."""
    from . import dashboard as dashboard_module

    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_alpha740_agile_primary", False):
        return

    def combined_alpha740_dashboard() -> bytes:
        return improve_alpha740_dashboard(original().decode("utf-8")).encode("utf-8")

    combined_alpha740_dashboard._kems_alpha740_agile_primary = True
    dashboard_module._combined_master_dashboard_bytes = combined_alpha740_dashboard
