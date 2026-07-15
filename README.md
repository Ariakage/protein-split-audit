<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# ProteinSplitAudit

ProteinSplitAudit builds a candidate protein enzyme dataset with enough provenance to audit each
source and transformation step. The current development version is 0.2.0.dev0. Its first
similarity-analysis foundations are now in place: validated v0.2.0 configuration and CLI
namespaces, an aggregate candidate-pool profile, controlled MMseqs2 execution and parsing, and
deterministic 30% identity candidate-discovery artifacts for the E. coli K-12 pilot.

## Project status

ProteinSplitAudit v0.1.0 is the project's first public software release. The v0.1.1 correction tag
updates public documentation and version metadata without changing its candidate-dataset
pipeline. Neither version is a frozen benchmark dataset.

The v0.2.0 development branch can validate and profile the full candidate pool, run a fixed 30%
identity MMseqs2 self-search, parse its output, and derive deterministic observed fixed-parameter
similarity components from the reported edges. This candidate-discovery pass validates the
engineering workflow before a pilot cohort is frozen. The default configuration runs in
development mode and marks its manifest as ineligible for release.

Deterministic provisional cohort selection and exact cohort-manifest validation are implemented.
The frozen rules require at least 40 sequences and 10 observed 30%-identity discovery components
per class, then select exactly five classes without using model performance. The current output is
named `pilot-v1-candidate` and is not release eligible. Formal 70%, 50%, and 30% cohort groupings,
random or cluster-aware train/validation/test splits, train-test similarity audits, features,
model training, and benchmark claims are not implemented yet.

Raw downloads and processed files containing UniProt sequences remain local and untracked. The
current development branch contains changes made after the v0.1.1 corrective tag.

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

## Commands currently available

```text
psaudit --version
psaudit doctor
psaudit data download --config configs/dataset/pilot.yaml
psaudit data build --config configs/dataset/pilot.yaml
psaudit data profile \
  --dataset data/processed/pilot.parquet \
  --build-manifest data/manifests/pilot.build.json \
  --output-dir results/runs/profile-pilot/
psaudit cohort profile \
  --dataset data/processed/pilot.parquet \
  --build-manifest data/manifests/pilot.build.json \
  --fasta data/processed/pilot.fasta \
  --output-dir results/runs/cohort-candidate-profile/
psaudit similarity cluster \
  --config configs/similarity/candidate-pool-cluster30.yaml
psaudit cohort select --config configs/cohort/pilot.yaml
psaudit cohort validate \
  --manifest data/manifests/cohorts/pilot-v1-candidate.parquet \
  --content-manifest data/manifests/cohorts/pilot-v1-candidate.json
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

`cohort profile` validates the candidate Parquet, build manifest, and FASTA together, then writes
three aggregate summaries without selecting classes or proteins. `similarity cluster` requires
those local candidate files plus a compatible local MMseqs2 installation. The supplied
`candidate-pool-cluster30.yaml` configuration is a development-only discovery run: it writes
deterministic normalized pair and component artifacts with content and run provenance, but it
does not freeze the pilot cohort or produce release-eligible grouping artifacts.

`cohort select` applies the fixed `40 sequences / 5 classes / 10 cluster30 groups` protocol and
runs a deterministic grouped-split feasibility preflight. It fails if fewer than five classes are
eligible; there is no automatic four-class fallback. `cohort validate` reloads the parent inputs
and recomputes the selection before accepting the provisional artifacts. Freezing `pilot-v1`
remains blocked until the candidate pipeline is regenerated from a fixed clean commit and its
deterministic difference report receives an external maintainer attestation.
After that review is signed, the tracked `configs/cohort/pilot-freeze.yaml` configuration binds
the reviewed clean lineage and publishes `pilot-v1`; it fails before publication if any bound
commit, lock, source, build, discovery, report, or attestation hash has changed.

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
