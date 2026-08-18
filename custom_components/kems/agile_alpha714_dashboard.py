"""Alpha 7.14 Agile deadline, hardware-SOC and backfill dashboard refinements."""

from __future__ import annotations

from typing import Any

from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from . import dashboard as dashboard_module

_HARDWARE_SOC_SENSOR = "sensor.kems_agile_live_hardware_battery_soc"

_DEADLINE_CARD = r"""
      - type: entities
        title: 10% battery target — cheap-window deadline
        show_header_toggle: false
        entities:
          - entity: sensor.kems_agile_deadline_status
            name: Deadline status
          - entity: sensor.kems_agile_deadline_target_soc
            name: Target SOC at cheap-window start
          - entity: sensor.kems_agile_simulated_battery_soc_now
            name: Agile simulated SOC now
          - entity: sensor.kems_agile_deadline_required_average_kw
            name: Required average battery discharge
          - entity: sensor.kems_agile_deadline_effective_discharge_kw
            name: Effective inverter/export discharge limit
          - entity: sensor.kems_agile_deadline_required_discharge_kwh
            name: Energy still needing discharge
          - entity: sensor.kems_agile_deadline_remaining_capacity_kwh
            name: Maximum discharge capacity remaining
          - entity: sensor.kems_agile_deadline_margin_kwh
            name: Deadline energy margin
          - entity: sensor.kems_agile_deadline_minimum_reachable_soc
            name: Minimum physically reachable SOC
"""

_BACKFILL_DIAGNOSTICS_CARD = r"""
      - type: markdown
        title: Historical backfill diagnostics
        content: |
          {% set b = states.sensor.kems_agile_history_backfill %}
          **Settled historical coverage:** {{ b.state if b else 'Unavailable' }}  
          **Backfill method:** {{ b.attributes.backfill_method if b else '—' }}  
          **Native settled KEMS days:** {{ b.attributes.native_kems_days if b else '—' }}  
          **HA statistics backfilled days:** {{ b.attributes.ha_statistics_backfilled_days if b else '—' }}  
          **Insufficient historical days:** {{ b.attributes.insufficient_days if b else '—' }}  
          **Resolution:** {{ b.attributes.backfill_resolution if b else '—' }}  
          **Reason:** {{ b.attributes.energy_fallback_reason or b.attributes.reason if b else '—' }}

          **Configured live-source long-term statistics**

          {% set direct = b.attributes.direct_source_diagnostics if b else {} %}
          | Source | Entity | Long-term stats | Rows | Oldest |
          |---|---|:---:|---:|---|
          {% for key, item in direct.items() if item is mapping %}
          | {{ key }} | `{{ item.get('entity_id', '—') }}` | {{ '✅' if item.get('long_term_statistics') else '❌' }} | {{ item.get('historical_rows', 0) }} | {{ item.get('oldest') or '—' }} |
          {% endfor %}

          **Home Assistant Energy-dashboard fallback**

          {% set energy = b.attributes.energy_source_diagnostics if b else {} %}
          {% if energy %}
          | Statistic | Type | Rows | Oldest |
          |---|---|---:|---|
          {% for entity, item in energy.items() %}
          | `{{ entity }}` | {{ item.get('kind', '—') }} | {{ item.get('historical_rows', 0) }} | {{ item.get('oldest') or '—' }} |
          {% endfor %}
          {% else %}
          No usable Energy-dashboard historical counters have been recovered yet.
          {% endif %}

          **Coverage wording:** the main replay counter can include **today's live replay**. The backfill counter above deliberately counts only **settled historical days before today**, so the two totals may differ by one while today is in progress.
"""


def _number(value: Any) -> float | None:
    """Return one finite-enough numeric state value when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hardware_soc(self) -> tuple[float | None, str | None]:
    """Prefer KEMS hardware SOC, then the Energy dashboard battery-SOC source."""
    direct = self._hass.states.get("sensor.kems_battery_state_of_charge")
    value = _number(direct.state) if direct is not None else None
    if value is not None:
        source = (
            direct.attributes.get("source_entity")
            or direct.attributes.get("source")
            or direct.entity_id
        )
        return value, str(source)

    backfill = self._hass.states.get("sensor.kems_agile_history_backfill")
    sources = (
        backfill.attributes.get("energy_fallback_sources", {})
        if backfill is not None
        else {}
    )
    candidates = sources.get("battery_soc", []) if isinstance(sources, dict) else []
    for entity_id in candidates if isinstance(candidates, list) else []:
        state = self._hass.states.get(str(entity_id))
        value = _number(state.state) if state is not None else None
        if value is not None:
            return value, str(entity_id)
    return None, None


def _patch_live_view(content: str) -> str:
    """Add deadline visibility and hardware-SOC fallback only to the Agile live view."""
    marker = "  - title: Agile Smart Export\n    path: agile-smart-export\n"
    start = content.find(marker)
    if start < 0:
        return content
    head = content[:start]
    live = content[start:]
    live = live.replace(
        "sensor.kems_battery_state_of_charge",
        _HARDWARE_SOC_SENSOR,
    )
    anchor = "      - type: history-graph\n        title: Agile scenario economics — 24 hours\n"
    if "title: 10% battery target — cheap-window deadline" not in live and anchor in live:
        live = live.replace(anchor, _DEADLINE_CARD + "\n" + anchor, 1)
    return head + live


def _patch_history_view(content: str) -> str:
    """Clarify live-vs-settled coverage and expose source diagnostics."""
    content = content.replace(
        "            name: Historical replay coverage\n",
        "            name: Replay coverage including today\n",
        2,
    )
    anchor = "      - type: history-graph\n        title: Cumulative Agile advantage\n"
    if "title: Historical backfill diagnostics" not in content and anchor in content:
        content = content.replace(
            anchor,
            _BACKFILL_DIAGNOSTICS_CARD + "\n" + anchor,
            1,
        )
    return content


def install_alpha714_dashboard_patch() -> None:
    """Install alpha7.14 publish and dashboard refinements exactly once."""
    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_alpha714_dashboard", False):
        original_publish = publish

        def publish_with_alpha714(self, state: dict[str, Any]) -> None:
            original_publish(self, state)
            value, source = _hardware_soc(self)
            self._set(
                _HARDWARE_SOC_SENSOR,
                agile._state(value),
                {
                    "friendly_name": "Live hardware battery SOC",
                    "unit_of_measurement": "%",
                    "available": value is not None,
                    "source_entity": source,
                    "meaning": "actual Home Assistant battery SOC, never simulated",
                },
            )

        publish_with_alpha714._kems_alpha714_dashboard = True
        runtime.EfficientAgileSmartExportManager._publish = publish_with_alpha714

    original_dashboard = dashboard_module._combined_master_dashboard_bytes
    if getattr(original_dashboard, "_kems_alpha714_dashboard", False):
        return

    def combined_dashboard_with_alpha714() -> bytes:
        content = original_dashboard().decode("utf-8")
        content = _patch_live_view(content)
        content = _patch_history_view(content)
        return content.encode("utf-8")

    combined_dashboard_with_alpha714._kems_alpha714_dashboard = True
    dashboard_module._combined_master_dashboard_bytes = combined_dashboard_with_alpha714
