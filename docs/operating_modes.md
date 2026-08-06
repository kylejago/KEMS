# KEMS operating modes and priorities

## User-selectable modes

- **Observe** — source monitoring and learning only.
- **Simulate** — run proposal-system and virtual KH7 control planning.
- **Shadow** — calculate desired commands from readings but send nothing.
- **Control** — reserved for the commissioned backend; real writes are hard-blocked in 0.7.0-alpha3.

## Normal strategy

During confirmed cheap periods, the plan supplies the home from the grid and charges the battery within the 7kW KH7 limit. Outside cheap periods, it protects forecast home demand and paces surplus battery export toward the next cheap period. Simulated export income remains fixed at 12p/kWh.

## Power Down priority

A joined Power Down session before the next recharge can reduce ordinary export so energy remains available to supply the house and maximise safe session export.

## Whole-house island priority

When the grid is unavailable, financial optimisation is suspended:

1. solar powers the whole house;
2. surplus solar charges the battery;
3. battery supplies only the solar shortfall;
4. EV charging and grid export are disabled;
5. the higher island reserve replaces the normal 10% export target;
6. normal planning resumes only after the grid-restoration stability hold.

## Priority order

1. Emergency stop
2. Whole-house island/EPS operation
3. Stale-data, inverter, EPS, and battery protection
4. Power Down session
5. Confirmed cheap charging
6. Home-energy reserve
7. Paced 12p export
8. Normal self-use
