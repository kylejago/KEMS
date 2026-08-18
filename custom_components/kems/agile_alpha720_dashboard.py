"""Alpha 7.20 dashboard cards for pre-install evidence and shadow readiness."""

# ruff: noqa: E501

from __future__ import annotations

from . import dashboard as dashboard_module

_HISTORY_CARD = r"""      - type: entities
        title: Pre-install historical evidence
        show_header_toggle: false
        entities:
          - entity: sensor.kems_preinstall_historical_evidence
            name: Proposal reconstruction
          - entity: sensor.kems_agile_history_backfill
            name: Total replay coverage
          - entity: sensor.kems_agile_backfill_source_map
            name: Replay source readiness
      - type: markdown
        title: Historical proposal-solar reconstruction
        content: |
          {% set e = states.sensor.kems_preinstall_historical_evidence %}
          {% set b = states.sensor.kems_agile_history_backfill %}
          **Status:** **{{ e.state if e else 'Unavailable' }}**  
          **Method:** {{ e.attributes.method if e else '—' }}  
          **Measured input:** {{ e.attributes.house_entity if e else '—' }}  
          **PV source:** {{ e.attributes.source if e else '—' }}  
          **Proposal:** {{ e.attributes.proposal_profile if e else '—' }}  
          **Reconstructed days:** {{ e.attributes.reconstructed_days if e else 0 }}  
          **Total replay coverage:** {{ b.state if b else '—' }}

          This is **hypothetical pre-install evidence**. Home Assistant's retained whole-house demand is measured history; PV generation is reconstructed from historical tilted irradiance applied to the accepted proposal arrays. It is never labelled as actual solar production or as the forecast KEMS would have had on that historical day.
"""

_CONTROL_CARD = r"""      - type: entities
        title: Shadow readiness — digital twin vs hardware
        show_header_toggle: false
        entities:
          - entity: sensor.kems_shadow_control_readiness
            name: Digital-twin shadow readiness
          - entity: sensor.kems_commissioning_readiness
            name: Hardware shadow readiness
          - entity: sensor.kems_shadow_command_safety
            name: Independent command-envelope safety
          - entity: binary_sensor.kems_real_control_backend_available
            name: Real control backend available
          - entity: binary_sensor.kems_control_commands_permitted
            name: Real commands permitted
      - type: markdown
        title: Commissioning stage split
        content: |
          {% set d = states.sensor.kems_shadow_control_readiness %}
          {% set h = states.sensor.kems_commissioning_readiness %}
          **Digital twin:** **{{ d.state if d else 'Unavailable' }}**  
          **Hardware:** **{{ h.state if h else 'Unavailable' }}**  
          **Maximum allowed hardware stage:** {{ h.attributes.maximum_allowed_stage if h else '—' }}  
          **Real hardware writes:** {{ h.attributes.real_hardware_writes if h else 'blocked' }}

          **Digital-twin shadow** means KEMS is validating the commands it *would* issue against the simulated system. **Hardware shadow** remains unavailable until the FoxESS mappings, power directions and commissioning checks are verified. Neither stage sends inverter writes in alpha7.20.
"""


def _inject_after_cards(content: str, path: str, cards: str) -> str:
    """Insert cards at the top of one final consolidated view."""
    marker = f"    path: {path}\n"
    start = content.find(marker)
    if start < 0:
        return content
    cards_marker = "    cards:\n"
    cards_at = content.find(cards_marker, start)
    if cards_at < 0:
        return content
    insert_at = cards_at + len(cards_marker)
    if cards.strip() in content[start : start + len(cards) + 1200]:
        return content
    return content[:insert_at] + cards.rstrip() + "\n" + content[insert_at:]


def install_alpha720_dashboard_patch() -> None:
    """Add pre-install evidence and split shadow-readiness presentation."""
    original = dashboard_module._combined_master_dashboard_bytes
    if getattr(original, "_kems_alpha720_dashboard", False):
        return

    def combined_dashboard_with_alpha720() -> bytes:
        content = original().decode("utf-8")
        content = content.replace(
            "            name: Ready for shadow\n",
            "            name: Digital-twin shadow readiness\n",
        )
        content = _inject_after_cards(content, "history", _HISTORY_CARD)
        content = _inject_after_cards(content, "control", _CONTROL_CARD)
        return content.encode("utf-8")

    combined_dashboard_with_alpha720._kems_alpha720_dashboard = True
    dashboard_module._combined_master_dashboard_bytes = combined_dashboard_with_alpha720
