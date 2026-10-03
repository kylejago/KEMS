# Alpha9.77 — restart-safe commissioning proof

## Live defect

On 3 October 2026 Home Assistant was deliberately restarted immediately before
the EV was connected. KEMS correctly rebuilt its physical commissioning evidence
from scratch, but that left `ready_for_control=false` for the sample-collection
window. During the resulting Intelligent extra slot, KEMS had released FoxESS
ownership and the battery supplied most of the EV load.

This was a lifecycle defect, not an Intelligent-slot detection defect.

## Change

Alpha9.77 keeps the raw FoxESS commissioning observations session-scoped. It adds
a separate persisted **proof certificate** only after a session has freshly
passed the complete physical telemetry proof.

The certificate records the authoritative physical source entity/unit
fingerprint, the battery-direction evidence-source fingerprint, and the
configured battery power sign convention.

After a normal HA/KEMS restart, the certificate may bridge only the temporal
`WAIT` states for:

- FoxESS telemetry stability;
- battery power direction; and
- whole-site power balance.

Fresh observations continue rebuilding normally in the new coordinator session.

The bridge also requires the current post-restart physical snapshot to be
complete and non-stale, to have no battery-direction evidence contradicting the
stored sign convention, and to pass a one-snapshot whole-site power-balance
check. This prevents an identity match from masking contradictory live data.

## Fail-closed boundary

The bridge is valid only while the current source and direction fingerprints
exactly match the certificate and the current physical mapping/unit gates remain
ready.

It never changes a `FAIL` to `PASS`. A mapping/unit/sign mismatch, unavailable
physical source, grid-direction failure, unsafe plan, command-surface failure,
FoxESS version mismatch, emergency/island/grid-loss state, explicit control
opt-out, or any other existing authority gate still blocks live writes.

Raw samples are not persisted and the certificate cannot create paid-export,
Force Discharge, direct Ohme, import/export-limit, or automatic Master-enable
authority.

## Validation target

After Alpha9.77 has completed one fresh commissioning session and stored the
certificate:

1. confirm Control + Commissioned + Master are enabled and KEMS is ready;
2. restart Home Assistant;
3. verify the first usable post-restart scan reports the restart certificate as
   matching and the temporal bridge active while the fresh sample window rebuilds;
4. connect the EV during an Intelligent cheap slot;
5. verify KEMS retains FoxESS authority and applies the existing EV MinSOC hold
   instead of allowing the battery to feed the EV;
6. confirm the bridge disappears once fresh commissioning evidence is complete.
