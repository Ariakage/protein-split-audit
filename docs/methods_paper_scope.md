<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Methods-paper scope and claim boundary

## Proposed article

Working title: **ProteinSplitAudit: a protocol-driven framework for auditable similarity-aware
evaluation of protein classifiers**.

The suitable article type is a methods/software paper with a bounded *E. coli* K-12 case study.
It is not a new splitting-algorithm paper and not a general enzyme benchmark paper.

## Contributions the evidence supports

1. An end-to-end workflow links source capture, candidate filtering, exact deduplication,
   deterministic cohort selection, similarity components, split allocation, leakage audits,
   model evaluation, Test-access control, replay, and aggregate publication.
2. Content artifacts are separated from timestamped run provenance and bound by SHA-256,
   configurations, software versions, Git state, and parent manifests.
3. Observed similarity edges are converted into strict connected components, and the matching
   grouped split is rejected if a component or exact sequence crosses a boundary.
4. A capability-style gate freezes Test identities, code, inputs, methods, session count, and
   maintainer approval before labels can be joined to predictions.
5. Deterministic replay and public allowlists make software and release failures visible instead
   of silently replacing earlier evidence.
6. A fully offline synthetic command lets readers exercise the core method path without access to
   controlled protein records or model snapshots.

## Claims that are explicitly blocked

- ProteinSplitAudit does not introduce the general idea of homology-aware or
  similarity-reduced splitting. GraphPart, SpanSeq, and DataSAIL already address that problem with
  different algorithms and objectives.
- The 442-protein pilot is not representative of bacteria, enzymes, or UniProtKB/Swiss-Prot.
- The released results do not establish a universal ordering of Random, Cluster70, Cluster50, and
  Cluster30 splits or of the seven evaluated methods.
- The project does not claim that Random splitting inflated this pilot's scores. All 21 frozen
  Random-minus-cluster Macro-F1 intervals include zero.
- A zero threshold violation is conditional on the frozen MMseqs2 search and predicate; it is not
  proof of evolutionary independence.
- The ESM-2 evaluation is not known to be independent of its pretraining corpus.
- The synthetic demo supplies software evidence only, not scientific validation.

## Pilot facts that may be reported

- UniProtKB/Swiss-Prot release `2026_02`, taxonomy ID 83333, 2,632 downloaded source records,
  1,182 accepted exact-deduplicated candidates, and 442 frozen cohort proteins.
- Five EC-level-2 classes with frozen counts 192, 85, 59, 57, and 49.
- 437 Cluster70, 427 Cluster50, and 398 Cluster30 strict components.
- Four splits with 308 Train, 68 Validation, and 66 Test records each.
- Zero matching-threshold component crossings in the three grouped splits; Random control counts
  of four observed Test-to-Train pairs at 30%, two at 50%, and none at 70%.
- Seven fixed methods across four splits; two replacement v0.5 sessions matched across 430
  deterministic artifacts.
- The v0.6 analysis replay matched all 11 deterministic analysis files. Small or unsupported
  strata were suppressed under frozen rules.

## Submission blockers and maintainer decisions

The manuscript may be drafted now. Submission remains blocked until all items below are resolved:

- choose a target journal and adapt its article template and length limits;
- the author and corresponding-author metadata are now fixed as Chen Jiajie (Aria Chen), Hangzhou No.11 High
  School, `ariakage233@gmail.com`, ORCID `0009-0001-6214-219X`; supply a postal address if the
  selected journal requires one;
- supply and approve the funding statement and conflict-of-interest statement;
- review and approve the AI-use disclosure in `paper/paper.md`;
- create a permanent software archive and DOI for the exact submission release;
- complete at least one independent clean-checkout reproduction by someone other than the primary
  implementation operator, recording environment and artifact hashes;
- decide whether the paper will remain a single-organism methods demonstration or add a separately
  prespecified external dataset before submission;
- verify every numerical statement against the released aggregate files and freeze the manuscript
  source hash before submission.

The historical released artifacts are immutable. Post-release approvals or clarifications must be
added as separate attestations, never written back into a released manifest.
