<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Third-party notices

ProteinSplitAudit uses or can interact with resources maintained by other projects. Those
resources keep their own licenses and terms. Mentioning them in configuration, manifests,
dependency metadata, or provenance does not relicense them.

## UniProtKB/Swiss-Prot

The candidate-data workflow can download reviewed protein sequences and annotations from
UniProtKB/Swiss-Prot. Files containing raw or processed sequences remain untracked. Before a
download, redistribution, or publication, review UniProt's current terms and attribution
guidance.

## Python packages

`pyproject.toml` declares the runtime, optional, development, and build dependencies; `uv.lock`
pins the resolved environment. Each package retains its upstream license. The lockfile records
dependency provenance but does not transfer licensing rights.

## Tools and model assets outside v0.1.0

The v0.1.0 workflow does not run MMseqs2, PyTorch, ESM-2 code or weights, or another clustering or
model resource. Any later approved use must record the resource's version, source, license, and
artifact hash.
