# Alpha9.75 — verified EV hold and source uncertainty grace

## Live defect

The 30 September 2026 Alpha9.74 live trace exposed two related EV-protection defects during an Intelligent extra slot.

1. KEMS could report `freeze_ev_hold` even while FoxESS MinSOC-on-grid still read 10%, so the claimed frozen EV hold had never been physically established.
2. Brief Ohme/Intelligent source dropouts could normalise to a non-cheap snapshot, clear the persisted EV floor, and restore the pre-KEMS 10% MinSOC baseline. When the extra slot re-confirmed, the EV could draw from the battery for one control cycle before KEMS re-applied the elevated floor.

The same trace also proved that once MinSOC was physically raised to 73–74%, the battery stayed approximately neutral while the grid supplied the EV.

## Alpha9.75 contract

### Physically verified freeze

An EV hold may be reported as frozen only when the physical MinSOC state is proven.

- A fresh FoxESS MinSOC readback at or above the latched EV floor is authoritative proof.
- A fresh readback below the latched floor blocks freeze, even if an older successful verification exists.
- Only when the current readback itself is unavailable may KEMS fall back to a persisted last verified MinSOC.
- The persisted verification is cleared when KEMS releases FoxESS ownership.
- Force Charge is never frozen.

This means a latched 73% hold with a live 10% readback can no longer report `freeze_ev_hold`.

### 90-second hold-only source grace

If a cheap EV session was positively confirmed and an EV MinSOC floor is already latched, a temporary raw Home Assistant source state of `unknown` or `unavailable` may retain that hold for up to 90 seconds.

The grace:

- preserves only the already-existing EV hold;
- issues no new FoxESS command;
- does not turn stale or unknown data into new cheap-period authority;
- does not authorise Force Charge;
- releases immediately on explicit EV disconnect or a usable explicit non-cheap state;
- releases on No Paid Export exit, Control/Master/commissioning opt-out, emergency stop, island/grid loss, or grace expiry.

If the hold is not physically verified during source uncertainty, KEMS performs no new write and reports `hold_grace_unverified`; it does not claim the battery is protected.

### Two-second settling refresh

Alpha9.73 already requests an immediate coordinator refresh for discrete Ohme and Octopus authority transitions. Alpha9.75 retains that immediate refresh and adds one bounded follow-up refresh two seconds later.

The follow-up does not bypass any tariff, commissioning, freshness, preflight, site-limit, EV, island or FoxESS write-authority gate. It only gives related Home Assistant states one additional opportunity to settle after an event-driven transition instead of waiting for the normal 60-second analysis poll.

## Hardware authority

Alpha9.75 adds no new hardware command surface. Existing reviewed Self Use, confirmed-cheap Force Charge and MinSOC-on-grid authority remains unchanged. Deliberate Force Discharge, direct Ohme commands, import/export power-limit writes, paid/Agile export control and automatic Master enable remain blocked.
