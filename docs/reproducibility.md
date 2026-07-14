<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Reproducing the v0.1.0 workflow

## Set up the repository

Use Python 3.12 and install from the checked-in uv lockfile:

```bash
uv lock --check
uv sync --locked --group dev
uv run --locked psaudit --version
uv run --locked psaudit doctor
uv run --locked psaudit data download --help
uv run --locked psaudit data build --help
uv run --locked psaudit data profile --help
```

`psaudit doctor` performs local checks only. It reports the package, Python version, platform,
project root, writable `data/`, `cache/`, and `results/` directories, Git status, lockfile, and
optional tools. MMseqs2 and PyTorch belong to later work, so their absence does not fail the
doctor check.

## Run the quality checks

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv run --locked pytest -v
```

An autouse test guard blocks real socket connections. Downloader tests use synthetic local
fixtures and mocked HTTP transport.

## Configuration and paths

The loader accepts a versioned YAML mapping and rejects unknown fields. It resolves `data_dir`,
`cache_dir`, and `results_dir` relative to the configuration file rather than the current working
directory. The current command-line interface does not implement `psaudit config validate`.

## Hashes and Git metadata

SHA-256 helpers stream file content and return lowercase hexadecimal digests. Git lookup is
read-only. When a repository is available, it reports `HEAD` and both tracked and untracked
changes. Missing Git information stays unknown; the software does not invent a commit value.

## Download the pilot source

The pilot configuration is `configs/dataset/pilot.yaml`. After a maintainer has approved the
query, run:

```bash
uv run --locked psaudit data download --config configs/dataset/pilot.yaml
```

The downloader writes a normalized TSV in deterministic gzip form to the ignored `data/raw/`
directory. Its JSON manifest goes to `data/manifests/` and records:

- the exact query, canonical request, and requested fields;
- the UTC download time and any available UniProt release headers;
- page, record, and expected total counts;
- normalized and compressed file hashes;
- package, Git, Python, and `uv.lock` metadata.

## Build the candidate data

After a successful authorized download, run:

```bash
uv run --locked psaudit data build --config configs/dataset/pilot.yaml
```

The builder first verifies that the raw gzip file agrees with its parent download manifest. It
writes `pilot.parquet` and `pilot.fasta` to the ignored `data/processed/` directory. The build
manifest, duplicate alias map, conflicting-label summary, and aggregate rejection counts go to
`data/manifests/`. These JSON audit files contain hashes and annotations, not sequences.

All tests use synthetic fixtures and make no real UniProt request.

## Profile the candidates

Pass the dataset, build manifest, and output directory explicitly:

```bash
uv run --locked psaudit data profile \
  --dataset data/processed/pilot.parquet \
  --build-manifest data/manifests/pilot.build.json \
  --output-dir results/runs/profile-pilot/
```

The profiler verifies the Parquet hash against the build manifest and reads only the EC-level-2,
sequence-length, and organism columns. Its deterministic summaries contain no protein-level rows
or private local paths.

## Keep artifacts in the right place

Raw and processed sequences and detailed audits stay in ignored local directories. Only sanitized
manifests and aggregate summaries may be tracked or attached to an approved release. Review a run
artifact before copying it to `results/released/`, and never overwrite a released file.
