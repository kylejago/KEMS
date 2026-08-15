from pathlib import Path

DASHBOARDS = (
    Path("dashboards/kems_master_dashboard.yaml"),
    Path("custom_components/kems/kems_master_dashboard.yaml"),
)
TEST = Path("tests/test_managed_dashboard.py")

VIEW = r'''  - title: Full KEMS Forecast
    path: full-kems-forecast
    icon: mdi:weather-sunny-alert
    cards:
      - type: markdown
        content: |
          # Full KEMS Forecast
          This is the forward-looking KEMS strategy intended for normal use once paid export is active. It keeps the profit-first Full KEMS behaviour, but only retains battery energy or solar when the forward model predicts that doing so is necessary to avoid otherwise unnecessary day-rate import.

          **Plan state:** **{{ states('sensor.kems_full_kems_forecast_status') }}**  
          **Reason:** {{ state_attr('sensor.kems_full_kems_forecast_status', 'reason') or '—' }}  
          **Forecast source:** {{ state_attr('sensor.kems_full_kems_forecast_status', 'forecast_source') or '—' }}  
          **Confidence:** {{ state_attr('sensor.kems_full_kems_forecast_status', 'confidence_percent') or '—' }}%  
          **Export tariff:** {{ states('sensor.kems_export_tariff_status') }}

      - type: grid
        columns: 4
        square: false
        cards:
          - type: tile
            entity: sensor.kems_full_kems_forecast_status
            name: Plan state
          - type: tile
            entity: sensor.kems_compare_full_kems_forecast_cost_today
            name: Forecast cost today
          - type: tile
            entity: sensor.kems_forecast_required_morning_soc
            name: Required morning SOC
          - type: tile
            entity: sensor.kems_forecast_solar_recovery_target
            name: Solar recovery target

      - type: grid
        columns: 4
        square: false
        cards:
          - type: tile
            entity: sensor.kems_forecast_solar_tomorrow
            name: Solar tomorrow
          - type: tile
            entity: sensor.kems_forecast_house_demand_tomorrow
            name: House tomorrow
          - type: tile
            entity: sensor.kems_forecast_maximum_overnight_soc
            name: Maximum overnight SOC
          - type: tile
            entity: sensor.kems_forecast_minimum_pre_cheap_soc
            name: Minimum pre-cheap SOC

      - type: markdown
        title: Current Full KEMS Forecast power routing
        content: |
          {% set e = 'sensor.kems_compare_full_kems_forecast_cost_today' %}
          | Flow | Power |
          |---|---:|
          | House demand | {{ state_attr(e, 'current_house_load_kw') if state_attr(e, 'current_house_load_kw') is not none else '—' }} kW |
          | Solar generation | {{ state_attr(e, 'current_solar_power_kw') if state_attr(e, 'current_solar_power_kw') is not none else '—' }} kW |
          | Grid import | {{ state_attr(e, 'current_grid_import_kw') if state_attr(e, 'current_grid_import_kw') is not none else '—' }} kW |
          | Grid export | {{ state_attr(e, 'current_grid_export_kw') if state_attr(e, 'current_grid_export_kw') is not none else '—' }} kW |
          | Solar → home | {{ state_attr(e, 'current_solar_to_home_kw') if state_attr(e, 'current_solar_to_home_kw') is not none else '—' }} kW |
          | Solar → battery | {{ state_attr(e, 'current_solar_to_battery_kw') if state_attr(e, 'current_solar_to_battery_kw') is not none else '—' }} kW |
          | Solar → export | {{ state_attr(e, 'current_solar_export_kw') if state_attr(e, 'current_solar_export_kw') is not none else '—' }} kW |
          | Grid → battery | {{ state_attr(e, 'current_grid_to_battery_kw') if state_attr(e, 'current_grid_to_battery_kw') is not none else '—' }} kW |
          | Battery → home | {{ state_attr(e, 'current_battery_to_home_kw') if state_attr(e, 'current_battery_to_home_kw') is not none else '—' }} kW |
          | Battery → export | {{ state_attr(e, 'current_battery_export_kw') if state_attr(e, 'current_battery_export_kw') is not none else '—' }} kW |
          | Scenario battery SOC | {{ state_attr(e, 'current_battery_soc_percent') if state_attr(e, 'current_battery_soc_percent') is not none else '—' }}% |

      - type: history-graph
        title: Cost in action — 24 hours
        hours_to_show: 24
        entities:
          - sensor.kems_observed_cost_today
          - sensor.kems_compare_no_system_cost_today
          - sensor.kems_compare_full_kems_cost_today
          - sensor.kems_compare_full_kems_forecast_cost_today

      - type: history-graph
        title: Forecast plan evolution — 24 hours
        hours_to_show: 24
        entities:
          - sensor.kems_forecast_solar_tomorrow
          - sensor.kems_forecast_house_demand_tomorrow
          - sensor.kems_forecast_required_morning_soc
          - sensor.kems_forecast_maximum_overnight_soc
          - sensor.kems_forecast_minimum_pre_cheap_soc
          - sensor.kems_forecast_solar_recovery_target

      - type: grid
        columns: 2
        square: false
        cards:
          - type: markdown
            title: Recharge & reserve decision
            content: |
              {% set e = 'sensor.kems_full_kems_forecast_status' %}
              | Decision | Value |
              |---|---:|
              | Expected solar remaining today | {{ state_attr(e, 'expected_solar_remaining_today_kwh') if state_attr(e, 'expected_solar_remaining_today_kwh') is not none else '—' }} kWh |
              | Expected solar tomorrow | {{ state_attr(e, 'expected_solar_tomorrow_kwh') if state_attr(e, 'expected_solar_tomorrow_kwh') is not none else '—' }} kWh |
              | Expected house remaining today | {{ state_attr(e, 'expected_house_remaining_today_kwh') if state_attr(e, 'expected_house_remaining_today_kwh') is not none else '—' }} kWh |
              | Expected house tomorrow | {{ state_attr(e, 'expected_house_tomorrow_kwh') if state_attr(e, 'expected_house_tomorrow_kwh') is not none else '—' }} kWh |
              | Projected SOC at cheap start | {{ state_attr(e, 'projected_soc_at_cheap_start_percent') if state_attr(e, 'projected_soc_at_cheap_start_percent') is not none else '—' }}% |
              | Cheap window | {{ state_attr(e, 'cheap_window_hours') if state_attr(e, 'cheap_window_hours') is not none else '—' }} h |
              | Overnight charge capacity | {{ state_attr(e, 'overnight_charge_capacity_kwh') if state_attr(e, 'overnight_charge_capacity_kwh') is not none else '—' }} kWh |
              | Maximum overnight SOC | {{ state_attr(e, 'maximum_overnight_soc_percent') if state_attr(e, 'maximum_overnight_soc_percent') is not none else '—' }}% |
              | Full charge feasible | {{ state_attr(e, 'full_charge_feasible') if state_attr(e, 'full_charge_feasible') is not none else '—' }} |
              | Extra cheap time to 100% | {{ state_attr(e, 'additional_cheap_time_to_full_hours') if state_attr(e, 'additional_cheap_time_to_full_hours') is not none else '—' }} h |
              | Required morning SOC | {{ state_attr(e, 'required_morning_soc_percent') if state_attr(e, 'required_morning_soc_percent') is not none else '—' }}% |
              | Recharge target feasible | {{ state_attr(e, 'recharge_target_feasible') if state_attr(e, 'recharge_target_feasible') is not none else '—' }} |
              | Recharge shortfall | {{ state_attr(e, 'recharge_shortfall_kwh') if state_attr(e, 'recharge_shortfall_kwh') is not none else '—' }} kWh |
              | Extra cheap time required | {{ state_attr(e, 'additional_cheap_time_required_hours') if state_attr(e, 'additional_cheap_time_required_hours') is not none else '—' }} h |
              | Minimum pre-cheap SOC | {{ state_attr(e, 'minimum_precheap_soc_percent') if state_attr(e, 'minimum_precheap_soc_percent') is not none else '—' }}% |
              | Solar recovery target | {{ state_attr(e, 'solar_recovery_target_percent') if state_attr(e, 'solar_recovery_target_percent') is not none else '—' }}% |
              | Projected minimum SOC tomorrow | {{ state_attr(e, 'projected_minimum_soc_tomorrow_percent') if state_attr(e, 'projected_minimum_soc_tomorrow_percent') is not none else '—' }}% |
              | Predicted day-rate import | {{ state_attr(e, 'predicted_day_rate_import_kwh') if state_attr(e, 'predicted_day_rate_import_kwh') is not none else '—' }} kWh |
              | Battery retention required | {{ state_attr(e, 'battery_retention_required') }} |
              | Solar recovery required | {{ state_attr(e, 'solar_recovery_required') }} |
          - type: markdown
            title: Forecast providers
            content: |
              {% set e = 'sensor.kems_full_kems_forecast_status' %}
              {% set f = state_attr(e, 'forecast') or {} %}
              | Forecast | Value |
              |---|---:|
              | Ready | {{ f.get('ready', '—') }} |
              | Source | {{ f.get('source', '—') }} |
              | Forecast.Solar available | {{ f.get('forecast_solar_available', '—') }} |
              | Forecast.Solar entities | {{ f.get('forecast_solar_entity_count', '—') }} |
              | Forecast.Solar remaining today | {{ f.get('forecast_solar_remaining_today_kwh', '—') }} kWh |
              | Forecast.Solar tomorrow | {{ f.get('forecast_solar_tomorrow_kwh', '—') }} kWh |
              | Open-Meteo available | {{ f.get('open_meteo_available', '—') }} |
              | Open-Meteo remaining today | {{ f.get('open_meteo_remaining_today_kwh', '—') }} kWh |
              | Open-Meteo tomorrow | {{ f.get('open_meteo_tomorrow_kwh', '—') }} kWh |
              | Fused remaining today | {{ f.get('expected_solar_remaining_today_kwh', '—') }} kWh |
              | Fused tomorrow | {{ f.get('expected_solar_tomorrow_kwh', '—') }} kWh |
              | Provider agreement | {{ f.get('agreement_percent', '—') }}% |
              | Forecast confidence | {{ f.get('confidence_percent', '—') }}% |
              | Cloud tomorrow | {{ f.get('average_cloud_cover_tomorrow_percent', '—') }}% |
              | Precipitation tomorrow | {{ f.get('precipitation_tomorrow_mm', '—') }} mm |
              | Last updated | {{ f.get('last_updated', '—') }} |
              | Error | {{ f.get('error') or 'None' }} |

      - type: markdown
        title: Hourly fused solar / weather outlook
        content: |
          {% set f = state_attr('sensor.kems_full_kems_forecast_status', 'forecast') or {} %}
          {% set hours = f.get('hourly', []) %}
          {% if hours %}
          | Time | Solar | Cloud | Precipitation |
          |---|---:|---:|---:|
          {% for h in hours %}
          | {{ h.get('timestamp', '—') }} | {{ h.get('solar_energy_kwh', '—') }} kWh | {{ h.get('cloud_cover_percent', '—') }}% | {{ h.get('precipitation_mm', '—') }} mm |
          {% endfor %}
          {% else %}
          No hourly fused forecast is available yet.
          {% endif %}

      - type: grid
        columns: 2
        square: false
        cards:
          - type: markdown
            title: Scenario finances today
            content: |
              {% set e = 'sensor.kems_compare_full_kems_forecast_cost_today' %}
              | Financial result | Value |
              |---|---:|
              | Ready | {{ state_attr(e, 'ready') }} |
              | Samples | {{ state_attr(e, 'samples') }} |
              | Data coverage | {{ state_attr(e, 'data_coverage') }}% |
              | Import cost | {{ state_attr(e, 'import_cost_pence') }} p |
              | Cheap import cost | {{ state_attr(e, 'cheap_import_cost_pence') }} p |
              | Day import cost | {{ state_attr(e, 'day_import_cost_pence') }} p |
              | Export income | {{ state_attr(e, 'export_income_pence') }} p |
              | Power Down income | {{ state_attr(e, 'power_down_income_pence') }} p |
              | Standing charge | {{ state_attr(e, 'standing_charge_pence') }} p |
              | Energy net cost | {{ state_attr(e, 'energy_net_cost_pence') }} p |
              | Total cost | {{ state_attr(e, 'total_cost_pence') }} p |
              | Saving vs no system | {{ state_attr(e, 'saving_vs_no_system_pence') }} p |
              | Day-rate import reduction value | {{ state_attr(e, 'day_rate_import_reduction_pence') }} p |
              | Cheap-rate import change | {{ state_attr(e, 'cheap_rate_import_change_pence') }} p |
          - type: markdown
            title: Scenario energy today
            content: |
              {% set e = 'sensor.kems_compare_full_kems_forecast_cost_today' %}
              | Energy result | Value |
              |---|---:|
              | House consumption | {{ state_attr(e, 'house_consumption_kwh') }} kWh |
              | Grid import | {{ state_attr(e, 'grid_import_kwh') }} kWh |
              | Cheap grid import | {{ state_attr(e, 'cheap_grid_import_kwh') }} kWh |
              | Day grid import | {{ state_attr(e, 'day_grid_import_kwh') }} kWh |
              | Grid export | {{ state_attr(e, 'grid_export_kwh') }} kWh |
              | Solar generation | {{ state_attr(e, 'solar_generation_kwh') }} kWh |
              | Solar → home | {{ state_attr(e, 'solar_to_home_kwh') }} kWh |
              | Solar → battery | {{ state_attr(e, 'solar_to_battery_kwh') }} kWh |
              | Solar → export | {{ state_attr(e, 'solar_export_kwh') }} kWh |
              | Solar curtailed | {{ state_attr(e, 'solar_curtailed_kwh') }} kWh |
              | Battery charged | {{ state_attr(e, 'battery_charge_kwh') }} kWh |
              | Battery grid charge | {{ state_attr(e, 'battery_grid_charge_kwh') }} kWh |
              | Battery solar charge | {{ state_attr(e, 'battery_solar_charge_kwh') }} kWh |
              | Battery → home | {{ state_attr(e, 'battery_to_home_kwh') }} kWh |
              | Battery → export | {{ state_attr(e, 'battery_export_kwh') }} kWh |
              | Ending SOC | {{ state_attr(e, 'ending_soc_percent') }}% |

      - type: markdown
        title: Forecast protection audit inside the scenario
        content: |
          {% set e = 'sensor.kems_compare_full_kems_forecast_cost_today' %}
          | Audit field | Value |
          |---|---:|
          | Forecast-bearing samples | {{ state_attr(e, 'forecast_samples') }} |
          | Protection state | {{ state_attr(e, 'forecast_protection_state') or '—' }} |
          | Required morning SOC | {{ state_attr(e, 'forecast_required_morning_soc_percent') if state_attr(e, 'forecast_required_morning_soc_percent') is not none else '—' }}% |
          | Minimum pre-cheap SOC | {{ state_attr(e, 'forecast_minimum_precheap_soc_percent') if state_attr(e, 'forecast_minimum_precheap_soc_percent') is not none else '—' }}% |
          | Solar recovery target | {{ state_attr(e, 'forecast_solar_recovery_target_percent') if state_attr(e, 'forecast_solar_recovery_target_percent') is not none else '—' }}% |
          | Recharge target feasible | {{ state_attr(e, 'forecast_recharge_target_feasible') if state_attr(e, 'forecast_recharge_target_feasible') is not none else '—' }} |
          | Recharge shortfall | {{ state_attr(e, 'forecast_recharge_shortfall_kwh') if state_attr(e, 'forecast_recharge_shortfall_kwh') is not none else '—' }} kWh |

      - type: grid
        columns: 4
        square: false
        cards:
          - type: tile
            entity: sensor.kems_forecast_validation_status
          - type: tile
            entity: sensor.kems_forecast_validation_days
          - type: tile
            entity: sensor.kems_forecast_validation_confidence
          - type: tile
            entity: sensor.kems_forecast_validation_best_solar_source

      - type: markdown
        title: Complete plan attributes
        content: |
          {% set e = states('sensor.kems_full_kems_forecast_status') %}
          {% set attrs = states.sensor.kems_full_kems_forecast_status.attributes if states.sensor.kems_full_kems_forecast_status is defined else {} %}
          | Attribute | Value |
          |---|---|
          {% for key, value in attrs.items() | sort %}
          {% if key not in ['forecast', 'friendly_name', 'icon'] %}
          | `{{ key }}` | {{ value }} |
          {% endif %}
          {% endfor %}

      - type: markdown
        title: Complete Full KEMS Forecast scenario attributes
        content: |
          {% set attrs = states.sensor.kems_compare_full_kems_forecast_cost_today.attributes if states.sensor.kems_compare_full_kems_forecast_cost_today is defined else {} %}
          | Attribute | Value |
          |---|---|
          {% for key, value in attrs.items() | sort %}
          {% if key not in ['friendly_name', 'icon', 'unit_of_measurement'] %}
          | `{{ key }}` | {{ value }} |
          {% endif %}
          {% endfor %}

'''

marker = "  - title: Compare\n"
for dashboard in DASHBOARDS:
    text = dashboard.read_text(encoding="utf-8")
    if "    path: full-kems-forecast\n" not in text:
        if marker not in text:
            raise SystemExit(f"Compare view marker missing from {dashboard}")
        text = text.replace(marker, VIEW + marker, 1)
        dashboard.write_text(text, encoding="utf-8")

text = TEST.read_text(encoding="utf-8")
if '        "full-kems-forecast",\n' not in text:
    needle = '        "forecast",\n'
    if needle not in text:
        raise SystemExit("Forecast path marker missing from dashboard test")
    text = text.replace(needle, needle + '        "full-kems-forecast",\n', 1)
    TEST.write_text(text, encoding="utf-8")
