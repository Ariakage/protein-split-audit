<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Changelog

ProteinSplitAudit follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses
semantic versioning where it applies.

## Unreleased

No changes recorded.

## 0.1.0 - 2026-07-14

### Added

- Governance and contribution guidance, along with the product, roadmap, protocol, data card,
  reproducibility, licensing, and scope documents.
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

## Publication status

No Git tag or GitHub Release has been published for this version.
