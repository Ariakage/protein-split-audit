<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# ProteinSplitAudit

ProteinSplitAudit builds auditable protein-enzyme datasets and checks whether similar sequences
cross Train, Validation, and Test boundaries. Version 0.6.0 adds a prespecified post-Test analysis
and robustness audit over the frozen v0.5.0 predictions. It uses the five classical methods
released in v0.3.0, the two frozen ESM-2 methods released in v0.4.0, and the four splits frozen in
v0.2.0.

The release publishes aggregate results for a 442-protein, five-class *E. coli* K-12 pilot. It is
not a general protein benchmark. Protein sequences, accessions, record-level predictions,
embeddings, fitted models, caches, and run logs remain local and untracked.

## v0.6.0 post-Test analysis

The v0.6 protocol asks six fixed questions about split-level performance, nearest-Train identity,
sequence length, EC-class errors, ESM-2 versus classical features, and Nearest Homolog failure
modes. Robustness checks cover bootstrap seeds, component influence, class-balance sensitivity,
prediction agreement, and fixed component-size bins.

Formal analysis used two replacement sessions from clean Attestation Commit B2 after an earlier
nullable-metadata incident had been preserved. Both sessions analyzed the same canonical frozen
v0.5 Run A output. Their replay compared 11 deterministic files and found zero mismatches. No
model was loaded or executed, and no new Test inference was run.

The reviewed directory `results/released/v0.6.0/` contains ten aggregate CSV tables, an analysis
manifest, a replay report, and six PDF figures. The figures were regenerated from those same
authenticated CSV bytes after a separate presentation review. Missing or under-supported cells
are omitted, not shown as zero.

These summaries describe one small, class-imbalanced, organism-specific pilot. Bootstrap
intervals are descriptive; the release makes no significance claim, universal model ranking, or
general bacterial-enzyme benchmark claim.

## v0.5.0 frozen Test pilot

The frozen matrix contains 28 cells: Majority, Length Logistic, AAC Logistic, 3-mer Logistic,
Nearest Homolog, ESM-2 35M, and ESM-2 150M across Random, Cluster70, Cluster50, and Cluster30.
Every cell fits on Train, excludes Validation, predicts Test once, seals the prediction inventory,
and only then permits an in-memory label join for evaluation.

Formal access consisted of Run A followed immediately by Replay B from independent cache
namespaces. The first formal attempt produced identical predictions, metrics, and bootstrap
results, but its session name entered several derived artifact identities. The replay gate found
36 deterministic mismatches and blocked publication. That attempt, both access ledgers, and its
incident report remain preserved.

Protocol revision r1 fixed only session-specific artifact identity and was tested with synthetic
fixtures before the maintainer approved two replacement sessions. The replacement Run A and Run B
completed all 28 cells. Their comparator checked 430 deterministic files and found zero
mismatches, prediction disagreements, metric differences, or bootstrap differences.

The twelve reviewed files under `results/released/v0.5.0/` contain aggregate metrics, per-class
summaries, complete aggregate confusion counts, component-bootstrap intervals, prespecified
method comparisons, generalization gaps, environment and input hashes, the replay report, and the
approved attestation.

In this pilot, all 32 prespecified ESM-versus-AAC or ESM-versus-3-mer directed differences were
positive, with paired component-bootstrap intervals above zero. All eight ESM-2 150M-minus-35M
intervals and all 21 Random-minus-cluster Macro-F1 intervals included zero. These intervals are
descriptive uncertainty summaries, not hypothesis tests or evidence of a universal method order.

The only real-Test CLI surface is intentionally all-or-nothing:

```bash
uv run --locked psaudit experiment test-matrix \
  --config configs/experiment/v050-test.yaml
```

The two r1 sessions have been consumed. Release Commit C is not the attestation execution commit,
so the authorization gate rejects another real Test run from the released tree. There is no
single-cell, resume, parameter override, or interactive Test command, and no third Test session is
authorized.

## v0.4.0 frozen ESM-2 Validation matrix

The release uses immutable snapshots of `facebook/esm2_t12_35M_UR50D` and
`facebook/esm2_t30_150M_UR50D`. Representations come from the final encoder layer and are averaged
over residue tokens only. The models are frozen, truncation is disabled, and each split gets its
own Train and Validation embedding cache. StandardScaler and logistic regression fit on Train
rows only.

The fixed matrix has eight cells: two ESM-2 models across Random, Cluster70, Cluster50, and
Cluster30. Two clean CPU executions started from empty embedding caches. The replay compared 97
deterministic artifacts and found them byte-identical. A separate comparison found all 24 cache
files byte-identical.

The reviewed files under `results/released/v0.4.0/` contain aggregate tables, schema and
environment summaries, model snapshot hashes, and the protocol attestation. Model files,
embeddings, fitted estimators, predictions, accessions, sequences, logs, and complete run
directories remain local and ignored.

The protocol keeps `real_test_access_authorized: false`. It also records an unresolved limitation:
the project has not audited whether the pilot sequences appeared in ESM-2 pretraining data.

## v0.3.0 classical Validation matrix

The matrix combines five baselines, including Majority, three fixed feature baselines with
logistic regression, and a training-only MMseqs2 Nearest Homolog, with Random, Cluster70,
Cluster50, and Cluster30. Parameters, class order, seed 42, and MMseqs2 thread count are fixed
before evaluation.

Two clean executions produced 169 byte-identical deterministic artifacts. Only four reviewed,
sequence-free aggregate files are published under `results/released/v0.3.0/`. Models, feature
caches, predictions, neighbor rows, confusion matrices, logs, and complete run directories remain
local and ignored.

The protocol attestation keeps `real_test_access_authorized: false`. Test evaluation is deferred
until a later, separately approved freeze after the planned representation work is complete.

## v0.2.0 pilot

The source is UniProtKB/Swiss-Prot release `2026_02`, restricted to reviewed, non-fragment,
EC-annotated *E. coli* K-12 entries. The clean regeneration read 2,632 source records and retained
1,182 exact-deduplicated candidates. It reproduced the historical candidate Parquet and FASTA byte
for byte.

The approved `pilot-v1` rule requires at least 40 candidates and 10 observed cluster30 components
per EC-level-2 class. It selects exactly five classes without using model performance and has no
four-class fallback. The resulting cohort contains 442 proteins from classes `2.7`, `3.1`, `1.1`,
`2.1`, and `4.1`.

One fixed 30% all-vs-all MMseqs2 search supplies the normalized pair table used to derive strict
connected components at 70%, 50%, and 30% identity. Descriptive MMseqs2 clusters are recorded
separately and are never used as split groups. The cohort has 437 Cluster70 components, 427
Cluster50 components, and 398 Cluster30 components; the partitions satisfy
Cluster70 → Cluster50 → Cluster30 nesting.

Each split contains 308 Train, 68 Validation, and 66 Test proteins. No exact sequence crosses a
split, and no named strict component crosses its corresponding cluster-aware split. Independent
audits found zero threshold violations for Cluster70, Cluster50, and Cluster30. The Random Split
retains observed similarities as control statistics: four reported pairs reached 30% identity and
two reached 50%; none reached 70% under the fixed audit predicate. These are data-engineering audit
counts, not performance results.

Reviewed aggregate manifests are in `results/released/v0.2.0/`. Sequence-bearing Parquet, FASTA,
raw downloads, detailed pair tables, and protein-level audit rows remain local and untracked.

## Install

ProteinSplitAudit requires Python 3.12 and uses the checked-in uv lockfile:

```bash
uv sync --locked
uv run --locked psaudit --version
uv run --locked psaudit doctor
```

The distribution is `protein-split-audit`, the import package is `protein_split_audit`, and the
command-line program is `psaudit`.

## Commands

```text
psaudit --version
psaudit doctor
psaudit data download --config configs/dataset/pilot.yaml
psaudit data build --config configs/dataset/pilot.yaml
psaudit data profile --dataset <parquet> --build-manifest <json> --output-dir <dir>
psaudit cohort profile --dataset <parquet> --build-manifest <json> --fasta <fasta> --output-dir <dir>
psaudit cohort select --config configs/cohort/pilot.yaml
psaudit cohort validate --manifest <parquet> --content-manifest <json>
psaudit similarity cluster --config <yaml>
psaudit split create --config <yaml>
psaudit similarity audit --config <yaml>
psaudit feature extract --help
psaudit model train --help
psaudit evaluate --help
psaudit experiment run --help
psaudit embedding fetch --config configs/embedding/esm2_35m.yaml
psaudit embedding verify-model --config configs/embedding/esm2_35m.yaml
psaudit embedding extract --help
psaudit experiment matrix --config configs/experiment/v040-validation.yaml
psaudit experiment replay-compare --help
psaudit experiment summarize --help
psaudit experiment finalize-test --config configs/experiment/v040-test-gated.yaml
psaudit experiment test-matrix --config configs/experiment/v050-test.yaml
```

Only `data download` and the explicit `embedding fetch` command use the network. Snapshot
verification, extraction, experiments, and tests run offline. Tests use synthetic fixtures,
mocked HTTP transport, and an application-level network guard. MMseqs2 is required for real
similarity operations and the Nearest Homolog baseline but is not run in default CI.

Formal v0.2 configurations live in `configs/similarity/`, `configs/splits/`, and
`configs/audits/`. They use fixed thresholds, seed 42, 70/15/15 target ratios, explicit output
paths, and no-overwrite publication.

## Verify the repository

```bash
uv lock --check
uv sync --locked --group dev
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv run --locked pytest -v
uv build
```

The data rules are in `docs/protocol.md`. The frozen Test protocol and its replay-identity revision
are in `docs/protocols/v0.5.0-frozen-test-evaluation.md`. The frozen ESM-2 protocol is in
`docs/protocols/v0.4.0-esm2-baselines.md`, and the classical protocol remains in
`docs/protocols/v0.3.0-classical-baselines.md`. `docs/reproducibility.md` explains the clean replay
workflow, while `docs/data_card.md` describes the pilot's scope and limitations. Release-specific
identities are summarized in `docs/releases/v0.5.0.md`.

## Data, licenses, and citation

Original code and tests use Apache-2.0. Original documentation uses CC-BY-4.0. UniProt-derived
sequences and metadata keep their upstream terms; ProteinSplitAudit does not relicense them. See
`LICENSES/`, `DATA_LICENSE.md`, `THIRD_PARTY_NOTICES.md`, and `docs/LICENSE_POLICY.md`.

Citation metadata is available in `CITATION.cff`.
