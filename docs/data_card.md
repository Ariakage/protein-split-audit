<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Candidate dataset card

## Status

No ProteinSplitAudit candidate or benchmark dataset has been produced or released. This card
describes the v0.1.0 candidate-data contract so that a later authorized build can be checked
against it.

Release preparation found no reviewed profile artifacts in `results/runs/`, so nothing was copied
to `results/released/v0.1.0/`.

## Source

The intended source is reviewed, non-fragment bacterial enzyme entries from
UniProtKB/Swiss-Prot. An authorized run must supply the exact query, source response and release
metadata, retrieval time, page hashes, and record counts. Estimated values are not acceptable.

## Records and labels

Candidate records contain the accession, entry and organism metadata, normalized sequence and
length, sequence SHA-256, one complete EC annotation, its EC-level-2 target, source row
coordinates, and same-label duplicate metadata.

Files containing sequences stay local and untracked. Maintainers may review sequence-free build
provenance, alias maps, conflict annotations, and aggregate rejection counts for tracking under
the repository's artifact policy.

## Filtering rules

- Sequence length must be 50 to 1000 residues, inclusive.
- Sequences may contain only the standard 20-amino-acid alphabet.
- Each record must have exactly one complete, four-level EC annotation.
- If identical sequences have conflicting EC-level-2 labels, the whole group is rejected.

Every source record must end in one of four places: the candidate dataset, a validation rejection,
a same-label duplicate audit row, or a conflicting-label duplicate audit row.

## Intended use

The candidate data can support a later benchmark for sequence-similarity leakage audits after a
separate review. Before that point, it may be used to inspect aggregate composition, check data
quality, and reproduce selection behavior from source and configuration hashes.

## Aggregate profile files

`psaudit data profile` reads candidate labels, sequence lengths, and organism identifiers or names
from a processed Parquet file. It checks that file against the build manifest, then writes the
following aggregate files to an explicit directory such as `results/runs/profile-pilot/`:

- `profile_summary.json` reports retained candidates, observed EC-level-2 classes, and distinct
  organisms. It also states that the profile is candidate-only and is not a benchmark.
- `ec_level_2_class_counts.csv` has one row per observed label. Rows are ordered by decreasing
  candidate count, then by label.
- `sequence_length_summary.json` reports count, minimum, maximum, mean, median, and the 0.05, 0.25,
  0.50, 0.75, and 0.95 quantiles.
- `organism_summary_top100.csv` contains at most 100 aggregate organism rows. Rows are ordered by
  decreasing candidate count, then by taxonomy ID and name.
- `filtering_flow.csv` gives the ordered record counts and removals at each build filter boundary.
- `deduplication_summary.json` gives the same-label duplicate and conflicting-label group and
  record totals.

Each output names the input Parquet file and build manifest and includes their SHA-256 hashes. The
JSON files also record the upstream configuration, source manifest, input file, and lockfile
hashes.

These summaries contain no sequences, protein-level rows, full organism listings, timestamps,
absolute local paths, secrets, class-selection decisions, split metrics, model results, or
benchmark claims. Development copies remain ignored in `results/runs/`. A maintainer may later
approve copies for `results/released/v0.1.0/`.

## Uses outside the contract

Do not treat the candidate data as a final or class-balanced benchmark. Do not use it to make
claims about leakage or model performance before the planned splits and experiments. The project's
code and documentation licenses do not cover redistribution of UniProt-derived content.

## Limitations

Swiss-Prot curation does not remove annotation uncertainty, taxonomic bias, research-attention
bias, multifunction proteins, or differences between releases. Requiring one complete EC
annotation narrows the source population and may change its composition. Exact deduplication also
leaves non-identical homologs in place; a later gate will address them through clustering.

## Licensing and access

UniProt-derived sequences and metadata retain their upstream terms. Raw and processed files that
contain sequences remain untracked. Read `DATA_LICENSE.md`, `THIRD_PARTY_NOTICES.md`, and
`docs/LICENSE_POLICY.md` before producing or sharing a data artifact.
