# KEMS Alpha7.50 — no-reserve row reporting

KEMS `0.7.0-alpha7.50` fixes a reporting contradiction in Full KEMS Agile when Octopus has not yet published a future Agile half-hour price.

Alpha7.46/7.47 already changed the optimiser policy so a verified clean Octopus publication gap does **not** reserve discretionary battery energy for the unknown price. The optimiser allocates exportable battery energy across the prices that are already published and re-ranks the plan when the missing price arrives.

The 21 August acceptance diagnostics showed the effective plan correctly had `0.0 kWh` provisional reserve and all exportable battery energy allocated, but the 23:00 row still displayed:

`Waiting for Octopus price — 3.500 kWh capacity reserved`

That 3.500 kWh came from inactive bounded-partial safety evidence, not from the executable plan.

Alpha7.50 reconciles the reporting layer so that, for a verified `octopus_missing_price` publication gap, when bounded-partial dispatch is inactive and the effective provisional reserve is zero, the row now reads:

`Waiting for Octopus price — no capacity reserved; re-rank when published`

The battery-plan summary is reconciled to the same effective no-reserve policy. Retrieval failures and an actually active bounded-partial path remain conservative and continue to show their genuine safety reservation.

This release changes reporting and diagnostics only. It does not change price ranking, deadline protection, Power Down, Happy Hour, battery routing, or real control permissions. Real FoxESS hardware writes remain blocked.
