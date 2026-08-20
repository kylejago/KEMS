"""KEMS Alpha7.35 product-type dashboard consolidation."""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ViewSpec:
    """Describe one final dashboard navigation page."""

    title: str
    path: str
    icon: str
    sources: tuple[str, ...] = ()
    prefix: str = ""


EXPECTED_SOURCE_TITLES = {
    "Overview",
    "Live Energy",
    "Simulation",
    "Forecast",
    "Full KEMS Forecast",
    "Compare",
    "Battery & Solar",
    "Tariff & EV",
    "Power Down",
    "Commissioning",
    "Control & EPS",
    "Finance & History",
    "Learning & Health",
    "Gas",
    "Updates",
    "All Entities",
    "Forecast vs Agile",
    "Agile Price Plan",
    "Agile History",
    "Agile Assumptions",
    "Agile Smart Export",
}

_HOME_PREFIX = """      - type: markdown
        title: Simple KEMS setup
        content: |
          # ⚡ KEMS
          KEMS now has four clear system types. Pick the capability you want, then choose **Live**, **Simulate** or **Control** where that type supports it.

          **System type:** {{ states('select.kems_system_type') }}  
          **Mode:** {{ states('select.kems_operating_mode') }}  
          **Status:** {{ states('sensor.kems_status') }}  
          **Advice:** {{ states('sensor.kems_advice') }}  
          **Commissioning:** {{ states('sensor.kems_commissioning_readiness') }}
      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Choose how KEMS works
            entities:
              - entity: select.kems_system_type
                name: KEMS type
              - entity: select.kems_operating_mode
                name: Mode
          - type: markdown
            title: Four simple types
            content: |
              **Live Data** — actual property data only.  
              **Battery & Solar** — tariff-aware battery/solar optimisation.  
              **Full KEMS** — forecasts + smart import tariffs.  
              **Full KEMS Agile** — Full KEMS + dynamic smart export.
"""

_LIVE_PREFIX = """      - type: markdown
        content: |
          # Live Data
          This page is deliberately **actual data only**. Nothing here is a simulated flow.
      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Live power now
            show_header_toggle: false
            entities:
              - entity: sensor.kems_house_load
                name: House load
              - entity: sensor.kems_solar_power
                name: Solar
              - entity: sensor.kems_grid_import
                name: Grid import
              - entity: sensor.kems_grid_export
                name: Grid export
              - entity: sensor.kems_battery_state_of_charge
                name: Battery SOC
              - entity: sensor.kems_battery_power
                name: Battery power
          - type: entities
            title: Live cost & energy today
            show_header_toggle: false
            entities:
              - entity: sensor.kems_current_import_rate
                name: Import rate now
              - entity: sensor.kems_observed_grid_import_today
                name: Grid import
              - entity: sensor.kems_observed_grid_export_today
                name: Grid export
              - entity: sensor.kems_observed_export_income_today
                name: Export income
              - entity: sensor.kems_observed_cost_today
                name: Electricity cost
              - entity: sensor.kems_whole_home_energy_today
                name: Whole-home energy
"""

_BATTERY_SOLAR_PREFIX = """      - type: markdown
        content: |
          # Battery & Solar
          A simple battery/solar system using the configured import and export tariffs. **Live** is the property; **Simulated** is the same demand replayed through the Battery & Solar strategy.
      - type: grid
        columns: 2
        square: false
        cards:
          - type: markdown
            title: LIVE — now & today
            content: |
              | Metric | Live |
              |---|---:|
              | House load | {{ states('sensor.kems_house_load') }} kW |
              | Solar | {{ states('sensor.kems_solar_power') }} kW |
              | Grid import | {{ states('sensor.kems_grid_import') }} kW |
              | Grid export | {{ states('sensor.kems_grid_export') }} kW |
              | Battery SOC | {{ states('sensor.kems_battery_state_of_charge') }}% |
              | Battery power | {{ states('sensor.kems_battery_power') }} kW |
              | Grid import today | {{ states('sensor.kems_observed_grid_import_today') }} kWh |
              | Grid export today | {{ states('sensor.kems_observed_grid_export_today') }} kWh |
              | Export income today | {{ states('sensor.kems_observed_export_income_today') }} |
              | Cost today | {{ states('sensor.kems_observed_cost_today') }} p |
          - type: markdown
            title: SIMULATED — Battery & Solar
            content: |
              {% set e = 'sensor.kems_compare_solar_and_battery_cost_today' %}
              | Metric | Simulated |
              |---|---:|
              | House load | {{ state_attr(e, 'current_house_load_kw') or 0 }} kW |
              | Solar | {{ state_attr(e, 'current_solar_power_kw') or 0 }} kW |
              | Grid import | {{ state_attr(e, 'current_grid_import_kw') or 0 }} kW |
              | Grid export | {{ state_attr(e, 'current_grid_export_kw') or 0 }} kW |
              | Battery → home | {{ state_attr(e, 'current_battery_to_home_kw') or 0 }} kW |
              | Battery → export | {{ state_attr(e, 'current_battery_export_kw') or 0 }} kW |
              | Battery SOC | {{ state_attr(e, 'current_battery_soc_percent') if state_attr(e, 'current_battery_soc_percent') is not none else '—' }}% |
              | Grid import today | {{ state_attr(e, 'grid_import_kwh') or 0 }} kWh |
              | Grid export today | {{ state_attr(e, 'grid_export_kwh') or 0 }} kWh |
              | Export income today | {{ state_attr(e, 'export_income_pence') or 0 }} p |
              | Cost today | {{ states(e) }} p |
      - type: entities
        title: Tariff used by Battery & Solar
        show_header_toggle: false
        entities:
          - sensor.kems_current_import_rate
          - binary_sensor.kems_cheap_period_confirmed
          - sensor.kems_export_tariff_status
"""

_FULL_KEMS_PREFIX = """      - type: markdown
        content: |
          # Full KEMS
          Full forecast-aware optimisation with smart **import** tariffs, EV awareness, reserve planning and grid-service logic. The same property is shown Live and Simulated side by side.
      - type: grid
        columns: 2
        square: false
        cards:
          - type: markdown
            title: LIVE — property
            content: |
              | Metric | Live |
              |---|---:|
              | House load | {{ states('sensor.kems_house_load') }} kW |
              | Solar | {{ states('sensor.kems_solar_power') }} kW |
              | Grid import | {{ states('sensor.kems_grid_import') }} kW |
              | Grid export | {{ states('sensor.kems_grid_export') }} kW |
              | Battery SOC | {{ states('sensor.kems_battery_state_of_charge') }}% |
              | Battery power | {{ states('sensor.kems_battery_power') }} kW |
              | Import rate | {{ states('sensor.kems_current_import_rate') }} p/kWh |
              | Cheap period | {{ states('binary_sensor.kems_cheap_period_confirmed') }} |
              | Grid import today | {{ states('sensor.kems_observed_grid_import_today') }} kWh |
              | Grid export today | {{ states('sensor.kems_observed_grid_export_today') }} kWh |
              | Cost today | {{ states('sensor.kems_observed_cost_today') }} p |
          - type: markdown
            title: SIMULATED — Full KEMS
            content: |
              {% set e = 'sensor.kems_compare_full_kems_forecast_cost_today' %}
              | Metric | Simulated |
              |---|---:|
              | House load | {{ state_attr(e, 'current_house_load_kw') or 0 }} kW |
              | Solar | {{ state_attr(e, 'current_solar_power_kw') or 0 }} kW |
              | Grid import | {{ state_attr(e, 'current_grid_import_kw') or 0 }} kW |
              | Grid export | {{ state_attr(e, 'current_grid_export_kw') or 0 }} kW |
              | Grid → battery | {{ state_attr(e, 'current_grid_to_battery_kw') or 0 }} kW |
              | Battery → home | {{ state_attr(e, 'current_battery_to_home_kw') or 0 }} kW |
              | Battery → export | {{ state_attr(e, 'current_battery_export_kw') or 0 }} kW |
              | Battery SOC | {{ state_attr(e, 'current_battery_soc_percent') if state_attr(e, 'current_battery_soc_percent') is not none else '—' }}% |
              | Grid import today | {{ state_attr(e, 'grid_import_kwh') or 0 }} kWh |
              | Grid export today | {{ state_attr(e, 'grid_export_kwh') or 0 }} kWh |
              | Export income today | {{ state_attr(e, 'export_income_pence') or 0 }} p |
              | Cost today | {{ states(e) }} p |
      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Smart import & EV
            entities:
              - sensor.kems_current_import_rate
              - sensor.kems_next_import_rate
              - binary_sensor.kems_cheap_period_confirmed
              - binary_sensor.kems_ev_connected
              - binary_sensor.kems_ev_charging
              - sensor.kems_ev_charging_power
              - sensor.kems_ev_state_of_charge
          - type: entities
            title: Forecast protection
            entities:
              - sensor.kems_full_kems_forecast_status
              - sensor.kems_forecast_solar_tomorrow
              - sensor.kems_forecast_house_demand_tomorrow
              - sensor.kems_forecast_required_morning_soc
"""

_AGILE_PREFIX = """      - type: markdown
        content: |
          # Full KEMS Agile
          Everything in Full KEMS, plus dynamic **smart export**. KEMS can hold or export battery energy according to Agile prices while still protecting the overnight deadline, reserve and shared inverter limit.
      - type: grid
        columns: 2
        square: false
        cards:
          - type: markdown
            title: LIVE — property
            content: |
              | Metric | Live |
              |---|---:|
              | House load | {{ states('sensor.kems_house_load') }} kW |
              | Solar | {{ states('sensor.kems_solar_power') }} kW |
              | Grid import | {{ states('sensor.kems_grid_import') }} kW |
              | Grid export | {{ states('sensor.kems_grid_export') }} kW |
              | Battery SOC | {{ states('sensor.kems_battery_state_of_charge') }}% |
              | Battery power | {{ states('sensor.kems_battery_power') }} kW |
              | Import rate | {{ states('sensor.kems_current_import_rate') }} p/kWh |
              | Agile export rate | {{ states('sensor.kems_agile_export_rate_now') }} p/kWh |
              | Cheap period | {{ states('binary_sensor.kems_cheap_period_confirmed') }} |
              | Cost today | {{ states('sensor.kems_observed_cost_today') }} p |
          - type: markdown
            title: SIMULATED — Full KEMS Agile
            content: |
              {% set e = 'sensor.kems_agile_live_scenario' %}
              {% set periods = state_attr('sensor.kems_agile_smart_export_plan', 'periods') or {} %}
              {% set today = periods.get('today', {}) %}
              {% set a = today.get('agile_smart_export', {}) %}
              | Metric | Simulated |
              |---|---:|
              | House load | {{ state_attr(e, 'current_house_load_kw') or 0 }} kW |
              | Solar | {{ state_attr(e, 'current_solar_power_kw') or 0 }} kW |
              | Grid import | {{ state_attr(e, 'current_grid_import_kw') or 0 }} kW |
              | Grid export | {{ state_attr(e, 'current_grid_export_kw') or 0 }} kW |
              | Grid → battery | {{ state_attr(e, 'current_grid_to_battery_kw') or 0 }} kW |
              | Battery → home | {{ state_attr(e, 'current_battery_to_home_kw') or 0 }} kW |
              | Battery → export | {{ state_attr(e, 'current_battery_export_kw') or 0 }} kW |
              | Battery SOC | {{ state_attr(e, 'simulated_soc_percent') if state_attr(e, 'simulated_soc_percent') is not none else '—' }}% |
              | Grid import today | {{ a.get('grid_import_kwh', 0) }} kWh |
              | Grid export today | {{ a.get('grid_export_kwh', 0) }} kWh |
              | Export income today | {{ a.get('export_income_pence', 0) }} p |
              | Economic cost today | {{ a.get('economic_net_cost_pence', 0) }} p |
      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Smart tariffs now
            entities:
              - sensor.kems_current_import_rate
              - binary_sensor.kems_cheap_period_confirmed
              - sensor.kems_agile_export_rate_now
              - sensor.kems_agile_price_data_quality
          - type: entities
            title: Agile decision
            entities:
              - sensor.kems_agile_smart_export_status
              - sensor.kems_agile_smart_export_plan
"""

_COMPARE_PREFIX = """      - type: markdown
        content: |
          # Compare every KEMS type
          The same household demand is presented in one table so you can compare **Live Data**, **Battery & Solar**, **Full KEMS** and **Full KEMS Agile** without switching pages.
      - type: markdown
        title: Right now — all power flows
        content: |
          {% set b = 'sensor.kems_compare_solar_and_battery_cost_today' %}
          {% set f = 'sensor.kems_compare_full_kems_forecast_cost_today' %}
          {% set a = 'sensor.kems_agile_live_scenario' %}
          | Metric | Live Data | Battery & Solar | Full KEMS | Full KEMS Agile |
          |---|---:|---:|---:|---:|
          | House load kW | {{ states('sensor.kems_house_load') }} | {{ state_attr(b, 'current_house_load_kw') or 0 }} | {{ state_attr(f, 'current_house_load_kw') or 0 }} | {{ state_attr(a, 'current_house_load_kw') or 0 }} |
          | Solar kW | {{ states('sensor.kems_solar_power') }} | {{ state_attr(b, 'current_solar_power_kw') or 0 }} | {{ state_attr(f, 'current_solar_power_kw') or 0 }} | {{ state_attr(a, 'current_solar_power_kw') or 0 }} |
          | Grid import kW | {{ states('sensor.kems_grid_import') }} | {{ state_attr(b, 'current_grid_import_kw') or 0 }} | {{ state_attr(f, 'current_grid_import_kw') or 0 }} | {{ state_attr(a, 'current_grid_import_kw') or 0 }} |
          | Grid export kW | {{ states('sensor.kems_grid_export') }} | {{ state_attr(b, 'current_grid_export_kw') or 0 }} | {{ state_attr(f, 'current_grid_export_kw') or 0 }} | {{ state_attr(a, 'current_grid_export_kw') or 0 }} |
          | Solar → home kW | — | {{ state_attr(b, 'current_solar_to_home_kw') or 0 }} | {{ state_attr(f, 'current_solar_to_home_kw') or 0 }} | {{ state_attr(a, 'current_solar_to_home_kw') or 0 }} |
          | Solar → battery kW | — | {{ state_attr(b, 'current_solar_to_battery_kw') or 0 }} | {{ state_attr(f, 'current_solar_to_battery_kw') or 0 }} | {{ state_attr(a, 'current_solar_to_battery_kw') or 0 }} |
          | Solar export kW | — | {{ state_attr(b, 'current_solar_export_kw') or 0 }} | {{ state_attr(f, 'current_solar_export_kw') or 0 }} | {{ state_attr(a, 'current_solar_export_kw') or 0 }} |
          | Grid → battery kW | — | {{ state_attr(b, 'current_grid_to_battery_kw') or 0 }} | {{ state_attr(f, 'current_grid_to_battery_kw') or 0 }} | {{ state_attr(a, 'current_grid_to_battery_kw') or 0 }} |
          | Battery → home kW | — | {{ state_attr(b, 'current_battery_to_home_kw') or 0 }} | {{ state_attr(f, 'current_battery_to_home_kw') or 0 }} | {{ state_attr(a, 'current_battery_to_home_kw') or 0 }} |
          | Battery → export kW | — | {{ state_attr(b, 'current_battery_export_kw') or 0 }} | {{ state_attr(f, 'current_battery_export_kw') or 0 }} | {{ state_attr(a, 'current_battery_export_kw') or 0 }} |
          | Battery SOC % | {{ states('sensor.kems_battery_state_of_charge') }} | {{ state_attr(b, 'current_battery_soc_percent') if state_attr(b, 'current_battery_soc_percent') is not none else '—' }} | {{ state_attr(f, 'current_battery_soc_percent') if state_attr(f, 'current_battery_soc_percent') is not none else '—' }} | {{ state_attr(a, 'simulated_soc_percent') if state_attr(a, 'simulated_soc_percent') is not none else '—' }} |
      - type: markdown
        title: Today — cost, energy & savings
        content: |
          {% set b = 'sensor.kems_compare_solar_and_battery_cost_today' %}
          {% set f = 'sensor.kems_compare_full_kems_forecast_cost_today' %}
          {% set periods = state_attr('sensor.kems_agile_smart_export_plan', 'periods') or {} %}
          {% set a = (periods.get('today', {}) or {}).get('agile_smart_export', {}) %}
          | Metric | Live Data | Battery & Solar | Full KEMS | Full KEMS Agile |
          |---|---:|---:|---:|---:|
          | Total / economic cost p | {{ states('sensor.kems_observed_cost_today') }} | {{ states(b) }} | {{ states(f) }} | {{ a.get('economic_net_cost_pence', '—') }} |
          | Import cost p | — | {{ state_attr(b, 'import_cost_pence') or 0 }} | {{ state_attr(f, 'import_cost_pence') or 0 }} | {{ a.get('import_cost_pence', 0) }} |
          | Export income p | {{ states('sensor.kems_observed_export_income_today') }} | {{ state_attr(b, 'export_income_pence') or 0 }} | {{ state_attr(f, 'export_income_pence') or 0 }} | {{ a.get('export_income_pence', 0) }} |
          | Grid import kWh | {{ states('sensor.kems_observed_grid_import_today') }} | {{ state_attr(b, 'grid_import_kwh') or 0 }} | {{ state_attr(f, 'grid_import_kwh') or 0 }} | {{ a.get('grid_import_kwh', 0) }} |
          | Grid export kWh | {{ states('sensor.kems_observed_grid_export_today') }} | {{ state_attr(b, 'grid_export_kwh') or 0 }} | {{ state_attr(f, 'grid_export_kwh') or 0 }} | {{ a.get('grid_export_kwh', 0) }} |
          | Solar generation kWh | — | {{ state_attr(b, 'solar_generation_kwh') or 0 }} | {{ state_attr(f, 'solar_generation_kwh') or 0 }} | — |
          | Solar → home kWh | — | {{ state_attr(b, 'solar_to_home_kwh') or 0 }} | {{ state_attr(f, 'solar_to_home_kwh') or 0 }} | {{ a.get('solar_to_home_kwh', 0) }} |
          | Solar → battery kWh | — | {{ state_attr(b, 'solar_to_battery_kwh') or 0 }} | {{ state_attr(f, 'solar_to_battery_kwh') or 0 }} | {{ a.get('solar_to_battery_kwh', 0) }} |
          | Solar export kWh | — | {{ state_attr(b, 'solar_export_kwh') or 0 }} | {{ state_attr(f, 'solar_export_kwh') or 0 }} | {{ a.get('solar_export_kwh', 0) }} |
          | Battery charge kWh | — | {{ state_attr(b, 'battery_charge_kwh') or 0 }} | {{ state_attr(f, 'battery_charge_kwh') or 0 }} | — |
          | Battery → home kWh | — | {{ state_attr(b, 'battery_to_home_kwh') or 0 }} | {{ state_attr(f, 'battery_to_home_kwh') or 0 }} | {{ a.get('battery_to_home_kwh', 0) }} |
          | Battery export kWh | — | {{ state_attr(b, 'battery_export_kwh') or 0 }} | {{ state_attr(f, 'battery_export_kwh') or 0 }} | {{ a.get('battery_export_kwh', 0) }} |
          | Ending SOC % | {{ states('sensor.kems_battery_state_of_charge') }} | {{ state_attr(b, 'ending_soc_percent') if state_attr(b, 'ending_soc_percent') is not none else '—' }} | {{ state_attr(f, 'ending_soc_percent') if state_attr(f, 'ending_soc_percent') is not none else '—' }} | {{ a.get('ending_soc_percent', '—') }} |
          | Saving vs no system p | — | {{ state_attr(b, 'saving_vs_no_system_pence') or 0 }} | {{ state_attr(f, 'saving_vs_no_system_pence') or 0 }} | — |
          | Agile weighted export p/kWh | — | — | — | {{ a.get('weighted_achieved_export_rate_pence', '—') }} |
      - type: history-graph
        title: Cost comparison — 24 hours
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

_HISTORY_PREFIX = """      - type: markdown
        title: History & finance
        content: |
          Historical energy, costs, export income, ROI, Agile evidence and gas are kept together here. Long-term Agile conclusions remain labelled incomplete until their required evidence window is complete.
"""

_ADVANCED_PREFIX = """      - type: markdown
        content: |
          # Advanced / Test Lab
          Normal users do not need these controls. They remain available for commissioning, EPS validation and deterministic virtual stress tests.

          **Engineering progression:** Observe → Simulate → Shadow → Control.  
          The normal user-facing selector intentionally exposes only **Live / Simulate / Control**; Shadow remains an internal commissioning stage.
      - type: entities
        title: Advanced test lab
        show_header_toggle: false
        entities:
          - entity: select.kems_virtual_scenario
            name: Virtual stress scenario
          - switch.kems_emergency_stop
          - switch.kems_master_control_enable
      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Safety gates
            entities:
              - binary_sensor.kems_control_plan_safe
              - binary_sensor.kems_control_data_fresh
              - binary_sensor.kems_real_control_backend_available
              - binary_sensor.kems_control_commands_permitted
          - type: entities
            title: Desired control plan
            entities:
              - sensor.kems_control_operating_reason
              - sensor.kems_desired_inverter_work_mode
              - sensor.kems_desired_battery_charge_power
              - sensor.kems_desired_battery_to_home_power
              - sensor.kems_desired_battery_export_power
              - sensor.kems_desired_minimum_soc
"""

_SYSTEM_PREFIX = """      - type: markdown
        title: System & diagnostics
        content: |
          Updates, learning health and deep entity diagnostics live here rather than taking space in the normal energy-management workflow.
"""

FINAL_VIEW_SPECS = (
    ViewSpec("Home", "home", "mdi:home-lightning-bolt", ("Overview",), _HOME_PREFIX),
    ViewSpec("Live Data", "live-data", "mdi:flash", ("Live Energy",), _LIVE_PREFIX),
    ViewSpec(
        "Battery & Solar",
        "battery-solar",
        "mdi:solar-power",
        ("Battery & Solar", "Simulation"),
        _BATTERY_SOLAR_PREFIX,
    ),
    ViewSpec(
        "Full KEMS",
        "full-kems",
        "mdi:home-lightning-bolt-outline",
        ("Forecast", "Full KEMS Forecast", "Tariff & EV", "Power Down"),
        _FULL_KEMS_PREFIX,
    ),
    ViewSpec(
        "Full KEMS Agile",
        "full-kems-agile",
        "mdi:transmission-tower-export",
        ("Agile Smart Export", "Agile Price Plan", "Agile Assumptions"),
        _AGILE_PREFIX,
    ),
    ViewSpec(
        "Compare",
        "compare",
        "mdi:compare-horizontal",
        ("Compare", "Forecast vs Agile"),
        _COMPARE_PREFIX,
    ),
    ViewSpec(
        "History",
        "history",
        "mdi:history",
        ("Finance & History", "Agile History", "Gas"),
        _HISTORY_PREFIX,
    ),
    ViewSpec(
        "Advanced / Test Lab",
        "advanced",
        "mdi:test-tube",
        ("Commissioning", "Control & EPS"),
        _ADVANCED_PREFIX,
    ),
    ViewSpec(
        "System",
        "system",
        "mdi:cog-outline",
        ("Learning & Health", "Updates", "All Entities"),
        _SYSTEM_PREFIX,
    ),
)


def _split_views(content: str) -> dict[str, str]:
    """Return top-level Home Assistant view blocks keyed by title."""
    lines = content.splitlines(keepends=True)
    starts = [
        index for index, line in enumerate(lines) if line.startswith("  - title: ")
    ]
    views: dict[str, str] = {}
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        title = lines[start].split(":", 1)[1].strip().strip('"').strip("'")
        views[title] = "".join(lines[start:end]).rstrip() + "\n"
    return views


def _cards_body(view_block: str) -> str:
    """Return the already-indented card list from one source view."""
    marker = "    cards:\n"
    if marker not in view_block:
        raise ValueError("KEMS dashboard source view has no cards section")
    return view_block.split(marker, 1)[1].rstrip() + "\n"


def _section_card(title: str) -> str:
    """Add a compact divider when several former tabs share one final page."""
    return "      - type: markdown\n" "        content: |\n" f"          ## {title}\n"


def _render_view(spec: ViewSpec, source_views: dict[str, str]) -> str:
    """Render one final navigation view from one or more source views."""
    parts = [
        f"  - title: {spec.title}\n",
        f"    path: {spec.path}\n",
        f"    icon: {spec.icon}\n",
        "    cards:\n",
    ]
    if spec.prefix:
        parts.append(spec.prefix.rstrip() + "\n")
    for source_title in spec.sources:
        if len(spec.sources) > 1:
            parts.append(_section_card(source_title))
        parts.append(_cards_body(source_views[source_title]))
    return "".join(parts).rstrip() + "\n"


def consolidate_dashboard(content: str) -> str:
    """Render the simplified nine-page KEMS product dashboard."""
    source_views = _split_views(content)
    missing = sorted(EXPECTED_SOURCE_TITLES - set(source_views))
    if missing:
        raise ValueError(
            "KEMS dashboard consolidation is missing source view(s): "
            + ", ".join(missing)
        )

    rendered = ["title: KEMS Master Dashboard\n\nviews:\n"]
    for spec in FINAL_VIEW_SPECS:
        rendered.append(_render_view(spec, source_views))
    return "\n".join(part.rstrip() for part in rendered).rstrip() + "\n"


def install_dashboard_consolidation() -> None:
    """Install final dashboard consolidation after all feature view patches."""
    from . import dashboard as dashboard_module

    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_dashboard_consolidated", False):
        return

    def combined_consolidated_dashboard() -> bytes:
        content = original().decode("utf-8")
        return consolidate_dashboard(content).encode("utf-8")

    combined_consolidated_dashboard._kems_dashboard_consolidated = True
    dashboard_module._combined_master_dashboard_bytes = combined_consolidated_dashboard
