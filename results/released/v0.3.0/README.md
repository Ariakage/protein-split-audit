<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# ProteinSplitAudit v0.3.0 aggregate Validation artifacts

This directory contains the reviewed, sequence-free outputs from the fixed 5 × 4 classical
Validation matrix. The real Test split was not accessed.

## Files

- `validation_summary.csv`: one aggregate metric row per split and baseline;
- `validation_per_class.csv`: aggregate per-class Validation metrics;
- `feature_schema.json`: frozen feature definitions and 3-mer vocabulary identity;
- `environment_summary.json`: deduplicated clean-run software environment;
- `protocol_attestation.yaml`: approved protocol, code, input, review, and publication identities.

The directory intentionally excludes sequences, accessions, record-level predictions, nearest
neighbors, fitted models, confusion matrices, caches, logs, and resource traces. The reported
values are Pilot-level Validation outputs, not final Test benchmark results.
