<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Prospective research protocol

## Current status

The candidate-construction software exists, but no candidate dataset or scientific result has
been produced or released. This protocol also predates any split, model, or metric selection.

## Research question

For bacterial enzyme classification at EC level 2, does a random sequence-level split report
higher performance than a split that keeps closely related sequence groups in separate
partitions?

## Source population

The planned source population consists of reviewed bacterial enzyme entries from
UniProtKB/Swiss-Prot with `fragment:false`. During an authorized download, the software records the
source query, response metadata, page hashes, retrieval events, and software environment.

## Candidate eligibility

A record enters the candidate dataset only if:

- its normalized sequence is between 50 and 1000 residues, inclusive;
- every residue is one of `ACDEFGHIKLMNPQRSTVWY`;
- it has exactly one EC annotation;
- that annotation has four numeric levels.

The target is the first two levels of the accepted EC annotation. Candidate construction does not
choose which level-2 classes will appear in a later benchmark.

Each rejected record needs a reason in the detailed local audit. The software must never discard
a record silently.

## Exact duplicate sequences

When accessions share both an exact sequence and an EC-level-2 label, the build keeps the
deterministic canonical accession and records the remaining accessions as aliases.

If one exact sequence has different level-2 labels, the build rejects every record in that group.
The configured sequence-free conflict summary records all accessions, complete EC annotations,
level-2 labels, and disagreement metadata.

## Rules for later splitting and modeling

- Approve class eligibility, similarity thresholds, split proportions, and seeds before looking
  at test performance.
- Give every random operation an explicit seed.
- Do not use test data to choose features, hyperparameters, early stopping, thresholds, or
  included classes.
- Compare random and cluster-aware partitions on the same frozen candidate population, with every
  exclusion reported.
- Choose primary metrics and uncertainty estimates before running model comparisons.

## Reporting limits

Candidate profiles describe data quality and composition. They are not benchmark results.
Scientific claims require completed experiments, hashes for the relevant artifacts, code and
environment provenance, and an independent check against this protocol.
