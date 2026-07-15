<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Pilot-v1 data card and v0.3 Validation use

## What is released

ProteinSplitAudit v0.2.0 publishes reviewed aggregate manifests for an *E. coli* K-12 enzyme pilot.
The release records a frozen cohort, three similarity partitions, four split strategies, and four
test-to-train similarity audits. It does not redistribute protein sequences or protein-level rows.

The release is not a performance benchmark. It provides fixed data identities that a later,
separately approved modeling protocol may use.

ProteinSplitAudit v0.3.0 uses those unchanged identities for a prespecified classical-baseline
Validation matrix. It does not rebuild the cohort or splits, access the real Test partition, or
publish protein-level predictions.

## Source and candidate pool

The source is UniProtKB/Swiss-Prot release `2026_02`, queried for reviewed, non-fragment,
EC-annotated entries from taxonomy ID 83333. This is a single-organism pilot, not a sample of all
reviewed bacterial enzymes.

The clean run downloaded 2,632 records and retained 1,182 candidates after EC, sequence, length,
conflict, and exact-duplicate processing. Its normalized source, candidate Parquet, and candidate
FASTA match the historical v0.1 artifacts byte for byte. Unlike the historical run, the v0.2
lineage records a fixed commit and `git_dirty: false`.

## Frozen cohort

The predeclared selection rule requires at least 40 candidates and 10 cluster30 groups per class,
selects exactly five classes, caps each class at 250, and uses seed 42. It does not use model
performance and does not fall back to four classes.

`pilot-v1` contains 442 proteins:

- EC 2.7: 192
- EC 3.1: 85
- EC 1.1: 59
- EC 2.1: 57
- EC 4.1: 49

## Similarity and splits

The frozen cohort has 437 strict Cluster70 components, 427 Cluster50 components, and 398 Cluster30
components. Each stricter partition refines the next coarser partition.

Random, Cluster70, Cluster50, and Cluster30 each contain 308 Train, 68 Validation, and 66 Test
proteins. Every class appears in every partition. Exact sequence hashes do not duplicate or cross
a split, and no named component crosses its cluster-aware split.

Independent audits found zero named-threshold violations in all three cluster-aware strategies.
The Random control reported four observed hits at or above 30% identity, two at or above 50%, and
none at or above 70%. These counts describe the fixed search output; they do not measure model
quality or biological novelty.

## Intended use

The cohort and splits are suitable for reproducing v0.2 data-separation behavior, checking
provenance, and preparing a later prespecified modeling study. They should not be generalized
beyond the E. coli K-12 pilot or used to claim that one split produces better models before that
study is designed and run.

The v0.3.0 aggregate Validation files are suitable for checking that five simple baselines can be
run reproducibly across all four frozen split strategies. They are Pilot-level engineering
outputs. They should not be treated as a final ranking of feature families or evidence that one
split strategy gives a universally better estimate of generalization.

## Limitations

Swiss-Prot curation does not eliminate annotation uncertainty, taxonomic bias, research-attention
bias, multifunction proteins, or release-to-release changes. Requiring one complete EC annotation
narrows the population. MMseqs2's fixed high-sensitivity search is heuristic, and an absence of a
reported hit is not proof of biological independence.

The cohort is small and class composition is uneven. Cluster-aware allocation is constrained by
indivisible components. The released counts describe one fixed source release, configuration,
tool version, and generation commit.

## Access and licensing

Reviewed v0.2 data manifests are in `results/released/v0.2.0/`; reviewed v0.3 Validation summaries
are in `results/released/v0.3.0/`. Raw downloads, sequence-bearing Parquet and FASTA, normalized
pair tables, protein-level manifests, predictions, models, detailed audits, run directories, and
caches remain ignored.

UniProt-derived content retains its upstream terms. ProteinSplitAudit does not relicense it. Read
`DATA_LICENSE.md`, `THIRD_PARTY_NOTICES.md`, and `docs/LICENSE_POLICY.md` before sharing any local
data artifact.
