<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Changelog

ProteinSplitAudit follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses
semantic versioning where it applies.

## Unreleased

## 0.4.0 - 2026-07-16

### Added

- Two frozen ESM-2 snapshots pinned to full Hugging Face revisions, expected weight hashes, and an
  exact five-file allowlist.
- Explicit snapshot fetching, offline verification, deterministic batching, residue-only mean
  pooling, and immutable Train/Validation embedding caches.
- Train-only scaling and the fixed v0.3 logistic-regression protocol over frozen ESM-2 embeddings.
- A fixed two-model by four-split Validation matrix covering Random, Cluster70, Cluster50, and
  Cluster30.
- Same-platform replay checks for embeddings, predictions, metrics, and deterministic manifests.
- Six reviewed aggregate Validation files and a machine-readable protocol attestation.
- Release guards for frozen inputs, model identities, aggregate hashes, privacy, and real Test
  denial.

### Scope

- Uses the unchanged v0.2 cohort and split identities and does not rerun the v0.3 classical cells.
- Publishes aggregate Validation outputs only. Model snapshots, embeddings, fitted estimators,
  predictions, sequences, accessions, logs, caches, and complete run directories remain local.
- Real Test access, model fine-tuning, hyperparameter search, and benchmark conclusions remain out
  of scope.

## 0.3.0 - 2026-07-15

### Added

- Deterministic sequence-length, amino-acid-composition, and fixed 8,000-dimensional 3-mer
  feature extraction with immutable, content-addressed caches.
- Prespecified Majority, logistic-regression, and training-only Nearest Homolog baselines.
- Train-only preprocessing, fixed class ordering, deterministic predictions, per-class metrics,
  confusion matrices, timing, memory, and no-hit reporting.
- A fixed 5-baseline × 4-split Validation matrix covering Random, Cluster70, Cluster50, and
  Cluster30.
- Validation experiment provenance, run-completion markers, deterministic replay comparison, and
  sequence-free aggregate publication.
- A machine-readable protocol-freeze attestation tied to the clean generation commit, lockfile,
  frozen v0.2 inputs, reviewed Validation artifacts, and permanent maintainer approval.
- An application-level denial gate that prevents v0.3.0 from opening the real Test inputs.

### Scope

- Publishes aggregate Validation summaries only. Feature caches, fitted models, predictions,
  nearest-neighbor rows, run logs, and sequence-bearing inputs remain untracked.
- Uses one fixed seed and one prespecified parameter set as a pipeline validation exercise, not a
  final benchmark or scientific comparison of split strategies.
- Does not run or publish real Test results, ESM-2 features, deep-learning models, hyperparameter
  searches, or final research conclusions.

## 0.2.0 - 2026-07-15

### Added

- Validated configuration models and CLI namespaces for cohort, similarity, and split workflows.
  Commands outside the implemented development slice fail with an explicit error.
- Aggregate candidate-pool profiling with joint checks for the candidate Parquet, build manifest,
  and FASTA.
- A controlled MMseqs2 runner with version detection, fixed command construction, strict output
  parsing, and sanitized run provenance.
- Deterministic 30% identity candidate discovery. The workflow writes normalized pair and
  component Parquet files, content hashes, and separate run provenance without overwriting an
  existing result.
- The approved cohort selector: at least 40 sequences and 10 cluster30 components per class,
  exactly five classes, and no model-performance input or four-class fallback.
- A grouped-split feasibility check and deterministic provisional cohort Parquet, FASTA, and
  aggregate manifests. Validation recomputes the cohort from its parents.
- Clean-regeneration comparison and a reviewed `pilot-v1` freeze gate. The gate binds the clean
  source and build chain, discovery manifest, difference report, generation commit, lock hash,
  and maintainer attestation before writing frozen artifacts.
- Formal MMseqs2 cluster manifests at 70%, 50%, and 30% identity, with descriptive native clusters
  kept separate from strict pair-edge connected components.
- Deterministic Random, Cluster70, Cluster50, and Cluster30 splits with fixed seed 42, complete
  class coverage, ratio validation, exact-sequence isolation, and whole-component allocation.
- Independent test-to-train similarity audits with explicit no-match rows, deterministic nearest
  neighbors, descriptive Random Split counts, and hard threshold gates for cluster-aware splits.
- A timestamp-free top-level provenance manifest and reviewed aggregate release summaries.

### Changed

- Clarified that the recorded v0.1.0 candidate build is an E. coli K-12 pilot with 2,632 input
  entries and 1,182 retained candidates, not an all-bacteria dataset.
- Documented that the pilot manifests record a dirty working tree and require clean regeneration
  before a formal research-data freeze.
- Moved the historical v0.1 accession-level deduplication map out of the active manifest path and
  preserved the same bytes under `results/released/v0.1.0/legacy/` with a machine-readable marker.
  The archived map was not part of the original GitHub Release and is not a v0.2 cohort input.

### Fixed

- Made CLI help tests robust to ANSI-styled output on GitHub Actions.
- Report the frozen `pilot-v1` state correctly after cohort validation.

### Scope

- Freezes the five-class E. coli K-12 `pilot-v1` cohort and its split/audit identities.
- Publishes aggregate manifests only. Raw sequences, processed sequence files, normalized pair
  tables, record-level split rows, and detailed audit rows remain untracked.
- Adds no features, model training, benchmark metrics, or scientific performance claims.

## 0.1.1 - 2026-07-14

### Changed

- Corrected public documentation to reflect that v0.1.0 has been published, and moved the former
  readiness report to the historical audits directory.
- Updated package and citation metadata for the v0.1.1 corrective tag.

### Release scope

v0.1.1 changes documentation and release metadata only. It does not change pipeline behavior,
publish a new dataset, or close the known acceptance gaps documented for v0.1.0.

## 0.1.0 - 2026-07-14

### Added

- Contribution guidance, roadmap, research protocol, data card, reproducibility guide, and
  licensing documentation.
- The `psaudit --version` and `psaudit doctor` commands.
- Validated YAML configuration, project-root discovery, SHA-256 hashing, and read-only Git
  metadata helpers.
- A validated pilot configuration and a paginated UniProtKB downloader with bounded retries,
  normalized TSV output, deterministic compression, and provenance manifests.
- Offline downloader tests for pagination and retry behavior, API and TSV errors, repeated pages,
  header changes, loops, and total-count reconciliation.
- EC and sequence validation, exact-sequence duplicate handling, deterministic Parquet and FASTA
  output, sequence-free audit summaries, and build provenance.
- Deterministic aggregate profiles for class counts, sequence lengths, top organisms, filtering,
  and deduplication. Each profile links back to the build and dataset hashes.
- Locked uv checks for CI and pre-commit, with an offline test suite.

### Changed

- The console entry point is `psaudit`.

### Publication

v0.1.0 was published as the first candidate-dataset pipeline release. Some originally proposed
CLI and audit capabilities remain planned for a future corrective release.
