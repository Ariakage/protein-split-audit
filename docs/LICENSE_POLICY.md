<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# License policy

ProteinSplitAudit assigns licenses by path. SPDX identifiers state the terms for original project
material. They do not apply those terms to third-party content.

## Original project material

| Path or material | License | SPDX identifier |
| --- | --- | --- |
| `src/**/*.py`, `tests/**/*.py` | Apache License 2.0 | `Apache-2.0` |
| Configuration examples, CI, and pre-commit files | Apache License 2.0 | `Apache-2.0` |
| `README.md`, `docs/**/*.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, and original figures | Creative Commons Attribution 4.0 | `CC-BY-4.0` |
| Metadata formats that do not allow comments | Terms declared in adjacent policy or metadata fields | As applicable |

The authoritative texts are `LICENSES/Apache-2.0.txt` and `LICENSES/CC-BY-4.0.txt`. Do not edit
them without explicit approval.

## Third-party data and software

UniProtKB/Swiss-Prot sequences and metadata retain UniProt's terms. ESM-2 code and weights,
MMseqs2, Python packages, and every other third-party resource retain their respective licenses.
Project configuration, manifests, and transformations do not transfer ownership or alter those
terms.

The two ESM-2 Hugging Face repositories approved for v0.4.0 report an MIT model license. Treat that
as upstream metadata, not as a ProteinSplitAudit warranty. Review the pinned repository revisions
and current redistribution terms at freeze time. Model and tokenizer files remain outside Git;
their sanitized content manifests may be tracked, but the project never applies Apache-2.0 or
CC-BY-4.0 to the upstream bytes.

Record upstream attribution and links in `THIRD_PARTY_NOTICES.md`. Put data-specific handling rules
in `DATA_LICENSE.md` and the data card.

## Generated artifacts

Keep raw downloads, processed sequence data, detailed rejection or duplicate audits, model
weights, and run caches out of Git. A sanitized manifest or aggregate summary may qualify as
original project documentation or data-description material, but a maintainer must review it
before tracking or attaching it to a release. It must not include third-party sequences or
record-level content.

## Adding a file

Before adding material, identify who created it, where it came from, which terms apply, where it
will live in the repository, and whether redistribution is allowed. If its provenance or license
is unclear, leave it out and ask the maintainer for a decision.
