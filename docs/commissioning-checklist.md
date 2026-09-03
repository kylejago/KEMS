# KH7 commissioning checklist — 17 August 2026

- Confirm exact KH7 model and firmware.
- Confirm direct Modbus connection and stable update interval.
- Before treating telemetry as commissioning evidence, retain at least 12 recent KEMS observations with at least 95% complete physical telemetry and no observation gap greater than three configured scan intervals. The required physical fields are battery SOC, battery power, solar power, house load, grid import, and grid export.
- Establish one authoritative FoxESS Modbus source for each commissioned physical role before `Ready for Shadow`: battery SOC, battery power (or the explicit voltage/current derivation), solar power, house load, grid import, and grid export. Distinct physical roles must not alias the same FoxESS entity.
- Treat the Octopus `current_demand` house-load/grid-import sharing as a pre-install fallback only. It may remain while FoxESS is absent, but commissioning must promote those roles to their distinct FoxESS physical sources before telemetry evidence can pass.
- Once a valid source mapping exists, automatic discovery must not replace it with another entity from the same platform on a later restart. Automatic replacement is limited to a declared higher-priority platform promotion, such as Octopus pre-install demand fallback to FoxESS Modbus physical telemetry.
- Record battery SOC, battery charge/discharge, solar, load, grid import/export, grid availability, and EPS entities.
- Verify every raw source unit and sign convention before any write is enabled. Direct power sources must be W or kW; battery SOC must be percent; voltage/current battery-power derivation must use V and A.
- Verify repeated whole-site power balance: solar + grid import + battery discharge must reconcile with house load + grid export + battery charge across recent observations, within the defined asynchronous-register tolerance.
- Compare KEMS shadow battery intent with the observed FoxESS battery direction and magnitude as commissioning evidence only. Until a real backend exists, physical tracking is informational and must never be interpreted as permission to write hardware.
- Confirm DNO export limit and KH7 continuous/short-duration EPS limits.
- Confirm whole-house EPS changeover and that Home Assistant/network/Modbus remain powered.
- Run shadow mode through cheap charge, self-use, paced export, and low-power export tests.
- Test emergency stop and stale-data blocking.
- Perform a controlled low-load grid-failure test with the installer present.
- Verify solar continues in island mode, surplus charges the battery, export is zero, and EV charging is blocked.
- Restore grid and verify the stability hold before normal planning resumes.
- Only then implement and enable the real FoxESS backend one command family at a time.

`kems_core.commissioning_evidence.assess_foxess_telemetry_stability()` is the read-only evidence primitive for the sustained telemetry requirement above. `sensor.kems_commissioning_readiness` now consumes that evidence only after all required physical observations are mapped to live FoxESS Modbus entities, using the configured KEMS scan interval as the continuity baseline. Collecting evidence remains a commissioning wait; materially incomplete/stale telemetry, excessive update gaps, or duplicate commissioned physical-source mappings fail closed and prevent `Ready for Shadow`. The commissioning snapshot also exposes the selected physical-source authority for each role so source ownership can be reviewed directly. This gate does not call Home Assistant services, implement a FoxESS write backend, or change the real-hardware write lock.

The physical telemetry contract is implemented by `assess_foxess_unit_contract()`, `assess_foxess_power_balance()`, and `compare_shadow_battery_target()`. These helpers are Home Assistant-independent and read-only. This slice proves their behaviour before a separate wiring change feeds live FoxESS entity metadata and commissioning state into them.
