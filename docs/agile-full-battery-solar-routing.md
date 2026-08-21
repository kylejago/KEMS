# Full KEMS Agile full-battery solar routing — 0.7.0-alpha7.48

Alpha7.48 fixes a current-routing display mismatch that could make Full KEMS Agile appear to charge an already-full simulated battery.

## Reported case

The reproduced operating snapshot had:

- simulated battery SOC: **100%**
- solar generation: **3.535 kW**
- house demand: **0.705 kW**
- displayed battery net: **-2.830 kW** (charging)
- displayed grid export: **0.000 kW**

That combination is physically inconsistent. At 100% SOC the battery has no charge room. With the battery held by the Agile price plan, the correct export-tariff-active routing is therefore:

- solar -> home: **0.705 kW**
- solar -> battery: **0.000 kW**
- battery -> export: **0.000 kW** until the selected Agile export slot
- solar -> grid: **2.830 kW**, subject to inverter/export limits
- grid import: **0.000 kW**

The battery is not deliberately discharged early merely because it is full. Battery-export timing remains controlled by the rolling Agile price plan.

## Root cause

The Agile day replay already enforces battery capacity. The mismatch was in the current operator snapshot: Alpha7.30 rebuilt solar routing from the proposal digital twin and then substituted the independent Agile rolling battery candidate. If the proposal replay and the Agile replay had different SOCs, proposal solar-to-battery power could survive into the display even though the authoritative Agile SOC was already 100%.

Alpha7.48 reconciles the final current-routing snapshot against the authoritative Agile SOC. At 100% it forces solar-to-battery and grid-to-battery to zero, preserves the already-selected solar-to-home route, and sends remaining PV to export when an export tariff is active. If export is unavailable or physical export/inverter headroom is exhausted, the remainder is reported as curtailment instead of impossible battery charging.

## Partial-slot capacity rule

The existing Agile replay capacity guard remains authoritative below 100% SOC. For example, a **99%** battery may accept only its actual remaining stored-energy room. If it reaches 100% part-way through a half-hour, the remainder of that same interval's surplus solar remains available for export rather than being assigned to battery charging for the whole slot.

This preserves three separate decisions:

1. physical capacity decides whether the battery can charge;
2. solar serves the home before normal daytime surplus routing;
3. the Agile optimiser decides when deliberate battery discharge/export is worthwhile.

Real FoxESS hardware writes remain blocked.
