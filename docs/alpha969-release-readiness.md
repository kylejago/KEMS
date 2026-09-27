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

## Blocking findings

1. No retained, independently corroborated physical data demonstrates
   EV-only grid supply and house-only battery support when the Ohme ePod is
   active on the KH7 AC bus. Software power accounting cannot prove physical
   power-source isolation.
2. No installer-controlled proof demonstrates the new below-floor Force Charge
   start, limiter, target-stop, MinSOC and restoration sequence under actual
   inverter/charger readbacks.
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
enforcing EV-grid/home-battery separation (or explicitly retain the physical
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
