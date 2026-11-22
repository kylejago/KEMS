# Alpha9.249 release acceptance — 22 November 2026

This is a read-only release evidence note. No FoxESS, Home Assistant control,
tariff, battery, EV, Power Down, Happy Hour, or update authority changes.

## User-approved policy

The operator confirmed that a plan may approach **10% at 23:30** through
household-only battery supply. **Deliberate grid export must stop at 15%**;
household supply may continue toward the independent **10% absolute floor**,
without making either floor a compulsory ending target.

## Reproduction and fix

On installed alpha9.248 at 13:47 GMT, Home Assistant reported 88% physical
FoxESS SOC. The paid-Agile physical ledger held 25 verified samples and a
conservative 43.019 kWh bound, equivalent to 87.294% planning SOC. The
separate comparison digital twin was only 59.2%.

The future-flow display incorrectly mixed twin SOC with physically planned
household and grid-export allocations, predicting 0% while displaying future
discharge. The "now and next" card also overwrote mixed house-plus-export slots
with "Battery powers house · no deliberate export".

The alpha9.249 changes in PR #538 anchor live future-flow displays to
same-scan verified physical energy when available, preserve twin independence
and the 15% grid-export / 10% household split, and correct action precedence in
both canonical and packaged dashboards. There are **no new inverter writes**.
The strict physical export guard remains final authority.

## Verification and installation distinction

- PR #538 pre-merge full Python 3.13 and 3.14 suites, Black/Ruff, ESPHome
  compile, HACS and hassfest all succeeded.
- PR #538 was merged into main as `65abe76dc4315124b48fbb435190a01134b39a0d`.
- Publication requires fresh Validate, HACS and hassfest **push** checks on
  the exact final main commit. A green PR head is not enough.
- The previously observed installed version is alpha9.248. Publishing
  alpha9.249 alone does not install or restart it on Home Assistant. Keep the
  usual automatic **06:00–06:30** safe-first window and avoid updates during
  live paid export or other protected activities.
- The updated flow and SOC are **forecasts**, not proof of actual 16:00
  inverter export; examine post-slot diagnostics to verify physical dispatch.
