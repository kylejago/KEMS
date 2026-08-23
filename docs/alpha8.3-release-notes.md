# KEMS 0.8.0-alpha8.3

KEMS `0.8.0-alpha8.3` is a Full KEMS Agile dispatch-reconciliation maintenance release.

It keeps the established Full KEMS Agile economic policy:

- the battery still targets **100%** when charging, even when the overnight window cannot physically reach it;
- the normal pre-cheap/export reserve remains **10%**;
- the configured **23:30–05:30** cheap period remains the authoritative house/battery charging window;
- after that window, available solar normally recovers remaining battery headroom, but **100% is a charge/recovery aim, not a hard gate** that blocks a better export opportunity;
- the configured overnight replacement price is the ordinary battery-export economic floor;
- normal battery export is allocated toward the **highest-value feasible Agile slots** while retaining house/reserve, inverter, export-limit and deadline constraints;
- a high-confidence solar forecast acts as a **timing/headroom constraint**: if headroom must exist before incoming solar would otherwise spill, KEMS moves only already-planned battery export into the highest eligible pre-headroom Agile slots above the overnight replacement-cost floor;
- forecast headroom no longer requires the earlier slot to beat the expected spill-period price by an extra fixed margin; the spill-period rate remains useful evidence, not a second export floor;
- when export must be moved earlier for forecast headroom, the lowest-value later planned allocations are reduced first so stronger later prices are preserved wherever physically possible;
- forecast solar-headroom re-timing must never increase the day's planned battery export, weaken protected house energy, or lower the 10% reserve;
- the later deadline plan remains able to discharge sufficiently toward the 10% pre-cheap target even if solar never physically reaches 100%;
- the battery may still support the home while solar is recovering battery SOC;
- extra Intelligent daytime slots remain non-authoritative for KEMS battery control;
- normal Agile price ranking, forecast protection, deadline reconciliation and Power Down priority remain in place.

The release reconciles the post-plan views of Full KEMS Agile so they describe the same charge decision:

- Weekend Happy Hour free charging is included in the main Agile day replay instead of being added only as a separate SOC overlay;
- the current Full KEMS Agile routing snapshot carries the final battery charge target during overnight cheap charging and Happy Hour;
- grid import/export is published as one net site-meter direction for the final charging route;
- the Agile independent shadow candidate carries the same charge target instead of hard-coding zero charge;
- the old Happy Hour direct graph override is suppressed once the final route owns presentation;
- once a configured Weekend Happy Hour has ended, `KEMS Weekend Happy Hour planning` automatically turns off while retaining the completed event as same-day replay/diagnostic evidence.

KEMS Web / Pi / PWA remains `0.8.0-alpha8-web.1` (unchanged).

The ESP32 panel remains `0.8.0-alpha8-panel.0` (unchanged).

Real FoxESS hardware writes remain blocked. This release changes simulation/shadow reconciliation only and does not commission or enable physical control.
