<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Reproducing ProteinSplitAudit

## v0.6 post-Test analysis lineage

Prediction-metadata revision r1 was prepared in Generation Commit A5
`5d5a7e817acb2b271b0353536ed4a270e104d18c`. Attestation Commit B2 is
`73febd1be2a18d3c9b54f7aacf5cd90a208fbd52`; its r1 attestation SHA-256 is
`8f802abac69b9aa925da40e391035576c1e8886a4442e7303f9bb204b644f54d`.

The maintainer approved the two r1 analysis sessions at
<https://github.com/Ariakage/protein-split-audit/pull/5#issuecomment-5010435346>.
`analysis-r1-a` and `analysis-r1-b` ran consecutively from a clean detached B2 checkout with
locked dependencies, network denial, no model execution, and no new Test inference. Both analyzed
the canonical frozen v0.5 Run A predictions. The replay compared 11 deterministic files, found
zero mismatches, and recorded SHA-256
`447cc115f469fb3cc0d6a1f78ffbb9219eada8cbefb548f039a465775b53bdf9`.

The first generated PDFs were retained as blocked visual-review evidence. Figure-presentation
revision r2 was implemented in Presentation Commit P1
`56cc94eeebb7d2c649dab8fd7b04ac0242b25abe` and tested only with synthetic fixtures before the
figures were regenerated from the authenticated aggregate CSVs. The figure-generator SHA-256 is
`3f50b83f5c1e96ed94b1f7ad1ff01423e51faa984e7b2e8078a6712949924388`.

The maintainer approved P1 and the exact CSV and PDF hashes at
<https://github.com/Ariakage/protein-split-audit/pull/5#issuecomment-5010597548>. Release Commit C
copies the approved 19 files into `results/released/v0.6.0/` without rewriting them. Check the
public bytes without opening Test inputs:

```bash
shasum -a 256 results/released/v0.6.0/* \
  results/released/v0.6.0/figures/*
uv run --locked pytest tests/test_v060_release_artifacts.py \
  tests/test_v060_release_privacy.py -v
```

Do not run `psaudit analysis run` against the formal inputs. Both r1 sessions have been consumed,
Release Commit C is not the attestation execution commit, and no further formal Test analysis is
authorized.

## v0.5 frozen Test lineage

The first v0.5 generation commit is `231685ce47a3573a77c0360ac925dc94ffc974c5` and its attestation
commit is `0ae83200cd9958bf2fa355301eace4e8aef5515a`. That formal attempt consumed Run A and Run B. The
predictions, metrics, and bootstrap results matched, but the replay report recorded 36
deterministic identity mismatches. Publication stopped, and the original outputs, ledgers, replay
report, and incident report were retained.

Replay-identity revision r1 was prepared in Generation Commit A2
`2d52b3c3a36318cf36f3dbaf05582090ff00ad6f`. It removes the session name from deterministic cache
and fitted-artifact identity without changing a method, input, prediction, metric, or statistical
rule. Attestation Commit B2 is `1d9c7e9df54fa3e2d0563f7a00ec94709928250d`. The attestation
SHA-256 is `28d03809b662b9ffd9b3d7e69830b203e1a9390887470dc114c38ef16e0e89c9`.

The maintainer approved r1 formal access at
<https://github.com/Ariakage/protein-split-audit/pull/4#issuecomment-5009657104>. The replacement
sessions ran consecutively from a clean detached B2 worktree with operating-system network denial,
locked dependencies, local model snapshots, and separate caches. Each session completed all 28
cells. The replay compared 430 deterministic files and reported zero differences. Its SHA-256 is
`8e7b18f293a0b88bf6ae57d5145fd3f79fb10c3a7e3cfde48c6642894ee785ed`.

The maintainer approved the twelve exact aggregate files at
<https://github.com/Ariakage/protein-split-audit/pull/4#issuecomment-5009767954>. Release Commit C
copies those bytes into `results/released/v0.5.0/`; it does not regenerate them. The public bundle
can be checked without opening Test:

```bash
shasum -a 256 results/released/v0.5.0/*
uv run --locked pytest tests/test_v050_release_artifacts.py \
  tests/test_v050_release_privacy.py -v
```

Do not rerun `psaudit experiment test-matrix` against the real inputs. Both approved r1 sessions
have been consumed, and Release Commit C is not the attestation execution commit. There is no
authorized third Test session.

The universal bootstrap unit is the frozen Cluster30 discovery component. Each primary metric uses
2,000 deterministic component draws and a percentile 95% interval. Same-split method differences
are paired; Random-minus-cluster gaps use independent draws. The dependency comparison in
`docs/audits/v0.5.0-dependency-diff.md` shows that the v0.4.0 and v0.5.0 lockfiles differ only in
the root package version.

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
uv sync --locked --group dev --extra esm
uv run --locked --extra esm ruff check .
uv run --locked --extra esm ruff format --check .
uv run --locked --extra esm mypy src
uv run --locked --extra esm pytest -v
uv build
```

Smoke-test the built wheel outside the project environment:

```bash
WHEEL=$(find "$PWD/dist" -name 'protein_split_audit-*.whl' -print -quit)
uv run --isolated --no-project --with "$WHEEL" psaudit --version
uv run --isolated --no-project --with "$WHEEL" psaudit doctor
uv run --isolated --no-project --with "$WHEEL" psaudit cohort --help
uv run --isolated --no-project --with "$WHEEL" psaudit similarity --help
uv run --isolated --no-project --with "$WHEEL" psaudit split --help
uv run --isolated --no-project --with "$WHEEL" psaudit feature --help
uv run --isolated --no-project --with "$WHEEL" psaudit model --help
uv run --isolated --no-project --with "$WHEEL" psaudit evaluate --help
uv run --isolated --no-project --with "$WHEEL" psaudit embedding --help
uv run --isolated --no-project --with "$WHEEL" psaudit experiment --help
uv run --isolated --no-project --with "$WHEEL" psaudit analysis --help
uv run --isolated --no-project --with "$WHEEL" psaudit report --help
```

## Artifact boundary

Do not track raw data, processed sequences, pair tables, record-level cohort or split Parquet,
detailed audit rows, feature caches, models, predictions, MMseqs2 databases, or run directories.
The v0.2 directory contains reviewed data manifests. `results/released/v0.3.0/` contains the
approved classical aggregate Validation artifacts, `results/released/v0.4.0/` contains the
approved ESM-2 aggregate Validation artifacts, `results/released/v0.5.0/` contains the twelve
approved aggregate Test files, and `results/released/v0.6.0/` contains the approved 19-file
post-Test analysis bundle. Formal run directories, access ledgers, incident evidence, blocked
figure candidates, and exploratory outputs stay local and ignored.
