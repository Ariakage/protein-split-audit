<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Limitations

ProteinSplitAudit is an audit workflow demonstrated on a small enzyme-classification pilot. It is
not a representative protein benchmark, and the released results do not establish a universal
model or split ranking.

## Population and labels

The frozen cohort contains 442 reviewed *E. coli* K-12 enzyme entries from five EC-level-2
classes. It covers one organism, one UniProtKB/Swiss-Prot release, and a deliberately narrow
candidate protocol. EC level 2 is a coarse label; Swiss-Prot review does not remove annotation,
taxonomic, research-attention, or sampling bias. Results should not be generalized to other
organisms, enzyme families, label granularities, or unreviewed proteins.

The class distribution is uneven. Each Test split contains 66 proteins, with class supports of
29, 13, 9, 8, and 7. Many v0.6 subgroup cells therefore fail the prespecified support or privacy
rules. Suppressed cells are missing evidence, not zero effects.

## Similarity controls

MMseqs2 search and the 70%, 50%, and 30% identity thresholds operationalize one form of
within-cohort similarity. Connected components prevent observed above-threshold pairs from
crossing the matching cluster-aware split, but they do not prove evolutionary or biological
independence. MMseqs2 is heuristic, and no reported hit is not proof that no relationship exists.

The Random split already has low observed leakage under the fixed audit: four Test-to-Train pairs
reach 30% identity, two reach 50%, and none reach 70%. The released pilot therefore has limited
power to estimate how much random splitting inflates performance. All 21 prespecified
Random-minus-cluster Macro-F1 intervals include zero; the project does not claim that a stricter
split must reduce scores.

## Models and evaluation

The matrix covers one seed, five classical methods, two ESM-2 checkpoints, one ESM pooling rule,
and one linear-probe protocol. It does not cover fine-tuning, larger protein language models,
alternative pooling or layers, structural inputs, tuned hyperparameters, repeated independently
sampled cohorts, or external datasets.

The v0.5 Test gate permitted one formal run and one replay after a replay-identity revision. The
replacement sessions were byte-identical across 430 deterministic artifacts. The v0.6 analysis
then answered fixed descriptive questions without rerunning inference. These controls strengthen
the evidence trail; they do not turn a small pilot into a confirmatory multi-dataset benchmark.

Bootstrap intervals use frozen Cluster30 discovery components and are descriptive. They are not
p-values, do not correct for a family of exploratory hypotheses, and should not be interpreted as
population-level confidence intervals for all bacterial enzymes.

## Protein-language-model pretraining

ESM-2 was pretrained outside this project. ProteinSplitAudit has not established whether pilot
proteins, close homologs, or related annotations occurred in the pretraining corpus. Separating
records inside the downstream cohort does not solve pretraining leakage. The ESM results must not
be described as pretraining-independent generalization.

## Reproduction and access

Raw downloads, protein sequences, identifiers, row-level predictions, nearest-neighbor rows,
embeddings, fitted models, caches, and formal access ledgers remain local under the project's data
and privacy policy. Public manifests and aggregates expose hashes and method identities, but an
independent scientific replay still requires lawful regeneration of the source data and approved
model snapshots.

The public synthetic demo removes that access barrier for software verification. Because its
records are generated and deliberately easy to separate, its metrics are smoke-test outputs only.
They are not substitutes for the frozen pilot evidence.

## Scope of a methods paper

A defensible manuscript can describe the software architecture, protocol gates, deterministic
artifacts, similarity-aware split audit, replay controls, and the bounded pilot demonstration. It
cannot currently support a broad benchmark claim, a universal model ranking, or a claim that the
workflow eliminates every source of protein-data leakage. The exact allowed and blocked claims
are maintained in `docs/methods_paper_scope.md`.
