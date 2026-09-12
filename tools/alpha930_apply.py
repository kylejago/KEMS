"""Guarded one-shot Alpha9.30 source migration; removed before candidate freeze."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def sub_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, found {count}")
    path.write_text(updated, encoding="utf-8")


# 1. Make the real KH7 instantaneous load/import entities deterministic winners.
discovery = ROOT / "custom_components/kems/entity_discovery.py"
replace_once(
    discovery,
    '''        excluded_tokens=("phase", "r phase", "s phase", "t phase"),\n        units=("kw", "w"),\n        device_classes=("power",),\n        exact_patterns=(\n            "sensor.foxess_*load*power*",\n            "sensor.octopus_energy_electricity_*_current_demand",\n        ),''',
    '''        excluded_tokens=(\n            "phase",\n            "r phase",\n            "s phase",\n            "t phase",\n            "total",\n            "today",\n            "energy",\n        ),\n        units=("kw", "w"),\n        device_classes=("power",),\n        exact_patterns=(\n            "sensor.*_load_power",\n            "sensor.foxess_*load*power*",\n            "sensor.octopus_energy_electricity_*_current_demand",\n        ),''',
)
replace_once(
    discovery,
    '''        excluded_tokens=("total", "daily", "export", "feed"),\n        units=("kw", "w"),\n        device_classes=("power",),\n        exact_patterns=(\n            "sensor.foxess_*grid*consumption*",\n            "sensor.octopus_energy_electricity_*_current_demand",\n        ),''',
    '''        excluded_tokens=(\n            "total",\n            "daily",\n            "today",\n            "energy",\n            "export",\n            "feed",\n        ),\n        units=("kw", "w"),\n        device_classes=("power",),\n        exact_patterns=(\n            "sensor.*_grid_consumption",\n            "sensor.foxess_*grid*consumption*",\n            "sensor.octopus_energy_electricity_*_current_demand",\n        ),''',
)

# 2. Teach the HA-independent evidence primitives about a no-battery site stage.
evidence = ROOT / "custom_components/kems/kems_core/commissioning_evidence.py"
replace_once(
    evidence,
    '''FOXESS_REQUIRED_TELEMETRY_FIELDS: tuple[str, ...] = (\n    "battery_soc",\n    "battery_power_kw",\n    "solar_power_kw",\n    "house_load_kw",\n    "grid_import_kw",\n    "grid_export_kw",\n)\n''',
    '''FOXESS_SITE_TELEMETRY_FIELDS: tuple[str, ...] = (\n    "solar_power_kw",\n    "house_load_kw",\n    "grid_import_kw",\n    "grid_export_kw",\n)\n\nFOXESS_REQUIRED_TELEMETRY_FIELDS: tuple[str, ...] = (\n    "battery_soc",\n    "battery_power_kw",\n    *FOXESS_SITE_TELEMETRY_FIELDS,\n)\n''',
)
replace_once(
    evidence,
    '''def assess_foxess_unit_contract(\n    source_units: Mapping[str, Any],\n    *,\n    battery_power_derived: bool = False,\n) -> UnitContractEvidence:''',
    '''def assess_foxess_unit_contract(\n    source_units: Mapping[str, Any],\n    *,\n    battery_power_derived: bool = False,\n    battery_required: bool = True,\n) -> UnitContractEvidence:''',
)
replace_once(
    evidence,
    '''    expected: dict[str, set[str]] = {\n        "battery_soc": {"%"},\n        "solar_power_kw": {"w", "kw"},\n        "house_load_kw": {"w", "kw"},\n        "grid_import_kw": {"w", "kw"},\n        "grid_export_kw": {"w", "kw"},\n    }\n    if battery_power_derived:\n        expected.update(\n            {\n                "battery_voltage": {"v"},\n                "battery_current": {"a"},\n            }\n        )\n    else:\n        expected["battery_power_kw"] = {"w", "kw"}\n''',
    '''    expected: dict[str, set[str]] = {\n        "solar_power_kw": {"w", "kw"},\n        "house_load_kw": {"w", "kw"},\n        "grid_import_kw": {"w", "kw"},\n        "grid_export_kw": {"w", "kw"},\n    }\n    if battery_required:\n        expected["battery_soc"] = {"%"}\n        if battery_power_derived:\n            expected.update(\n                {\n                    "battery_voltage": {"v"},\n                    "battery_current": {"a"},\n                }\n            )\n        else:\n            expected["battery_power_kw"] = {"w", "kw"}\n''',
)
replace_once(
    evidence,
    '''def assess_foxess_telemetry_stability(\n    records: tuple[Any, ...] | list[Any],\n    *,\n    expected_interval_seconds: float,\n    minimum_samples: int = 12,''',
    '''def assess_foxess_telemetry_stability(\n    records: tuple[Any, ...] | list[Any],\n    *,\n    expected_interval_seconds: float,\n    battery_required: bool = True,\n    minimum_samples: int = 12,''',
)
replace_once(
    evidence,
    '''    recent = list(records)[-max(int(recent_sample_limit), minimum_samples, 1) :]\n\n    complete_samples = 0''',
    '''    recent = list(records)[-max(int(recent_sample_limit), minimum_samples, 1) :]\n    required_fields = set(\n        FOXESS_REQUIRED_TELEMETRY_FIELDS\n        if battery_required\n        else FOXESS_SITE_TELEMETRY_FIELDS\n    )\n\n    complete_samples = 0''',
)
replace_once(
    evidence,
    '''        sample_missing = {\n            field\n            for field in FOXESS_REQUIRED_TELEMETRY_FIELDS\n            if getattr(record, field, None) is None\n        }\n        sample_stale = set(getattr(record, "stale_fields", ()) or ()) & set(\n            FOXESS_REQUIRED_TELEMETRY_FIELDS\n        )''',
    '''        sample_missing = {\n            field for field in required_fields if getattr(record, field, None) is None\n        }\n        sample_stale = set(getattr(record, "stale_fields", ()) or ()) & required_fields''',
)
replace_once(
    evidence,
    '''def assess_foxess_power_balance(\n    records: tuple[Any, ...] | list[Any],\n    *,\n    positive_is_discharge: bool,\n    minimum_samples: int = 12,''',
    '''def assess_foxess_power_balance(\n    records: tuple[Any, ...] | list[Any],\n    *,\n    positive_is_discharge: bool,\n    battery_required: bool = True,\n    minimum_samples: int = 12,''',
)
replace_once(
    evidence,
    '''    required = set(FOXESS_REQUIRED_TELEMETRY_FIELDS)\n\n    for record in recent:''',
    '''    required = set(\n        FOXESS_REQUIRED_TELEMETRY_FIELDS\n        if battery_required\n        else FOXESS_SITE_TELEMETRY_FIELDS\n    )\n\n    for record in recent:''',
)
replace_once(
    evidence,
    '''        for field in FOXESS_REQUIRED_TELEMETRY_FIELDS:\n            value = getattr(record, field, None)''',
    '''        for field in required:\n            value = getattr(record, field, None)''',
)
replace_once(
    evidence,
    '''        if not 0.0 <= values["battery_soc"] <= 100.0:\n            invalid += 1\n            continue''',
    '''        if battery_required and not 0.0 <= values["battery_soc"] <= 100.0:\n            invalid += 1\n            continue''',
)
replace_once(
    evidence,
    '''        charge, discharge = _battery_routing(\n            values["battery_power_kw"],\n            positive_is_discharge=positive_is_discharge,\n        )''',
    '''        if battery_required:\n            charge, discharge = _battery_routing(\n                values["battery_power_kw"],\n                positive_is_discharge=positive_is_discharge,\n            )\n        else:\n            charge = 0.0\n            discharge = 0.0''',
)

# 3. Add an explicit solar-only commissioning stage while leaving writes blocked.
commissioning = ROOT / "custom_components/kems/commissioning.py"
replace_once(
    commissioning,
    '''def _source_check(\n    hass: HomeAssistant,''',
    '''def _entity_numeric_state(\n    hass: HomeAssistant, entity_id: str | None\n) -> float | None:\n    """Return one finite numeric source state when available."""\n    if not entity_id:\n        return None\n    state = hass.states.get(entity_id)\n    if state is None or state.state in {"unknown", "unavailable"}:\n        return None\n    try:\n        return float(state.state)\n    except (TypeError, ValueError):\n        return None\n\n\ndef _battery_installation_pending(\n    hass: HomeAssistant, mappings: Mapping[str, str]\n) -> bool:\n    """Identify the commissioned-inverter stage before the HV battery is fitted.\n\n    A missing SOC by itself could be a fault, so KEMS only identifies the battery\n    as not yet detected when FoxESS also reports essentially zero battery power and\n    current plus a near-zero/sentinel battery voltage. This state is informational\n    and can never relax control/write safety.\n    """\n    soc = mappings.get(CONF_BATTERY_SOC)\n    power = mappings.get(CONF_BATTERY_POWER)\n    voltage = mappings.get(CONF_BATTERY_VOLTAGE)\n    current = mappings.get(CONF_BATTERY_CURRENT)\n    entities = (soc, power, voltage, current)\n    if any(\n        not entity_id or _entity_platform(hass, entity_id) != FOXESS_PLATFORM\n        for entity_id in entities\n    ):\n        return False\n    if _entity_available(hass, soc):\n        return False\n\n    power_value = _entity_numeric_state(hass, power)\n    voltage_value = _entity_numeric_state(hass, voltage)\n    current_value = _entity_numeric_state(hass, current)\n    return (\n        power_value is not None\n        and abs(power_value) <= 0.05\n        and current_value is not None\n        and abs(current_value) <= 0.1\n        and voltage_value is not None\n        and abs(voltage_value) <= 10.0\n    )\n\n\ndef _source_check(\n    hass: HomeAssistant,''',
)

sub_once(
    commissioning,
    r'''def _foxess_unit_evidence\(\n    hass: HomeAssistant,\n    mappings: Mapping\[str, str\],\n\):\n    """Return the raw-unit contract and deterministic source signature\."""\n    common_sources = \(.*?\n    evidence = assess_foxess_unit_contract\(\n        source_units,\n        battery_power_derived=battery_power_derived,\n    \)''',
    '''def _foxess_unit_evidence(\n    hass: HomeAssistant,\n    mappings: Mapping[str, str],\n    *,\n    battery_required: bool = True,\n):\n    """Return the raw-unit contract and deterministic source signature."""\n    common_sources = (\n        ("solar_power_kw", CONF_SOLAR_POWER),\n        ("house_load_kw", CONF_HOUSE_LOAD),\n        ("grid_import_kw", CONF_GRID_IMPORT),\n        ("grid_export_kw", CONF_GRID_EXPORT),\n    )\n    if battery_required:\n        common_sources = (("battery_soc", CONF_BATTERY_SOC), *common_sources)\n\n    source_units: dict[str, str | None] = {}\n    signature: list[tuple[str, str | None]] = []\n\n    for role, key in common_sources:\n        entity_id = mappings.get(key)\n        unit = _entity_unit(hass, entity_id)\n        source_units[role] = unit\n        identity = f"{entity_id}|{unit}" if entity_id else None\n        signature.append((role, identity))\n\n    battery_power_derived = False\n    if battery_required:\n        direct = mappings.get(CONF_BATTERY_POWER)\n        direct_is_foxess = bool(\n            direct and _entity_platform(hass, direct) == FOXESS_PLATFORM\n        )\n        battery_power_derived = not direct_is_foxess\n        if battery_power_derived:\n            for role, key in (\n                ("battery_voltage", CONF_BATTERY_VOLTAGE),\n                ("battery_current", CONF_BATTERY_CURRENT),\n            ):\n                entity_id = mappings.get(key)\n                unit = _entity_unit(hass, entity_id)\n                source_units[role] = unit\n                identity = f"{entity_id}|{unit}" if entity_id else None\n                signature.append((role, identity))\n        else:\n            unit = _entity_unit(hass, direct)\n            source_units["battery_power_kw"] = unit\n            signature.append(\n                ("battery_power_kw", f"{direct}|{unit}" if direct else None)\n            )\n\n    evidence = assess_foxess_unit_contract(\n        source_units,\n        battery_power_derived=battery_power_derived,\n        battery_required=battery_required,\n    )''',
)

replace_once(
    commissioning,
    '''    physical_source_duplicates = duplicate_physical_sources(mappings)\n\n    checks: list[dict[str, Any]] = []''',
    '''    physical_source_duplicates = duplicate_physical_sources(mappings)\n    battery_installation_pending = _battery_installation_pending(hass, mappings)\n    solar_only_commissioning = bool(\n        foxess_registered and battery_installation_pending\n    )\n\n    checks: list[dict[str, Any]] = []''',
)
replace_once(
    commissioning,
    '''            (\n                PASS\n                if data.quality.score >= 95.0 and not data.quality.stale_fields\n                else FAIL\n            ),''',
    '''            (\n                PASS\n                if data.quality.score >= 95.0 and not data.quality.stale_fields\n                else WAIT if solar_only_commissioning else FAIL\n            ),''',
)
replace_once(
    commissioning,
    '''    checks.append(\n        _source_check(hass, mappings, CONF_BATTERY_SOC, "Battery SOC mapping")\n    )\n    battery_power_check = _battery_power_source_check(hass, mappings)\n    checks.append(battery_power_check)''',
    '''    if battery_installation_pending:\n        checks.append(\n            _check(\n                CONF_BATTERY_SOC,\n                "Battery SOC mapping",\n                WAIT,\n                "Battery installation pending — SOC proof deferred",\n            )\n        )\n        battery_power_check = _check(\n            "battery_power_mapping",\n            "Battery power mapping",\n            WAIT,\n            "Battery installation pending — power/direction proof deferred",\n        )\n    else:\n        checks.append(\n            _source_check(hass, mappings, CONF_BATTERY_SOC, "Battery SOC mapping")\n        )\n        battery_power_check = _battery_power_source_check(hass, mappings)\n    checks.append(battery_power_check)''',
)
replace_once(
    commissioning,
    '''    mapping_checks = {item["key"]: item for item in checks}\n    foxess_physical_mappings_ready = all(\n        mapping_checks[key]["status"] == PASS\n        for key in (\n            CONF_BATTERY_SOC,\n            "battery_power_mapping",\n            CONF_SOLAR_POWER,\n            CONF_GRID_IMPORT,\n            CONF_GRID_EXPORT,\n            CONF_HOUSE_LOAD,\n            "physical_source_uniqueness",\n        )\n    )\n\n    unit_evidence, source_signature, battery_power_derived = _foxess_unit_evidence(\n        hass,\n        mappings,\n    )''',
    '''    mapping_checks = {item["key"]: item for item in checks}\n    site_physical_mappings_ready = all(\n        mapping_checks[key]["status"] == PASS\n        for key in (\n            CONF_SOLAR_POWER,\n            CONF_GRID_IMPORT,\n            CONF_GRID_EXPORT,\n            CONF_HOUSE_LOAD,\n            "physical_source_uniqueness",\n        )\n    )\n    foxess_physical_mappings_ready = site_physical_mappings_ready and all(\n        mapping_checks[key]["status"] == PASS\n        for key in (CONF_BATTERY_SOC, "battery_power_mapping")\n    )\n    commissioning_physical_mappings_ready = (\n        site_physical_mappings_ready\n        if solar_only_commissioning\n        else foxess_physical_mappings_ready\n    )\n\n    unit_evidence, source_signature, battery_power_derived = _foxess_unit_evidence(\n        hass,\n        mappings,\n        battery_required=not solar_only_commissioning,\n    )''',
)
replace_once(
    commissioning,
    '''    if not foxess_physical_mappings_ready:\n        unit_check = _check(''',
    '''    if not commissioning_physical_mappings_ready:\n        unit_check = _check(''',
)
replace_once(
    commissioning,
    '''    foxess_evidence_sources_ready = (\n        foxess_physical_mappings_ready and unit_evidence.ready\n    )\n    records, session_metadata = collect_foxess_session_records(\n        coordinator,\n        source_signature=source_signature,\n        snapshot=data.snapshot,\n        ready=foxess_evidence_sources_ready,\n    )''',
    '''    commissioning_evidence_sources_ready = (\n        commissioning_physical_mappings_ready and unit_evidence.ready\n    )\n    foxess_evidence_sources_ready = (\n        foxess_physical_mappings_ready\n        and unit_evidence.ready\n        and not solar_only_commissioning\n    )\n    records, session_metadata = collect_foxess_session_records(\n        coordinator,\n        source_signature=source_signature,\n        snapshot=data.snapshot,\n        ready=commissioning_evidence_sources_ready,\n    )''',
)
replace_once(
    commissioning,
    '''    if not foxess_evidence_sources_ready:\n        telemetry_check = _check(''',
    '''    if not commissioning_evidence_sources_ready:\n        telemetry_check = _check(''',
)
replace_once(
    commissioning,
    '''        telemetry_evidence = assess_foxess_telemetry_stability(\n            records,\n            expected_interval_seconds=coordinator.settings.scan_interval_seconds,\n        )''',
    '''        telemetry_evidence = assess_foxess_telemetry_stability(\n            records,\n            expected_interval_seconds=coordinator.settings.scan_interval_seconds,\n            battery_required=not solar_only_commissioning,\n        )''',
)
replace_once(
    commissioning,
    '''    if not foxess_evidence_sources_ready:\n        battery_direction = _check(''',
    '''    if solar_only_commissioning:\n        battery_direction = _check(\n            "battery_power_direction",\n            "Battery power direction",\n            WAIT,\n            "Battery installation pending — sign proof deferred until the pack is fitted",\n        )\n    elif not foxess_evidence_sources_ready:\n        battery_direction = _check(''',
)
replace_once(
    commissioning,
    '''    if not foxess_evidence_sources_ready:\n        power_balance_check = _check(''',
    '''    if not commissioning_evidence_sources_ready:\n        power_balance_check = _check(''',
)
replace_once(
    commissioning,
    '''    elif battery_direction["status"] != PASS:\n        power_balance_check = _check(\n            "foxess_power_balance",\n            "FoxESS whole-site power balance",\n            WAIT,\n            "Waiting for the battery power sign convention to be proven",\n        )\n    else:\n        power_balance_evidence = assess_foxess_power_balance(\n            records,\n            positive_is_discharge=configured_positive_is_discharge,\n        )''',
    '''    elif not solar_only_commissioning and battery_direction["status"] != PASS:\n        power_balance_check = _check(\n            "foxess_power_balance",\n            "FoxESS whole-site power balance",\n            WAIT,\n            "Waiting for the battery power sign convention to be proven",\n        )\n    else:\n        power_balance_evidence = assess_foxess_power_balance(\n            records,\n            positive_is_discharge=configured_positive_is_discharge,\n            battery_required=not solar_only_commissioning,\n        )''',
)
replace_once(
    commissioning,
    '''            PASS if shadow_safe else FAIL,''',
    '''            PASS if shadow_safe else WAIT if solar_only_commissioning else FAIL,''',
)
replace_once(
    commissioning,
    '''    foxess_telemetry_proof_ready = bool(telemetry_proof_checks) and all(\n        status == PASS for status in telemetry_proof_checks.values()\n    )\n\n    return {''',
    '''    foxess_telemetry_proof_ready = (\n        not solar_only_commissioning\n        and bool(telemetry_proof_checks)\n        and all(status == PASS for status in telemetry_proof_checks.values())\n    )\n    site_telemetry_proof_checks = {\n        item["key"]: item["status"]\n        for item in checks\n        if item["key"]\n        in {\n            "foxess_unit_contract",\n            "foxess_telemetry_stability",\n            "grid_direction",\n            "foxess_power_balance",\n        }\n    }\n    foxess_site_telemetry_proof_ready = bool(site_telemetry_proof_checks) and all(\n        status == PASS for status in site_telemetry_proof_checks.values()\n    )\n\n    return {''',
)
replace_once(
    commissioning,
    '''        "foxess_telemetry_mapping_gate_passed": foxess_physical_mappings_ready,\n        "foxess_evidence_sources_ready": foxess_evidence_sources_ready,''',
    '''        "battery_installation_pending": battery_installation_pending,\n        "solar_only_commissioning": solar_only_commissioning,\n        "foxess_site_mapping_gate_passed": site_physical_mappings_ready,\n        "foxess_telemetry_mapping_gate_passed": foxess_physical_mappings_ready,\n        "foxess_site_evidence_sources_ready": commissioning_evidence_sources_ready,\n        "foxess_evidence_sources_ready": foxess_evidence_sources_ready,''',
)
replace_once(
    commissioning,
    '''        "foxess_telemetry_proof_ready": foxess_telemetry_proof_ready,''',
    '''        "foxess_site_telemetry_proof_ready": foxess_site_telemetry_proof_ready,\n        "foxess_telemetry_proof_ready": foxess_telemetry_proof_ready,''',
)

# 4. Advance core release metadata only; the live-proven panel remains panel.3.
manifest = ROOT / "custom_components/kems/manifest.json"
manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
if manifest_data.get("version") != "0.9.0-alpha9.29":
    raise RuntimeError(f"unexpected manifest version: {manifest_data.get('version')}")
manifest_data["version"] = "0.9.0-alpha9.30"
manifest.write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8")

bundle_path = ROOT / "release/kems-bundle.template.json"
bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
panel_version = bundle["components"]["panel"]["version"]
if panel_version != "0.9.0-alpha9-panel.3":
    raise RuntimeError(f"unexpected panel version: {panel_version}")
reason = bundle["maintenance"]["reason"]
if not reason.startswith("Alpha9 coordinated parity baseline;"):
    raise RuntimeError("unexpected release reason prefix")
bundle["maintenance"]["reason"] = (
    "Alpha9 coordinated parity baseline; Alpha9.30 promotes live FoxESS KH7 "
    "load_power and grid_consumption over the pre-install Octopus current-demand "
    "fallback once those physical sources are available, and adds a read-only "
    "solar-only commissioning evidence stage while the battery installation is "
    "pending. Site PV, house, grid direction, raw units, stability and whole-site "
    "power balance can therefore be proven without pretending that battery SOC or "
    "battery direction exists; full commissioning and every real FoxESS write remain "
    "blocked until the battery and all control evidence are present. "
    + reason[len("Alpha9 coordinated parity baseline; ") :]
)
bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")

print("Alpha9.30 guarded production migration applied successfully")
