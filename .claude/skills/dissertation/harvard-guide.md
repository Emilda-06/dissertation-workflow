# Harvard citations (Cite Them Right) in pandoc syntax

The build formats everything automatically from the CSL style. Write citations only in pandoc
syntax, and never type a formatted citation like "(Smith, 2020)" by hand.

| You write | Output in Word |
|---|---|
| `[@rose2020zero]` | (Rose et al., 2020) |
| `@rose2020zero` | Rose et al. (2020) |
| `[@rose2020zero, p. 12]` | (Rose et al., 2020, p. 12) |
| `[@rose2020zero; @kindervag2010no]` | (Rose et al., 2020; Kindervag, 2010) |
| `[-@rose2020zero]` | (2020), used after naming the authors in the sentence |
| `[see @key]`, `[e.g. @a; @b]` | (see Smith, 2021), (e.g. Smith, 2021; Lee, 2022) |

Rules:
- **Every key must exist in the library and be verified.** check.py blocks the build otherwise.
- Cite where the claim is made, not in a bundle at the end of a paragraph.
- Use 1–3 sources per claim. Long bundles of citations are a sign of poor synthesis.
- **Narrative citations** (`@key`) when the author is the subject: "@rose2020zero define...".
  **Parenthetical** (`[@key]`) when the idea is the subject.
- **Direct quotes** must be short, rare, in "double quotes", and always carry a page:
  `[@key, p. 4]`. Paraphrasing still needs a citation.
- **Secondary citations:** avoid them. Find and cite the original.
- The reference list is generated at the end ("REFERENCES"), alphabetical, with DOIs and URLs.
  Don't write it by hand.

## Source quality and recency

- Prefer peer-reviewed journals and conferences (IEEE, ACM, Springer, Elsevier, USENIX, MDPI
  journals with good standing), standards (NIST, ISO, IETF RFCs) and reputable industry
  reports (Gartner, Verizon DBIR, ENISA) for statistics.
- Avoid blogs, Wikipedia, vendor marketing pages and random websites. Use preprints (arXiv) only
  when no peer-reviewed version exists, and only if recent.
- **Preferred years: 2016 to today**, the more recent the better for current-state claims. Pre-2016 sources are
  allowed when they are the best or original source (seminal papers, standards, the original
  definition of a concept). Record why with `refs.py mark-foundational`. 2016 onwards is the preferred
  range (target 80% or more of a chapter's sources), not a hard cutoff.
- Standards and reports without DOIs: add with `refs.py add-manual`, for example:
  `{"type":"report","title":"Zero Trust Architecture","author":[{"family":"Rose","given":"Scott"}],"issued":{"date-parts":[[2020]]},"publisher":"National Institute of Standards and Technology","number":"NIST SP 800-207","DOI":"10.6028/NIST.SP.800-207"}`
  (this one has a DOI, so `refs.py add --doi` is better). Always check first whether a DOI exists.
