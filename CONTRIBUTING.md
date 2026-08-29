<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Contributing to ProteinSplitAudit

Contributions must preserve the project's research record. That means keeping transformations
traceable, respecting data licenses, and staying within the approved milestone.

## Set up a development environment

Use Python 3.12 and the checked-in uv lockfile:

```bash
uv lock --check
uv sync --locked --group dev
uv run --locked psaudit --version
uv run --locked psaudit doctor
```

Do not update dependency versions as part of unrelated work.

## Prepare a change

Read `README.md`, `docs/protocol.md`, and the relevant public protocol before editing code. For
paper-facing changes, also read `docs/methods_paper_scope.md`. Keep the change inside the current
milestone and do not add placeholder modules for future work.

For behavior changes, begin with a failing test and implement only what is needed to pass it. Use
small synthetic fixtures. Tests must never contact UniProt or another network service.

Before requesting review, run:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv run --locked pytest -v
```

## Handle research data carefully

- Do not invent data, metrics, API responses presented as real, or experimental results.
- Every discarded record needs a configured and reported reason.
- Keep raw and processed sequences, detailed audits, caches, weights, and run output out of Git.
- Test fixtures should be synthetic and as small as possible. Document the source and license
  before adding any unavoidable third-party fixture.
- Benchmark claims and paper conclusions require completed, reviewed experiments.

## Code and documentation

Public functions need type hints. Add a short docstring when the contract is not clear from the
name and signature. Use `pathlib.Path`, deterministic ordering, and UTC timestamps.

Original code, tests, configuration, and CI files use the Apache-2.0 SPDX identifier. Original
documentation uses CC-BY-4.0. Update the documentation and the `Unreleased` section when behavior
changes.

## Request review

Describe the scope, checks run, effect on data or licensing, and any unresolved risks. A
contribution does not authorize anyone to commit for the maintainer, push, tag, publish a package,
or create a release.

Use a public GitHub issue for reproducible bug reports and feature proposals. Sensitive security
reports follow `SECURITY.md`; support and maintenance expectations are in `SUPPORT.md`, and project
decision authority is described in `GOVERNANCE.md`.
