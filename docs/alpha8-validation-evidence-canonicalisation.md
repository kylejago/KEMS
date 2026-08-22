# Alpha8 validation-evidence canonicalisation

This slice is an **ownership migration only**. It moves the proven Alpha7.19
validation/evidence and validation-dashboard layers behind canonical Alpha8 names
without changing their runtime bodies or observable behaviour.

## Baseline

The branch starts from exact `main`:

- commit `a30bca894eb60da382a75548c49add4a9e6485ec`
- tree `8d6487f01572d6e8eaab0f4a7655557551c0e3f3`

## Byte-parity boundary

The canonical runtime files reuse the historical Git blobs exactly:

- validation/evidence: `ed35ca4347d7d02892e31f11821f02678786deb2`
- validation dashboard: `34462b34777116a386d4cc932eed1c0f14c54a93`

No runtime body is rewritten. Historical Alpha7.19 files remain in the tree as
regression evidence and the historical Alpha7 compatibility-order metadata remains
unchanged.

## Frozen dependency bridge

Frozen Alpha7.26 provisional planning imports both Alpha7.19 modules by historical
name. It replaces `_decision_audit` and `_soc_trajectory` on the validation module
and replaces `_AGILE_CARDS` on the dashboard module. The canonical facade therefore
binds both historical import names to the canonical byte-identical module objects
before Alpha7.26 is imported.

This is a module-identity bridge only; it does not alter provisional planning.

## Deliberately excluded

Alpha7.20 remains historical live ownership in this slice. Its pre-install evidence
reconstruction and dashboard layer are not moved, rewritten, or otherwise changed.
They are the next boundary to inspect independently after this migration is proven.

## Safety

The Alpha7.19 validation layer still uses Home Assistant
`recorder.get_statistics` for read-only historical evidence. That is not a control
service call. No FoxESS provider write, inverter service call, commissioning bypass,
`commands_permitted=True`, or `safe_to_write_hardware=True` path is introduced;
real hardware writes remain blocked.

The manifest remains `0.8.0-alpha8.0`; this cleanup has no release, tag, or version
bump.
