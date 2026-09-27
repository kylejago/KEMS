# Alpha9.69 — merge and release readiness

Date: 27 September 2026. Candidate PR #296, branch
`feature/no-export-cheap-routing-alpha969`; reviewed base Alpha9.68 main
`8663995905d8b272d8d10095eceafc7bf3e6a67a`.

## Verified source/CI

- Candidate `a48a060cf080485ba0d1d8930d1b7878030f60bd`: push and PR Validate,
  HACS and hassfest passed. Core validation reports 1,533 passing tests,
  Black, Ruff, Python compilation, dashboard checks; ESPHome panel compile passed.
- New no-export cheap routing is a proposed twin/shadow policy, **not** a
  physically commissioned KH7 energy-routing capability.
- `alpha969_routing_shadow_only` is checked by the FoxESS write authority,
  survives Happy Hour replacement of the operating reason, and forces the
  existing safe release path for this new plan. It does not grant any new
  hardware command.

## Confirmed property topology and existing KEMS data (27 September)

The owner confirms **grid and inverter enter the EPS/changeover equipment;
its downstream output feeds Henley blocks supplying both the main and EV
consumer units**. House and EV are therefore on a shared downstream supply,
not two independently selectable KH7 outputs. This description is sufficient
for planning; do not request the same wiring diagram again. The precise EPS
changeover/island isolation and EV shedding still require readback or installer
verification before island-mode authority is broadened.

Use the already configured KEMS Octopus/Ohme/FoxESS providers and snapshots:
Ohme status/power, FoxESS Load/PV/battery/grid powers, SOC, confirmed cheap
slot, source freshness, work-mode/MinSOC and existing retained history.
`Collector` already compares both EV membership hypotheses across three
consecutive balances and records `ev_load_in_house_load`; KEMS retains
read-only snapshots every 300 seconds. The snapshot history is not a
high-frequency synchronized physical commissioning trace, so a dedicated
read-only event capture or HA history around transitions may still be needed.
Current uploaded diagnostics captured with the EV idle cannot substitute for
actual charging transition measurements; this does **not** require the owner
to re-enter readings already available to KEMS.

Earlier live Alpha9.59 evidence already demonstrates bounded, confirmed-cheap
Force Charge at a 7 kW request, approximately 6.8 kW battery charge, 8.1 kW
site import and safe Self Use/MinSOC restoration. Reuse that as existing
proof, **not** as evidence of the new target-limited below-floor sequence
or simultaneous EV/grid and household/battery dispatch.

The engineering objective on the shared bus is a measured **site-level power
balance**: constrain total KH7 AC/battery output to verified non-EV demand
while checking that site grid import covers at least the equivalent Ohme
power (subject to PV/charging states and physical limits). This is a grid
allocation, not proof of electron/circuit isolation. Presently reviewed
Self Use/Force Charge/MinSOC authority cannot independently cap KH7 output
while retaining battery-to-house supply under EV load; enabling an additional
output-control mechanism would need its own measured fail-closed validation.
If the control cannot enforce this balance, retain the EV-active SOC hold
rather than claiming EV/grid isolation.

## Blocking findings

1. Existing KEMS measurements can identify and estimate EV demand, but no
   retained charging-transition evidence yet demonstrates a supported KH7
   output constraint plus the site-grid-import response necessary to achieve
   the target shared-bus EV/house allocation. Strict separate physical feeds
   cannot be created by software on the confirmed shared supply.
2. Existing Alpha9.59 Force Charge and restoration were physically observed;
   the new **below-floor to target** limiter, stop, transition and EV-overlap
   sequence remains unproven against actual readbacks.
3. The candidate planner selects the new Alpha9.69 route during a confirmed
   cheap period even in Control mode. Its physical write barrier correctly
   rejects that route, but this also suspends the previously reviewed
   Alpha9.67 cheap-period live write path. Thus merging the current PR would
   change existing live behaviour and cannot be called a transparent
   shadow-only update.
4. The manifest and bundle template still identify Alpha9.68. The automatic
   publish workflow keys off the manifest version and skips an existing tag;
   merging unchanged would **not** publish an Alpha9.69 release, irrespective
   of green CI. Do not bump the manifest or merge while the physical/behavioural
   gates remain open.

## Acceptable paths to a release

**A. Full physical Alpha9.69:** acquire the passive transition evidence in
`alpha969-physical-evidence-gates.md`; prove a supported KH7 means of
enforcing the measured shared-bus site-import/EV allocation (or explicitly retain the physical
EV-active fallback); validate the new below-floor command sequence and all
failure/ownership transitions. Only a separately reviewed and tested
write-authority change may lift the sticky shadow barrier. Retain accurate
readback and current/previous configuration restore proof.

**B. Distinct shadow-only release:** explicitly preserve the Alpha9.68
production Control-mode tariff target, work-mode/MinSOC and existing bounded
charging behaviour while exposing the Alpha9.69 simulation and diagnostic
readouts independently. Add cross-mode regressions proving existing live
commands and all higher-priority overrides are unchanged. This requires a
separate behavioural review and revised release scope; merely leaving the
current block in place is insufficient.

After the chosen scope is proven: ensure exact HEAD CI is all green, update
`manifest.json` and the canonical maintenance reason to
`0.9.0-alpha9.69`, revise identity assertions, freeze the candidate, merge
the reviewed PR, verify the merge SHA is on main, verify the release tag points
exactly at that merge commit, and verify the automatic release bundle and its
checksum. No implicit Pi/Web or panel component version bump. Do not publish
a tag pointing at the draft branch.

**Present decision:** HOLD — draft PR only, no merge, no new hardware writes,
no release identity bump. This is a factual release gate, not a CI failure.
