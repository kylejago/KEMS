# KEMS 0.8.0-alpha8.56

Alpha8.56 is a narrowly bounded canonical flow-precision correction following Alpha8.55 field proof.

## Changed

- Close only quantisation-sized (<= 0.001 kWh) future daytime home-demand residuals with battery-to-home when the battery is above the protected floor and both discharge and shared-inverter headroom can physically supply the remainder.
- Publish exactly zero grid import for that case, preventing a mathematically insignificant 1 Wh remainder from appearing as `IMPORT · 0.00 kWh`.
- Preserve genuine grid residuals whenever the physical discharge/inverter/SOC headroom cannot cover them.

## Field regression

The regression reproduces the 30 Aug 11:30 slot: 1.315 kW conservative house demand over a half-hour, 0.315 kWh solar-to-home, 0.342 kWh rounded planned battery-to-home and ample battery headroom. The canonical projection closes the approximately 0.0005 kWh quantisation remainder with battery-to-home and publishes Grid IDLE / 0.000 kWh.

A companion regression exhausts the physical discharge limit and proves a genuine residual remains Grid IMPORT rather than being suppressed by the precision tolerance.

## Protected boundaries

No export ranking, solar storage economics, reserve policy, Power Down, Happy Hour, EV policy, cheap-window routing, FoxESS commissioning or real hardware writes are changed. Real hardware writes remain blocked.
