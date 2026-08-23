# KEMS 0.8.0-alpha8.9

Alpha8.9 is a reporting-truth and regression release for the Full KEMS Agile half-hour decision table. It fixes a presentation defect exposed on 23 August 2026, when a Home Assistant/KEMS runtime gap left several already-past settlement slots carrying the replay placeholder `future slot`; the dashboard incorrectly removed that placeholder and displayed the empty result as a deliberate `Hold battery / normal solar` decision.

Alpha8.9 does not change the proven rolling Agile dispatch algorithm, event priority, EV charging policy, settlement rules, Pi/Web release, managed panel firmware or hardware-write boundary.

## Truthful settlement-slot evidence

- A past slot whose retained replay still contains only `future slot` is now shown as **No KEMS decision recorded — runtime/data gap**.
- That row is explicitly marked with **No retained KEMS sample** evidence instead of implying that KEMS deliberately held the battery.
- Genuine completed replay rows remain marked as **Recorded simulation**.
- Current/future planned exports and intentional holds are marked as **Live rolling plan** only when the rolling-plan sensor is actually available.
- If a known current/future price exists but no live rolling plan is available, KEMS reports **Waiting for live rolling plan — no decision published** rather than inventing a hold.
- Power Down / Happy Hour rows identify event-priority evidence, while the overnight cheap window identifies tariff-policy evidence.
- The dashboard table gains a compact **Evidence** column so operator intent and data provenance are visible together.

## Profit-first regression

The rolling optimiser itself remains byte-identical to the proven Alpha7.16/canonical Alpha8 runtime. Alpha8.9 adds an executable regression using the price shape that exposed the confusing 23 August 2026 dashboard:

- 15:30 at 12.79p
- 16:00 at 21.57p
- 16:30 at 21.08p
- 17:00 at 21.31p
- 17:30 at 22.44p
- 18:00 at 23.30p
- 18:30 at 23.64p
- later 12–16p settlement periods

With enough remaining physical discharge capacity and no deadline-forced current-slot requirement, the test requires the six higher-value 16:00–18:30 periods to be selected before the lower 15:30 and later 12–16p periods. This locks the existing highest-feasible-price-first behaviour while preserving the separate safety/deadline exception path.

## Unchanged coordinated components and safety

- KEMS Web / Pi / PWA / public: `0.8.0-alpha8-web.2` (unchanged)
- managed ESP32 panel: `0.8.0-alpha8-panel.1` (unchanged)
- automatic Octopus Weekend Happy Hour discovery/retention remains unchanged
- selectable EV charging policy remains unchanged
- Safety > Power Down > Happy Hour > permitted EV > normal Agile remains unchanged
- no Home Assistant service call to Octopus or Ohme is added
- no FoxESS hardware write is added

Real hardware writes remain blocked.
