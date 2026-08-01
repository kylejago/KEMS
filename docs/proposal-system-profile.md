# Proposal system profile

KEMS v0.6.0-alpha1 includes a fixed proposal profile for simulation before the physical solar/battery system is commissioned.

## Hardware assumptions

| Component | Simulation value |
|---|---:|
| PV modules | 21 × DMEGC 460 W |
| Total PV capacity | 9.66 kWp |
| Inverter | Fox ESS KH10 |
| Inverter / battery power limit | 10 kW |
| Battery | 2 × Fox ESS ECS4100-H7 |
| Nominal capacity | 56.42 kWh |
| Proposal usable capacity | 50.77 kWh |
| Default reserve | 10% |
| Charge efficiency | 95% |
| Discharge efficiency | 95% |

## Array model

| Roof group | Panels | Capacity | Azimuth | Tilt |
|---|---:|---:|---:|---:|
| East | 9 | 4.14 kWp | 92° | 39° |
| West | 9 | 4.14 kWp | 271° | 39° |
| South | 3 | 1.38 kWp | 181° | 44° |

The proposal reports a 0.938 shade factor and 8,016 kWh annual output. Its monthly table is rounded and totals 8,017 kWh; KEMS preserves the quoted monthly values and the separate 8,016 kWh annual headline.

## Monthly generation baseline

| Month | kWh |
|---|---:|
| January | 258 |
| February | 351 |
| March | 643 |
| April | 778 |
| May | 1,027 |
| June | 1,195 |
| July | 1,192 |
| August | 930 |
| September | 665 |
| October | 475 |
| November | 289 |
| December | 214 |

The deterministic curve is only a proposal baseline. Live FoxESS PV data takes priority once available.

## Tariff and operating assumptions

- Import rates come from the current Intelligent Octopus Go entities.
- The 12 p/kWh fixed export rate is used only when no live export-rate entity is available.
- Cheap periods are normal Octopus off-peak or an Intelligent slot confirmed by active Ohme charging.
- The default strategy exports solar first, powers the home from battery outside cheap periods, preserves forecast demand, and can export surplus battery energy while retaining the reserve.
- The 10 kW export limit is a user-editable simulation value, not proof of DNO approval.
