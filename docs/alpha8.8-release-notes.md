# KEMS 0.8.0-alpha8.8

Alpha8.8 is an audit-quality Home Assistant/dashboard maintenance release for the automatic Weekend Happy Hour discovery introduced in Alpha8.7. It does not change the Agile dispatch policy, EV charging policy, Pi/Web release, managed panel firmware, settlement rules or hardware-write boundary.

## Retained automatic Happy Hour evidence

- KEMS now stores the last confidently classified automatic Octopus Weekend Happy Hour in Home Assistant durable storage.
- When BottlecapDave Octopus Energy later removes the completed event from its live Power Up coordinator, KEMS retains the automatic source, event identifiers, account, start/end, duration and classification evidence instead of reverting the completed plan presentation to manual fallback.
- Retained automatic events are reported as `retained_upcoming`, `retained_active` or `retained_completed` according to the current time.
- Live automatic evidence remains authoritative whenever BottlecapDave is still publishing the joined event.
- Ambiguous live Power Up data never falls back to retained evidence; KEMS continues to fail safe to the manual controls.
- A genuinely newer current/future manual Happy Hour is never hidden by an older retained automatic event.
- Retained evidence older than 35 days is preserved as available history but is not promoted back into the active Happy Hour plan.
- Storage restore is non-blocking; after a Home Assistant restart, retained evidence is restored without delaying KEMS setup and is used on the next normal planning pass once loaded.

## Full KEMS Agile dashboard

- The existing Weekend Happy Hour card now also reports whether its automatic event evidence is `live` or `retained`.
- The established source/start/end/duration and manual-fallback presentation remains unchanged.

## Unchanged coordinated components

- KEMS Web / Pi / PWA / public: `0.8.0-alpha8-web.2` (unchanged)
- managed ESP32 panel: `0.8.0-alpha8-panel.1` (unchanged)
- Power Down remains higher priority than Happy Hour
- Happy Hour remains higher priority than normal Agile price dispatch
- selectable EV charging policy remains unchanged
- no Home Assistant service call to Octopus or Ohme is added
- no FoxESS hardware write is added

Real hardware writes remain blocked.
