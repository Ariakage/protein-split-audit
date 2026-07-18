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

## Gate 4: v0.4.0 frozen ESM-2 models on Validation (complete)

- Pinned two ESM-2 repositories to full revisions, verified their local file sets and hashes, and
  recorded model acquisition manifests without tracking the model files.
- Prespecified residue-only mean pooling, deterministic batching, CPU float32 execution,
  Train-only scaling, and the fixed logistic-regression protocol before formal Validation.
- Ran the two-model by four-split Validation matrix twice from empty embedding caches and verified
  byte-identical deterministic artifacts.
- Published six reviewed aggregate files and kept the real Test split closed.

## Gate 5: v0.5.0 frozen Test pilot (complete)

- Froze all seven methods and four split strategies before first Test access.
- Required owner-authored approvals, machine-readable attestations, and exact two-session access
  accounting.
- Preserved the first blocked replay and its incident evidence, then completed protocol revision
  r1 with two separately approved replacement sessions.
- Compared 430 deterministic files with zero replay differences and published only twelve reviewed
  aggregate files.

## Decisions left for later gates

Any later study must define a new cohort or external evaluation question before implementation.
The v0.2 cohort and splits, v0.3 classical protocol, v0.4 ESM-2 protocol, and v0.5 Test results are
frozen evidence. They cannot be retuned or selectively rerun after Test inspection.
