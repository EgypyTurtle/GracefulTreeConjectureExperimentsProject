# Original k=14 server artifact

`eg_k14_20261019T071359Z_7f7a4c1a.tar.gz` is the unchanged, post-run server
collection. Its SHA-256 is
`8a814c86d59797a0ee8061e73e11f748c6f71e5d00506b2b8542e478839ed1c5`.

It includes original/refined manifests, all 6,269 preserved source completion
records, all 18,060 final completion records, logs, collected source, server
binary and collection-time environment. `ARTIFACT_SHA256SUMS` inside the
archive covers its member files. Collection-time sources/tests/docs predate
the added local audit reports and post-run test additions in this Git snapshot;
the C++ search and refinement engines are unchanged.

This is not a full independently verified search certificate. See
`../../publication/VERIFICATION.md` and the reports under `../../results/`.
Extract into a separate, new directory; do not overwrite live checkpoints.
