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
