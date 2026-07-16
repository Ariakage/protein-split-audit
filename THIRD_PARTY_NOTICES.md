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

## ESM-2 model and tokenizer assets

v0.4.0 can use the official Hugging Face repositories
[`facebook/esm2_t12_35M_UR50D`](https://huggingface.co/facebook/esm2_t12_35M_UR50D/tree/6fbf070e65b0b7291e7bbcd451118c216cff79d8)
and
[`facebook/esm2_t30_150M_UR50D`](https://huggingface.co/facebook/esm2_t30_150M_UR50D/tree/a695f6045e2e32885fa60af20c13cb35398ce30c).
Their repository metadata reports an MIT license. That upstream statement is not a project
warranty and must be reviewed again when formal artifacts are frozen.

Model weights, tokenizer files, and repository files retain their upstream terms. ProteinSplitAudit
does not copy them into Git, distribute them as project code, or relicense them. The tracked
snapshot manifests record the pinned source revisions and local content hashes without containing
the model bytes.

## Other external tools

MMseqs2, PyTorch, Transformers, Safetensors, Hugging Face Hub, and other packages remain separate
third-party projects under their own terms. Their versions and provenance are recorded where they
affect a frozen run.
