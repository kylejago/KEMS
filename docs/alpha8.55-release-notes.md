# KEMS 0.8.0-alpha8.55

Alpha8.55 is a simulation/planning/shadow parity correction driven by field evidence from 30 August 2026.

## Changes

- Makes the daytime house-routing invariant explicit outside confirmed cheap/Intelligent slots: solar serves the house first, then permissible battery discharge, and grid supplies only the physically unavoidable residual once the protected battery budget/headroom is exhausted.
- Keeps deliberate Agile export subordinate to home demand. A low-price export hold no longer turns usable battery energy into premium-rate grid import.
- Reconciles confirmed cheap-charge control/shadow targets with the canonical charging route so the shadow target carries charge power and zero battery discharge instead of an export-centric stale house-discharge target.
- Values surplus-solar storage against the marginal future Agile slot after already-available battery energy has occupied the stronger slots. Charge efficiency, discharge efficiency and battery wear are included before choosing store-versus-export.

## Protected boundaries

- Power Down and Happy Hour priority are unchanged.
- The 10% hard battery reserve and physical inverter/export/discharge limits remain authoritative.
- Cheap/Intelligent charging policy is unchanged apart from shadow-target parity reporting.
- EV policy is unchanged.
- FoxESS commissioning state and all real hardware writes remain blocked.
