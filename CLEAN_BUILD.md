# KEMS preserved-history upgrade 0.6.0-alpha4

This is not a clean-history release. It deliberately keeps the existing
`clean_v6_alpha2` observation namespace so the learning data already collected
continues without interruption.

The simulated financial ledger has its own migration version. On the first
alpha4 startup, the value created by the superseded alpha3 reserve calculation is
reset while observed history, mappings, gas data, and actual post-install totals
remain untouched.
