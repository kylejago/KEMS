# KEMS 0.7.0-alpha7.52 — tomorrow no-reserve and rounding cleanup

Alpha7.52 closes two reporting inconsistencies found in the live Alpha7.51
acceptance diagnostics on 21 August 2026.

## Tomorrow progressive publication

The active current-day Agile plan already follows the Alpha7.46/7.47 policy:
when Octopus has simply not published a future price yet, KEMS does not reserve
battery energy for that unknown price. It allocates against the prices it knows
and re-ranks when the missing price arrives.

The separate tomorrow progressive-publication state was still exposing the old
Alpha7.41 reserve model. In the captured case tomorrow had **46/48** published
prices, with 23:00 and 23:30 missing, and diagnostics reported **7.0 kWh** of
unknown-slot capacity reserved.

Alpha7.52 makes a clean partially published tomorrow horizon use the same
no-reserve reporting policy:

- known prices remain usable as progressive planning evidence;
- unpublished prices receive **0.0 kWh** reserved capacity;
- no price is invented;
- KEMS records that the plan will be re-ranked when additional prices publish;
- a retrieval error remains conservative and does not receive the no-reserve
  relaxation.

This patch does not weaken current-day deadline safety or change executable
battery dispatch. When tomorrow becomes the active day, the established
current-day safety layers still decide what may actually run.

## Sub-rounding residuals

The same acceptance diagnostics showed **35.109 kWh** exportable and **35.108
kWh** planned, leaving a mathematical **0.001 kWh** residual. That is within the
existing 0.01 kWh target-covered tolerance but was still displayed as a real
unaccounted requirement and could leave the coverage field blank.

Alpha7.52 normalises reporting-only residuals at or below 0.01 kWh to:

- **0.0 kWh** truly unaccounted requirement;
- **100.0%** published-price plan coverage;
- target covered = true.

The raw residual is retained as diagnostic evidence. A real reserve or a
residual above the tolerance is never hidden.

## Safety

Power Down and Happy Hour priority are unchanged. Deadline and minimum-SOC
protections are unchanged. Real FoxESS hardware writes remain blocked until the
separate commissioning/control gates explicitly permit them.
