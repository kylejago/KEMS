# KEMS architecture

KEMS remains a Home Assistant custom integration with a Home Assistant-independent analysis core packaged inside `custom_components/kems/kems_core`.

```text
Home Assistant entities
        │
        ▼
Entity discovery and configured mapping
        │
        ▼
Octopus electricity ─┐
Octopus gas ─────────┤
Ohme ────────────────┼─► Collector ─► Snapshot
FoxESS Modbus ───────┘                     │
                                           ▼
                                  Persistent history
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    ▼                      ▼                      ▼
                 Learn                  Advise                 Simulate
                    │                      │                      │
                    └──────────────┬───────┴──────────────┬──────┘
                                   ▼                      ▼
                              Gas summary          Whole-home summary
                                   │                      │
                                   └──────────┬───────────┘
                                              ▼
                                      Coordinator data
                                              │
                                              ▼
                                   Sensors, binary sensors,
                                   diagnostics and dashboards
```

## Provider boundary

Providers read only from Home Assistant's state machine and normalise values. No provider calls services or writes settings.

## Proposal simulation boundary

The simulation uses observed household demand and tariff history. Live FoxESS solar is preferred when available; otherwise the fixed proposal system profile generates an orientation-weighted solar estimate. Simulation results never command physical equipment.

## Gas boundary

Gas remains observed rather than optimised. It contributes to learning, whole-home energy, and whole-home cost. Simulated whole-home cost combines simulated electricity with observed gas.

## Future Control phase

Control will require a separate opt-in design, safety limits, explicit device capabilities, dry-run comparison, audit history, and manual override. Nothing in this branch implements Control.

## ROI and lifetime pipeline

After the normal Observe/Learn/Advise/Simulate pipeline, KEMS updates a separate permanent lifetime ledger and calculates ROI:

```text
Snapshot + retained history
        ↓
Daily observed/simulated cumulative totals
        ↓
Persistent lifetime delta ledger
        ↓
Predicted ROI before commissioning
        ↓
Actual payback after commissioning
        ↓
Profit Mode after the investment is recovered
```

The lifetime store is intentionally separate from Home Assistant Recorder so long-term totals are not lost when Recorder history is purged.
