---
title: >-
  ProteinSplitAudit: a protocol-driven framework for auditable
  similarity-aware evaluation of protein classifiers
tags:
  - bioinformatics
  - protein classification
  - data leakage
  - reproducible research
  - machine learning
author: Aria Chen
authors:
  - name: Aria Chen
    affiliation: Hangzhou No.11 High School
    email: ariakage233@gmail.com
    orcid: 0009-0001-6214-219X
    corresponding: true
bibliography: paper.bib
---

# Summary

Sequence similarity complicates evaluation of protein classifiers. A random split can place
related proteins on both sides of a Train--Test boundary, while a similarity-aware split can
quietly fail if search parameters, graph construction, allocation rules, data identities, or
model-selection steps are not recorded. ProteinSplitAudit is an open-source Python workflow for
turning those choices into reviewable artifacts. It connects source acquisition, candidate
filtering, exact deduplication, deterministic cohort selection, MMseqs2 search, strict similarity
components, grouped splitting, Train--Test leakage audits, model evaluation, controlled Test
access, deterministic replay, and aggregate-only release reporting.

The software is demonstrated on a bounded five-class *Escherichia coli* K-12 enzyme pilot. The
pilot illustrates the audit path; it is not offered as a representative enzyme benchmark or as
evidence for a universal model ranking. A separate synthetic command reproduces the core software
path entirely offline without exposing protein records or opening the frozen pilot Test set.

# Statement of need

Protein researchers need evaluation workflows that preserve more than a final split file. The
source query can drift, duplicate annotations can conflict, a cluster representative can be
mistaken for a strict component, a model can learn from Validation or Test, and a reporting step
can detach results from the code and inputs that generated them. A successful training command
does not show that these boundaries held. ProteinSplitAudit is intended for researchers and
reviewers who need to inspect that evidence chain without trusting undocumented preprocessing or
private operational history.

# State of the field

Homology-aware partitioning is an established requirement in biological machine learning.
GraphPart constructs homology-separated partitions while retaining labeled examples
[@teufel2023graphpart]. SpanSeq uses similarity-based sequence partitioning at scales that include
proteins, genes, and genomes [@ferrerflorensa2024spanseq]. DataSAIL formalizes leakage-reduced
splitting for one- and two-dimensional biomedical data and balances specified classes
[@joeres2025datasail]. These tools address the partitioning problem with different algorithms and
objectives.

ProteinSplitAudit addresses the complementary operational problem of preserving the complete
evaluation lineage around a similarity-aware split. It builds on UniProt, MMseqs2, scikit-learn,
and frozen protein-language-model representations instead of replacing those tools.

The project therefore treats protocols, content hashes, manifests, gates, replay reports, and
release allowlists as first-class outputs. Its main contribution is not a new graph-partitioning
algorithm. It is an integrated and testable method for making a similarity-aware evaluation
auditable from source bytes to public aggregates.

# Software design

ProteinSplitAudit is organized as a sequence of narrow stages. Each stage validates its parent
artifacts before processing and refuses silent overwrite. Deterministic content artifacts exclude
timestamps and host-specific paths; run provenance records operational details separately.
SHA-256 links source files, configurations, parent manifests, derived outputs, the lockfile, and
software state.

The candidate stage downloads a fixed UniProtKB search [@uniprot2025], normalizes paginated TSV,
and records a sanitized response-header allowlist. It accepts one complete four-level EC
annotation, maps the target to EC level 2, validates the standard amino-acid alphabet and length,
and handles exact duplicates by explicit rules. Equal-label duplicates retain one canonical
record and aliases; conflicting-label duplicates are removed as a group and reported.

The similarity stage calls MMseqs2 [@steinegger2017mmseqs2] with frozen identity, coverage,
E-value, sensitivity, alignment, and thread settings. Descriptive MMseqs2 clusters are kept
separate from the strict graph used for leakage control. For a threshold (t), the graph contains
an undirected edge for every accepted observed pair with identity at least (t). Connected
components are indivisible allocation units. Component identifiers are hashes of sorted exact
sequence hashes, which makes membership independent of input order or an MMseqs2 representative.

The split stage creates one sequence-stratified Random control and grouped splits at 70%, 50%, and
30% identity. It checks exact cohort coverage, label coverage, target-ratio tolerances, exact-
sequence isolation, component isolation, and nesting of strict partitions. A separate
Test-to-Train search audits the resulting boundary instead of assuming that construction implies
successful separation.

The evaluation stages enforce Train-only preprocessing and fitting. Classical baselines and
frozen ESM-2 representations [@lin2023esm2] use fixed configurations and label order. Because
downstream splitting alone cannot establish independence from protein-language-model pretraining
[@hermann2024pretraining], ProteinSplitAudit records that uncertainty rather than treating it as
resolved.

The real Test path is capability-gated. An attestation binds a clean execution commit, lockfile,
input hashes, method matrix, allowed session names, session count, and permanent maintainer
approval. Predictions are sealed before Test labels are joined in memory. Formal execution cannot
resume a partial matrix or add a third session. Publication admits only a fixed aggregate file
set and rejects record identifiers, sequences, private paths, and secrets.

# Bounded pilot demonstration

The frozen pilot uses UniProtKB/Swiss-Prot release `2026_02` and taxonomy ID 83333. Of 2,632 source
records, 1,182 passed candidate construction. A predeclared rule selected five EC-level-2 classes
without model performance, producing 442 proteins. The strict graphs contain 437, 427, and 398
components at 70%, 50%, and 30% identity. Each split contains 308 Train, 68 Validation, and 66
Test records.

The three grouped splits have zero component crossings and zero matching-threshold Test-to-Train
violations under the frozen MMseqs2 predicate. The Random control contains four reported pairs at
or above 30% identity, two at or above 50%, and none at or above 70%. Thus, this particular Random
split already has little observed high-identity leakage; it is not a strong experiment for
estimating how much random splitting inflates performance.

Seven fixed methods were evaluated across four splits. After a session-identity defect was caught
by replay and corrected using synthetic fixtures, two approved replacement Test sessions matched
across 430 deterministic artifacts. The fixed post-Test analysis was also replayed exactly. All
21 prespecified Random-minus-cluster Macro-F1 intervals include zero. ProteinSplitAudit therefore
does not claim that increasingly strict clustering monotonically lowers performance or that one
split is universally preferable.

# Reproducibility and availability

The package targets Python 3.12 and uses a checked-in `uv.lock`. CI checks the lock, formatting,
static types, unit and integration tests, tracked-artifact policy, package build, and an isolated
wheel smoke test. Network access is denied inside the test process; HTTP tests use mocked
transports, and default CI does not execute UniProt, MMseqs2, or ESM-2.

`psaudit demo run` provides an access-independent reproduction path. It generates 90
protein-like records, constructs 45 strict synthetic components, creates Random and Cluster30
splits, extracts amino-acid composition, fits a Train-only logistic model, evaluates synthetic
Test rows, and writes three aggregate files. Two runs in new directories are byte-identical. The
demo is deliberately synthetic and supplies software verification, not scientific evidence.

Source code is available under Apache-2.0 and original documentation under CC-BY-4.0 at
<https://github.com/Ariakage/protein-split-audit> [@proteinsplitaudit]. UniProt-derived data retain
their upstream terms and are not redistributed as part of the public repository. Versioned
release aggregates contain no protein sequence or row-level prediction.

# Research impact

ProteinSplitAudit demonstrates how leakage control can be represented as a reviewable protocol
rather than an undocumented preprocessing choice. Its components are useful independently: a
project can adopt deterministic content manifests, strict observed-edge components, split
validators, Test capability gates, replay inventories, or aggregate publication guards without
using the pilot dataset. The incident-preserving workflow also provides negative evidence: a
failed replay remains visible and cannot be silently replaced by a successful rerun.

The intended impact is methodological discipline for small and medium protein-prediction studies,
especially those where data access, pretrained representations, and post-Test analysis make the
lineage difficult to inspect. The pilot shows feasibility and exposes where evidence remains
weak; broader scientific conclusions require more organisms, cohorts, seeds, and independent
reproduction.

# Limitations

The pilot contains one organism, five coarse classes, one seed, and 66 Test proteins per split.
Class supports are uneven, and many subgroup analyses are suppressed. The fixed MMseqs2 predicate
does not prove biological independence. Only two ESM-2 checkpoints, one pooling rule, and one
linear probe are evaluated. Pretraining overlap is unmeasured. Raw sequence-bearing artifacts are
not published, so an independent scientific replay requires lawful source regeneration. These
limits are part of the claim boundary, not caveats to be removed by interpretation.

# AI-use disclosure

OpenAI Codex was used during software development for code generation, refactoring, test design,
repository inspection, and drafting documentation. The maintainer defined the scientific scope,
approved frozen protocols and access gates, supplied permanent approval records, reviewed
changes, and controlled commits and releases. Generated work was checked with static analysis,
offline tests, artifact hashes, replay gates, and human review. No AI system was authorized to
approve a protocol, impersonate the maintainer, open additional Test access, or create a release
without explicit maintainer authorization. This disclosure must be reviewed and adapted to the
target journal's policy before submission.

# Acknowledgements

Funding, contributor roles, conflicts of interest, and the target journal's required declarations
remain to be supplied and approved by the maintainer before submission.
