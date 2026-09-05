# KEMS Alpha9

Alpha9 starts from the fully cleaned and proven Alpha8 baseline. The first Alpha9 release is a coordinated parity/consolidation release, not a new control release.

## Alpha9.0 coordinated baseline

- KEMS: `0.9.0-alpha9.0`
- Pi Web: `0.9.0-alpha9-web.0`
- Public Web: `0.9.0-alpha9-public.0`
- Panel: `0.9.0-alpha9-panel.0`

The four tracks have independent version identities. Pi Web and Public Web may share a repository, but they use separate version sources, tags and release publishers. Panel has its own release identity even though KEMS remains responsible for managed delivery through Home Assistant/ESPHome.

## Behaviour boundary

Alpha9.0 preserves the proven Alpha8.79 KEMS runtime and the Web.11/Panel.1 behaviour that followed the cleanup work. It does not enable FoxESS writes or change optimisation/control policy.

Real FoxESS control remains fail-closed until physical device mapping, commissioning, parity and first-write safety gates are proven. In particular, Alpha9.0 does not set `commands_permitted` or `safe_to_write_hardware` true and does not add Home Assistant service calls for physical control.

## Validation boundary

Alpha9.0 is not releasable until the frozen exact branch heads pass their complete validation suites, fresh pull-request checks pass on those same heads, main is confirmed not to have drifted, and the guarded merges and post-merge exact-main proofs succeed.

The frozen Alpha9.0 candidate carries generation-aware historical release contracts: current-version assertions accept the Alpha9 generation reset while immutable Alpha8 release-note evidence remains pinned to its original release identities.

## Why Alpha9

Alpha8 accumulated the implementation, parity work and cleanup needed to establish a clean product boundary. Alpha9 provides a single coordinated baseline from which KEMS, Pi Web, Public Web and Panel can advance independently without losing the ability to state an exact compatible four-track set.

## Alpha9.1 KEMS-only dashboard patch

- KEMS: `0.9.0-alpha9.1`
- Pi Web remains: `0.9.0-alpha9-web.0`
- Public Web remains: `0.9.0-alpha9-public.0`
- Panel remains: `0.9.0-alpha9-panel.0`

Alpha9.1 is presentation-only. It trims Jinja control-block whitespace around the dynamic **Component verification** and **Recent updates** Markdown rows so Home Assistant keeps those rows inside their tables. It does not change optimisation, simulation, commissioning, panel firmware, web behaviour or FoxESS write safety.

Candidate validation note: Alpha9.1 is frozen as a KEMS-only presentation patch; Pi Web, Public Web and Panel remain on their Alpha9.0 baselines.


## Alpha9.2 KEMS-only Happy Hour policy/control patch

- KEMS: `0.9.0-alpha9.2`
- Pi Web remains: `0.9.0-alpha9-web.0`
- Public Web remains: `0.9.0-alpha9-public.0`
- Panel remains: `0.9.0-alpha9-panel.0`

Alpha9.2 makes Weekend Happy Hour a strict per-reward-hour import authority. Every booked reward hour has its own **16 kWh** cap. Unused allowance does not carry into the next hour and a later reward hour cannot be borrowed early. The active-hour budget reserves the maximum useful battery charge first, protects projected non-EV home import next, and exposes only the remainder to EV charging. Once the current reward-hour ledger reaches 16 kWh, Happy Hour authority ends for the rest of that reward hour and KEMS immediately returns to normal tariff logic; an independently confirmed overnight/Intelligent cheap authority may still permit import, but Happy Hour alone cannot cause paid expensive import beyond its cap.

The default EV policy continues to allow the configured overnight cheap window plus a daytime Intelligent dispatch only after KEMS' existing fail-closed multi-signal confirmation. Raw/stale Intelligent flags and Agile price alone do not authorise EV charging. Happy Hour is separate from Intelligent dispatch authority.

Alpha9.2 also adds an explicit opt-in **Happy Hour Ohme control** switch. When enabled, KEMS may temporarily select the Ohme `Max charge` mode only for an automatically verified active Octopus Happy Hour with a complete hourly import ledger, a healthy safety envelope and sufficient allowance remaining after the battery/home reserve. KEMS preserves the pre-event Ohme mode and restores it when its Happy Hour authority ends. Manual Happy Hour fallback remains planning/shadow only and cannot start the car. Slow scans, Power Down, emergency stop, island operation, stale/unsafe data or an incomplete reward ledger all fail closed.

This is the only new physical/cloud write path in Alpha9.2. **FoxESS writes remain hard-blocked** pending physical commissioning and parity proof.
