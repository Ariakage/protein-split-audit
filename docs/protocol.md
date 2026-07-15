<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# ProteinSplitAudit data protocol

This document defines the frozen v0.2 cohort and split foundation. The Validation-only classical
feature and model protocol is frozen separately in
`docs/protocols/v0.3.0-classical-baselines.md` and its approved machine-readable attestation.

## Purpose and boundary

This protocol defines how ProteinSplitAudit v0.2.0 turns one reviewed candidate pool into a fixed
pilot cohort, three nested similarity partitions, and four Train/Validation/Test splits. It tests
data separation and provenance. It does not specify features, train a classifier, or support a
claim about predictive performance.

## Source and candidate rules

The pilot source is reviewed, non-fragment, EC-annotated *E. coli* K-12 entries from
UniProtKB/Swiss-Prot. A candidate must have one complete four-level EC annotation, a sequence of 50
to 1000 residues, and only the standard amino-acid alphabet `ACDEFGHIKLMNPQRSTVWY`. The target is
EC level 2.

Same-sequence, same-label duplicates retain the lexicographically smallest accession as canonical.
Aliases stay in a local audit. If an exact sequence has different EC-level-2 labels, the complete
group is rejected. Every source record has an explicit retained, rejected, duplicate, or conflict
outcome.

## Frozen pilot cohort

The selection rule is `pilot-ec2-5class-min40-c30g10-cap250-seed42-v1`:

- at least 40 candidate sequences per class;
- at least 10 observed cluster30 components per class;
- exactly five classes, ranked deterministically;
- at most 250 selected sequences per class;
- seed 42;
- no use of model or test performance;
- hard failure if fewer than five classes qualify.

The 50-sequence/four-class alternative is not a fallback. It would require a separate protocol
revision and maintainer approval.

## Similarity groups

MMseqs2 runs with fixed sensitivity, e-value, coverage, identity-mode, alignment-mode, and thread
settings recorded in each manifest. The Cluster30 operation performs one all-vs-all self-search.
Its normalized pair table is the sole edge source for strict 70%, 50%, and 30% connected
components. This guarantees that Cluster70 refines Cluster50, which refines Cluster30.

MMseqs2 `easy-cluster` also runs at each threshold. Those native clusters are descriptive and are
stored separately from the strict components used for splitting. The search is a fixed,
high-sensitivity heuristic, not a mathematical proof that every possible homologous pair was
found. Independent test-to-train audits remain necessary.

## Splits

All four strategies target 70% Train, 15% Validation, and 15% Test with seed 42 and an absolute
five-percentage-point tolerance.

The Random Split ranks each accession within its class by
`SHA-256(seed + "\n" + accession + "\n" + sequence_sha256)` and applies largest-remainder counts.
The Cluster70, Cluster50, and Cluster30 strategies allocate strict components as indivisible
groups. They fail rather than split a component, omit a class from a partition, leave a partition
empty, or exceed the ratio tolerance.

Every cohort record appears exactly once. An exact sequence hash may not duplicate or cross a
split. For cluster-aware strategies, the named component may not cross Train, Validation, and
Test.

## Leakage audit

Each strategy runs a fresh MMseqs2 Test-to-Train search. Every Test record receives either its
deterministically chosen nearest observed Train neighbor or an explicit no-match row. Threshold
checks scan all observed hits, not only the selected neighbor.

Random Split exceedances are control statistics and are not repaired. A Cluster70, Cluster50, or
Cluster30 hit at or above its named threshold is a hard failure and blocks release eligibility.

## Provenance and reporting

Deterministic manifests contain configuration, command, tool, input, output, Git, Python, and
lockfile hashes but no timestamps. Run timestamps and machine-specific staging paths stay in
ignored provenance. Formal artifacts require a fixed clean generation commit and clean parent
lineage.

Public release artifacts are aggregate and sequence-free. Raw source data, processed Parquet and
FASTA, pair tables, protein-level split rows, detailed audits, caches, and MMseqs2 databases remain
untracked. No artifact in this release is a model benchmark result.
