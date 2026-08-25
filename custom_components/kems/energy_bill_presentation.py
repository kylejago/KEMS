"""Home Assistant publication and dashboard presentation for Alpha8.14 bills."""

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

_OVERVIEW_CARD = r"""      - type: markdown
        title: Live Data vs KEMS
        content: |
          {% set p = ((state_attr('sensor.kems_energy_cost_comparison', 'periods') or {}).get('today', {}) or {}) %}
          {% set live = p.get('live_data', {}) or {} %}
          {% set kems = p.get('kems', {}) or {} %}
          # ⚡ KEMS
          KEMS has two user-facing views: **Live Data** shows what the property actually did; **KEMS** shows what KEMS would have done using the strategy selected for the configured tariff and system.

          | Today | Live Data | KEMS |
          |---|---:|---:|
          | Total energy cost | **{{ ('£%.2f' | format((live.get('total_energy_cost_pence') | float) / 100)) if live.get('total_energy_cost_pence') is not none else '—' }}** | **{{ ('£%.2f' | format((kems.get('total_energy_cost_pence') | float) / 100)) if kems.get('total_energy_cost_pence') is not none else '—' }}** |
          | Electricity | {{ ('£%.2f' | format((live.get('electricity_total_cost_pence') | float) / 100)) if live.get('electricity_total_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('electricity_total_cost_pence') | float) / 100)) if kems.get('electricity_total_cost_pence') is not none else '—' }} |
          | Gas | {{ ('£%.2f' | format((live.get('gas_total_cost_pence') | float) / 100)) if live.get('gas_total_cost_pence') is not none else '—' }} | {{ ('£%.2f' | format((kems.get('gas_total_cost_pence') | float) / 100)) if kems.get('gas_total_cost_pence') is not none else '—' }} |

          **Saving today:** {{ ('£%.2f' | format((p.get('saving_pence') | float) / 100)) if p.get('saving_pence') is not none else '—' }}  
          **KEMS strategy:** {{ state_attr('sensor.kems_energy_cost_comparison', 'selected_kems_strategy_label') or '—' }}
"""

_ENERGY_VIEW = (
    r"""

  - title: Energy Cost
    path: energy-cost
    icon: mdi:home-currency-gbp
    cards:
"""
    + _PERIOD_CARD.replace("      - type:", "      - type:", 1)
    + "\n"
    + _TODAY_CARD.replace("      - type:", "      - type:", 1)
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


def _remove_view(content: str, title: str) -> str:
    """Remove one legacy engineering view from the managed user dashboard."""
    marker = f"\n  - title: {title}\n"
    start = content.find(marker)
    if start < 0 and content.startswith(f"  - title: {title}\n"):
        start = 0
    if start < 0:
        return content
    search_from = start + len(marker)
    end = content.find("\n  - title:", search_from)
    if end < 0:
        end = len(content)
    return content[:start] + content[end:]


def _align_live_kems_navigation(content: str) -> str:
    """Make Live Data and KEMS the only product choices in the managed dashboard."""
    content = content.replace(
        "  - title: Live Energy\n    path: live-energy\n",
        "  - title: Live Data\n    path: live-data\n",
    ).replace(
        "          # Live / observed home\n",
        "          # Live Data\n",
    ).replace(
        "  - title: Simulation\n    path: simulation\n",
        "  - title: KEMS\n    path: kems\n",
    ).replace(
        "        title: Simulated power — 24 hours\n",
        "        title: KEMS power — 24 hours\n",
    ).replace(
        "            name: Sim battery SOC\n",
        "            name: KEMS battery SOC\n",
    ).replace(
        "            name: Observed electricity\n",
        "            name: Live Data electricity\n",
    ).replace(
        "            name: Simulated KEMS\n",
        "            name: KEMS electricity\n",
    ).replace(
        "            name: Simulated saving\n",
        "            name: KEMS saving\n",
    )

    # These engines remain in code and standalone evidence dashboards, but are no
    # longer customer-facing product tabs in the managed master dashboard.
    for legacy_title in (
        "Full KEMS Forecast",
        "Forecast vs Agile",
        "Advanced strategy validation",
        "Agile Price Plan",
        "Agile History",
        "Agile Assumptions",
        "Battery & Solar",
    ):
        content = _remove_view(content, legacy_title)
    return content


def improve_energy_bill_dashboard(content: str) -> str:
    """Present one canonical Live Data vs KEMS product model in Home Assistant."""
    content = _align_live_kems_navigation(content)
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

    # Put the canonical bill-equivalent comparison at the top of Overview without
    # removing operational status/advice cards that remain useful underneath it.
    overview_cards = "  - title: Overview\n    path: overview\n    icon: mdi:home-lightning-bolt\n    cards:\n"
    if overview_cards in content and "        title: Live Data vs KEMS\n" not in content:
        content = content.replace(
            overview_cards,
            overview_cards + _OVERVIEW_CARD,
            1,
        )

    if "\n  - title: Energy Cost\n" not in content and "\nviews:\n" in content:
        content = content.rstrip() + _ENERGY_VIEW + "\n"
    return content


def install_energy_bill_dashboard_patch() -> None:
    """Apply Alpha8.14 dashboard presentation and post-restart verification repair."""
    from . import dashboard
    from . import update_orchestrator_reliable as reliable

    original = dashboard._dashboard_readability_pass
    if not getattr(original, "_kems_alpha814_energy_bill", False):

        def readability_with_energy_bill(content: str) -> str:
            return improve_energy_bill_dashboard(original(content))

        readability_with_energy_bill._kems_alpha814_energy_bill = True
        dashboard._dashboard_readability_pass = readability_with_energy_bill

    original_verify = reliable.ReliableKEMSUpdateOrchestrator.async_verify_pending
    if not getattr(original_verify, "_kems_alpha814_dashboard_resync", False):

        async def verify_with_dashboard_resync(self: Any, *, save: bool = True) -> None:
            # A HACS update can restart into the new core while /config still holds
            # an absent or stale managed dashboard. Once the verified release bundle
            # is back, repair the dashboard first, then run the existing exact-byte
            # component verification. This makes the transaction converge instead
            # of remaining indefinitely at dashboard=waiting / stage=verifying.
            if self.pending and self.latest_bundle is not None:
                await reliable._async_sync_update_dashboard(self.hass)
            await original_verify(self, save=save)

        verify_with_dashboard_resync._kems_alpha814_dashboard_resync = True
        reliable.ReliableKEMSUpdateOrchestrator.async_verify_pending = (
            verify_with_dashboard_resync
        )


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
