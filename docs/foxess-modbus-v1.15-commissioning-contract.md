# FoxESS Modbus v1.15 KH commissioning contract

Alpha8.60 freezes the Home Assistant telemetry contract KEMS expects from `nathanmarlor/foxess_modbus` for FoxESS KH-family commissioning.

## Reviewed upstream baseline

- Integration: `nathanmarlor/foxess_modbus`
- Reviewed release: `v1.15.0`
- KH families covered by the reviewed definitions: `KH_PRE119`, `KH_PRE133`, `KH_133`
- This contract is read-only. It does not enable a FoxESS service call, Modbus write, work-mode change, remote-control command, or any other hardware write path.

## Required KEMS telemetry

KEMS uses the stable upstream entity keys below as its preferred physical sources once the inverter is commissioned in Home Assistant:

| KEMS field | foxess_modbus key | Upstream name | Unit |
| --- | --- | --- | --- |
| `battery_soc` | `battery_soc` | Battery SoC | % |
| `battery_power_kw` | `invbatpower` | Inverter Battery Power | kW |
| `solar_power_kw` | `pv_power_now` | PV Power | kW |
| `house_load_kw` | `load_power` | Load Power | kW |
| `grid_import_kw` | `grid_consumption` | Grid Consumption | kW |
| `grid_export_kw` | `feed_in` | Feed-in | kW |

`invbatpower` is the preferred battery-power source. In the reviewed upstream implementation, positive values are exposed through Battery Discharge and negative values through Battery Charge, matching the KEMS commissioning expectation that positive direct battery power represents discharge. The real installation must still prove the observed sign convention before control can advance.

`pv_power_now` is the upstream aggregate PV sensor. For KH it combines PV1-PV4, so KEMS must not add the string sensors itself.

`grid_consumption` and `feed_in` are already direction-normalised by foxess_modbus from `grid_ct`: Grid Consumption is import-only and Feed-in is export-only. KEMS should use those two physical sources and retain `grid_ct` only as an independent commissioning cross-check.

## Battery-power fallback

The reviewed KH definitions also expose inverter-side battery voltage and current:

- `invbatvolt` — Inverter Battery Voltage
- `invbatcurrent` — Inverter Battery Current

KEMS may use this pair only if direct `invbatpower` is unavailable. The direct power entity remains authoritative when present.

The separate BMS `batvolt` / `bat_current` entities are not part of this required contract because their model coverage differs across KH firmware families in v1.15.0.

## Optional read-only commissioning evidence

The following sources are useful for reconciliation but are not required to leave `Awaiting FoxESS`:

- `grid_ct` — raw signed grid direction
- `rpower` — inverter AC power
- `bms_kwh_remaining` — battery energy remaining where the model exposes it
- `pv1_power`, `pv2_power`, `pv3_power`, `pv4_power` — string-level PV cross-checks

## Known writable capabilities — deliberately blocked

foxess_modbus v1.15.0 exposes KH configuration entities including:

- `work_mode`
- `max_charge_current`
- `max_discharge_current`
- `min_soc`
- `max_soc`
- `min_soc_on_grid`
- `export_power_limit` on KH_133
- `import_power_limit` on KH_133

Alpha8.60 records these names for commissioning awareness only. They are not KEMS input mappings and are not invoked by the integration. Existing KEMS hardware-write blocks, commissioning gates, emergency-stop protections, and explicit operator-authorisation requirements remain unchanged.

## Installation-day acceptance

Before KEMS can advance beyond read-only commissioning evidence:

1. FoxESS Modbus must own and report the mapped physical entities.
2. Battery SOC, direct battery power (or the approved fallback pair), solar, house load, grid import and grid export must be available and fresh.
3. Battery-power sign must be observed during both a real charge and a real discharge condition.
4. `grid_consumption` / `feed_in` must reconcile with the raw `grid_ct` direction and the site meter.
5. `pv_power_now` must reconcile with the active PV string powers within expected measurement tolerance.
6. Telemetry must remain stable for the existing KEMS commissioning stability window.
7. Real hardware writes remain blocked throughout this acceptance work.
