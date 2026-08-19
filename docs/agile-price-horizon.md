# Agile Smart Export price-horizon safety

KEMS distinguishes two different kinds of Agile readiness:

- **Live readiness** means the current Agile export price is known and the current-day simulation has enough observation coverage to make a live routing decision.
- **Settlement readiness** means the complete local-day Agile price set is available, so the whole-day comparison can be treated as complete.

A live strategy can therefore remain usable while the full local day is still missing one or more future price slots. Missing prices are never guessed or filled with synthetic values.

## Battery-export horizon

For deliberate battery export, KEMS requires every Agile price slot from the current half-hour up to the next normal cheap-period start to be known. If a relevant future slot is missing, price-optimised battery export is held while solar-first and house-first routing continue normally.

The missing slot labels, known/expected slot counts and deadline are published through `sensor.kems_agile_price_horizon_status` and as attributes on the normal Agile status/rolling-plan entities.

A missing price after the normal cheap-period start does not block battery export that must finish before that deadline.

## Deadline override

The existing 10% pre-cheap target remains protected. If the current Agile price is known and the physical discharge window has tightened enough that waiting would make the target unreachable, KEMS may use the existing deadline-following or maximum-discharge path even while a later future price is missing.

KEMS never uses the deadline override when the current Agile price itself is unknown.

## Historical evidence

This live price-horizon rule does not change the historical evidence boundary. KEMS still requires valid daily replays for historical comparisons and does not invent missing house-load, tariff, solar or strategy history. The 365-day result remains coverage-gated until 365 valid daily replays exist.

All Agile Smart Export behaviour remains simulation/shadow only until the normal FoxESS commissioning and control gates are satisfied.
