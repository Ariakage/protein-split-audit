<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Changelog

ProteinSplitAudit follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses
semantic versioning where it applies.

## Unreleased

### Added

- Added validated v0.2.0 configuration models and CLI namespaces for cohort, similarity, and split
  workflows. Commands outside the implemented development slice still fail explicitly.
- Added deterministic aggregate profiling for the complete candidate pool, with joint validation
  of the candidate Parquet, build manifest, and FASTA inputs.
- Added local MMseqs2 discovery, version reporting, deterministic command construction, controlled
  execution through an injectable runner, strict output parsing, and sanitized run provenance.
- Added deterministic observed fixed-parameter similarity-component construction and a
  development-only 30% identity candidate-discovery workflow that publishes normalized pair and
  component Parquet artifacts, hashes, a content manifest, and run provenance without overwriting
  existing outputs.
- Added deterministic provisional cohort selection using the approved 40-sequence, five-class,
  and 10-cluster30-group eligibility rules, including hard failure when fewer than five classes
  qualify and no model-performance input or automatic four-class fallback.
- Added exact grouped-split feasibility preflight, deterministic provisional Parquet and FASTA
  artifacts, aggregate cohort manifests, and a validator that recomputes the selection from its
  parent artifacts.
- Added clean-regeneration lineage reconciliation and deterministic historical-difference
  reporting. Formal `pilot-v1` freezing remains fail-closed until a fixed clean generation commit
  and external maintainer review attestation are available.
- Added an operational, fail-closed `pilot-v1` freeze path that verifies the canonical difference
  report, clean regenerated lineage, release-eligible discovery manifest, lock hash, generation
  commit, and external review attestation before publishing frozen cohort artifacts.

### Changed

- Clarified that the recorded v0.1.0 candidate build is an E. coli K-12 pilot with 2,632 input
  entries and 1,182 retained candidates, not an all-bacteria dataset.
- Documented that the pilot manifests record a dirty working tree and require clean regeneration
  before a formal research-data freeze.
- Moved the historical v0.1 accession-level deduplication map out of the active manifest path and
  preserved its exact bytes under `results/released/v0.1.0/legacy/` with a machine-readable legacy
  marker. The archived map is not an original GitHub Release asset and is not a v0.2 cohort input.

### Fixed

- Made CLI help tests robust to ANSI-styled output on GitHub Actions.

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
