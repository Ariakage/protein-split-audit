<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# ProteinSplitAudit

ProteinSplitAudit builds a candidate protein enzyme dataset with enough provenance to audit each
source and transformation step. Version 0.1.1 is a documentation and release-metadata correction
to the reviewed UniProtKB/Swiss-Prot E. coli K-12 enzyme pilot workflow published in v0.1.0. It
does not change the pipeline, choose final EC classes, create train/validation/test splits, train
models, or report benchmark results.

## Project status

ProteinSplitAudit v0.1.0 is the project's first public software release. The v0.1.1 correction tag
updates public documentation and version metadata without changing its candidate-dataset
pipeline. Neither version is a frozen benchmark dataset. The software does not run MMseqs2
clustering, create train/validation/test splits, train or evaluate models, or make claims about
sequence leakage or predictive performance.

Raw downloads and processed files containing UniProt sequences remain local and untracked. The
current development branch may contain changes made after the v0.1.0 tag.

The tracked pilot manifests record 2,632 downloaded E. coli K-12 entries and 1,182 retained
candidate proteins. Both the download and build were produced from commit `9a08feb` while the
working tree was dirty. Their hashes remain useful for auditing the local files, but this run is a
development pilot, not a clean research-data freeze. Any formally frozen dataset must be
regenerated from a clean working tree and record `git_dirty: false`.

See `docs/releases/v0.1.0.md` for the published pipeline scope and `docs/releases/v0.1.1.md` for
the corrective tag. The earlier readiness review is preserved in
`docs/audits/v0.1.0-pre-release-readiness.md` as a historical record.

## Install

ProteinSplitAudit requires Python 3.12. Install the environment from the checked-in uv lockfile:

```bash
uv sync --locked
uv run psaudit --version
uv run psaudit doctor
```

The distribution is named `protein-split-audit`, the Python package is `protein_split_audit`, and
the command-line program is `psaudit`.

## Commands available in v0.1.1

```text
psaudit --version
psaudit doctor
psaudit data download --config configs/dataset/pilot.yaml
psaudit data build --config configs/dataset/pilot.yaml
psaudit data profile \
  --dataset data/processed/pilot.parquet \
  --build-manifest data/manifests/pilot.build.json \
  --output-dir results/runs/profile-pilot/
```

Only `data download` may contact UniProt. Run it after a maintainer has reviewed the query. The
test suite uses synthetic fixtures, mocked HTTP transport, and an application-level network guard.

`data build` accepts records with one complete four-level EC annotation, maps each accepted EC to
level 2, and checks sequences against the standard 20-amino-acid alphabet and the inclusive length
range of 50 to 1000 residues. Exact duplicate handling is deterministic. The resulting Parquet and
FASTA files stay in the ignored `data/processed/` directory.

`data profile` produces deterministic aggregate summaries only. Development output belongs in
`results/runs/`. A maintainer may later approve sequence-free copies for
`results/released/v0.1.0/`.

## Check the repository

```bash
uv lock --check
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv build
```

The research rules are in `docs/protocol.md`, and `docs/reproducibility.md` explains how hashes and
provenance support replay. `docs/data_card.md` describes the candidate data and approved aggregate
outputs.

## Data, licenses, and citation

Original code and tests use Apache-2.0. Original documentation uses CC-BY-4.0. UniProt-derived
sequences and metadata keep their upstream terms; this project does not relicense them. Details are
in `LICENSES/`, `DATA_LICENSE.md`, `THIRD_PARTY_NOTICES.md`, and `docs/LICENSE_POLICY.md`.

Citation metadata is available in `CITATION.cff`.
