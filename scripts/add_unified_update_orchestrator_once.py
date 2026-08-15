"""Apply the coordinated update-orchestrator integration changes once."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected patch anchor not found in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Integration lifecycle and time platform.
patch(
    "custom_components/kems/__init__.py",
    "from .settings import KEMSSettings\n",
    "from .settings import KEMSSettings\nfrom .update_orchestrator import (\n    async_setup_update_orchestrator,\n    async_unload_update_orchestrator,\n)\n",
)
patch(
    "custom_components/kems/__init__.py",
    "    Platform.SELECT,\n    Platform.SWITCH,\n]",
    "    Platform.SELECT,\n    Platform.SWITCH,\n    Platform.TIME,\n]",
)
patch(
    "custom_components/kems/__init__.py",
    "    await coordinator.async_config_entry_first_refresh()\n    entry.runtime_data = coordinator\n    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)\n",
    "    await coordinator.async_config_entry_first_refresh()\n    entry.runtime_data = coordinator\n    await async_setup_update_orchestrator(hass, entry)\n    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)\n",
)
patch(
    "custom_components/kems/__init__.py",
    "    coordinator: KEMSCoordinator = entry.runtime_data\n    await coordinator.async_shutdown()\n",
    "    coordinator: KEMSCoordinator = entry.runtime_data\n    await async_unload_update_orchestrator(hass, entry)\n    await coordinator.async_shutdown()\n",
)

# Proper update sensors.
patch(
    "custom_components/kems/sensor.py",
    "from .kems_core import FOXHOLE_PROPOSAL_PROFILE, KEMSData\n",
    "from .kems_core import FOXHOLE_PROPOSAL_PROFILE, KEMSData\nfrom .update_orchestrator import build_update_sensor_entities\n",
)
patch(
    "custom_components/kems/sensor.py",
    "    entities.extend(build_commissioning_entities(hass, coordinator))\n    entities.append(KEMSSourceValidationSensor(coordinator))\n",
    "    entities.extend(build_commissioning_entities(hass, coordinator))\n    entities.extend(build_update_sensor_entities(hass, coordinator, entry))\n    entities.append(KEMSSourceValidationSensor(coordinator))\n",
)

# Update policy switches.
patch(
    "custom_components/kems/switch.py",
    "from .runtime_options import async_set_runtime_option\n",
    "from .runtime_options import async_set_runtime_option\nfrom .update_orchestrator import build_update_switch_entities\n",
)
patch(
    "custom_components/kems/switch.py",
    "    async_add_entities(\n        (\n            KEMSEmergencyStopSwitch(coordinator),\n            KEMSMasterControlEnableSwitch(coordinator),\n        )\n    )\n",
    "    entities = [\n        KEMSEmergencyStopSwitch(coordinator),\n        KEMSMasterControlEnableSwitch(coordinator),\n    ]\n    entities.extend(build_update_switch_entities(hass, coordinator, entry))\n    async_add_entities(entities)\n",
)

# Update mode selector.
patch(
    "custom_components/kems/select.py",
    "from .runtime_options import async_set_runtime_option\n",
    "from .runtime_options import async_set_runtime_option\nfrom .update_orchestrator import build_update_select_entities\n",
)
patch(
    "custom_components/kems/select.py",
    "    async_add_entities(\n        (\n            KEMSOperatingModeSelect(coordinator),\n            KEMSVirtualScenarioSelect(coordinator),\n        )\n    )\n",
    "    entities = [\n        KEMSOperatingModeSelect(coordinator),\n        KEMSVirtualScenarioSelect(coordinator),\n    ]\n    entities.extend(build_update_select_entities(hass, coordinator, entry))\n    async_add_entities(entities)\n",
)

# Diagnostics include the durable update transaction and maintenance notice.
patch(
    "custom_components/kems/diagnostics.py",
    "from .providers.octopus import DEFAULT_INTELLIGENT_STALE_DATA_SECONDS\n",
    "from .providers.octopus import DEFAULT_INTELLIGENT_STALE_DATA_SECONDS\nfrom .update_orchestrator import update_orchestrator_snapshot\n",
)
patch(
    "custom_components/kems/diagnostics.py",
    '        "panel_health": panel_health_snapshot(hass),\n',
    '        "panel_health": panel_health_snapshot(hass),\n        "updates": update_orchestrator_snapshot(hass, entry),\n',
)

# Add the same read-only/config update view to both managed-dashboard copies.
update_view = r'''  - title: Updates
    path: updates
    icon: mdi:update
    cards:
      - type: markdown
        content: |
          # KEMS coordinated updates
          KEMS now checks one verified release bundle and updates only the components that bundle targets. Home Assistant restarts are held for the maintenance window and announced before they happen.

          **Automatic updates are opt-in.** Turn them on below when you are happy for KEMS to install tested releases unattended.
      - type: grid
        columns: 4
        square: false
        cards:
          - type: tile
            entity: sensor.kems_update_status
          - type: tile
            entity: sensor.kems_maintenance_status
          - type: tile
            entity: switch.kems_automatic_updates
          - type: tile
            entity: switch.kems_automatic_maintenance_restart
      - type: entities
        title: Update policy
        entities:
          - select.kems_update_mode
          - time.kems_maintenance_window_start
          - time.kems_maintenance_window_end
          - switch.kems_backup_before_update
          - switch.kems_automatic_updates
          - switch.kems_automatic_maintenance_restart
      - type: markdown
        title: Current bundle and maintenance
        content: |
          {% set update = states.sensor.kems_update_status %}
          {% set maintenance = states.sensor.kems_maintenance_status %}
          **Overall:** {{ update.state | default('Unavailable') }}  
          **Bundle:** {{ update.attributes.bundle | default('No coordinated bundle published yet', true) }}  
          **Running KEMS:** {{ update.attributes.running_kems_version | default('Unknown', true) }}  
          **Last checked:** {{ update.attributes.last_checked | default('Not checked yet', true) }}  
          **Maintenance:** {{ maintenance.state | default('none') }}  
          **Scheduled:** {{ maintenance.attributes.scheduled_for | default('Not scheduled', true) }}  
          **Reason:** {{ maintenance.attributes.reason | default('No maintenance required', true) }}
      - type: markdown
        title: Component verification
        content: |
          {% set items = state_attr('sensor.kems_update_status', 'components') or [] %}
          | Component | Target | Installed | Status |
          |---|---|---|---|
          {% for item in items %}
          | {{ item.key }} | {{ item.target or '—' }} | {{ item.installed or '—' }} | **{{ item.status }}** |
          {% endfor %}
      - type: markdown
        title: Recent update history
        content: |
          {% set items = state_attr('sensor.kems_update_status', 'history') or [] %}
          {% if items %}
          | Completed | Bundle | Result |
          |---|---|---|
          {% for item in items | reverse %}
          | {{ item.completed_at | default('—') }} | {{ item.bundle | default('—') }} | **{{ item.result | default('—') }}** |
          {% endfor %}
          {% else %}
          No coordinated update has completed yet.
          {% endif %}

'''
for dashboard in (
    "custom_components/kems/kems_master_dashboard.yaml",
    "dashboards/kems_master_dashboard.yaml",
):
    file = ROOT / dashboard
    text = file.read_text(encoding="utf-8")
    anchor = "  - title: All Entities\n"
    if anchor not in text:
        raise SystemExit(f"All Entities anchor not found in {dashboard}")
    file.write_text(text.replace(anchor, update_view + anchor, 1), encoding="utf-8")

# Keep the one-shot implementation helper out of the finished branch.
for transient in (
    ROOT / "scripts/add_unified_update_orchestrator_once.py",
    ROOT / ".github/workflows/add-unified-update-orchestrator-once.yml",
):
    transient.unlink(missing_ok=True)
