# Alpha9.265 Power Down reconciliation

Optional private local reference: `/config/kems_power_down_awards.json`.
Format `kems-power-down-awards-v1`, with `rows` containing timezone-aware
half-hour-aligned `start`, `end`, and explicit integer
`rewarded_octopoints`. Only confirmed rows; a pending session is not zero.
Load at integration setup; no credentials or private data in the repository.
Financial commissioning-date filtering remains in the existing ROI ledger.

Exact event windows match retained IDs, otherwise a financial-only window key
is used. A subsequently known ID replaces that alias. Explicit positive
supplier awards for matched events do not require KEMS physical success.
The current live feed's ambiguous zero is still withheld; an explicit local
confirmed zero is permitted. Local snapshots never supersede an already
confirmed award. No claims of supplier cash redemption or physical success.

The existing live baseline recorder remains authoritative for estimates only.
Complete matched half-hour baseline and actual meter readings yield a
provisional bonus, clipping reduction independently per half-hour.
Confirmed supplier awards replace that estimate. Ordinary Agile export income
is not added again. No historical baseline reconstruction or Recorder baseline
queries; historical electricity charge recovery is separate.

Live baseline availability needs a new natural session; do not infer an
upstream sensor fault from an after-event diagnostic alone. No physical
control or base electricity/gas cost ledger changes.
