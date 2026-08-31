<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# JOSS LaTeX rendering

This folder contains a LaTeX rendering of the JOSS paper, adapted from the
canonical Markdown draft at `paper/paper.md` and formatted to resemble a
published JOSS article (sans headings, author-year references).

## Important: submission format

JOSS requires submissions as Markdown (`paper.md` plus a BibTeX file) hosted
in the software repository; see the official submission guide:
<https://openjournals.readthedocs.io/en/latest/submitting.html>. This LaTeX
version is therefore **not** the file to upload for a JOSS submission. It
exists for local reading, internal review, and reuse (for example as a
preprint source). If JOSS is submitted later, the Markdown draft remains the
authoritative submission artifact and must stay in sync with this rendering.

## Files

- `paper.tex` — the JOSS-structured paper: Summary, Statement of Need, State
  of the Field, Software Design, Bounded Pilot Demonstration, Reproducibility
  and Availability, Research Impact, Limitations, AI-Use Disclosure,
  Acknowledgements, References.
- `paper.bib` — references copied from `paper/paper.bib`; the software entry
  is expressed as a `misc` entry so `plainnat` renders it without warnings.
- `Makefile` — builds `build/paper.pdf` with latexmk (ignored by Git).

## Build

```bash
make            # writes build/paper.pdf
make clean      # removes build outputs
```

Requires a TeX Live distribution with `latexmk`, `natbib`, and `titlesec`.

## Content sync

Every number here mirrors the verified manuscript (`docs/paper/paper.typ`)
and the JOSS draft (`paper/paper.md`). Do not introduce numbers into this
rendering without updating those sources and rerunning
`scripts/verify_manuscript_numbers.py`.

## Status

Draft rendered on 2026-08-31 from the frozen v0.7.0 state. JOSS submission
itself remains gated on the six-month public-history requirement
(2027-01-14) and research-use evidence; see `docs/venue_assessment.md`.
