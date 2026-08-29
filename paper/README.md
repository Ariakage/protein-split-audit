# Manuscript source

`paper.md` is a venue-neutral methods/software-paper draft. It deliberately keeps the scientific
claim boundary narrow and cites the released v0.6.0 pilot as a bounded demonstration.

The draft is not ready to submit. Before adapting it to a journal template, the maintainer must:

- select the journal;
- confirm affiliation and correspondence metadata;
- supply funding, contributor-role, conflict-of-interest, and data-availability declarations;
- review the AI-use disclosure;
- complete and record an independent clean-checkout reproduction;
- archive the exact submission release and add its DOI; and
- verify every number against the immutable released aggregate files.

`docs/venue_assessment.md` recommends preparing for JOSS while explicitly recording why the
repository is not yet eligible to submit there.

Do not add unpublished exploratory results or regenerate the frozen Test analysis while editing
the manuscript. The authoritative claim boundary is `docs/methods_paper_scope.md`.

## Render the draft

The venue-neutral preview requires Pandoc with Citeproc and Typst:

```bash
cd paper
make check
```

This creates ignored `paper/build/paper.html` and `paper/build/paper.pdf` files. The PDF is a
review copy, not a journal template. The checked draft currently renders as five pages with the
bibliography resolved. Run `make clean` to remove local previews.
