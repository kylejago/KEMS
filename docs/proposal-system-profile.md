# Proposal system profile

KEMS v0.7.0-alpha2 uses the revised proposal profile for simulation before the
physical solar/battery system is commissioned.

## Hardware assumptions

| Component | Simulation value |
|---|---:|
| PV modules | 21 × DMEGC 460 W |
| Total PV capacity | 9.66 kWp |
| Inverter | Fox ESS KH7 |
| Inverter AC limit | 7 kW |
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

The proposal reports a 0.938 shade factor and 8,016 kWh annual output. Its
monthly table is rounded and totals 8,017 kWh; KEMS preserves the quoted monthly
values and the separate 8,016 kWh annual headline.

## Tariff and operating assumptions

- Import rates come from the current Intelligent Octopus Go entities.
- Simulated export is always valued at the configured fixed 12p/kWh rate.
- Intelligent Octopus Flux export rates are not used.
- Cheap periods are normal Octopus off-peak or an Intelligent slot confirmed by
  active Ohme charging.
- Outside cheap periods, the home is supplied from battery where possible and
  proposal solar is exported.
- Battery energy above the 10% reserve and forecast home requirement is spread
  across the remaining hours until the next cheap period.
- Combined solar and battery AC output cannot exceed 7kW.
- The separate grid-export limit remains editable for the final DNO approval.
- A standard six-hour cheap window at 7kW and 95% efficiency adds about 39.9kWh, so a battery starting at the 10% reserve reaches roughly 80.7% unless confirmed extra Intelligent slots extend charging.

## Power Down override

A joined Octoplus Power Down session temporarily overrides ordinary paced export. Before the event, KEMS holds the energy needed for forecast home use plus maximum useful session output. During the event, the home is covered and remaining KH7 output is exported. Normal export remains valued at 12p/kWh; the Octopoints bonus is additional and uses 8 points = 1p.
