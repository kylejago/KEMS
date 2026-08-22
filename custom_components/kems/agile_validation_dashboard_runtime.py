"""Alpha 7.19 cards for validation evidence and shadow-control readiness."""

# ruff: noqa: E501

from __future__ import annotations

from . import dashboard as dashboard_module

_PLAN_CARD = r"""      - type: entities
        title: Plan validation readiness
        show_header_toggle: false
        entities:
          - entity: sensor.kems_forecast_validation_status
            name: Forecast validation
          - entity: sensor.kems_forecast_validation_days
            name: Validated forecast days
          - entity: sensor.kems_forecast_validation_confidence
            name: Forecast confidence
          - entity: sensor.kems_forecast_validation_best_solar_source
            name: Best solar forecast source
          - entity: sensor.kems_agile_soc_trajectory
            name: Current planned SOC
          - entity: sensor.kems_agile_projected_soc_at_deadline
            name: Projected SOC at 23:30 target
          - entity: sensor.kems_agile_overnight_recharge_target
            name: Overnight recharge target
"""

_LIVE_CARD = r"""      - type: markdown
        title: Actual → Target → Difference readiness
        content: |
          {% set p = states.sensor.kems_shadow_plan_vs_outcome %}
          {% set target = p.attributes.target if p else {} %}
          {% set outcome = p.attributes.outcome if p else {} %}
          {% set diff = p.attributes.difference if p else {} %}
          **Current comparison basis:** **{{ p.attributes.basis if p else 'digital_twin' }}**  
          **Physical hardware:** {{ 'commissioned' if is_state('binary_sensor.kems_battery_data_available', 'on') else 'not commissioned — digital twin used for validation' }}

          | Signal | KEMS target | Validation outcome | Difference |
          |---|---:|---:|---:|
          | Battery charge | {{ target.get('charge_kw', '—') }} kW | {{ outcome.get('charge_kw', '—') }} kW | {{ diff.get('charge_kw', '—') }} kW |
          | Battery → home | {{ target.get('battery_to_home_kw', '—') }} kW | {{ outcome.get('battery_to_home_kw', '—') }} kW | {{ diff.get('battery_to_home_kw', '—') }} kW |
          | Battery → export | {{ target.get('battery_export_kw', '—') }} kW | {{ outcome.get('battery_export_kw', '—') }} kW | {{ diff.get('battery_export_kw', '—') }} kW |
          | Total discharge | {{ target.get('total_discharge_kw', '—') }} kW | {{ outcome.get('total_discharge_kw', '—') }} kW | {{ diff.get('total_discharge_kw', '—') }} kW |

          Before commissioning, **Validation outcome** is the digital twin rather than physical FoxESS telemetry. The same card is ready to become Actual → Target → Difference once battery direction and Modbus mappings are verified.
"""

_AGILE_CARDS = r"""      - type: entities
        title: Agile validation evidence
        show_header_toggle: false
        entities:
          - entity: sensor.kems_agile_comparison_evidence
            name: Fixed-window evidence
          - entity: sensor.kems_agile_decision_audit
            name: Current decision reason
          - entity: sensor.kems_agile_soc_trajectory
            name: Current simulated SOC
          - entity: sensor.kems_agile_projected_soc_at_deadline
            name: Projected SOC at cheap start
          - entity: sensor.kems_agile_overnight_recharge_target
            name: Overnight recharge target
      - type: markdown
        title: Receding-horizon SOC trajectory
        content: |
          {% set t = states.sensor.kems_agile_soc_trajectory %}
          **Basis:** {{ t.attributes.basis if t else '—' }}  
          **Current SOC:** {{ t.attributes.current_soc_percent if t else '—' }}%  
          **23:30 target:** {{ t.attributes.target_soc_percent if t else '—' }}%  
          **Projected at deadline:** {{ t.attributes.projected_deadline_soc_percent if t else '—' }}%  
          **Overnight target:** {{ t.attributes.overnight_target_soc_percent if t else '—' }}%  
          **Projected morning SOC:** {{ t.attributes.projected_morning_soc_percent if t else '—' }}%

          | Time | SOC | Basis | Planned action |
          |---|---:|---|---|
          {% set ns = namespace(count=0) %}
          {% for item in (t.attributes.points if t else []) %}
          {% if ns.count < 20 and as_timestamp(item.get('timestamp')) >= as_timestamp(now()) - 60 %}
          | {{ as_datetime(item.get('timestamp')).astimezone().strftime('%d %b %H:%M') }} | {{ item.get('soc_percent', '—') }}% | {{ item.get('source', '—') }} | {{ item.get('action', '—') }} |
          {% set ns.count = ns.count + 1 %}
          {% endif %}
          {% endfor %}

          Future solar is deliberately **not pre-spent**. If real/simulated solar later raises SOC or supplies the house, the next KEMS scan recalculates the remaining trajectory and Agile export allocation.
      - type: markdown
        title: Why KEMS chose each upcoming Agile slot
        content: |
          {% set a = states.sensor.kems_agile_decision_audit %}
          | Time | Rate | Reason | Planned battery export |
          |---|---:|---|---:|
          {% for item in (a.attributes.upcoming if a else []) %}
          | {{ item.get('label', '—') }} | {{ item.get('rate_pence', '—') }}p | {{ (item.get('reason_codes') or []) | join(', ') }} | {{ item.get('planned_battery_export_kwh') if item.get('planned_battery_export_kwh') is not none else '—' }} kWh |
          {% endfor %}
"""

_HISTORY_CARD = r"""      - type: markdown
        title: Historical source proof
        content: |
          {% set s = states.sensor.kems_agile_backfill_source_map %}
          {% set b = states.sensor.kems_agile_history_backfill %}
          **Direct replay prerequisites:** **{{ s.state if s else 'Unavailable' }}**  
          **Diagnostic resolution:** {{ s.attributes.query_resolution if s else '—' }}  
          **Backfill method:** {{ s.attributes.backfill_method if s else '—' }}  
          **Settled coverage:** {{ b.state if b else '—' }}  
          **Missing prerequisites:** {{ (s.attributes.missing_prerequisites if s else []) | join('; ') or 'None' }}

          | Logical KEMS source | Configured entity | Hourly rows | Oldest | Newest |
          |---|---|---:|---|---|
          {% for key, item in (s.attributes.logical_sources if s else {}).items() %}
          | {{ key }} | `{{ item.get('entity_id', '—') }}` | {{ item.get('historical_rows', 0) }} | {{ item.get('oldest') or '—' }} | {{ item.get('newest') or '—' }} |
          {% endfor %}

          This uses the **same hourly diagnostic resolution as the direct historical replay**, so a source is no longer described as historically useful merely because it has a daily aggregate.
"""

_CONTROL_CARDS = r"""      - type: entities
        title: Shadow-control validation
        show_header_toggle: false
        entities:
          - entity: sensor.kems_shadow_control_status
            name: Shadow status
          - entity: sensor.kems_shadow_control_readiness
            name: Ready for shadow
          - entity: sensor.kems_shadow_command_safety
            name: Independent command safety
          - entity: sensor.kems_shadow_tracking_score
            name: Plan tracking score
          - entity: sensor.kems_shadow_plan_vs_outcome
            name: Current plan vs outcome
          - entity: sensor.kems_shadow_half_hour_validation
            name: Settled half-hour evidence
          - entity: sensor.kems_shadow_decision_audit
            name: Decision audit
      - type: markdown
        title: Shadow command envelope
        content: |
          {% set s = states.sensor.kems_shadow_command_safety %}
          **Result:** **{{ s.state if s else 'Unavailable' }}**  
          **Passed:** {{ s.attributes.passed_checks if s else '—' }}/{{ s.attributes.total_checks if s else '—' }}  
          **Failed checks:** {{ (s.attributes.failed_checks if s else []) | join(', ') or 'None' }}

          | Check | Result | Detail |
          |---|:---:|---|
          {% for item in (s.attributes.checks if s else []) %}
          | {{ item.get('key', '—') }} | {{ '✅' if item.get('passed') else '❌' }} | {{ item.get('detail', '—') }} |
          {% endfor %}

          These checks run **independently of the main ControlEngine**. Alpha7.19 still exposes no real FoxESS control backend and sends **zero inverter writes**.
      - type: markdown
        title: Recent settled half-hour plan validation
        content: |
          {% set h = states.sensor.kems_shadow_half_hour_validation %}
          | Half-hour | Samples | Tracking | Safety | Reason |
          |---|---:|---:|:---:|---|
          {% for item in (h.attributes.recent_half_hours if h else [])[-8:] %}
          | {{ item.get('slot', '—') }} | {{ item.get('samples', 0) }} | {{ item.get('tracking_score_percent', '—') }}% | {{ '✅' if item.get('safety_passed_all') else '❌' }} | {{ (item.get('operating_reasons') or []) | join(', ') }} |
          {% endfor %}
"""


def _inject_after_cards(content: str, path: str, cards: str) -> str:
    """Insert cards at the top of one final consolidated view."""
    path_marker = f"    path: {path}\n"
    start = content.find(path_marker)
    if start < 0:
        return content
    cards_marker = "    cards:\n"
    cards_at = content.find(cards_marker, start)
    if cards_at < 0:
        return content
    insert_at = cards_at + len(cards_marker)
    if cards.strip() in content[start : start + len(cards) + 1000]:
        return content
    return content[:insert_at] + cards.rstrip() + "\n" + content[insert_at:]


def install_alpha719_dashboard_patch() -> None:
    """Add validation and shadow cards after the eleven-page compositor."""
    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_alpha719_dashboard", False):
        return

    def combined_dashboard_with_alpha719() -> bytes:
        content = original().decode("utf-8")
        content = _inject_after_cards(content, "live", _LIVE_CARD)
        content = _inject_after_cards(content, "plan", _PLAN_CARD)
        content = _inject_after_cards(content, "agile", _AGILE_CARDS)
        content = _inject_after_cards(content, "history", _HISTORY_CARD)
        content = _inject_after_cards(content, "control", _CONTROL_CARDS)
        return content.encode("utf-8")

    combined_dashboard_with_alpha719._kems_alpha719_dashboard = True
    dashboard_module._combined_master_dashboard_bytes = combined_dashboard_with_alpha719
