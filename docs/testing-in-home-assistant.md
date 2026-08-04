# Testing in Home Assistant

1. Merge the branch into `develop`.
2. Copy the full `develop` commit SHA.
3. Install that SHA using `update.install` against `update.kems_update`.
4. Restart Home Assistant.
5. Add or reconfigure KEMS.
6. Confirm the detected mappings.
7. Check KEMS diagnostics and these entities:
   - phase
   - data quality
   - learning confidence
   - advice
   - observed and simulated cost
8. Search the logs for `custom_components.kems`.

A new installation will remain in Observe/Learn while history accumulates. Simulation requires at least several usable intervals, and learning readiness requires at least seven observed days and 96 useful samples.
