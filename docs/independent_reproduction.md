<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Independent reproduction protocol

This protocol lets an external reviewer verify the public software path without receiving frozen
protein records, model snapshots, formal Test credentials, or private run artifacts.

## Reviewer boundary

The reviewer should not be the primary implementation operator. They must use a new clean clone
or detached worktree at the exact commit supplied for review. No real UniProt request, MMseqs2
execution, ESM-2 fetch, or frozen Test command is needed.

## Commands

```bash
git status --porcelain
git rev-parse HEAD
shasum -a 256 uv.lock
uv lock --check
uv sync --locked --group dev --extra esm
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv run --locked pytest
uv build --clear

uv run --locked psaudit demo run --output-dir results/runs/external-demo-a
uv run --locked psaudit demo run --output-dir results/runs/external-demo-b
diff -ru \
  --exclude=.psaudit-publication.lock \
  results/runs/external-demo-a \
  results/runs/external-demo-b
shasum -a 256 results/runs/external-demo-a/{README.md,split_summary.csv,demo_manifest.json}
```

The initial and final Git status must be reported. Generated directories are ignored and should
not be committed.

## Report template

The reviewer should publish a permanent, maintainer-verifiable record containing:

- reviewer identity and an explicit statement of independence from primary implementation;
- full reviewed commit SHA and `uv.lock` SHA-256;
- operating system, architecture, and Python version;
- every command above with exit status;
- the three demo file hashes;
- whether the two demo directories matched exactly;
- any warnings, deviations, or failures; and
- a link to the CI run for the same commit.

Do not include local home-directory paths, hostnames, secrets, protein records, or caches. The
maintainer may acknowledge a report, but neither an agent nor the project may write the reviewer's
approval on their behalf.

## Scientific replay is separate

This procedure independently checks the public software package. Reproducing the frozen pilot
from source is a separate activity requiring lawful source regeneration, the recorded UniProt
release and hashes, MMseqs2 `18-8cc5c`, approved model snapshots, and the historical protocol
gates. It does not authorize another formal Test session or post-Test analysis.
