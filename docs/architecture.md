# Architecture

```text
Home Assistant entity registry and state machine
        │
        ├── OctopusProvider
        ├── OhmeProvider
        └── FoxESSProvider
                │
             Collector
                │
             Snapshot
                │
        persistent rolling history
                │
        ┌───────┼────────┐
        │       │        │
      Learn   Advise  Simulate
        └───────┼────────┘
                │
             KEMSData
                │
      DataUpdateCoordinator
                │
      sensors and binary sensors
```

All runtime files are inside `custom_components/kems`, because HACS installs only that directory. The analysis core is inside `custom_components/kems/kems_core` and has no Home Assistant imports, which keeps it testable and reusable.

## Extensibility

New energy sources should be added as provider adapters that return normalised values. A future provider can be introduced without changing the learning, advice, or simulation engines. Control must be implemented as a separate, explicitly enabled phase and must never be added to the current providers.
