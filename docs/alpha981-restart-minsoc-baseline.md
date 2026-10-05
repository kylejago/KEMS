# Alpha9.81 — restore the physical MinSOC baseline after EV/cheap hold

## Live defect

The 4–5 October 2026 overnight test proved the Alpha9.75 EV hold and freeze path in real operation: while Ohme charged at about 3 kW in the cheap window, FoxESS battery power stayed approximately neutral and the grid supplied the EV.

After the cheap period ended at 05:30, however, the physical MinSOC-on-grid remained at 89%. Diagnostics showed no active EV hold, no pending Intelligent hold and no source-grace latch, but `previous_min_soc_on_grid`, observed MinSOC and the effective MinSOC were all 89%. The home therefore imported its roughly 0.6 kW load from the grid instead of resuming battery supply.

## Root cause

The FoxESS backend restored its pre-KEMS Work Mode and MinSOC during ownership release, but treated a successful Home Assistant service call as a completed restore without requiring the resulting entity readback to match. It then cleared KEMS ownership.

On a later takeover, `_async_take_ownership()` captured the current physical MinSOC as the new pre-KEMS baseline. If the prior 89% EV hold was still physically/readback-visible, that temporary hold became the remembered baseline. Alpha9.71 then correctly preserved the wrong value outside cheap time.

## Alpha9.81 behavior

Alpha9.81 makes ownership release readback-verified. KEMS does not clear FoxESS ownership until both the local Work Mode and MinSOC entity read back at the requested restore targets. If a restore command is accepted but readback has not converged, ownership remains persisted so a restart cannot recapture the lingering temporary hold as a fresh baseline.

The release also repairs the already-observed contaminated state, but only with strong physical evidence:

- cheap time is not confirmed;
- no EV hold is latched;
- no Alpha9.75 source grace is active;
- no Alpha9.76 pending Intelligent hold is active;
- No Paid Export and explicit Control/Master/commissioning gates remain active;
- the remembered baseline is above the current normal non-cheap target;
- live MinSOC and KEMS' last physically verified EV hold both match that remembered value;
- the reviewed Home Assistant MinSOC number entity exposes a lower minimum.

Only then is the contaminated baseline repaired to that reviewed entity minimum. On the commissioned KH7 this is 10%.

The same control cycle can therefore return Self Use MinSOC to 10%, allowing the battery to resume supplying the house outside cheap periods.

## Preserved safety scope

Alpha9.81 does not change the proven Alpha9.75 verified EV hold/freeze contract, Alpha9.76 pending Intelligent publication-gap hold or Alpha9.77 restart commissioning bridge. It adds no new FoxESS command, deliberate Force Discharge, import/export power-limit write, paid/Agile export authority, automatic Master enable or direct Ohme charging command.
