# Alpha9.160 — pre-cheap house-demand horizon without weakening physical protection

**Incident:** 29 October 2026 at 21:45 KEMS stopped paid export at 25% reported SOC despite cheap charging at 23:30. The proven physical battery lower bound was 12.912 kWh. KEMS budgeted 2.512 kWh forecast house demand to calendar midnight, even though the cheap period starts 30 minutes earlier, and added the separate 2.0 kWh minimum house buffer. The observed 0.64 kW house load and predicted 1.869 kWh to off-peak highlighted unnecessary over-reservation.

## Scope and behavior
- Where an earlier cheap-start is **strictly before UTC midnight** and no more than four hours away, prorate the remaining-calendar-day demand to that confirmed deadline. Never allow this to be below *fresh physical measured house load times hours to cheap*, and never above the conservative full-day forecast. When source age >90 seconds, missing or non-finite load, stale field, missing deadline, cross-midnight, or ambiguous clock basis, **do not shorten** the forecast.
- Apply the identical pure helper to the rolling physical planning allowance and the final independent FoxESS physical command guard; the last veto remains authoritative.
- **Retain the complete independent 2.0 kWh or 20% house buffer** (whichever is larger) and the full 15% battery target, conservative physical SOC continuity, minimum 10% hard safety floor, EV/Ohme hold, 7 kW DNO limit, commissioning, tariff ranking, Power Down and Happy Hour overrides. No changes to startup settlement (Alpha9.159 preserved).
- Do not credit forecast solar from after the cheap deadline into the shortened horizon (conservatively set solar credit zero on this path). Existing solar credit operates only when keeping full-day demand.
- Expose both calendar-day and precheap house forecast values, basis and house buffer in diagnostics; do not mislabel no-export as a proven physical 15% target reached.
- The proportional approximation is intentionally *not* a new guarantee about load shape: the existing 2kWh buffer, fresh-load floor and live physical guard absorb uncertainty. The physical report is re-evaluated on each scan.
- The correction is intentionally conservative around overnight or DST boundaries, where it retains full-day protection. A future timezone-aware exact hourly house model would make this finer-grained.

## Expected recreation
At 21:45 with cheap start 23:30, learned 2.512 kWh until midnight, fresh 0.64 kW, conservative stored energy 12.912, capacity 56.42 and discharge efficiency 95%: new forecast ~1.954 kWh, stored home protected ~4.057 kWh including the original 2kWh margin, minimum 15% reserve 8.463 kWh, verified additional export headroom ~0.392 stored / 0.373 AC kWh **before instantaneous control caps**. Previously the zero export budget was caused by ~4.644 kWh protected home energy. No guarantee of future export: current physical proof and tariff must qualify.
