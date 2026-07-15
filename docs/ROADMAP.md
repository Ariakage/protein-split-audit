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

## Gate 1: v0.1.0 candidate dataset pipeline (released with documented debt)

The repository now has:

- a validated pilot configuration and `psaudit data download`;
- paginated UniProt TSV retrieval with bounded retries, normalized output, deterministic
  compression, and download provenance;
- fixed EC and sequence eligibility rules, exact duplicate handling, deterministic Parquet and
  FASTA output, sequence-free audits, and build provenance;
- aggregate candidate profiles tied to dataset and build hashes.

The v0.1 series shipped the candidate pipeline. Its remaining acceptance debt is documented rather
than silently closed: `psaudit config validate` and `psaudit data run` are still absent, and the
historical release data recorded a dirty working tree. v0.2.0 therefore regenerated the candidate
chain from a clean fixed commit before freezing any research artifact.

Gate 1 ends when every v0.1.0 acceptance criterion passes. It does not publish a benchmark dataset
or support a research claim.

## Gate 2: v0.2.0 cohort and leakage-aware splits (complete)

- Frozen five-class `pilot-v1` cohort selected without model-performance input.
- Recorded MMseqs2 native clusters and strict 70/50/30 connected components separately.
- Produced deterministic Random and Cluster70/50/30 splits with whole-component isolation.
- Audited every Test sequence against Train and enforced zero named-threshold violations for the
  three cluster-aware strategies.
- Published only reviewed aggregate manifests; sequence and protein-level artifacts remain local.

## Gate 3: v0.3.0 classical features and Validation models (complete)

- Added deterministic Length, AAC, and fixed 3-mer representations.
- Added Majority, fixed logistic-regression, and training-only Nearest Homolog baselines.
- Ran the prespecified 5 × 4 Validation matrix twice and verified byte-identical deterministic
  outputs.
- Published aggregate Validation summaries only and kept real Test access denied.

## Gate 4: representation models on Validation

- Review compute, licensing, and provenance before adding frozen ESM-2 representations.
- Prespecify all pooling, classifier, and evaluation choices before running Validation.
- Keep the real Test split closed and avoid tuning against Test behavior.

## Gate 5: separately approved Test freeze

- Freeze the complete planned method set before first Test access.
- Require a new permanent maintainer approval and machine-readable Test attestation.
- Publish aggregate Test results only after independent validation.

## Decisions left for later gates

Later protocol decisions must set representation models, multi-seed analyses, and statistical
tests. The v0.2.0 cohort and split identities and the v0.3.0 classical protocol are frozen inputs,
not values to retune after seeing future Test performance.
