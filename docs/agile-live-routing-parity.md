# KEMS 0.7.0-alpha7.29 — Agile live-routing parity

Alpha7.29 corrects a reporting mismatch on the Agile workspace. The Live tab shows the instantaneous KEMS house-load entity, `sensor.kems_house_load`, while the Agile live-routing card historically labelled an elapsed simulated half-hour average as **House demand**. Those values can legitimately differ during a half-hour, which made the Agile page appear to be using the wrong live demand.

This release is deliberately **reporting-only**.

## What changes

- The Agile routing card now shows **House demand (live)** directly from `sensor.kems_house_load`, the same entity used on the Live tab.
- The previous simulated demand is retained separately as **Digital-twin slot-average demand**.
- `sensor.kems_agile_live_scenario` retains the simulated value as `simulated_house_load_kw` and exposes the live value as `live_house_load_kw`.
- The scenario also records the live source entity, timestamp, live-vs-simulated difference and the display basis.
- The exported Agile state receives a compact `live_house_load_parity` diagnostic block so support diagnostics can distinguish the two measurements.

If the live KEMS house-load entity is unavailable, Alpha7.29 does not invent a value. The existing simulated elapsed-slot average remains available as an explicitly labelled fallback/evidence value.

## What does not change

Alpha7.29 does not modify the rolling optimiser, Agile price ranking, SOC trajectory, bounded partial-horizon logic, reserved unknown-slot capacity, current dispatch targets, independent safety checks or non-zero export proof.

The Alpha7.28 bounded partial-horizon pathway therefore remains unchanged for the planned non-zero shadow-export validation. Real FoxESS hardware writes remain blocked exactly as before.
