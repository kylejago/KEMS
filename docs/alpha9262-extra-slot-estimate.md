# EV-only charging estimate and backlog acceptance

Alpha9.261 is live. The supplier gas calorific value is confirmed as 975.3,
which explains the 277.05 kWh/m3 conversion. Correct the provider's account
configuration using the actual bill calorific value; do not guess or rewrite
historical gas data. Require new valid nonzero overlap evidence.

The owner accepts brief battery discharge at the start of Ohme extra charging;
the reactive hold and release were observed on 27 November. No pre-arming or
new inverter writes are needed. The confirmed policy is EV-only extra discount,
not whole-house cheap rate. The estimate uses short adjacent observed samples
with smart-charge/policy evidence, no reward event, corroborated tariff,
fresh power, adequate grid import and no material PV or battery discharge.
It excludes uncertain samples, gaps and half-hour boundary crossings. Retained
trace estimates are not complete session totals or actual settlement and never
change ROI, the existing import ledger, tariff or physical commands.

Remaining: independently verified discounted EV energy/settlement and durable
financial reconciliation; source gas setting correction and validation;
bounded supplier history already querying; exact Power Down baselines still
unavailable; independent FoxESS meter provenance and Recorder database
persistence; solar-only pilot; exact-cache serialization optimization.
