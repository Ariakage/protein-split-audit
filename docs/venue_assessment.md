<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Methods/software-paper venue assessment

Assessment date: 2026-08-29.

## Recommendation

Prepare the current manuscript in Journal of Open Source Software (JOSS) format, but do not submit
it yet. JOSS is the closest match because the paper's contribution is research software design,
auditability, and reusable infrastructure rather than a new biological result. The draft already
uses the required Markdown/BibTeX structure and is within the official 750--1,750 word range.

The recommendation is a preparation target, not a submission decision. The maintainer must still
approve the venue, authorship metadata, declarations, and final archive.

## JOSS fit and current gate

Official requirements:

- <https://joss.readthedocs.io/en/latest/submitting.html>
- <https://joss.readthedocs.io/en/latest/paper.html>
- <https://joss.readthedocs.io/en/latest/review_criteria.html>

ProteinSplitAudit already has an OSI-approved software license, installable Python package,
versioned releases, tests, CI, contribution guidance, a public issue path, a statement of need,
state-of-field comparison, software-design discussion, research-impact statement, AI-use
disclosure, and a reproducible synthetic demonstration.

It is not currently eligible for JOSS submission. The public repository was created on
2026-07-14, while JOSS requires more than six months of public history with active development
spread over that period. The earliest calendar date is therefore after 2027-01-14, and timing
alone is insufficient: the history must show continued public iteration rather than a burst of
commits. JOSS also expects realized research use and strongly values independent adoption or
community engagement. No external reproduction or adoption record exists yet.

## Alternative routes

### Bioinformatics Advances Application Note

The journal accepts Application Notes for openly accessible software systems and their use:
<https://academic.oup.com/bioinformaticsadvances/pages/author-guidelines>.

This route becomes stronger if the project adds a separately prespecified external dataset or a
broader use case. With only the current small single-organism pilot, the paper should not imply a
general enzyme benchmark. An Application Note would also require adaptation to the journal's
template and a clearer biological-use narrative.

### GigaScience Technical Note

GigaScience emphasizes reproducibility, usability, utility, and persistent public access to the
data and research objects supporting reported results:
<https://academic.oup.com/gigascience/pages/instructions_to_authors>.

The project's open workflow aligns with those values, but the non-redistribution of sequence-level
inputs and the current lack of a permanent archive require early editorial clarification. This is
not the preferred first route for the present manuscript.

### MethodsX

MethodsX publishes reusable descriptions of methods and protocols, including software-supported
methods. It is a plausible route if the article is rewritten around the protocol itself rather
than the research-software package. That would be a different manuscript and should not be chosen
implicitly.

## Decision rule

- Choose JOSS after sustained public development, one independent reproduction, evidence of
  research use, and a permanent release DOI.
- Choose Bioinformatics Advances only after deciding that the manuscript will include enough
  biological application evidence for an Application Note.
- Choose MethodsX only if the maintainer wants a protocol article rather than a software paper.
- Seek an editor's scope opinion before choosing GigaScience because public sequence-level support
  data are intentionally restricted.

Until the maintainer decides, `paper/readiness.yaml` keeps `target_journal: null` and the manuscript
remains venue-neutral.
