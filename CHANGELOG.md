<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Changelog

ProteinSplitAudit follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses
semantic versioning where it applies.

## Unreleased

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
