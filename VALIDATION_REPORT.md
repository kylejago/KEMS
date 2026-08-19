# KEMS Alpha7.32 validation report

Build: `0.7.0-alpha7.32`

## Behavioural baseline

Alpha7.32 is intentionally a platform-contract/cleanup release. The economic and dispatch baseline remains Alpha7.31.

Fresh Alpha7.31 runtime evidence before this cleanup showed:

- genuine non-zero Agile battery export selected by the optimiser;
- Feed-in First command shape for deliberate export;
- 13/13 independent shadow-command safety;
- 100% strict candidate-applied digital-twin tracking at 0.01 kW tolerance;
- combined solar + battery KH7 AC output held to the 7 kW configured limit;
- minimum 10% SOC protection retained;
- real hardware writes blocked.

## Alpha7.32 validation scope

The release must prove:

- manifest and coordinated bundle versions agree;
- property Web and Pi agent both target `0.7.0-alpha7-web.13`;
- the public website target is the same Web release but remains externally delivered by IONOS;
- Panel4 remains the expected firmware because no display behaviour changed;
- stale Alpha6 root build instructions and the obsolete checksum manifest are removed;
- Alpha7.31 remains the last installed Agile runtime patch, confirming this cleanup release does not silently alter optimiser/dispatch behaviour.

## Required automated checks

- packaged dashboard current
- Black
- Ruff
- Pytest
- Python compile
- hassfest
- HACS

Real FoxESS writes remain blocked.
