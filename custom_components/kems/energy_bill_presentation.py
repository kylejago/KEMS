"""Home Assistant publication and dashboard presentation for Alpha8 bills."""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .energy_bill import build_energy_cost_comparison
from .product_types import export_tariff_type_from_options

ENTITY_ID = "sensor.kems_energy_cost_comparison"

_PERIOD_CARD = r"""      - type: markdown
        title: Total energy cost by period — Live Data vs KEMS
        content: |
          {% set periods = state_attr('sensor.kems_energy_cost_comparison', 'periods') or {} %}
          **Bill basis:** electricity import + electricity standing charge − electricity export income − supplier/account energy credits + gas usage + gas standing charge. **Battery wear is not included.**

          **KEMS strategy:** {{ state_attr('sensor.kems_energy_cost_comparison', 'selected_kems_strategy_label') or '—' }}

          | Period | Live Data | KEMS | Saving |
          |---|---:|---:|---:|
          {% for key in ['today', 'yesterday', '7_days', '30_days', 'year', '365_days', 'all_time'] %}
          {% set p = periods.get(key, {}) or {} %}
          {% set live = p.get('live_data', {}) or {} %}
          {% set kems = p.get('kems', {}) or {} %}
          | {{ p.get('label', key) }} | {{ ('£%.2f' | format((live.get('total_energy_cost_pence') | float) / 100)) if live.get('total_energy_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('total_energy_cost_pence') | float) / 100)) if kems.get('total_energy_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((p.get('saving_pence') | float) / 100)) if p.get('saving_pence') is not none else '—' }} |
          {% endfor %}

          KEMS still retains its individual replay engines internally for validation, but they are no longer separate user-facing products.
"""

_TODAY_CARD = r"""      - type: markdown
        title: Today — total energy cost breakdown
        content: |
          {% set p = ((state_attr('sensor.kems_energy_cost_comparison', 'periods') or {}).get('today', {}) or {}) %}
          {% set live = p.get('live_data', {}) or {} %}
          {% set kems = p.get('kems', {}) or {} %}
          | Bill component | Live Data | KEMS |
          |---|---:|---:|
          | Electricity import | {{ ('£%.2f' | format((live.get('electricity_import_cost_pence') | float) / 100)) if live.get('electricity_import_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('electricity_import_cost_pence') | float) / 100)) if kems.get('electricity_import_cost_pence') is not none else '—' }} |
          | Electricity standing charge | {{ ('£%.2f' | format((live.get('electricity_standing_charge_pence') | float) / 100)) if live.get('electricity_standing_charge_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('electricity_standing_charge_pence') | float) / 100)) if kems.get('electricity_standing_charge_pence') is not none else '—' }} |
          | Electricity export income | {{ ('-£%.2f' | format((live.get('electricity_export_income_pence') | float) / 100)) if live.get('electricity_export_income_pence') is not none else '—' }} | {{ ('-£%.2f' | format((kems.get('electricity_export_income_pence') | float) / 100)) if kems.get('electricity_export_income_pence') is not none else '—' }} |
          | Supplier/account credits | {{ ('-£%.2f' | format((live.get('supplier_energy_credit_pence') | float) / 100)) if live.get('supplier_energy_credit_pence') is not none else '—' }} | {{ ('-£%.2f' | format((kems.get('supplier_energy_credit_pence') | float) / 100)) if kems.get('supplier_energy_credit_pence') is not none else '—' }} |
          | **Electricity total** | **{{ ('£%.2f' | format((live.get('electricity_total_cost_pence') | float) / 100)) if live.get('electricity_total_cost_pence') is not none else '—' }}** | **{{ ('£%.2f' | format((kems.get('electricity_total_cost_pence') | float) / 100)) if kems.get('electricity_total_cost_pence') is not none else '—' }}** |
          | Gas usage | {{ ('£%.2f' | format((live.get('gas_usage_cost_pence') | float) / 100)) if live.get('gas_usage_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('gas_usage_cost_pence') | float) / 100)) if kems.get('gas_usage_cost_pence') is not none else '—' }} |
          | Gas standing charge | {{ ('£%.2f' | format((live.get('gas_standing_charge_pence') | float) / 100)) if live.get('gas_standing_charge_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('gas_standing_charge_pence') | float) / 100)) if kems.get('gas_standing_charge_pence') is not none else '—' }} |
          | **Gas total** | **{{ ('£%.2f' | format((live.get('gas_total_cost_pence') | float) / 100)) if live.get('gas_total_cost_pence') is not none else '—' }}** | **{{ ('£%.2f' | format((kems.get('gas_total_cost_pence') | float) / 100)) if kems.get('gas_total_cost_pence') is not none else '—' }}** |
          | **TOTAL ENERGY COST** | **{{ ('£%.2f' | format((live.get('total_energy_cost_pence') | float) / 100)) if live.get('total_energy_cost_pence') is not none else '—' }}** | **{{ ('£%.2f' | format((kems.get('total_energy_cost_pence') | float) / 100)) if kems.get('total_energy_cost_pence') is not none else '—' }}** |

          **KEMS strategy:** {{ kems.get('strategy_label', '—') }}. Battery wear is deliberately excluded from every total above.
"""

_PRODUCT_VIEWS = r"""  - title: Live Data vs KEMS
    path: overview
    icon: mdi:home-lightning-bolt
    cards:
      - type: markdown
        content: |
          # Live Data vs KEMS
          **Live Data** is what your home actually did. **KEMS** is what KEMS calculates it would do with the strategy selected for your tariff and system.

          {% set p = ((state_attr('sensor.kems_energy_cost_comparison', 'periods') or {}).get('today', {}) or {}) %}
          {% set live = p.get('live_data', {}) or {} %}
          {% set kems = p.get('kems', {}) or {} %}
          | Today | Live Data | KEMS |
          |---|---:|---:|
          | Total energy cost | **{{ ('£%.2f' | format((live.get('total_energy_cost_pence') | float) / 100)) if live.get('total_energy_cost_pence') is not none else '—' }}** | **{{ ('£%.2f' | format((kems.get('total_energy_cost_pence') | float) / 100)) if kems.get('total_energy_cost_pence') is not none else '—' }}** |
          | Electricity total | {{ ('£%.2f' | format((live.get('electricity_total_cost_pence') | float) / 100)) if live.get('electricity_total_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('electricity_total_cost_pence') | float) / 100)) if kems.get('electricity_total_cost_pence') is not none else '—' }} |
          | Gas total | {{ ('£%.2f' | format((live.get('gas_total_cost_pence') | float) / 100)) if live.get('gas_total_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('gas_total_cost_pence') | float) / 100)) if kems.get('gas_total_cost_pence') is not none else '—' }} |

          **Saving today:** {{ ('£%.2f' | format((p.get('saving_pence') | float) / 100)) if p.get('saving_pence') is not none else '—' }}  
          **KEMS strategy:** {{ state_attr('sensor.kems_energy_cost_comparison', 'selected_kems_strategy_label') or '—' }}
      - type: grid
        columns: 2
        square: false
        cards:
          - type: tile
            entity: sensor.kems_status
            name: KEMS status
          - type: tile
            entity: sensor.kems_data_quality
            name: Data quality

  - title: Live Data
    path: live-data
    icon: mdi:home-clock-outline
    cards:
      - type: markdown
        content: |
          # Live Data
          What actually happened in your home and on your supplier account. The headline is the canonical bill-equivalent total, not an engineering cost model.

          {% set p = ((state_attr('sensor.kems_energy_cost_comparison', 'periods') or {}).get('today', {}) or {}) %}
          {% set live = p.get('live_data', {}) or {} %}
          **Today's total energy cost:** {{ ('£%.2f' | format((live.get('total_energy_cost_pence') | float) / 100)) if live.get('total_energy_cost_pence') is not none else '—' }}
      - type: grid
        columns: 2
        square: false
        cards:
          - type: tile
            entity: sensor.kems_house_load
            name: Home power
          - type: tile
            entity: sensor.kems_grid_net_power
            name: Grid power
          - type: tile
            entity: sensor.kems_grid_import
            name: Grid import
          - type: tile
            entity: sensor.kems_grid_export
            name: Grid export
      - type: history-graph
        title: Live power — 24 hours
        hours_to_show: 24
        entities:
          - sensor.kems_house_load
          - sensor.kems_grid_import
          - sensor.kems_grid_net_power
          - sensor.kems_ev_charging_power

  - title: KEMS
    path: kems
    icon: mdi:lightning-bolt-circle
    cards:
      - type: markdown
        content: |
          # KEMS
          KEMS automatically uses the correct internal strategy for the configured tariff and system. The old Battery & Solar / Full KEMS / Full KEMS Agile names are retained only as internal evidence engines.

          {% set p = ((state_attr('sensor.kems_energy_cost_comparison', 'periods') or {}).get('today', {}) or {}) %}
          {% set kems = p.get('kems', {}) or {} %}
          **Selected strategy:** {{ state_attr('sensor.kems_energy_cost_comparison', 'selected_kems_strategy_label') or '—' }}  
          **Today's total energy cost:** {{ ('£%.2f' | format((kems.get('total_energy_cost_pence') | float) / 100)) if kems.get('total_energy_cost_pence') is not none else '—' }}  
          **Saving vs Live Data:** {{ ('£%.2f' | format((p.get('saving_pence') | float) / 100)) if p.get('saving_pence') is not none else '—' }}
      - type: grid
        columns: 2
        square: false
        cards:
          - type: tile
            entity: sensor.kems_simulated_house_load_power
            name: KEMS home power
          - type: tile
            entity: sensor.kems_simulated_grid_net_power
            name: KEMS grid power
          - type: tile
            entity: sensor.kems_simulated_battery_state_of_charge
            name: KEMS battery SOC
          - type: tile
            entity: sensor.kems_full_kems_forecast_status
            name: KEMS plan

"""

_COMPARE_VIEW_HEADER = r"""

  - title: Compare
    path: compare
    icon: mdi:compare-horizontal
    cards:
"""

_VIEW_RENAMES = (
    (
        "  - title: Overview\n    path: overview\n",
        "  - title: System Overview\n    path: system-overview\n",
    ),
    (
        "  - title: Live Energy\n    path: live-energy\n",
        "  - title: Live System\n    path: live-system\n",
    ),
    (
        "  - title: Simulation\n    path: simulation\n",
        "  - title: Engineering Simulation\n    path: engineering-simulation\n",
    ),
    (
        "  - title: Forecast\n    path: forecast\n",
        "  - title: KEMS Planning\n    path: kems-planning\n",
    ),
    (
        "  - title: Full KEMS Forecast\n    path: full-kems-forecast\n",
        "  - title: Advanced KEMS Strategy\n    path: advanced-kems-strategy\n",
    ),
    (
        "  - title: Compare\n    path: compare\n    icon: mdi:compare-horizontal\n",
        "  - title: Scenario Evidence\n    path: scenario-evidence\n    icon: mdi:flask-outline\n",
    ),
    (
        "  - title: Battery & Solar\n    path: battery-solar\n",
        "  - title: System Detail\n    path: system-detail\n",
    ),
    (
        "  - title: Forecast vs Agile\n",
        "  - title: Advanced Strategy Validation\n",
    ),
    (
        "  - title: Agile Price Plan\n",
        "  - title: Advanced Price Plan\n",
    ),
    (
        "  - title: Agile History\n",
        "  - title: Advanced Strategy History\n",
    ),
    (
        "  - title: Agile Assumptions\n",
        "  - title: Advanced Assumptions\n",
    ),
    (
        "# Full KEMS Forecast vs Agile Smart Export",
        "# Advanced KEMS strategy validation",
    ),
)


def _replace_markdown_card(
    content: str, title: str, replacement: str
) -> tuple[str, bool]:
    marker = f"      - type: markdown\n        title: {title}\n"
    start = content.find(marker)
    if start < 0:
        return content, False
    end = content.find("\n      - type:", start + len(marker))
    if end < 0:
        end = len(content)
    return content[:start] + replacement.rstrip() + content[end:], True


def improve_energy_bill_dashboard(content: str) -> str:
    """Make Live Data and KEMS the only normal user-facing product choices."""
    content, _ = _replace_markdown_card(
        content,
        "Winner by period — user-facing KEMS products",
        _PERIOD_CARD,
    )
    content, _ = _replace_markdown_card(
        content,
        "Today — cost, energy & savings",
        _TODAY_CARD,
    )

    for old, new in _VIEW_RENAMES:
        content = content.replace(old, new, 1)

    if "\n  - title: Live Data vs KEMS\n" not in content:
        marker = "views:\n"
        if marker not in content:
            raise ValueError("Managed KEMS dashboard has no views section")
        content = content.replace(marker, marker + _PRODUCT_VIEWS, 1)

    if "\n  - title: Compare\n    path: compare\n" not in content:
        compare_view = "".join(
            (_COMPARE_VIEW_HEADER, _PERIOD_CARD, "\n", _TODAY_CARD)
        )
        content = content.rstrip() + compare_view + "\n"
    return content


def install_energy_bill_dashboard_patch() -> None:
    """Apply the bill and Live Data/KEMS presentation before dashboard sync."""
    from . import dashboard

    original = dashboard._dashboard_readability_pass
    if getattr(original, "_kems_alpha813_energy_bill", False):
        return

    def readability_with_energy_bill(content: str) -> str:
        return improve_energy_bill_dashboard(original(content))

    readability_with_energy_bill._kems_alpha813_energy_bill = True
    dashboard._dashboard_readability_pass = readability_with_energy_bill


def _payload(coordinator: Any) -> dict[str, Any] | None:
    data = coordinator.data
    if data is None:
        return None
    lifetime = coordinator._lifetime
    agile = coordinator._agile_smart_export
    return build_energy_cost_comparison(
        data=data,
        agile_state=coordinator.agile_smart_export_state,
        agile_daily=dict(agile._daily),
        daily_records=dict(lifetime._daily_records),
        tracking_date=lifetime._tracking_date,
        tracking_values=dict(lifetime._tracking_values),
        history_records=coordinator._history.records,
        export_tariff_type=export_tariff_type_from_options(coordinator.entry.options),
        now=dt_util.now(),
    )


def async_setup_energy_bill_state(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: Any,
) -> None:
    """Publish one transient canonical financial state after each KEMS refresh."""

    def publish() -> None:
        payload = _payload(coordinator)
        if payload is None:
            return
        state = payload.get("today_kems_total_energy_cost_pence")
        hass.states.async_set(
            ENTITY_ID,
            "unavailable" if state is None else str(state),
            {
                "friendly_name": "KEMS total energy cost comparison",
                "unit_of_measurement": "p",
                **payload,
            },
        )

    remove_listener = coordinator.async_add_listener(publish)
    entry.async_on_unload(remove_listener)
    entry.async_on_unload(lambda: hass.states.async_remove(ENTITY_ID))
    publish()
