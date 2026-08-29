<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Offline methods demonstration

This tutorial checks the core ProteinSplitAudit method path without downloading UniProt data,
installing MMseqs2, fetching ESM-2, or opening the frozen pilot Test set.

## Run

From a clean checkout with Python 3.12:

```bash
uv lock --check
uv sync --locked --group dev
uv run --locked psaudit demo run --output-dir results/runs/methods-demo-a
uv run --locked psaudit demo run --output-dir results/runs/methods-demo-b
```

The command refuses to overwrite an existing output. Use two new directories to verify replay:

```bash
diff -ru \
  --exclude=.psaudit-publication.lock \
  results/runs/methods-demo-a \
  results/runs/methods-demo-b
```

An empty diff is the expected result.

## What it exercises

The generator creates 90 protein-like records in three synthetic classes and 45 paired
similarity components. It then:

1. builds strict connected components from a fixed synthetic edge list;
2. creates the deterministic Random and Cluster30 assignments with seed 42;
3. measures whether a synthetic component crosses each assignment;
4. extracts amino-acid composition features;
5. fits the frozen logistic-regression pipeline on Train rows only;
6. predicts synthetic Test rows; and
7. publishes aggregate-only summaries with deterministic hashes.

The generated edge list is an offline fixture. It does not emulate MMseqs2 sensitivity or replace
the formal MMseqs2 workflow used for the pilot.

## Outputs

- `README.md` states the evidence boundary.
- `split_summary.csv` records split sizes, component crossings, and smoke-test metrics.
- `demo_manifest.json` records the synthetic specification hash, software version, file hashes,
  and aggregate results.

No output contains the generated record strings, row identifiers, local paths, timestamps,
secrets, or frozen pilot material. The numbers demonstrate that the software path executes and
replays; they must not be cited as biological findings or benchmark performance.
