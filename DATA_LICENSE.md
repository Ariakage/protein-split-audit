<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Data license and handling

The licenses for ProteinSplitAudit code and documentation do not cover third-party biological
data. UniProtKB/Swiss-Prot sequences, annotations, accessions, organism metadata, and any derived
file that contains sequences keep the applicable upstream terms.

Do not track or attach these materials to a release:

- `data/raw/`, `data/interim/`, or `data/processed/`;
- detailed protein-level audits;
- model weights, features, embeddings, or caches.

A maintainer may approve sanitized manifests or aggregate summaries for tracking or release
attachment. Before approval, verify that they contain no sequence, protein-level row, secret, or
private local path. Files in `results/runs/` are development output, not approved redistribution
copies. Reviewed copies belong in `results/released/<version>/`.

Check the data provider's current terms before redistributing anything. Configuration, hashing,
filtering, and aggregation do not change ownership or relicense source data.
