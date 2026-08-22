# KH7 commissioning checklist — 17 August 2026

- Confirm exact KH7 model and firmware.
- Confirm direct Modbus connection and stable update interval.
- Before treating telemetry as commissioning evidence, retain at least 12 recent KEMS observations with at least 95% complete physical telemetry and no observation gap greater than three configured scan intervals. The required physical fields are battery SOC, battery power, solar power, house load, grid import, and grid export.
- Record battery SOC, battery charge/discharge, solar, load, grid import/export, grid availability, and EPS entities.
- Verify every unit and sign convention before any write is enabled.
- Confirm DNO export limit and KH7 continuous/short-duration EPS limits.
- Confirm whole-house EPS changeover and that Home Assistant/network/Modbus remain powered.
- Run shadow mode through cheap charge, self-use, paced export, and low-power export tests.
- Test emergency stop and stale-data blocking.
- Perform a controlled low-load grid-failure test with the installer present.
- Verify solar continues in island mode, surplus charges the battery, export is zero, and EV charging is blocked.
- Restore grid and verify the stability hold before normal planning resumes.
- Only then implement and enable the real FoxESS backend one command family at a time.

`kems_core.commissioning_evidence.assess_foxess_telemetry_stability()` is the read-only evidence primitive for the sustained telemetry requirement above. It analyses retained observations only; it does not call Home Assistant services, implement a FoxESS write backend, or change the real-hardware write lock.
