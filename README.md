<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# ProteinSplitAudit

ProteinSplitAudit builds auditable protein-enzyme datasets and checks whether similar sequences
leak across Train, Validation, and Test boundaries. Version 0.2.0 adds a frozen E. coli K-12 pilot
cohort, MMseqs2 similarity groups, one random split, three cluster-aware splits, and independent
test-to-train similarity audits.

This release answers an engineering question: can the same candidate proteins be partitioned in a
deterministic, traceable way while keeping each strict similarity component intact? It does not
train a model or report benchmark performance.

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
```

Only `data download` contacts UniProt. Tests use synthetic fixtures, mocked HTTP transport, and an
application-level network guard. MMseqs2 is required for real similarity operations but is not
run in default CI.

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

The research rules are in `docs/protocol.md`. `docs/reproducibility.md` explains the clean
generation and publication commits, and `docs/data_card.md` describes the pilot's scope and
limitations. Release-specific hashes and audit counts are summarized in
`docs/releases/v0.2.0.md`.

## Data, licenses, and citation

Original code and tests use Apache-2.0. Original documentation uses CC-BY-4.0. UniProt-derived
sequences and metadata keep their upstream terms; ProteinSplitAudit does not relicense them. See
`LICENSES/`, `DATA_LICENSE.md`, `THIRD_PARTY_NOTICES.md`, and `docs/LICENSE_POLICY.md`.

Citation metadata is available in `CITATION.cff`.
