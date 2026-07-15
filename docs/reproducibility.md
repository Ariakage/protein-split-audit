<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Reproducing ProteinSplitAudit v0.2.0

## Two-commit release model

Formal data was generated from clean commit
`47ba9cd7a79b7fda191e779be2f98cd2a33cefa3`, called generation commit A. Its `uv.lock` SHA-256 is
`326cd0e038ab9deabd8d82a8138dbbf848d5239b55b09d814a3d7c01ff542fde`. Every formal content
manifest records that commit with `git_dirty: false`.

The release commit, publication commit B, adds reviewed aggregate copies, documentation, citation
metadata, and version `0.2.0`. It does not regenerate sequence-bearing artifacts. This separation
avoids a circular requirement in which release files would have to be present before the data
generation commit could be fixed.

## Environment

Use Python 3.12, the checked-in lockfile, and MMseqs2 `18-8cc5c` for formal similarity replay:

```bash
uv lock --check
uv sync --locked --group dev
uv run --locked psaudit --version
uv run --locked psaudit doctor
```

Only `psaudit data download` uses the network. Tests block real socket connections and use mocked
HTTP transport. Default CI does not install or run MMseqs2.

## Clean candidate regeneration

Create an isolated checkout at generation commit A, confirm `git status --porcelain` is empty, and
run:

```bash
uv run --locked psaudit data download \
  --config configs/dataset/pilot-clean-regeneration.yaml
uv run --locked psaudit data build \
  --config configs/dataset/pilot-clean-regeneration.yaml
uv run --locked psaudit similarity cluster \
  --config configs/similarity/candidate-pool-cluster30-clean-regeneration.yaml
```

The v0.2 run recorded UniProt release `2026_02`, 2,632 source records, and 1,182 retained
candidates. The deterministic difference report against v0.1 is `byte_identical`. The maintainer
attestation binds the new source, build, discovery, difference, commit, and lock hashes before the
cohort freeze can run.

## Cohort, similarity, and splits

After the approved attestation is present:

```bash
uv run --locked psaudit cohort select --config configs/cohort/pilot-freeze.yaml

uv run --locked psaudit similarity cluster \
  --config configs/similarity/pilot-v1-cluster30.yaml
uv run --locked psaudit similarity cluster \
  --config configs/similarity/pilot-v1-cluster50.yaml
uv run --locked psaudit similarity cluster \
  --config configs/similarity/pilot-v1-cluster70.yaml

for name in random cluster70 cluster50 cluster30; do
  uv run --locked psaudit split create --config "configs/splits/${name}.yaml"
done
```

Cluster30 creates the normalized base pair table. Cluster50 and Cluster70 verify its configured
hash and derive strict components from those same edges. A matrix-wide check must confirm exact
cohort coverage and Cluster70 → Cluster50 → Cluster30 nesting.

## Train-to-test audits

```bash
for name in random cluster70 cluster50 cluster30; do
  uv run --locked psaudit similarity audit --config "configs/audits/${name}.yaml"
done
```

Every Test sequence must receive a nearest observed Train neighbor or an explicit no-match row.
Random exceedances are descriptive. Any hit at or above 70%, 50%, or 30% in the corresponding
cluster-aware audit makes that artifact ineligible for release.

## Deterministic and run-specific artifacts

Content manifests are canonical, timestamp-free JSON. They use project-relative logical paths and
bind configuration, parents, commands, tool versions, row artifacts, Git, Python, and lockfile
hashes. Timestamped run provenance contains staging and machine details and remains ignored.

The top-level v0.2 provenance manifest binds 13 required aggregate identities. Its SHA-256 is
`513da2ba3695b71f3e38d78f5ab045c7a301aba7fde9aeb87527243599ff56b4`.

## Quality and package checks

```bash
uv lock --check
uv sync --locked --group dev
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv run --locked pytest -v
uv build
```

Smoke-test the built wheel outside the project environment:

```bash
WHEEL=$(find "$PWD/dist" -name 'protein_split_audit-0.2.0-*.whl' -print -quit)
uv run --isolated --no-project --with "$WHEEL" psaudit --version
uv run --isolated --no-project --with "$WHEEL" psaudit doctor
uv run --isolated --no-project --with "$WHEEL" psaudit cohort --help
uv run --isolated --no-project --with "$WHEEL" psaudit similarity --help
uv run --isolated --no-project --with "$WHEEL" psaudit split --help
```

## Artifact boundary

Do not track raw data, processed sequences, pair tables, record-level cohort or split Parquet,
detailed audit rows, MMseqs2 databases, caches, or run directories. Only reviewed aggregate JSON
and release documentation belong in `results/released/v0.2.0/`.
