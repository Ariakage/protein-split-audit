# ProteinSplitAudit: A Protocol-Driven Framework for Auditable Similarity-Aware Evaluation of Protein Classifiers

**Authors:** Aria Chen (corresponding author), Hangzhou No.11 High School, Hangzhou, China. Email: ariakage233@gmail.com. ORCID: 0009-0001-6214-219X.

## Abstract

Sequence similarity complicates evaluation of protein classifiers: a random split can place related proteins on both sides of a Train/Test boundary, and a similarity-aware split can quietly fail when search parameters, graph construction, allocation rules, or model-selection steps are not recorded. ProteinSplitAudit is an open-source Python framework that turns those decisions into reviewable artifacts. It connects source acquisition, candidate filtering, exact deduplication, deterministic cohort selection, MMseqs2 similarity search, strict similarity components, grouped splitting, leakage audits, Train-only evaluation, capability-gated Test access, deterministic replay, and aggregate-only publication, joined by one SHA-256 evidence chain. The software is demonstrated on a bounded five-class *Escherichia coli* K-12 enzyme pilot and on an offline synthetic demonstration that is byte-identical across runs and platforms.

**Keywords:** protein classification; data leakage; similarity-aware splitting; reproducible research; research software; bioinformatics

## (1) Overview

### Introduction

Protein researchers need evaluation workflows that preserve more than a final split file. The source query can drift, duplicate annotations can conflict, a cluster representative can be mistaken for a strict component, a model can learn from Validation or Test data, and a reporting step can detach results from the code and inputs that generated them. A successful training command does not show that these boundaries held. ProteinSplitAudit is intended for researchers and reviewers who need to inspect that evidence chain without trusting undocumented preprocessing or private operational history.

Homology-aware partitioning is an established requirement in biological machine learning. GraphPart constructs homology-separated partitions while retaining labeled examples [@teufel2023graphpart]. SpanSeq uses similarity-based sequence partitioning at scales that include proteins, genes, and genomes [@ferrerflorensa2024spanseq]. DataSAIL formalizes leakage-reduced splitting for one- and two-dimensional biomedical data and balances specified classes [@joeres2025datasail]. These tools address the partitioning problem with different algorithms and objectives. ProteinSplitAudit addresses the complementary operational problem of preserving the complete evaluation lineage around a similarity-aware split. It builds on UniProt [@uniprot2025], MMseqs2 [@steinegger2017mmseqs2], scikit-learn [@pedregosa2011scikit], and frozen protein-language-model representations instead of replacing those tools.

The framework therefore treats protocols, content hashes, manifests, gates, replay reports, and release allowlists as first-class outputs. Its main contribution is not a new graph-partitioning algorithm; it is an integrated and testable method for making a similarity-aware evaluation auditable from source bytes to public aggregates.

## (2) Implementation and Architecture

ProteinSplitAudit is organized as a sequence of narrow stages behind a single command-line interface (`psaudit`). Each stage validates its parent artifacts before processing and refuses silent overwrite. Deterministic content artifacts exclude timestamps and host-specific paths; run provenance records operational details separately. SHA-256 links connect source files, configurations, parent manifests, derived outputs, the lockfile, and software state.

The candidate stage downloads a fixed UniProtKB search, normalizes paginated TSV responses, and records a sanitized response-header allowlist. It accepts one complete four-level EC annotation per record, maps the target to EC level 2, validates the standard amino-acid alphabet and length, and handles exact duplicates by explicit rules: equal-label duplicates retain one canonical record plus aliases, while conflicting-label duplicates are removed as a group and reported.

The similarity stage calls MMseqs2 with frozen identity, coverage, E-value, sensitivity, alignment, and thread settings. Descriptive MMseqs2 clusters are kept separate from the strict graph used for leakage control. For a threshold *t*, the graph contains an undirected edge for every accepted observed pair with identity at least *t*. Connected components are indivisible allocation units. Component identifiers are hashes of sorted exact-sequence hashes, which makes membership independent of input order or of any MMseqs2 representative.

The split stage creates one sequence-stratified Random control and grouped splits at 70%, 50%, and 30% identity. It checks exact cohort coverage, label coverage, target-ratio tolerances, exact-sequence isolation, component isolation, and nesting of strict partitions. A separate Test-to-Train search audits the resulting boundary instead of assuming that construction implies successful separation.

The evaluation stages enforce Train-only preprocessing and fitting. Classical baselines and frozen ESM-2 representations [@lin2023esm2] use fixed configurations and label order. Because downstream splitting alone cannot establish independence from protein-language-model pretraining [@hermann2024pretraining], the framework records that uncertainty rather than treating it as resolved.

The real Test path is capability-gated. An attestation binds a clean execution commit, the lockfile, input hashes, the method matrix, allowed session names, the session count, and permanent maintainer approval. Predictions are sealed before Test labels are joined in memory. Formal execution cannot resume a partial matrix or add a session. Publication admits only a fixed aggregate file set and rejects record identifiers, sequences, private paths, and secrets.

### Bounded pilot demonstration

The frozen pilot uses UniProtKB/Swiss-Prot release 2026_02 and taxonomy ID 83333. Of 2,632 source records, 1,182 passed candidate construction. A predeclared rule selected five EC-level-2 classes without model performance, producing a cohort of 442 proteins. The strict graphs contain 437, 427, and 398 components at 70%, 50%, and 30% identity. Each split contains 308 Train, 68 Validation, and 66 Test records. The three grouped splits have zero component crossings and zero matching-threshold Test-to-Train violations under the frozen MMseqs2 predicate; the Random control contains four reported pairs at or above 30% identity, two at or above 50%, and none at or above 70%. Seven fixed methods evaluated across four splits, after a session-identity defect was caught by replay and corrected, matched across 430 deterministic artifacts. All 21 prespecified Random-minus-cluster Macro-F1 intervals include zero, so the pilot does not support a claim that stricter clustering monotonically lowers performance. The pilot illustrates the audit path; it is not offered as a representative enzyme benchmark.

## (3) Quality Control

The package targets Python 3.12 and uses a checked-in `uv.lock` lockfile (176 resolved packages). Continuous integration on every push and tag checks the lock, formatting, static types, 837 unit and integration tests, a tracked-artifact policy, the package build, and an isolated wheel smoke test. Network access is denied inside the test process; HTTP tests use mocked transports, and default CI does not execute UniProt, MMseqs2, or ESM-2.

Determinism is exercised by `psaudit demo run`, an access-independent synthetic path that generates 90 protein-like records, constructs 45 strict components, creates Random and Cluster30 splits, extracts amino-acid composition, fits a Train-only logistic model, evaluates synthetic Test rows, and writes three aggregate files. Two runs in new directories are byte-identical; an independent reviewer on a different architecture reproduced the same artifact hashes (see below). Every numerical statement in the companion manuscript was cross-checked against the frozen release artifacts by a verification script (47 matching checks), with the manuscript source hashes registered in an attestation record.

The project also preserves negative evidence. A replay gate detected a session-identity defect in the first formal Test session; the failed replay and its incident report remain visible in the repository and cannot be silently replaced by a successful rerun.

An independent reproduction from a clean checkout of tag v0.7.0 was completed by a reviewer other than the primary implementation operator (GitHub user urntt); the public record (GitHub issue #7) reports the environment, every command with exit status, 837 passing tests, two byte-identical demo runs whose artifact hashes match the maintainer's archived container run, the CI run for the same commit, and a statement of no deviations.

## (4) Availability

**Operating system:** Linux (tested in CI and container reproduction) and macOS (development); the synthetic demonstration is platform-independent and was reproduced byte-identically across aarch64 and x86_64.

**Programming language:** Python 3.12.

**Additional system requirements:** The `uv` package manager installs the exact locked environment; no separate Python installation is required. The offline synthetic demonstration needs no external tools and no network access. Replaying the frozen pilot additionally requires MMseqs2 `18-8cc5c` and ESM-2 weights, which are documented separately and are not required to install or exercise the software.

**Dependencies:** biopython, httpx, joblib, matplotlib, numpy, pandas, psutil, pyarrow, pydantic, pyyaml, rich, scikit-learn, scipy, tqdm, typer (core); PyTorch and fair-esm only for the optional ESM embedding extra. All versions are pinned in `uv.lock`.

**List of contributors:** Aria Chen (sole author).

**Software location:**

- **Archive:** Zenodo record 22164608, DOI 10.5281/zenodo.22164608 (v0.7.0, bound to the GitHub tag `v0.7.0`), Apache-2.0, published 2026-08-29 [@proteinsplitaudit].
- **Code repository:** https://github.com/ariakage/protein-split-audit (Apache-2.0; original documentation CC-BY-4.0).
- **Documentation:** In-repository documentation (`docs/`) including a tutorial, the independent-reproduction protocol, and the reproducibility guide; the CLI exposes `psaudit --help` at every level.

**Language:** English.

UniProt-derived data retain their upstream terms and are not redistributed as part of the public repository; released aggregates contain no protein sequence or row-level prediction.

## (5) Reuse Potential

ProteinSplitAudit demonstrates how leakage control can be represented as a reviewable protocol rather than an undocumented preprocessing choice. Its components are useful independently: a project can adopt deterministic content manifests, strict observed-edge components, split validators, Test capability gates, replay inventories, or aggregate publication guards without using the pilot dataset. The offline synthetic demonstration lets any reader exercise the core software path without controlled data, and the independent-reproduction protocol documents exactly how a third party can verify a released tag. The intended audience is small and medium protein-prediction studies where data access, pretrained representations, and post-analysis steps make the evaluation lineage difficult to inspect. Known limits are part of the claim boundary: one organism, five coarse classes, one cohort seed, 66 Test proteins per split, two ESM-2 checkpoints, one pooling rule, one linear probe, and unmeasured pretraining overlap.

## Funding Statement

No research funding supported this work. The project was partially refined during the Zhijisong Minicamp2026 hackathon (AI+Life Science track champion; prize: a 500-CNY JD.com E-card). This is a competition award, not research funding.

## Competing Interests

The author declares no competing interests.

## Acknowledgements

The author thanks the maintainers of UniProt, MMseqs2, ESM-2, and scikit-learn, and the independent reviewer (GitHub user urntt) who completed the clean-checkout reproduction recorded in issue #7.

## Author Contributions

Aria Chen is the sole author and performed all CRediT roles: conceptualization, methodology, software, validation, formal analysis, writing (original draft), writing (review and editing), visualization, and project administration.

## AI-Use Disclosure

OpenAI Codex was used during software development for code generation, refactoring, test design, repository inspection, and drafting documentation. The author defined the scientific scope, approved frozen protocols and access gates, supplied permanent approval records, reviewed changes, and controlled commits and releases. Generated work was checked with static analysis, offline tests, artifact hashes, replay gates, and human review. No AI system was authorized to approve a protocol, impersonate the author, open additional Test access, or create a release without explicit author authorization.

## References
