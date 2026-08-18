"""Final KEMS master-dashboard consolidation for the production-style UI."""

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
        title: Operating context
        content: |
          {% if is_state('binary_sensor.kems_system_installed', 'on') %}
          **Dashboard context:** **{{ states('sensor.kems_operating_mode') | upper }}**  
          {% else %}
          **Dashboard context:** **SIMULATION / PRE-INSTALL**  
          {% endif %}
          **KEMS status:** {{ states('sensor.kems_status') }}  
          **Commissioning:** {{ states('sensor.kems_commissioning_readiness') }}  
          **Real control permitted:** {{ states('binary_sensor.kems_control_commands_permitted') }}  
          **Current advice:** {{ states('sensor.kems_advice') }}

          The same production dashboard is used before and after installation. Simulation values remain active until the physical solar, battery and inverter are commissioned; live hardware values then take over progressively.
"""

_LIVE_PREFIX = """      - type: markdown
        title: Live control tracking — prepared for commissioning
        content: |
          {% set commissioned = is_state('binary_sensor.kems_battery_data_available', 'on') %}
          **Hardware state:** **{{ 'LIVE DATA AVAILABLE' if commissioned else 'NOT COMMISSIONED — SIMULATION ONLY' }}**  
          **Operating mode:** {{ states('sensor.kems_operating_mode') }}  
          **Control commands permitted:** {{ states('binary_sensor.kems_control_commands_permitted') }}

          | Control signal | Actual hardware | KEMS target |
          |---|---:|---:|
          | Battery power | {{ states('sensor.kems_battery_power') if commissioned else '—' }} kW | {{ states('sensor.kems_desired_total_battery_discharge_power') }} kW discharge |
          | Battery export | — until commissioned | {{ states('sensor.kems_desired_battery_export_power') }} kW |
          | Battery charge | — until commissioned | {{ states('sensor.kems_desired_battery_charge_power') }} kW |
          | Minimum SOC | {{ states('sensor.kems_battery_state_of_charge') if commissioned else '—' }}% actual SOC | {{ states('sensor.kems_desired_minimum_soc') }}% minimum |

          Once FoxESS direction verification passes, KEMS can normalise the hardware flows and this section can show **Actual → Target → Difference** directly without guessing battery sign conventions before commissioning.
"""

_PLAN_PREFIX = """      - type: markdown
        title: KEMS plan — one forward view
        content: |
          This page combines the forecast, Full KEMS Forecast strategy and digital-twin simulation into one operating plan. It is the place to answer **what KEMS expects to happen, what it intends to do, and why**.
"""

_AGILE_PREFIX = """      - type: markdown
        title: Agile Smart Export workspace
        content: |
          Live Agile dispatch, rolling export allocation, half-hour price planning and assumptions are consolidated here. The strategy remains **simulation-only** until real-control commissioning explicitly permits hardware writes.
"""

_COMPARE_PREFIX = """      - type: markdown
        title: Compare & optimise
        content: |
          Compare the available system strategies and tariff choices in one place. Incomplete fixed windows should be treated as **collecting evidence**, not as authoritative long-term winners.
"""

_HISTORY_PREFIX = """      - type: markdown
        title: History & finance
        content: |
          Energy, Agile replay history, costs, export income, ROI, payback and gas history are grouped here so long-term performance can be judged from one page.
"""

_BATTERY_PREFIX = """      - type: markdown
        title: Battery & solar plant
        content: |
          Before installation this page describes the proposed/digital-twin system. After commissioning it becomes the physical plant page for solar, inverter and battery performance, limits and health.
"""

_EV_PREFIX = """      - type: markdown
        title: EV, tariff & grid-services
        content: |
          Intelligent/cheap slots, EV charging and Power Down participation are grouped because they all affect when KEMS should import, charge, reserve or export energy.
"""

_EPS_CARDS = """      - type: markdown
        content: |
          # Backup / EPS
          This page is prepared for the physical EPS installation. Until the hardware is commissioned, unavailable live readings are expected.

          **Grid available:** {{ states('binary_sensor.kems_grid_available_for_control') }}  
          **Island mode:** {{ states('binary_sensor.kems_whole_house_island_mode') }}  
          **Estimated outage runtime:** {{ states('sensor.kems_estimated_outage_runtime') }}  
          **Commissioning readiness:** {{ states('sensor.kems_commissioning_readiness') }}
      - type: grid
        columns: 2
        square: false
        cards:
          - type: tile
            entity: binary_sensor.kems_grid_available_for_control
            name: Grid available
          - type: tile
            entity: binary_sensor.kems_whole_house_island_mode
            name: Island mode
          - type: tile
            entity: sensor.kems_whole_house_eps_load
            name: EPS load
          - type: tile
            entity: sensor.kems_estimated_outage_runtime
            name: Estimated runtime
      - type: entities
        title: EPS loading and headroom
        show_header_toggle: false
        entities:
          - sensor.kems_eps_headroom
          - sensor.kems_eps_utilisation
          - sensor.kems_eps_load_status
          - binary_sensor.kems_eps_load_warning
          - binary_sensor.kems_eps_load_critical
          - sensor.kems_kh7_output_headroom
          - sensor.kems_eps_output_limit
      - type: markdown
        title: If the grid failed now
        content: |
          {% set live = is_state('binary_sensor.kems_battery_data_available', 'on') %}
          **SOC source:** {{ 'Live hardware' if live else 'Simulation' }}  
          **Battery SOC:** {{ states('sensor.kems_battery_state_of_charge') if live else states('sensor.kems_simulated_battery_state_of_charge') }}%  
          **Whole-home EPS demand:** {{ states('sensor.kems_whole_house_eps_load') }}  
          **Estimated runtime:** {{ states('sensor.kems_estimated_outage_runtime') }}  
          **EPS warning:** {{ states('binary_sensor.kems_eps_load_warning') }}  
          **EPS critical:** {{ states('binary_sensor.kems_eps_load_critical') }}

          The live version of this page will become the outage dashboard when the EPS and FoxESS hardware are commissioned.
"""

_CONTROL_PREFIX = """      - type: markdown
        title: Control progression
        content: |
          **Operating mode:** {{ states('sensor.kems_operating_mode') }}  
          **Commissioning:** {{ states('sensor.kems_commissioning_readiness') }}  
          **Control preflight:** {{ states('sensor.kems_control_preflight') }}  
          **Real backend:** {{ states('binary_sensor.kems_real_control_backend_available') }}  
          **Commands permitted:** {{ states('binary_sensor.kems_control_commands_permitted') }}

          Progression remains **Simulation → Shadow → Live**. Real writes must stay blocked until commissioning, source freshness, direction verification and safety checks all pass.
      - type: entities
        title: Control lab
        entities:
          - select.kems_operating_mode
          - select.kems_virtual_scenario
          - switch.kems_emergency_stop
          - switch.kems_master_control_enable
      - type: grid
        columns: 2
        square: false
        cards:
          - type: tile
            entity: binary_sensor.kems_control_plan_safe
          - type: tile
            entity: binary_sensor.kems_control_data_fresh
          - type: tile
            entity: binary_sensor.kems_real_control_backend_available
          - type: tile
            entity: binary_sensor.kems_control_commands_permitted
      - type: entities
        title: KEMS target / desired plan
        show_header_toggle: false
        entities:
          - sensor.kems_control_operating_reason
          - sensor.kems_desired_inverter_work_mode
          - sensor.kems_desired_battery_charge_power
          - sensor.kems_desired_battery_to_home_power
          - sensor.kems_desired_battery_export_power
          - sensor.kems_desired_total_battery_discharge_power
          - sensor.kems_desired_minimum_soc
          - sensor.kems_control_next_action
"""

_SYSTEM_PREFIX = """      - type: markdown
        title: System, learning & diagnostics
        content: |
          KEMS learning/forecast health, coordinated updates and deep diagnostics live here rather than occupying separate day-to-day navigation tabs.
"""

FINAL_VIEW_SPECS = (
    ViewSpec("Home", "home", "mdi:home-lightning-bolt", ("Overview",), _HOME_PREFIX),
    ViewSpec("Live", "live", "mdi:flash", ("Live Energy",), _LIVE_PREFIX),
    ViewSpec(
        "Plan",
        "plan",
        "mdi:chart-timeline-variant-shimmer",
        ("Forecast", "Full KEMS Forecast", "Simulation"),
        _PLAN_PREFIX,
    ),
    ViewSpec(
        "Agile",
        "agile",
        "mdi:transmission-tower-export",
        ("Agile Smart Export", "Agile Price Plan", "Agile Assumptions"),
        _AGILE_PREFIX,
    ),
    ViewSpec(
        "Compare",
        "compare",
        "mdi:compare-horizontal",
        ("Forecast vs Agile", "Compare"),
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
        "Battery / Solar",
        "battery-solar",
        "mdi:solar-power",
        ("Battery & Solar",),
        _BATTERY_PREFIX,
    ),
    ViewSpec(
        "EV / Tariff",
        "ev-tariff",
        "mdi:ev-station",
        ("Tariff & EV", "Power Down"),
        _EV_PREFIX,
    ),
    ViewSpec("EPS", "eps", "mdi:shield-home", (), _EPS_CARDS),
    ViewSpec(
        "Control",
        "control",
        "mdi:tune-variant",
        ("Commissioning",),
        _CONTROL_PREFIX,
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
    """Reduce the assembled KEMS dashboard to the production eleven-page layout."""
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
    """Install the final dashboard consolidation after all feature view patches."""
    from . import dashboard as dashboard_module

    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_dashboard_consolidated", False):
        return

    def combined_consolidated_dashboard() -> bytes:
        content = original().decode("utf-8")
        return consolidate_dashboard(content).encode("utf-8")

    combined_consolidated_dashboard._kems_dashboard_consolidated = True
    dashboard_module._combined_master_dashboard_bytes = combined_consolidated_dashboard
