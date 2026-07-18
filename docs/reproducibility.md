<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Reproducing ProteinSplitAudit

## v0.5 Generation A: prepare without opening Test

The v0.5.0 Generation A candidate contains code, tests, the frozen configuration, the human-readable
protocol, and the dependency comparison. It deliberately contains no v0.5 attestation, real Test
result, release aggregate, release note, tag, or release date.

Before Generation A is proposed, run the locked offline checks:

```bash
uv lock --check
uv sync --locked --extra esm --group dev
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv run --locked pytest -v
uv build --clear
```

The Test command is present so its denial and CLI surface can be tested, but it must not progress
past authorization in this state:

```bash
uv run --locked psaudit experiment test-matrix \
  --config configs/experiment/v050-test.yaml
```

Formal execution requires a later, permanent owner-authored approval URL and an attestation-only
Commit B whose sole parent is Generation A. The approved command then consumes Run A and Replay B
automatically. It has no resume or single-cell option. Any failure after the first Test read
consumes that session and requires an incident report, a protocol revision, and new approval before
a replacement run can exist.

The universal Bootstrap unit is the frozen Cluster30 discovery component. Each primary metric uses
2,000 deterministic component draws and a percentile 95% interval. Same-split method differences
are paired; Random-minus-cluster gaps use independent draws. Exact A/B replay is required before a
twelve-file sequence-free aggregate review can be generated.

`docs/audits/v0.5.0-dependency-diff.md` proves that the v0.4.0 and v0.5.0 lockfiles differ only in
the root package version. `CITATION.cff` continues to describe the latest published release,
v0.4.0, until v0.5.0 is actually released.

## v0.4 generation, attestation, and formal replay

Generation Commit A is `d764c30c0945231113f2f51cdb9761ab62815c73`. It fixes the code,
configuration, protocol, model acquisition manifests, and `uv.lock` before formal results exist.
The lockfile SHA-256 is
`f924d6965ea4272e6f9faa378b19e57502a9a4feeab6918122a873588919d346`.

Attestation Commit B is `31d2ff208f344e823ce04801596664f14679a2e5`. Its protocol attestation
SHA-256 is `ddeed606f308363a457e3edf0646275f788eae657778de03c86c3eed9bb214f7`.
The attestation binds Generation A, the frozen v0.2 and v0.3 inputs, both model snapshots, the
eight-cell matrix, the canonical runtime, and `real_test_access_authorized: false`.

Formal execution used Darwin arm64, Python 3.12.11, CPU float32, eight PyTorch intraop threads,
one interop thread, and deterministic algorithms. Both runs recorded `git_dirty: false`.

## Model acquisition and offline verification

Model acquisition is the only networked part of the v0.4 workflow. It must use the explicit fetch
command with the approved full revision already present in each configuration:

```bash
uv sync --locked --extra esm --group dev
uv run --locked psaudit embedding fetch \
  --config configs/embedding/esm2_35m.yaml
uv run --locked psaudit embedding fetch \
  --config configs/embedding/esm2_150m.yaml
```

Do not run those commands during a release replay if the approved snapshots are already present.
Verification, extraction, experiments, and replay run offline:

```bash
uv run --locked psaudit embedding verify-model \
  --config configs/embedding/esm2_35m.yaml
uv run --locked psaudit embedding verify-model \
  --config configs/embedding/esm2_150m.yaml
```

Verification requires the exact five-file allowlist, rejects symlinks and extra files, and hashes
the local bytes. It does not accept a mutable branch, tag, abbreviated revision, or alternative
snapshot.

## Replaying the ESM-2 Validation matrix

Start from a detached clean checkout of Attestation Commit B. Restore the eleven frozen inputs
listed in `docs/attestations/v0.4.0-protocol-freeze.yaml`, restore the two approved snapshots, and
recompute their hashes before model loading. Then run:

```bash
uv lock --check
uv sync --locked --extra esm --group dev
uv run --locked psaudit experiment matrix \
  --config configs/experiment/v040-validation.yaml
```

Preserve the first matrix and its entire embedding cache outside the configured output paths.
Start the second run with an empty embedding cache and run the same command again. Compare the two
matrix directories and generate the aggregate preview:

```bash
uv run --locked psaudit experiment replay-compare \
  --kind esm \
  --first <first-matrix-dir> \
  --second <second-matrix-dir> \
  --output <replay-report.json>

uv run --locked psaudit experiment summarize \
  --kind esm \
  --matrix-dir <second-matrix-dir> \
  --output-dir <aggregate-review-dir> \
  --classical-summary results/released/v0.3.0/validation_summary.csv \
  --classical-sha256 73ee1c4f8c454a8570058224c9257d4f924eac8c8681fcb78991d99fa6612dc2
```

The approved replay compared 97 deterministic artifacts. Every artifact was byte-identical and
`replay_difference` was zero. A direct comparison of the separately generated embedding caches
found all 24 files byte-identical. Both matrix summaries have SHA-256
`3a0c5e33f07e4dbbec4ecc6b89e1be5a11c895ea91cae69fc552516de8ef6682`.
The replay report SHA-256 is
`0fad7c3a4c6862ccce4e1a1fc318fed47113ed505d73be1a172d86a1c18e8c69`.

The six approved aggregate files are copied to `results/released/v0.4.0/` without rewriting
their bytes. Model files, embedding caches, fitted estimators, predictions, per-record outputs,
logs, resource traces, and complete matrix directories stay local and ignored.

The real Test command remains denied:

```bash
uv run --locked psaudit experiment finalize-test \
  --config configs/experiment/v040-test-gated.yaml
```

It must fail before opening a real Test input.

## v0.3 generation and publication commits

The formal classical Validation matrix was generated twice from clean commit
`aa6305784706c36bfd1a198ad7d7c3b374d31807`. Its `uv.lock` SHA-256 is
`99dc065b3279746c80d30fecc672694d970715417365d1bc31471e61e190e815`. Every formal cell records
that commit with `git_dirty: false`, Python 3.12.11, package version 0.3.0, and MMseqs2 18-8cc5c.

The publication commit adds the reviewed aggregate copies, protocol attestation, release notes,
and citation metadata. It does not regenerate, rewrite, or track feature caches, models,
predictions, or sequence-bearing inputs.

The v0.3 protocol remains Validation-only. Do not run `configs/experiment/v030-test.yaml`; its
`real_test_access_authorized` field is false, and the application gate must fail before opening any
real Test input.

## Replaying the classical Validation matrix

Start from a detached clean checkout of Generation Commit A with the frozen v0.2 local inputs
listed in `docs/attestations/v0.3.0-protocol-freeze.yaml`, then run:

```bash
uv lock --check
uv sync --locked --group dev
uv run --locked psaudit doctor
uv run --locked psaudit experiment matrix \
  --config configs/experiment/v030-validation.yaml
```

For an independent replay, preserve the first result directory, remove or relocate the local
feature and MMseqs2 caches, and run the same matrix command again. Compare the two directories and
create a sequence-free review aggregate with:

```bash
uv run --locked psaudit experiment replay-compare \
  --first <first-matrix-dir> \
  --second <second-matrix-dir> \
  --output <replay-report.json>
uv run --locked psaudit experiment summarize \
  --matrix-dir <second-matrix-dir> \
  --output-dir <aggregate-review-dir>
```

The approved run compared 169 deterministic files, found zero mismatches, and published only the
four aggregate files listed in `results/released/v0.3.0/README.md` plus the protocol attestation.

## Frozen v0.2 input lineage

The v0.3 experiment consumes the following v0.2 lineage without changing its cohort or split
identities.

### v0.2 generation and publication commits

Formal data was generated from clean commit
`47ba9cd7a79b7fda191e779be2f98cd2a33cefa3`, called generation commit A. Its `uv.lock` SHA-256 is
`326cd0e038ab9deabd8d82a8138dbbf848d5239b55b09d814a3d7c01ff542fde`. Every formal content
manifest records that commit with `git_dirty: false`.

The release commit, publication commit B, adds reviewed aggregate copies, documentation, citation
metadata, and version `0.2.0`. It does not regenerate sequence-bearing artifacts. This separation
avoids a circular requirement in which release files would have to be present before the data
generation commit could be fixed.

### v0.2 environment

Use Python 3.12, the checked-in lockfile, and MMseqs2 `18-8cc5c` for formal similarity replay:

```bash
uv lock --check
uv sync --locked --group dev
uv run --locked psaudit --version
uv run --locked psaudit doctor
```

Only `psaudit data download` uses the network. Tests block real socket connections and use mocked
HTTP transport. Default CI does not install or run MMseqs2.

### Clean candidate regeneration

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

### Cohort, similarity, and splits

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

### Train-to-test audits

```bash
for name in random cluster70 cluster50 cluster30; do
  uv run --locked psaudit similarity audit --config "configs/audits/${name}.yaml"
done
```

Every Test sequence must receive a nearest observed Train neighbor or an explicit no-match row.
Random exceedances are descriptive. Any hit at or above 70%, 50%, or 30% in the corresponding
cluster-aware audit makes that artifact ineligible for release.

### Deterministic and run-specific artifacts

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
WHEEL=$(find "$PWD/dist" -name 'protein_split_audit-0.4.0-*.whl' -print -quit)
uv run --isolated --no-project --with "$WHEEL" psaudit --version
uv run --isolated --no-project --with "$WHEEL" psaudit doctor
uv run --isolated --no-project --with "$WHEEL" psaudit cohort --help
uv run --isolated --no-project --with "$WHEEL" psaudit similarity --help
uv run --isolated --no-project --with "$WHEEL" psaudit split --help
uv run --isolated --no-project --with "$WHEEL" psaudit feature --help
uv run --isolated --no-project --with "$WHEEL" psaudit model --help
uv run --isolated --no-project --with "$WHEEL" psaudit experiment --help
```

## Artifact boundary

Do not track raw data, processed sequences, pair tables, record-level cohort or split Parquet,
detailed audit rows, feature caches, models, predictions, MMseqs2 databases, or run directories.
The v0.2 directory contains reviewed data manifests. `results/released/v0.3.0/` contains the
approved classical aggregate Validation artifacts, while `results/released/v0.4.0/` contains the
approved ESM-2 aggregate Validation artifacts and protocol attestation.
