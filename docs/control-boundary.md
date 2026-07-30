# Control boundary

This release is intentionally read-only.

It does not:

- call Home Assistant services belonging to Octopus, Ohme, or FoxESS Modbus;
- write Modbus registers;
- approve or start an Ohme charge;
- change inverter work mode, reserve, charge periods, or power limits;
- create automations that operate energy hardware.

A future Control phase should use a separate policy layer, explicit opt-in, simulation comparison, safety constraints, audit logging, and a global kill switch.
