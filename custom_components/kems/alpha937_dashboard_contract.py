"""Final customer-dashboard data-contract repair for Alpha9.37.

This layer is presentation-only.  It runs after the established Alpha9.5 dashboard
presentation so every customer-facing current-day KEMS figure comes from the same
canonical live simulation entities, while stale dashboard entity references are
mapped to their registered Home Assistant entities.
"""

from __future__ import annotations

from collections.abc import Callable

DashboardBytesFn = Callable[[], bytes]

_installed = False

_ROI_ENTITY_RENAMES = {
    "sensor.kems_financial_house_consumption": (
        "sensor.kems_house_consumption_since_commissioning"
    ),
    "sensor.kems_financial_solar_generation": (
        "sensor.kems_solar_generation_since_commissioning"
    ),
    "sensor.kems_financial_grid_import": "sensor.kems_grid_import_since_commissioning",
    "sensor.kems_financial_grid_export": "sensor.kems_grid_export_since_commissioning",
    "sensor.kems_financial_export_income": (
        "sensor.kems_paid_export_income_since_commissioning"
    ),
}

_LIVE_ENERGY_TODAY = """      - type: markdown
        title: Energy today
        content: |
          {% set solar = state_attr('sensor.kems_simulated_kems_cost_today', 'actual_solar_generation_kwh') %}
          | Energy | Live Data |
          |---|---:|
          | Whole-home energy | {{ states('sensor.kems_whole_home_energy_today') }} kWh |
          | Grid import | {{ states('sensor.kems_observed_grid_import_today') }} kWh |
          | Grid export | {{ states('sensor.kems_observed_grid_export_today') }} kWh |
          | Solar generation | {{ (solar ~ ' kWh') if solar is not none else '—' }} |
          | Gas usage | {{ states('sensor.kems_gas_usage_today') }} kWh |
          | Export income | {{ states('sensor.kems_observed_export_income_today') }} p |
"""

_COMPARE_KEMS = """          - type: markdown
            title: KEMS
            content: |
              {% set bad = ['unknown', 'unavailable', 'none', ''] %}
              {% set total_state = states('sensor.kems_whole_home_simulated_cost_today') %}
              {% set total = (total_state | float(0)) if total_state | lower not in bad else none %}
              {% set gas_state = states('sensor.kems_gas_cost_today') %}
              {% set gas = (gas_state | float(0)) if gas_state | lower not in bad else none %}
              {% set electricity = (total - gas) if total is not none and gas is not none else none %}
              **Today total energy cost**  
              # {{ ('£%.2f' | format(total / 100)) if total is not none else '—' }}

              Electricity: {{ ('£%.2f' | format(electricity / 100)) if electricity is not none else '—' }}  
              Gas: {{ ('£%.2f' | format(gas / 100)) if gas is not none else '—' }}  
              Grid import: {{ states('sensor.kems_simulated_grid_import_today') }} kWh  
              Grid export: {{ states('sensor.kems_simulated_grid_export_today') }} kWh

              _Configured KEMS digital twin — canonical current-day simulation._
"""

_COMPARE_SIDE_BY_SIDE = """      - type: markdown
        title: Today — side by side
        content: |
          {% set bad = ['unknown', 'unavailable', 'none', ''] %}
          {% set gas_state = states('sensor.kems_gas_cost_today') %}
          {% set gas = (gas_state | float(0)) if gas_state | lower not in bad else none %}
          {% set base_state = states('sensor.kems_compare_no_system_cost_today') %}
          {% set base_e = (base_state | float(0)) if base_state | lower not in bad else none %}
          {% set live_state = states('sensor.kems_whole_home_observed_cost_today') %}
          {% set live_total = (live_state | float(0)) if live_state | lower not in bad else none %}
          {% set live_e = (live_total - gas) if live_total is not none and gas is not none else none %}
          {% set kems_state = states('sensor.kems_whole_home_simulated_cost_today') %}
          {% set kems_total = (kems_state | float(0)) if kems_state | lower not in bad else none %}
          {% set kems_e = (kems_total - gas) if kems_total is not none and gas is not none else none %}
          {% set base_total = (base_e + gas) if base_e is not none and gas is not none else none %}
          | Metric | Without KEMS | Live | KEMS |
          |---|---:|---:|---:|
          | Total energy cost | {{ ('£%.2f' | format(base_total / 100)) if base_total is not none else '—' }} | {{ ('£%.2f' | format(live_total / 100)) if live_total is not none else '—' }} | {{ ('£%.2f' | format(kems_total / 100)) if kems_total is not none else '—' }} |
          | Electricity | {{ ('£%.2f' | format(base_e / 100)) if base_e is not none else '—' }} | {{ ('£%.2f' | format(live_e / 100)) if live_e is not none else '—' }} | {{ ('£%.2f' | format(kems_e / 100)) if kems_e is not none else '—' }} |
          | Gas | {{ ('£%.2f' | format(gas / 100)) if gas is not none else '—' }} | {{ ('£%.2f' | format(gas / 100)) if gas is not none else '—' }} | {{ ('£%.2f' | format(gas / 100)) if gas is not none else '—' }} |
          | Grid import | {{ state_attr('sensor.kems_compare_no_system_cost_today', 'grid_import_kwh') or '—' }} | {{ states('sensor.kems_observed_grid_import_today') }} | {{ states('sensor.kems_simulated_grid_import_today') }} |
          | Grid export | {{ state_attr('sensor.kems_compare_no_system_cost_today', 'grid_export_kwh') or 0 }} | {{ states('sensor.kems_observed_grid_export_today') }} | {{ states('sensor.kems_simulated_grid_export_today') }} |

          {% if base_total is not none and live_total is not none %}
          **Live system value vs no system:** £{{ '%.2f' | format((base_total - live_total) / 100) }}
          {% endif %}
          {% if base_total is not none and kems_total is not none %}
          **KEMS potential value vs no system:** £{{ '%.2f' | format((base_total - kems_total) / 100) }}
          {% endif %}
"""


def _replace_between(content: str, start: str, end: str, replacement: str) -> str:
    """Replace one deterministic dashboard region."""
    begin = content.find(start)
    if begin < 0:
        return content
    finish = content.find(end, begin + len(start))
    if finish < 0:
        return content
    return content[:begin] + replacement.rstrip() + "\n" + content[finish:]


def _repair_compare_view(content: str) -> str:
    """Make Compare use the same canonical KEMS-today contract as the KEMS page."""
    marker = "\n  - title: Compare\n"
    start = content.find(marker)
    if start < 0:
        return content
    end = content.find("\n  - title:", start + len(marker))
    if end < 0:
        end = len(content)
    compare = content[start:end]
    compare = _replace_between(
        compare,
        "          - type: markdown\n            title: KEMS\n",
        "      - type: markdown\n        title: Today — side by side\n",
        _COMPARE_KEMS,
    )
    compare = _replace_between(
        compare,
        "      - type: markdown\n        title: Today — side by side\n",
        "      - type: history-graph\n        title: Electricity cost — Live vs KEMS\n",
        _COMPARE_SIDE_BY_SIDE,
    )
    return content[:start] + compare + content[end:]


def _repair_live_energy_today(content: str) -> str:
    """Publish measured solar without referencing an entity that is not registered."""
    marker = "\n  - title: Live Data\n"
    start = content.find(marker)
    if start < 0:
        return content
    end = content.find("\n  - title:", start + len(marker))
    if end < 0:
        end = len(content)
    live = content[start:end]
    live = _replace_between(
        live,
        "      - type: entities\n        title: Energy today\n",
        "      - type: markdown\n        title: Power history — today\n",
        _LIVE_ENERGY_TODAY,
    )
    return content[:start] + live + content[end:]


def repair_dashboard_contract(payload: bytes) -> bytes:
    """Return customer dashboard bytes with one coherent registered-entity contract."""
    content = payload.decode("utf-8")

    for old, new in _ROI_ENTITY_RENAMES.items():
        content = content.replace(old, new)

    content = content.replace(
        "sensor.kems_lifetime_gas_usage",
        "sensor.kems_lifetime_gas_consumption",
    ).replace(
        "sensor.kems_lifetime_total_energy_cost",
        "sensor.kems_lifetime_net_energy_cost",
    )

    content = _repair_live_energy_today(content)
    content = _repair_compare_view(content)
    return content.encode("utf-8")


def install_alpha937_dashboard_contract() -> None:
    """Make Alpha9.37's final reporting contract authoritative for dashboard sync."""
    global _installed
    if _installed:
        return

    from . import dashboard
    from . import update_orchestrator_convergent as convergent

    current: DashboardBytesFn = dashboard._combined_master_dashboard_bytes

    def dashboard_bytes_with_alpha937() -> bytes:
        return repair_dashboard_contract(current())

    dashboard_bytes_with_alpha937._kems_alpha937_dashboard_contract = True
    dashboard._combined_master_dashboard_bytes = dashboard_bytes_with_alpha937
    convergent._managed_dashboard_bytes = dashboard_bytes_with_alpha937
    _installed = True
