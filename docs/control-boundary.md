# Control boundary — 0.7.0-alpha2

This release contains a complete hardware-independent control planner and virtual KH7 scenario lab, but remains safe to install before the inverter exists.

It calculates desired work mode, charge/discharge/export power, SOC limits, whole-house island routing, EPS warnings, Power Down behaviour, and fail-safe actions.

It still does **not**:

- call FoxESS Modbus services or write registers;
- approve/start Ohme charging;
- change Octopus enrolment;
- electrically create island mode;
- permit commands when the real backend is unavailable.

`binary_sensor.kems_control_commands_permitted` remains off in alpha2. The real backend will be added only after installation-day entity/service mapping, sign validation, command verification, and controlled outage testing.
