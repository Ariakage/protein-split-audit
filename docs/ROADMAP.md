<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# ProteinSplitAudit roadmap

The gates below define scope, not release dates. Work moves to the next gate only after a
maintainer approves it and the preceding gate can be reproduced.

## Gate 0: project foundation (complete)

Gate 0 established the repository rules, research protocol, data and licensing policies, and
decision records. It also set up the Python 3.12 uv project, locked checks, configuration and path
helpers, hashing, read-only Git metadata, and the first two commands: `psaudit --version` and
`psaudit doctor`.

This gate deliberately contained no network downloader or dataset-processing code.

## Gate 1: v0.1.0 candidate dataset pipeline (in progress)

The repository now has:

- a validated pilot configuration and `psaudit data download`;
- paginated UniProt TSV retrieval with bounded retries, normalized output, deterministic
  compression, and download provenance;
- fixed EC and sequence eligibility rules, exact duplicate handling, deterministic Parquet and
  FASTA output, sequence-free audits, and build provenance;
- aggregate candidate profiles tied to dataset and build hashes.

The gate is still open. It requires `psaudit config validate`, `psaudit data run`, separate
release-level content manifests and run provenance, packaging completion, and the remaining
acceptance fixes.

Gate 1 ends when every v0.1.0 acceptance criterion passes. It does not publish a benchmark dataset
or support a research claim.

## Gate 2: benchmark protocol and leakage-aware splits

- Freeze a reviewed candidate dataset only after data and licensing review.
- Approve the final EC-level-2 class rules without tuning on test data.
- Add MMseqs2 clustering and deterministic random and cluster-aware splits.
- Measure train/test sequence-similarity leakage and verify partition invariants.

## Gate 3: baseline features and models

- Add classical sequence features and prespecified baseline classifiers.
- Add frozen ESM-2 representations after compute, licensing, and provenance review.
- Keep test data out of hyperparameter selection.

## Gate 4: evaluation and reporting

- Run the approved experiments and uncertainty analyses.
- Validate results independently before publishing metrics, limitations, or leakage findings.
- Build reports or dashboards only from verified artifacts.

## Decisions left for later gates

Later protocol decisions must set the final EC classes, cluster thresholds, split proportions,
model families, metrics, and statistical tests. Pipeline work must not infer any of them from the
test set.
