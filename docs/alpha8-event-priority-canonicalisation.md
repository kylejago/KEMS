# Alpha8 event-priority canonicalisation

This Alpha8 cleanup slice moves the proven Alpha7.43 Power Down and Weekend Happy Hour runtime ownership behind canonical, non-versioned module names without changing the validated behavior.

## Canonical ownership

- `agile_event_priority.py` is the canonical installer facade used by the executable compatibility registry.
- `agile_event_priority_runtime.py` is byte-identical to the historical `agile_alpha743_event_priority.py` implementation for this parity slice.
- `agile_alpha743_event_priority.py` remains in the repository as historical regression evidence but is no longer in the executable registry.

## Preserved behavior

Power Down remains an absolute priority over Agile price. Joined-session energy is protected before ordinary Agile export, active sessions serve the house first and then maximise safe export within configured limits, and Agile price cannot override the event.

Weekend Happy Hour planning remains manual and conservative. KEMS creates only required charging headroom using known pre-event Agile prices, never guesses unpublished prices, suppresses deliberate battery export while charging, corrects the digital-twin SOC for free charging, and then allows the rolling planner to re-optimise replenished energy afterwards.

The priority order remains `safety > Power Down > Happy Hour > Agile price`.

## Safety boundary

This remains simulation/shadow behavior. No FoxESS provider write path, Home Assistant service write, commissioning bypass, or hardware-write permission is introduced. Real FoxESS hardware writes remain blocked.

No version bump is made for this parity-preserving architectural cleanup.
