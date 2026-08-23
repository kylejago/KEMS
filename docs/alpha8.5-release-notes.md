# KEMS 0.8.0-alpha8.5

Alpha8.5 adds the first explicit selectable EV charging policy to the KEMS shadow-control contract while keeping every real charger and inverter write blocked.

## Coordinated versions

- KEMS Home Assistant / managed dashboard: `0.8.0-alpha8.5`
- KEMS Web / Pi / PWA / public demo: `0.8.0-alpha8-web.2`
- ESP32 managed panel: `0.8.0-alpha8-panel.1`

## EV policy

The default **EV cheap-window mode** permits EV charging only during the authoritative configured **23:30–05:30** overnight cheap window. Daytime Intelligent slots and negative daytime Agile prices do not widen that window.

Home Assistant also exposes **EV surplus mode** and **EV disabled** as explicit selectable alternatives. Power Down remains higher priority than EV charging, including in the unusual case of an overlap with the overnight window.

Whenever KEMS permits EV charging, the desired shadow command holds battery-to-home, battery export and total battery discharge at zero so stored battery energy is not routed into the EV. If the real charger is still drawing power after KEMS has blocked charging, the shadow command keeps battery discharge/export isolated until that observed EV load disappears, except where a higher-priority Power Down action owns the dispatch.

## Presentation parity

The managed Home Assistant Full KEMS Agile view now shows the selected EV policy, actual connection/charging state, KEMS Allow/Block decision, EV power and the authoritative overnight-window state.

The managed 16×16 panel reports `0.8.0-alpha8-panel.1`. In Full KEMS Agile, a plugged-in EV that KEMS blocks is shown red; permitted charging keeps the existing magenta EV presentation. Live Data continues to represent actual charger state.

KEMS Web `0.8.0-alpha8-web.2` preserves the same distinction: **Live** follows actual Ohme telemetry, while the current **Simulated Full KEMS Agile** panel applies the KEMS EV Allow/Block decision. Historical EV chart data remains retained observed EV demand; Alpha8.5 does not fabricate an overnight shifted-energy replay that has not yet been proven by the accounting model.

The public demo may publish aggregate delayed EV kWh only after the existing minimum seven-day privacy delay. EV identity, connection state, SoC and charge times remain private.

## Existing Agile policy retained

- Battery overnight charge target remains **100%**.
- Reserve/export target remains **10%**.
- The authoritative ordinary cheap window remains **23:30–05:30**.
- Power Down remains higher priority than Happy Hour, and Happy Hour remains higher priority than normal Agile dispatch.

## Safety boundary

Alpha8.5 remains shadow/simulation only. It adds no Home Assistant service call to Ohme, no charger backend write, and no FoxESS hardware write. Real control permissions and commissioning gates are unchanged and hardware commands remain blocked.
