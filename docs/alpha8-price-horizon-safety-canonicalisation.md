# Alpha8 price-horizon safety canonicalisation

This slice is an **ownership migration only**. It moves the proven Alpha7.22
price-horizon readiness and battery-export safety layer behind a non-versioned
Alpha8 boundary without changing its runtime body.

## Exact retained runtime

- Alpha7.22 price-horizon runtime Git blob:
  `a968f1f0ee330fb2df72770cc00d6adc706d0ddf`

`agile_price_horizon_safety_runtime.py` reuses that exact blob. No runtime body is rewritten.

## Why a bridge is required

The live compatibility registry imports patches sequentially. The canonical
price-horizon facade therefore loads first and binds the historical
`agile_alpha722_horizon` import name to the canonical byte-identical runtime.

Frozen Alpha7.26 provisional planning still imports that historical name, captures
`_hold_price_optimised_export`, and replaces the helper in place so the executable
price-horizon hold remains conservative while provisional economic intent stays
visible. The narrow alias keeps that mutation on the same canonical module object
rather than creating a duplicate historical copy.

No Alpha7.19, Alpha7.20, Alpha7.23, or Alpha7.26 runtime body is rewritten by this
slice. Historical Alpha7.22 remains packaged as regression evidence, and the
historical compatibility-order metadata remains unchanged.

## Preserved behaviour

The migration keeps the exact Alpha7.22 contract:

- the next normal cheap-period boundary defines the relevant price horizon;
- unknown relevant future prices hold deliberate battery export at zero;
- house battery supply is preserved while export is held;
- deadline-following and maximum-discharge overrides require the current price
  slot to be known;
- cheap-period operation is treated as a complete horizon;
- live readiness remains distinct from full settlement readiness;
- missing half-hour prices remain explicit rather than invented; and
- Alpha7.26 can still attach its provisional economic plan to the same hold helper.

## Safety boundary

This remains simulation/shadow only. No Home Assistant hardware service call is
added and no FoxESS provider write path is added. Downstream shadow command
publication keeps `commands_permitted` false and `safe_to_write_hardware` false;
real hardware writes remain blocked. Commissioning is not bypassed.

There is no release, tag or manifest-version change in this cleanup slice.
