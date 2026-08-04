# KH7 commissioning checklist — 17 August 2026

- Confirm exact KH7 model and firmware.
- Confirm direct Modbus connection and stable update interval.
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
