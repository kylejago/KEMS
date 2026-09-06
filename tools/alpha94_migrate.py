from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: Path, old: str, new: str, minimum: int = 1) -> int:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count < minimum:
        raise SystemExit(f"{path}: expected at least {minimum} matches, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    return count


simulation = ROOT / "custom_components/kems/kems_core/simulation.py"
scenario = ROOT / "custom_components/kems/kems_core/scenario_comparison.py"
adapter = ROOT / "custom_components/kems/foxess_command_shadow.py"
manifest = ROOT / "custom_components/kems/manifest.json"
bundle = ROOT / "release/kems-bundle.template.json"
alpha9 = ROOT / "docs/ALPHA9.md"

replace_once(
    simulation,
    '''def _load_kw(snapshot: Snapshot) -> float | None:\n    """Return the best available house-load observation."""\n    if snapshot.house_load_kw is not None:\n        return max(snapshot.house_load_kw, 0.0)\n    if snapshot.grid_import_kw is not None:\n        return max(snapshot.grid_import_kw, 0.0)\n    return None\n''',
    '''def _fresh_snapshot_value(snapshot: Snapshot, field: str) -> float | None:\n    """Return one numeric observation only when that source is not stale."""\n    if field in snapshot.stale_fields:\n        return None\n    value = getattr(snapshot, field, None)\n    if value is None:\n        return None\n    return float(value)\n\n\ndef _load_kw(snapshot: Snapshot) -> float | None:\n    """Return fresh house demand without depending on optional physical telemetry."""\n    house = _fresh_snapshot_value(snapshot, "house_load_kw")\n    if house is not None:\n        return max(house, 0.0)\n    grid_import = _fresh_snapshot_value(snapshot, "grid_import_kw")\n    if grid_import is not None:\n        return max(grid_import, 0.0)\n    return None\n''',
)
replace_once(
    simulation,
    "            initial_soc = today[0].battery_soc\n",
    '            initial_soc = _fresh_snapshot_value(today[0], "battery_soc")\n',
)
replace_once(
    simulation,
    '''            # Do not integrate a frozen live reading across the next history\n            # interval. Requiring both ends to be usable deliberately leaves a\n            # small gap rather than inventing energy from a stale power value.\n            if current.stale_fields or following.stale_fields:\n                continue\n            if _load_kw(following) is None:\n                continue\n\n            rate = current.current_import_rate\n            load_kw = _load_kw(current)\n            if rate is None or load_kw is None:\n                continue\n''',
    '''            # Simulation has its own evidence boundary. Optional physical\n            # FoxESS telemetry may be stale/offline before commissioning without\n            # invalidating fresh house-demand and tariff observations.\n            if _load_kw(following) is None:\n                continue\n\n            rate = current.current_import_rate\n            load_kw = _load_kw(current)\n            if (\n                rate is None\n                or "current_import_rate" in current.tariff_stale_fields\n                or load_kw is None\n            ):\n                continue\n''',
)
replace_once(
    simulation,
    '''            solar_kw = self._simulated_solar_power(current, config)\n            actual_import_kw = (\n                max(current.grid_import_kw, 0.0)\n                if current.grid_import_kw is not None\n                else max(load_kw - max(current.solar_power_kw or 0.0, 0.0), 0.0)\n            )\n            actual_export_kw = max(current.grid_export_kw or 0.0, 0.0)\n\n            actual_house_kwh = load_kw * hours\n            actual_import_kwh = actual_import_kw * hours\n            actual_export_kwh = actual_export_kw * hours\n            actual_house += actual_house_kwh\n            actual_ev += max(current.ev_power_kw or 0.0, 0.0) * hours\n            actual_solar += max(current.solar_power_kw or 0.0, 0.0) * hours\n            battery_power_kw = current.battery_power_kw or 0.0\n''',
    '''            solar_kw = self._simulated_solar_power(current, config)\n            observed_solar_kw = _fresh_snapshot_value(current, "solar_power_kw")\n            observed_grid_import_kw = _fresh_snapshot_value(current, "grid_import_kw")\n            observed_grid_export_kw = _fresh_snapshot_value(current, "grid_export_kw")\n            actual_import_kw = (\n                max(observed_grid_import_kw, 0.0)\n                if observed_grid_import_kw is not None\n                else max(load_kw - max(observed_solar_kw or 0.0, 0.0), 0.0)\n            )\n            actual_export_kw = max(observed_grid_export_kw or 0.0, 0.0)\n\n            actual_house_kwh = load_kw * hours\n            actual_import_kwh = actual_import_kw * hours\n            actual_export_kwh = actual_export_kw * hours\n            actual_house += actual_house_kwh\n            actual_ev += max(current.ev_power_kw or 0.0, 0.0) * hours\n            actual_solar += max(observed_solar_kw or 0.0, 0.0) * hours\n            battery_power_kw = (\n                _fresh_snapshot_value(current, "battery_power_kw") or 0.0\n            )\n''',
)
replace_once(
    simulation,
    '''        if snapshot.solar_power_kw is not None:\n            return min(\n                max(snapshot.solar_power_kw, 0.0),\n                max(config.inverter_limit_kw, 0.0),\n            )\n''',
    '''        observed_solar_kw = _fresh_snapshot_value(snapshot, "solar_power_kw")\n        if observed_solar_kw is not None:\n            return min(\n                max(observed_solar_kw, 0.0),\n                max(config.inverter_limit_kw, 0.0),\n            )\n''',
)
replace_all(
    simulation,
    "            proposal_solar_active=config.proposal_solar_enabled\n            and all(item.solar_power_kw is None for item in today),\n",
    '            proposal_solar_active=config.proposal_solar_enabled\n            and all(\n                _fresh_snapshot_value(item, "solar_power_kw") is None for item in today\n            ),\n',
)
replace_once(
    simulation,
    "            proposal_solar_active=config.proposal_solar_enabled\n            and snapshot.solar_power_kw is None,\n",
    '            proposal_solar_active=config.proposal_solar_enabled\n            and _fresh_snapshot_value(snapshot, "solar_power_kw") is None,\n',
)

# The scenario engine must use the same simulation-only evidence boundary.
replace_all(
    scenario,
    "            if current.stale_fields or following.stale_fields:\n                continue\n",
    "",
    minimum=2,
)
replace_once(
    scenario,
    "        if snapshot is None or snapshot.stale_fields:\n",
    "        if snapshot is None:\n",
)
replace_all(
    scenario,
    '''            rate = current.current_import_rate\n            if rate is None:\n                continue\n''',
    '''            rate = current.current_import_rate\n            if rate is None or "current_import_rate" in current.tariff_stale_fields:\n                continue\n''',
    minimum=1,
)

# Domain-scope writable command discovery and keep sensor counterparts as readback.
replace_once(
    adapter,
    '''FOXESS_PLATFORM = "foxess_modbus"\nCOMMAND_KEYS = (\n    "work_mode",\n    "force_charge_power",\n    "force_discharge_power",\n    "min_soc_on_grid",\n    "export_power_limit",\n)\nUNKNOWN_STATES = {"unknown", "unavailable"}\n\n\ndef _entry_command_key(entry: object) -> str | None:\n    """Return the reviewed FoxESS entity-description key from a registry entry."""\n    if str(getattr(entry, "platform", "")).casefold() != FOXESS_PLATFORM:\n        return None\n    unique_id = str(getattr(entry, "unique_id", ""))\n    for key in COMMAND_KEYS:\n        if unique_id == f"foxess_modbus_{key}" or unique_id.endswith(f"_{key}"):\n            return key\n    return None\n''',
    '''FOXESS_PLATFORM = "foxess_modbus"\nCOMMAND_KEYS = (\n    "work_mode",\n    "force_charge_power",\n    "force_discharge_power",\n    "min_soc_on_grid",\n    "export_power_limit",\n)\nCOMMAND_DOMAINS = {\n    "work_mode": "select",\n    "force_charge_power": "number",\n    "force_discharge_power": "number",\n    "min_soc_on_grid": "number",\n    "export_power_limit": "number",\n}\nUNKNOWN_STATES = {"unknown", "unavailable"}\n\n\ndef _entry_reviewed_key(entry: object) -> str | None:\n    """Return the reviewed FoxESS key independent of HA entity domain."""\n    if str(getattr(entry, "platform", "")).casefold() != FOXESS_PLATFORM:\n        return None\n    unique_id = str(getattr(entry, "unique_id", ""))\n    for key in COMMAND_KEYS:\n        if unique_id == f"foxess_modbus_{key}" or unique_id.endswith(f"_{key}"):\n            return key\n    return None\n\n\ndef _entry_command_key(entry: object) -> str | None:\n    """Return a reviewed key only for its writable select/number domain."""\n    key = _entry_reviewed_key(entry)\n    if key is None:\n        return None\n    domain = str(getattr(entry, "entity_id", "")).partition(".")[0].casefold()\n    return key if domain == COMMAND_DOMAINS[key] else None\n\n\ndef _entry_readback_key(entry: object) -> str | None:\n    """Return a reviewed key for a matching read-only sensor counterpart."""\n    key = _entry_reviewed_key(entry)\n    if key is None:\n        return None\n    domain = str(getattr(entry, "entity_id", "")).partition(".")[0].casefold()\n    return key if domain == "sensor" else None\n''',
)
replace_once(
    adapter,
    '''def _command_candidates(\n    entries: Iterable[object],\n    device_id: str,\n) -> dict[str, tuple[object, ...]]:\n    """Return reviewed command entities belonging to exactly one FoxESS device."""\n    grouped: dict[str, list[object]] = {key: [] for key in COMMAND_KEYS}\n    for entry in entries:\n        if str(getattr(entry, "device_id", "")) != device_id:\n            continue\n        key = _entry_command_key(entry)\n        if key is not None:\n            grouped[key].append(entry)\n    return {\n        key: tuple(sorted(values, key=lambda item: str(getattr(item, "entity_id", ""))))\n        for key, values in grouped.items()\n    }\n''',
    '''def _keyed_candidates(\n    entries: Iterable[object],\n    device_id: str,\n    classifier,\n) -> dict[str, tuple[object, ...]]:\n    """Return reviewed entities grouped by key on one FoxESS device."""\n    grouped: dict[str, list[object]] = {key: [] for key in COMMAND_KEYS}\n    for entry in entries:\n        if str(getattr(entry, "device_id", "")) != device_id:\n            continue\n        key = classifier(entry)\n        if key is not None:\n            grouped[key].append(entry)\n    return {\n        key: tuple(sorted(values, key=lambda item: str(getattr(item, "entity_id", ""))))\n        for key, values in grouped.items()\n    }\n\n\ndef _command_candidates(\n    entries: Iterable[object],\n    device_id: str,\n) -> dict[str, tuple[object, ...]]:\n    """Return only writable reviewed command entities on one FoxESS device."""\n    return _keyed_candidates(entries, device_id, _entry_command_key)\n\n\ndef _readback_candidates(\n    entries: Iterable[object],\n    device_id: str,\n) -> dict[str, tuple[object, ...]]:\n    """Return matching read-only sensor evidence on one FoxESS device."""\n    return _keyed_candidates(entries, device_id, _entry_readback_key)\n''',
)
replace_once(
    adapter,
    '''        candidates = _command_candidates(registry.entities.values(), selected_device)\n    elif not telemetry_devices:\n''',
    '''        candidates = _command_candidates(registry.entities.values(), selected_device)\n        readbacks = _readback_candidates(registry.entities.values(), selected_device)\n    elif not telemetry_devices:\n''',
)
replace_once(
    adapter,
    '''        candidates = {key: () for key in COMMAND_KEYS}\n    else:\n''',
    '''        candidates = {key: () for key in COMMAND_KEYS}\n        readbacks = {key: () for key in COMMAND_KEYS}\n    else:\n''',
)
replace_once(
    adapter,
    '''        candidates = {key: () for key in COMMAND_KEYS}\n\n    observed: dict[str, object] = {}\n''',
    '''        candidates = {key: () for key in COMMAND_KEYS}\n        readbacks = {key: () for key in COMMAND_KEYS}\n\n    observed: dict[str, object] = {}\n''',
)
replace_once(
    adapter,
    '''    for key in COMMAND_KEYS:\n        matches = candidates[key]\n        if len(matches) != 1:\n''',
    '''    for key in COMMAND_KEYS:\n        matches = candidates[key]\n        readback_matches = readbacks[key]\n        if len(matches) != 1:\n''',
)
replace_once(
    adapter,
    '''        entry = matches[0]\n        entity_id = str(entry.entity_id)\n        raw_value, unit = _state_value(hass, entity_id)\n        available = raw_value is not None\n''',
    '''        entry = matches[0]\n        entity_id = str(entry.entity_id)\n        readback_entry = readback_matches[0] if len(readback_matches) == 1 else None\n        observation_entry = readback_entry or entry\n        observation_entity_id = str(observation_entry.entity_id)\n        raw_value, unit = _state_value(hass, observation_entity_id)\n        available = raw_value is not None\n''',
)
replace_once(
    adapter,
    '''            "entity_id": entity_id,\n            "unique_id": str(getattr(entry, "unique_id", "")),\n            "device_id": str(getattr(entry, "device_id", "")),\n            "raw_state": raw_value,\n            "unit": unit,\n            "normalised_observation": value,\n            "reason": (\n                "Read-only FoxESS command entity observed"\n                if available and value is not None\n                else "FoxESS command entity exists but has no usable read-only state"\n            ),\n''',
    '''            "entity_id": entity_id,\n            "unique_id": str(getattr(entry, "unique_id", "")),\n            "device_id": str(getattr(entry, "device_id", "")),\n            "readback_entity_id": (\n                str(readback_entry.entity_id) if readback_entry is not None else None\n            ),\n            "candidate_readback_entity_ids": [\n                str(getattr(item, "entity_id", "")) for item in readback_matches\n            ],\n            "observation_entity_id": observation_entity_id,\n            "observation_source": (\n                "sensor_readback" if readback_entry is not None else "command_entity"\n            ),\n            "raw_state": raw_value,\n            "unit": unit,\n            "normalised_observation": value,\n            "reason": (\n                "Read-only FoxESS sensor readback observed"\n                if available and value is not None and readback_entry is not None\n                else (\n                    "Read-only FoxESS command entity observed"\n                    if available and value is not None\n                    else "FoxESS command/readback entity has no usable read-only state"\n                )\n            ),\n''',
)

# Release identity: KEMS only. Other tracks remain unchanged.
manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
if manifest_data.get("version") != "0.9.0-alpha9.3":
    raise SystemExit(f"Unexpected manifest version: {manifest_data.get('version')}")
manifest_data["version"] = "0.9.0-alpha9.4"
manifest.write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8")

bundle_data = json.loads(bundle.read_text(encoding="utf-8"))
bundle_data["maintenance"]["reason"] = (
    "Alpha9 coordinated parity baseline; Alpha9.4 KEMS-only simulation/commissioning "
    "separation: keep virtual/current-day simulations driven by fresh house/tariff "
    "evidence plus proposal/forecast solar when uncommissioned FoxESS telemetry is "
    "offline, and domain-scope FoxESS command binding to writable select/number "
    "entities with sensor counterparts retained as read-only evidence; no Happy Hour, "
    "optimiser, FoxESS write, Pi Web, Public Web or Panel behaviour changes; Pi Web "
    "remains 0.9.0-alpha9-web.0, Public Web remains 0.9.0-alpha9-public.0, Panel "
    "remains 0.9.0-alpha9-panel.0; canonical 15% optimisation target / 10% hard floor "
    "/ 12% recovery remains unchanged; FoxESS hardware writes hard-blocked until "
    "physical commissioning is complete"
)
bundle.write_text(json.dumps(bundle_data, indent=2) + "\n", encoding="utf-8")

for test_path in (
    ROOT / "tests/test_alpha9_baseline.py",
    ROOT / "tests/test_alpha8_consolidation.py",
):
    replace_once(test_path, '"0.9.0-alpha9.3"', '"0.9.0-alpha9.4"')

alpha9_text = alpha9.read_text(encoding="utf-8")
section = '''\n\n## Alpha9.4 simulation / commissioning separation\n\n- KEMS: `0.9.0-alpha9.4`\n- Pi Web remains: `0.9.0-alpha9-web.0`\n- Public Web remains: `0.9.0-alpha9-public.0`\n- Panel remains: `0.9.0-alpha9-panel.0`\n\nAlpha9.4 restores the intended separation between virtual simulation and physical FoxESS commissioning. Current-day and scenario replay now require fresh house-demand and tariff evidence, but stale or unavailable uncommissioned FoxESS SOC, battery-power, PV or grid-export telemetry no longer invalidates those virtual calculations. When live PV is unavailable or stale, proposal/forecast solar remains the simulation authority; stale optional physical values are not silently reused as observations.\n\nPhysical FoxESS telemetry remains independently fail-closed for commissioning, hardware shadow and control. Alpha9.4 also distinguishes the writable command surface from readback evidence by entity domain: Work Mode binds through `select.*`, numeric commands bind through `number.*`, and matching `sensor.*` entities are retained as read-only observation evidence rather than treated as competing commands. **FoxESS writes remain hard-blocked.**\n'''
if "## Alpha9.4 simulation / commissioning separation" in alpha9_text:
    raise SystemExit("Alpha9.4 docs section already exists")
alpha9.write_text(alpha9_text.rstrip() + section + "\n", encoding="utf-8")

new_test = ROOT / "tests/test_alpha94_simulation_commissioning_separation.py"
if new_test.exists():
    raise SystemExit(f"Unexpected existing file: {new_test}")
new_test.write_text(
    '''"""Alpha9.4 simulation/physical-commissioning separation contracts."""\n\nfrom __future__ import annotations\n\nfrom datetime import UTC, datetime, timedelta\nfrom pathlib import Path\n\nfrom kems_core import ScenarioComparisonEngine, SimulationConfig, SimulationEngine, Snapshot\n\nROOT = Path(__file__).resolve().parents[1]\nADAPTER = ROOT / "custom_components/kems/foxess_command_shadow.py"\n\n\ndef _offline_foxess_records() -> list[Snapshot]:\n    start = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)\n    stale_physical = (\n        "battery_power_kw",\n        "battery_soc",\n        "grid_export_kw",\n        "solar_power_kw",\n    )\n    return [\n        Snapshot(\n            timestamp=start + timedelta(minutes=15 * index),\n            current_import_rate=28.3,\n            next_import_rate=28.3,\n            off_peak=False,\n            house_load_kw=1.2,\n            grid_import_kw=1.2,\n            battery_soc=None,\n            battery_power_kw=None,\n            solar_power_kw=None,\n            grid_export_kw=None,\n            stale_fields=stale_physical,\n        )\n        for index in range(4)\n    ]\n\n\ndef test_uncommissioned_offline_foxess_does_not_block_virtual_simulation() -> None:\n    records = _offline_foxess_records()\n    result = SimulationEngine().simulate_today(\n        records,\n        records[-1].timestamp + timedelta(minutes=1),\n        SimulationConfig(\n            battery_initial_percent=50.0,\n            proposal_solar_enabled=True,\n        ),\n        current_snapshot=records[-1],\n    )\n\n    assert result.ready is True\n    assert result.data_coverage == 100.0\n    assert result.proposal_solar_active is True\n    assert result.simulated_grid_import_kwh is not None\n    assert result.simulated_battery_soc is not None\n    assert result.actual_solar_generation_kwh == 0.0\n    assert result.actual_battery_charge_kwh == 0.0\n    assert result.actual_battery_discharge_kwh == 0.0\n    assert result.actual_grid_export_kwh == 0.0\n\n\ndef test_current_day_scenarios_survive_uncommissioned_offline_foxess() -> None:\n    records = _offline_foxess_records()\n    result = ScenarioComparisonEngine().compare(\n        records,\n        records[-1].timestamp + timedelta(minutes=1),\n        SimulationConfig(\n            battery_initial_percent=50.0,\n            proposal_solar_enabled=True,\n        ),\n        current_snapshot=records[-1],\n    )\n    today = result.periods["today"]\n    summaries = {item.key: item for item in today.scenarios}\n\n    for key in (\n        "no_system",\n        "solar_only",\n        "solar_battery",\n        "kems_no_export",\n        "kems_full",\n        "kems_forecast",\n        "full_island",\n    ):\n        assert summaries[key].ready is True, key\n        assert summaries[key].data_coverage == 100.0, key\n\n\ndef test_stale_required_house_and_grid_evidence_still_fails_closed() -> None:\n    records = _offline_foxess_records()\n    records = [\n        Snapshot.from_dict(\n            {\n                **record.to_dict(),\n                "stale_fields": [\n                    *record.stale_fields,\n                    "house_load_kw",\n                    "grid_import_kw",\n                ],\n            }\n        )\n        for record in records\n    ]\n    result = SimulationEngine().simulate_today(\n        records,\n        records[-1].timestamp + timedelta(minutes=1),\n        SimulationConfig(proposal_solar_enabled=True),\n        current_snapshot=records[-1],\n    )\n\n    assert result.ready is False\n    assert result.data_coverage == 0.0\n\n\ndef test_foxess_binding_separates_commands_from_sensor_readback_without_writes() -> None:\n    source = ADAPTER.read_text(encoding="utf-8")\n\n    assert '"work_mode": "select"' in source\n    for key in (\n        "force_charge_power",\n        "force_discharge_power",\n        "min_soc_on_grid",\n        "export_power_limit",\n    ):\n        assert f'"{key}": "number"' in source\n    assert "_entry_readback_key" in source\n    assert 'domain == "sensor"' in source\n    assert '"readback_entity_id"' in source\n    assert '"observation_source"' in source\n    assert '"sensor_readback"' in source\n\n    for forbidden in (\n        ".services.async_call(",\n        "async_select_option(",\n        "async_set_native_value(",\n        "write_register(",\n        "write_registers(",\n        "ModbusClient",\n    ):\n        assert forbidden not in source\n''',
    encoding="utf-8",
)

# This helper is staging-only. Its deletion is included in the gated product commit.
Path(__file__).unlink()
