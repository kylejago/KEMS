# Alpha8 history-dashboard canonicalisation

This change is an **ownership migration only** for the proven Alpha7.14 and
Alpha7.15 Agile dashboard presentation layers.

The Alpha7.14 runtime is retained byte-for-byte as
`agile_deadline_history_dashboard_runtime.py` with historical blob
`d17ca7fb46162058d3b376e2f7d61a3a9325f122`.

The Alpha7.15 runtime is retained byte-for-byte as
`agile_history_diagnostics_dashboard_runtime.py` with historical blob
`dceecc3e7bea567033ba1d8fbac429621c8275e9`.

Alpha7.15 imports Alpha7.14 by its historical module name only to reuse the
`_BACKFILL_DIAGNOSTICS_CARD` constant. The canonical facade therefore binds the
historical Alpha7.14 name to the canonical Alpha7.14 runtime object before the
frozen Alpha7.15 runtime is imported. No Alpha7.15 legacy alias is required.

The live compatibility registry keeps the original ordering around this pair:
Alpha7.17 dispatch first, then canonical Alpha7.14 presentation, canonical
Alpha7.15 diagnostics presentation, followed by the unchanged Alpha7.16 and
Alpha7.17 dashboard wrappers.

The migration preserves the deadline card, hardware-SOC observational sensor,
settled-history wording and sensor-backed backfill diagnostics. It does not
change tariff policy, dispatch, export, SOC targets, commissioning or hardware
control. No Home Assistant hardware service calls or FoxESS provider writes are
added; real hardware writes remain blocked.

Historical Alpha7.14 and Alpha7.15 files remain in the package as regression
evidence. KEMS remains `0.8.0-alpha8.0`; there is no release or tag change.
