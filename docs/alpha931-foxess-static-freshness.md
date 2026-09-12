# Alpha9.31 — FoxESS static telemetry freshness

Alpha9.31 corrects the live-freshness contract for mapped FoxESS Modbus telemetry whose value can legitimately remain unchanged across repeated inverter polls.

## Behaviour

- KEMS keeps each mapped source's raw Home Assistant report age in diagnostics.
- A mapped numeric FoxESS source whose own report age exceeds the normal 180-second freshness threshold remains usable only when another configured numeric source registered by `foxess_modbus` on the identical Home Assistant `device_id` has reported within that threshold.
- The same-device cohort age is used for aggregate/control freshness so a sustained unchanged value such as 0 kW grid import does not falsely stale Control Lab or commissioning while the inverter cohort is demonstrably live.
- No value, including zero, receives a special exemption and the 180-second threshold is unchanged.

## Fail-closed boundaries

KEMS still rejects the stale-looking source when registry identity is unavailable, when the fresh sibling belongs to another Home Assistant device, or when the whole same-device FoxESS cohort is stale.

## Release scope

This is a telemetry/freshness correction only. It does not change optimiser allocation, tariff handling, Happy Hour, Power Down, SOC policy, panel behaviour, or FoxESS command/write authority. Alpha9.30's solar-only commissioning path remains read-only while the battery installation is pending, and real FoxESS hardware writes remain blocked.

## Post-deployment proof

After installation and restart, collect a fresh solar-only commissioning soak of at least 12 samples. The release is live-proven only when FoxESS telemetry stability is ready/stable, whole-site power balance is ready/balanced, and `foxess_site_telemetry_proof_ready` is `true`.
