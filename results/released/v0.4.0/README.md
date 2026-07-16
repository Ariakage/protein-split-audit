<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# ProteinSplitAudit v0.4.0 aggregate Validation artifacts

This directory contains the reviewed, sequence-free outputs from the fixed two-model by
four-split ESM-2 Validation matrix. The real Test split was not accessed.

## Files

- `esm_validation_summary.csv`: one aggregate metric row per split and ESM-2 model.
- `esm_validation_per_class.csv`: aggregate per-class Validation metrics.
- `classical_vs_esm_summary.csv`: the frozen v0.3 classical rows alongside the v0.4 ESM rows.
- `embedding_feature_schema.json`: model dimensions, pooling rule, and output dtype.
- `model_snapshot_hashes.json`: canonical hashes for the two approved local model snapshots.
- `environment_summary.json`: the deduplicated clean-run software and hardware environment.
- `protocol_attestation.yaml`: the approved protocol, code, inputs, model identities, and Test
  denial.

The two formal runs used Attestation Commit B
`31d2ff208f344e823ce04801596664f14679a2e5`. The replay compared 97 deterministic artifacts and
found them byte-identical, with `replay_difference: 0`. The replay report SHA-256 is
`0fad7c3a4c6862ccce4e1a1fc318fed47113ed505d73be1a172d86a1c18e8c69`.

`real_test_access_authorized: false`

Model files, embeddings, fitted estimators, predictions, accessions, sequences, complete run
directories, and logs are not included. These are Validation-only pilot outputs. They are not
final Test results or evidence that one model or split strategy is generally superior.
