# Gas revision evidence

The 27 November diagnostics confirm the provider setting is now 39.3 MJ/m3
(11.16382 kWh/m3), replacing 975.3. Four previously inflated nonzero intervals
now have conflict flags; conflict alone does not prove a corrected reading.

Retain actual observed kWh and m3 pairs separately when the provider setting
is plausible and the pair matches the documented volume correction and
three-decimal rounding. Separate settings and conflicting readings are
tracked, with a bounded store, restart persistence, nonzero CSV comparison
and DST-aware day completeness. Never synthesize missing readings, rewrite
original raw observations, change CSV, update finances, ROI or control, or
grant settlement authority. Actual bill calorific values can vary over time.
A complete observed day is not a verified billed day.
