# Optional Octopus supplier half-hour reconciliation

**Introduced in alpha9.231.** This is an owner-initiated, read-only forensic
comparison in the **KEMS diagnostic export**. It is not a live Octopus tariff
integration and does not authorise charging, financial rewrites or historical
backfill.

## Prepare the private files

Export **electricity import** and **electricity export** *half-hourly* usage CSVs
from your Octopus account. Keep them private; do not commit them to GitHub.

On your Home Assistant host, create the folder `/config/kems_supplier_evidence`
and copy the two CSVs using these exact names:

- `/config/kems_supplier_evidence/octopus_import.csv`
- `/config/kems_supplier_evidence/octopus_export.csv`

These must be the raw Octopus CSVs containing `Consumption (kwh)`,
`Estimated Cost Inc. Tax (p) if applicable`, `Start` and `End`.
The latter two must contain timezone-aware ISO timestamps and each interval
must be exactly 30 minutes.

The integration reads those **fixed paths** only when a KEMS diagnostics
download is requested, via the Home Assistant executor. No Home Assistant
restart is required **after** copying the files. A missing file is not a fault
and appears as `awaiting_local_octopus_csv` or an explicit file-load error.

## Inspect the evidence

Download a new KEMS diagnostic from **Settings → Devices & services → KEMS →
Download diagnostics** (exact menu labels may vary by Home Assistant version).
Look for `data.historical_supplier_meter_reconciliation`:

- `supplier_import` and `supplier_export`: per-day 46/48/50 half-hour
  coverage, kWh and *estimated* energy costs or export earnings **excluding**
  standing charges. An ongoing/incomplete day is not certified complete.
- `grid_import_comparison` and `grid_export_comparison`: signed supplier minus
  KEMS recorded kWh differences. The 2% threshold is an **investigation-only**
  tolerance, not meter certification or billing reconciliation.
- `import_energy_cost_evidence` and `export_energy_income_evidence`: estimated
  differences from KEMS's calculations, with explicit tariff-scope caveats.
- `extra_cheap_import_candidate_slots`: historical estimated supplier prices
  resembling that day's overnight rate **outside 23:30–05:30**, where there is
  enough daytime price evidence. This does not prove live Intelligent dispatch.
- `supplier_export_half_hour_examples`: up to 12 largest supplier export
  intervals per day, intended for separate Agile digital-twin investigation.
- `simulation_replay_complete_unchanged`: unchanged by this feature. Physical
  meter corroboration is separate from missing KEMS simulation observations.

Invalid, duplicate, timezone-naive or non-half-hour entries cannot silently
certify daily completeness. CSVs are capped at 2 MB each and symlinked files
and directories are rejected. These are read-only local files; KEMS neither
uploads them nor changes or deletes them. Keep originals and replace the
copies manually when newer Octopus readings arrive.

## What it never does

No automatic correction to KEMS import/export totals, import costs, export
income, Happy Hour refunds, Power Down rewards, ROI or simulation completeness;
no live Intelligent dispatch inference, physical inverter commands or EV
changes. A successful Octopus CSV comparison is **not** final Octopus
settlement, and shared FoxESS/CT measurement error may still exist.
