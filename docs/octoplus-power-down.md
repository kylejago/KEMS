# Octoplus Power Down integration

KEMS is a read-only consumer of BottlecapDave's Octopus Energy entities. It does not call the join service.

## Supported source names

KEMS discovers both:

- `event.octopus_energy_*_octoplus_power_down_events`
- `event.octopus_energy_*_octoplus_saving_session_events`

The selected event must appear in `joined_events`. Active joined events are preferred; otherwise KEMS selects the next upcoming joined event.

## Optional baselines

KEMS can map the import and export variants of the Power Down baseline sensor. The import baseline is required for an estimated reward. If an export baseline exists, net baseline is import minus export. Incomplete baselines remain visible as provisional through a diagnostic binary sensor.

## Planning priorities

Before a joined event that occurs before the next cheap recharge:

1. preserve the 10% battery reserve;
2. preserve forecast household demand;
3. preserve enough stored energy to run useful inverter output up to the KH7 limit during the session;
4. pace only the remaining battery energy as ordinary export.

During the session:

1. prevent grid import where stored energy permits;
2. supply the home;
3. export remaining solar/battery output;
4. respect the inverter, battery-discharge, and grid-export limits.

## Reward calculation

```text
net baseline = import baseline - export baseline
simulated net = simulated import - simulated export
rewardable reduction = max(net baseline - simulated net, 0)
bonus p/kWh = Octopoints per kWh / 8
Power Down bonus = rewardable reduction × bonus p/kWh
total session income = fixed 12p export income + Power Down bonus
```

The bonus is an estimate until Octopus publishes the final result.
