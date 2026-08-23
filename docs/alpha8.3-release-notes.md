# KEMS 0.8.0-alpha8.3

KEMS `0.8.0-alpha8.3` is a Full KEMS Agile dispatch-reconciliation maintenance release.

It keeps the established Full KEMS Agile economic policy:

- the battery still targets **100%** when charging, even when the overnight window cannot physically reach it;
- the normal pre-cheap/export reserve remains **10%**;
- the configured **23:30–05:30** cheap period remains the authoritative house/battery charging window;
- after that window, if the battery is still below 100%, available solar normally recovers the remaining headroom before ordinary deliberate battery export resumes;
- **100% is a charge/recovery aim, not a hard gate that blocks economically useful forecast headroom export**: when high-confidence solar is expected to fill the battery later and force lower-value solar spill/export, KEMS may move already-planned battery export into an earlier, better-priced Agile slot to create that headroom;
- forecast solar-headroom re-timing must never increase the day's planned battery export, weaken protected house energy, or lower the 10% reserve;
- the later deadline plan must remain able to discharge sufficiently toward the 10% pre-cheap target even if solar never physically reaches 100%;
- the battery may still support the home during solar recovery;
- extra Intelligent daytime slots remain non-authoritative for KEMS battery control;
- normal Agile price ranking, forecast protection, solar-headroom optimisation, deadline reconciliation and Power Down priority remain in place.

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
