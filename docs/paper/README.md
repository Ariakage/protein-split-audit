<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Bilingual manuscript

This directory contains one bilingual manuscript of the ProteinSplitAudit methods paper:

- `paper.typ`: a single document that carries both Chinese and English. Section headings,
  the abstract, keywords, declarations, and captions are bilingual; the body is written in
  Chinese with the English technical terms kept inline, and the conclusion restates the
  defensible claim in English.

The source uses the pinned Typst Universe package `@preview/elegant-paper:0.1.0` in the same
layout style as the project's reference template, the shared `references.bib`, and the
immutable aggregate figures released with ProteinSplitAudit v0.6.0. The bibliography is
rendered in GB/T 7714 author-date style. Numbers and claim boundaries follow the frozen
release evidence; the English portions are written independently, not machine-translated.

## Build

Run from the repository root:

```bash
make -C docs/paper clean all
```

The command writes `docs/paper/build/paper.pdf`. Build output is ignored. Typst may download
the pinned template package on the first run; later builds can use the local Typst package
cache. Missing CJK font families only produce warnings and fall back to installed system
fonts.

The current file is a draft, not an accepted or submitted article. Funding,
competing-interest, venue-specific declarations, an independent clean-checkout reproduction,
and a permanent archive DOI still require author or maintainer action before submission.
