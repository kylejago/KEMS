# Alpha8 cheap-window handover canonicalisation

Alpha8 now owns the proven Alpha7.35 cheap-window reporting handover through the non-versioned `agile_cheap_window_handover` boundary.

The canonical runtime owner `agile_cheap_window_handover_runtime.py` is byte-for-byte identical to the historical `agile_alpha735_cheap_handover.py` implementation. The historical file remains in the repository as frozen regression evidence but no longer appears in the executable Alpha7 compatibility registry.

Installation order is preserved: the Alpha7.34 deadline guard remains authoritative first, then the cheap-window reporting handover is installed, followed by canonical product presentation.

The boundary remains reporting-only. It corrects the current routing snapshot and live scenario at the configured overnight cheap-window transition, suppresses stale display export targets, and keeps the manual configured overnight schedule authoritative. It does not replace the deadline guard, alter optimisation, patch dispatch or rolling-plan functions, change commissioning, or enable real hardware writes.

This ownership migration intentionally leaves the runtime's proven Alpha7.30 current-routing helper dependency unchanged. That dependency should only move when the Alpha7.30/7.31 routing boundary is canonicalised in its own parity-gated slice.
