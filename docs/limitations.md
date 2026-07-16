<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Limitations

ProteinSplitAudit is an audit pipeline, not a finished enzyme-function benchmark. Each release
freezes a narrow engineering layer so that later comparisons can be traced to explicit inputs,
configurations, and tool versions.

## Pilot data

The frozen pilot cohort is small and comes from reviewed *E. coli* K-12 enzyme entries selected by
the earlier candidate and cohort protocols. It is not representative of all bacteria, all
enzymes, or UniProtKB/Swiss-Prot as a whole. EC level 2 is a coarse target, and curation and
sampling choices can affect class balance and apparent difficulty.

## Similarity controls

Random and cluster-aware splits answer different leakage questions. MMseqs2 thresholds and the
connected-component construction reduce specified forms of within-cohort similarity leakage;
they do not prove biological independence or absence of related proteins elsewhere. A zero
reported threshold violation means only that the implemented audit found none under its frozen
settings.

## Validation-only model results

The v0.3 and v0.4 experiments use Validation only. Real Test access remains disabled. Validation
scores are useful for checking the pipeline and comparing frozen protocols, but they are not final
benchmark estimates and should not be described as Test performance.

## ESM-2 representations

v0.4 covers only the approved 35M and 150M ESM-2 checkpoints, final-layer residue-mean pooling,
and one fixed linear probe. It does not study fine-tuning, alternative layers or pooling, larger
models, structural information, or hyperparameter optimization.

ESM-2 pretraining-corpus contamination is not audited. The project therefore cannot claim that
Validation or Test proteins, close homologs, or related annotations were absent from pretraining.
Cluster-aware cohort splits do not resolve this uncertainty.

## Reproducibility and hardware

Formal v0.4 replay is defined on a fixed Darwin/arm64 CPU float32 environment and requires exact
artifact equality. Cross-platform tolerance checks are diagnostic only. Exact replay on another
operating system, architecture, dependency set, or accelerator is not promised. Model files,
embeddings, detailed predictions, fitted estimators, and sequence-bearing inputs remain local and
must be obtained or regenerated under their upstream terms.

## Interpretation

The project records deterministic outputs and provenance; it does not guarantee that an input
database annotation is correct, that a similarity threshold captures functional relatedness, or
that a measured difference is scientifically meaningful. Formal conclusions require a separately
approved analysis after the Test gate is opened in a future release.
