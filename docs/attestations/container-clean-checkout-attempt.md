<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Container clean-checkout reproduction attempt at v0.6.0 and v0.7.0

Date: 2026-08-30 (UTC+8).

## Operator disclosure

This run was performed by the project maintainer's AI agent inside an isolated
Linux container on the maintainer's machine. It is NOT an independent
third-party reproduction. `docs/independent_reproduction.md` requires the
reviewer to be someone other than the primary implementation operator and to
publish their own record. The readiness field `independent_human_reproduction`
therefore remains `false`, and this document must not be cited as independent
reproduction evidence.

## Environment

- Host: macOS 26 (darwin arm64), Apple Container virtualization runtime.
- Container image: `python:3.12-slim-bookworm` (Debian GNU/Linux 12, Linux aarch64).
- Python 3.12.14; uv 0.12.7 installed via `pip install uv`.
- Resources: 4 CPUs, 4 GiB memory.

## Reviewed state

- Source: clean clone of the public repository
  `https://github.com/ariakage/protein-split-audit`.
- Commit: `b170619a1f14e8ca13f1a09d09b738bc3f58851b` (tag `v0.6.0`,
  committer date 2026-07-18T17:07:40+08:00).
- `uv.lock` SHA-256:
  `efe81a00b6c2cbcda06ec89b3720a75ff4cac11e7edfe46d46ba08748a2fd5d3`.
- Initial `git status --porcelain`: empty.

## Attempt 1: protocol commands as written

Environment sync used `uv sync --locked --group dev`, as written in the
reproduction protocol at the time.

| Command | Exit |
| --- | --- |
| apt-get update | 0 |
| apt-get install git ca-certificates | 0 |
| pip install uv | 0 |
| uv --version | 0 |
| clone public repository | 0 |
| checkout frozen tag v0.6.0 | 0 |
| git status --porcelain (initial) | 0 |
| git rev-parse HEAD | 0 |
| shasum uv.lock | 0 |
| uv lock --check | 0 |
| uv sync --locked --group dev | 0 |
| uv run --locked ruff check . | 0 |
| uv run --locked ruff format --check . | 0 |
| uv run --locked mypy src | 1 |
| uv run --locked pytest | 2 |
| uv build --clear | 0 |
| demo run external-demo-a | 2 |
| demo run external-demo-b | 2 |
| diff two demo runs | 2 |
| sha256 demo files | 1 |
| git status --porcelain (final) | 0 |

Overall: FAIL.

## Attempt 2: corrected environment sync

Environment sync changed to `uv sync --locked --group dev --extra esm`,
matching the CI workflow of the same commit. All other commands unchanged.

| Command | Exit |
| --- | --- |
| apt-get update | 0 |
| apt-get install git ca-certificates | 0 |
| pip install uv | 0 |
| uv --version | 0 |
| clone public repository | 0 |
| checkout frozen tag v0.6.0 | 0 |
| git status --porcelain (initial) | 0 |
| git rev-parse HEAD | 0 |
| shasum uv.lock | 0 |
| uv lock --check | 0 |
| uv sync --locked --group dev --extra esm | 0 |
| uv run --locked ruff check . | 0 |
| uv run --locked ruff format --check . | 0 |
| uv run --locked mypy src | 0 |
| uv run --locked pytest | 0 |
| uv build --clear | 0 |
| demo run external-demo-a | 2 |
| demo run external-demo-b | 2 |
| diff two demo runs | 2 |
| sha256 demo files | 1 |
| git status --porcelain (final) | 0 |

Overall: FAIL, with the software gate fully green: `pytest` reported
`821 passed in 21.45s` in the clean container.

## Attempt 3: released tag v0.7.0

After the v0.7.0 release, the same container environment and the same script
(`scripts/container_reproduction.sh`, with `CHECKOUT_TAG=v0.7.0`) cloned the
public repository and checked out tag `v0.7.0`.

Reviewed state:

- Commit: `50b6ce08cccb3afe38ad53eeee0f6691fae66a82` (tag `v0.7.0`, merge
  commit of pull request #6).
- `uv.lock` SHA-256:
  `edbd3bcf7b46636244391e9974ce49aa20a248cc59042551c8312d3b57a66552`.
- Environment sync: `uv sync --locked --group dev --extra esm`.

| Command | Exit |
| --- | --- |
| apt-get update | 0 |
| apt-get install git ca-certificates | 0 |
| pip install uv | 0 |
| uv --version | 0 |
| clone public repository | 0 |
| checkout frozen tag v0.7.0 | 0 |
| git status --porcelain (initial) | 0 |
| git rev-parse HEAD | 0 |
| shasum uv.lock | 0 |
| uv lock --check | 0 |
| uv sync --locked --group dev --extra esm | 0 |
| uv run --locked ruff check . | 0 |
| uv run --locked ruff format --check . | 0 |
| uv run --locked mypy src | 0 |
| uv run --locked pytest | 0 |
| uv build --clear | 0 |
| demo run external-demo-a | 0 |
| demo run external-demo-b | 0 |
| diff two demo runs | 0 |
| sha256 demo files | 0 |
| git status --porcelain (final) | 0 |

Overall: PASS. `pytest` reported `837 passed in 20.89s` in the clean
container. The two demo runs were byte-identical after excluding the
publication lock file, and the demo artifacts hashed to:

- `README.md`: `8ced30f3b64842d1e88b01bce20cfcd3bd4a5e5c38ae3fcfada8b17810a86491`
- `split_summary.csv`: `e24c59813b365a9862dafc3b09e7e6968bd5cb6c30d9c297bcc8707e662d017c`
- `demo_manifest.json`: `4eab5be9501b45d6b9d7a67d51eb561fe7a14780c16c5e7e8dbdbbbe05e6f1e8`

This attempt resolves findings 1 and 2: the corrected sync command is the
released protocol, and the demo code is included in the released tag.

## Findings

1. Protocol defect (fixed in workspace). The reproduction protocol's sync
   command lacked `--extra esm`. Without it, `torch` and `click` are absent,
   `pytest` collection fails with 15 import errors, and `mypy src` fails on
   the missing torch stub. The v0.6.0 CI always synced with
   `--group dev --extra esm`. The workspace copy of
   `docs/independent_reproduction.md` now matches CI.
2. Demo command absent at the released tag. `psaudit demo run` does not exist
   at tag v0.6.0 (`src/protein_split_audit/demo.py` is part of the
   uncommitted v0.7.0 readiness work). The demo path of the reproduction
   protocol, Appendix A.1 of the paper, and the demo statements in
   `paper/readiness.yaml` therefore cannot be reproduced at the last released
   tag. A PASS reproduction requires a release that contains the demo code.
3. Environment note. uv was installed with `pip install uv` inside the
   container instead of the standalone installer; the lock check still passed.
   `uv 0.12.7` is newer than the `uv-build` upper bound recorded in
   `pyproject.toml`, producing only a warning during `uv build`.

## Deviations from the protocol report template

- No CI link for the reviewed commit is included; GitHub Actions history for
  `b170619a1f14e8ca13f1a09d09b738bc3f58851b` can be consulted separately.
- Operator is the maintainer's AI agent, not an independent reviewer.

## Status

- Independent reproduction: not achieved; remains a submission blocker per
  `paper/readiness.yaml`.
- Attempt 3 verifies that the complete v0.7.0 protocol (lock check, lint,
  format, types, 837 tests, wheel build, and two byte-identical offline demo
  runs) reproduces in a clean isolated environment from the public tag.
- Attempts 1 and 2 verify that the v0.6.0 software gate (lock check, lint,
  format, types, 821 tests, wheel build) reproduces once the environment sync
  matches CI.
