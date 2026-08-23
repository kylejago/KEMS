# KEMS 0.8.0-alpha8.7

Alpha8.7 makes Octopus Energy the preferred source for Weekend Happy Hour timing in Full KEMS Agile. It is a Home Assistant/dashboard maintenance release: KEMS Web / Pi / PWA / public remains `0.8.0-alpha8-web.2` and the managed ESP32 panel remains `0.8.0-alpha8-panel.1`.

## Automatic Weekend Happy Hour

- BottlecapDave HomeAssistant-OctopusEnergy `19.0.1+` separates Power Down from Power Up / Weekend Happy Hour data. KEMS now reads that Power Up stream automatically.
- When the public `event.octopus_energy_*_octoplus_power_up_events` entity is enabled, KEMS prefers it as the public source.
- Because BottlecapDave keeps the Power Up entity disabled by default, KEMS can also read the integration's existing `POWER_UP_DOWN_COORDINATOR` result as a read-only fallback. KEMS never changes Octopus settings, entities, services or coordinator state.
- The Home Assistant-facing Power Up payload does not retain the upstream GraphQL `eventType`. KEMS therefore classifies conservatively: only code-less weekend one/two-hour joined Power Up windows are eligible for automatic Weekend Happy Hour handling.
- Two consecutive one-hour rewards are merged into one two-hour Happy Hour with the existing 16 kWh-per-hour planning cap.
- Generic coded free-electricity events and weekday Power Up windows are not treated as Weekend Happy Hour.
- Multiple non-contiguous eligible Power Up windows are treated as ambiguous and KEMS falls back to the existing manual Happy Hour controls rather than guessing.
- If BottlecapDave 19.0.1+ Power Up data is unavailable or its runtime shape changes, manual Happy Hour remains the safe fallback.

## Full KEMS Agile dashboard

- The Weekend Happy Hour card now shows whether the source is **Octopus Energy — automatic** or **Manual fallback**.
- It shows the detected start, end, duration and automatic-source status.
- The existing planning switch, start datetime and duration selector remain visible in a clearly labelled **Happy Hour fallback controls** card.
- The dashboard uses the same established event-priority insertion path, so Safety > Power Down > Happy Hour > Agile price remains unchanged.

## Safety and unchanged coordinated components

- KEMS Web / Pi / PWA / public: `0.8.0-alpha8-web.2` (unchanged)
- managed ESP32 panel: `0.8.0-alpha8-panel.1` (unchanged)
- EV policy remains the selectable shadow policy introduced in Alpha8.5
- no Home Assistant service call to Octopus is added
- no Home Assistant service call to Ohme is added
- no FoxESS hardware write is added
- real hardware writes remain blocked

Manual completed-event metadata remains durable historical evidence; automatic discovery changes the source of future/current Happy Hour timing, not the established settlement or completion contract.
