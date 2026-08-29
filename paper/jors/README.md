<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# JORS submission draft

This folder holds the manuscript adapted to the Journal of Open Research
Software (JORS) software-metapaper format, chosen by the maintainer on
2026-08-30 as the first journal submission venue. The bilingual Typst draft
(`docs/paper/`) remains the full companion manuscript; the JOSS draft
(`paper/paper.md`) remains prepared for a possible later JOSS submission.

## Files

- `paper.md` — the JORS-structured manuscript: Abstract, Keywords,
  (1) Overview, (2) Implementation and Architecture, (3) Quality Control,
  (4) Availability, (5) Reuse Potential, plus Funding Statement, Competing
  Interests, Acknowledgements, Author Contributions, and AI-Use Disclosure.
  The section structure mirrors recently published JORS software metapapers.
- `references.bib` — references used by `paper.md`, kept consistent with
  `docs/paper/references.bib`.
- `Makefile` — renders a submission DOCX with pandoc into `build/`.

## Render the submission file

```bash
make            # writes build/paper.docx
```

JORS (Ubiquity Press) typesets accepted manuscripts itself; a DOCX rendered
from this markdown source is a suitable submission file. Verify the rendered
reference list and section order before upload.

## Pre-submission checklist

- Maintainer final read of `paper.md` (all numbers must stay consistent with
  `docs/paper/paper.typ` and `scripts/verify_manuscript_numbers.py`).
- Confirm the JORS article-processing charge and create an account at the
  journal's submission system.
- Suggested reviewers: identify independent candidates (the reviewer of
  GitHub issue #7 is already known to the project; do not list them without
  consent).
- Cover letter: mention the Zenodo archive (DOI 10.5281/zenodo.22164608),
  the independent reproduction record (GitHub issue #7), and the AI-use
  disclosure.

## Status

Draft adapted on 2026-08-30 from the frozen v0.7.0 state. Not yet submitted;
`paper/readiness.yaml` keeps `submission_status: blocked` until the
maintainer approves this draft and completes the submission steps above.
