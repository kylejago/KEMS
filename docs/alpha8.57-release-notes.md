# KEMS 0.8.0-alpha8.57

Alpha8.57 replaces the Alpha8.56 fixed 1 Wh precision tolerance with a canonical house-first discharge reconciliation proven from the 30 Aug Alpha8.56 field diagnostic.

## Changed

- Outside confirmed cheap/Intelligent import periods, canonical future routing now supplies remaining house demand from all physically usable battery AC headroom above the protected SOC floor before allowing Grid import.
- A rounded or stale `planned_battery_to_home_kwh` value can no longer create a daytime Grid residual when the battery can physically cover the house.
- When a planned battery export is already using the slot discharge/inverter ceiling, the canonical projection reduces that discretionary export before allowing Grid import for the house.
- Planned battery export is never increased and the export-slot ranking itself is unchanged.
- Genuine Grid import remains whenever solar plus physically permissible battery discharge cannot cover the house.

## Field regressions

The regression reproduces the Alpha8.56 16:00 shape: 0.733 kWh house demand, 0.386 kWh solar-to-home, a rounded 0.342 kWh planned battery-to-home allocation and 2.767 kWh planned battery export. Canonical routing must top battery-to-home up to 0.347 kWh and publish zero Grid import while preserving the export because physical headroom exists.

A second regression saturates total battery discharge and proves that an increased house requirement is funded by reducing battery export before Grid import. A third regression proves a real physical battery shortfall still appears as Grid import only after discretionary export has been reduced to zero.

## Protected boundaries

No export price ranking, solar storage economics, reserve floor, Power Down, Happy Hour, EV policy, cheap-window routing, FoxESS commissioning or real hardware writes are changed. Real hardware writes remain blocked.
