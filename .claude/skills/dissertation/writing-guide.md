# Writing guide

## Voice and language

- **Plain academic English.** Short to medium sentences (15–25 words on average). One idea per
  sentence, one point per paragraph. Prefer active voice when the actor matters ("This study
  measured...", "Rose et al. define...").
- **Use technical terms where needed, and define them on first use.** Write the term in full,
  give the acronym and a one-line definition: "Zero Trust Architecture (ZTA), a security model
  in which no user or device is trusted by default, even inside the network perimeter [@key]".
  After that, use the term consistently. Never switch between synonyms for the same concept.
- Use third person and an objective tone. No "I", "we" or "you", except "the researcher" when
  describing your own method if the guideline allows it.
- Be precise: give numbers, versions, dates and named tools, not vague words like "many",
  "various" or "recently".
- Use hedging only when the evidence is genuinely uncertain ("suggests", "indicates").
- **Avoid filler and AI-typical phrasing.** Do not use: "delve", "in today's digital landscape",
  "it is worth noting", "plays a crucial role", "a testament to", "tapestry", "realm", "navigate
  the complexities", "furthermore/moreover" to open every paragraph, "in conclusion" mid-chapter,
  rhetorical questions, three-adjective lists, or em-dash heavy sentences. Vary how sentences and
  paragraphs start.

## Natural prose (what makes text read as written by a person)

Flat, predictable text reads as machine-written whoever wrote it. The cure is better writing, never
word-swapping or added randomness. `naturalness.py <n>` measures all of this and lists every sentence to
revise; `check.py` reports it as `voice:` warnings.

- **Rhythm.** Vary sentence length on purpose. After a long sentence that connects several ideas, a short
  one lands the point. Never four sentences of the same length in a row. Some sentences should be well
  under the style's average and some well over it.
- **Openings.** Start sentences in different ways: the subject, the evidence, a number, a condition, a
  time. Do not open sentences with a connective by habit: most sentences need none, because the logic
  carries them. Never start three sentences in a row with the same word.
- **Connectives are a budget, not a palette.** Use any one ("however", "therefore", "moreover") no more
  than about 2-3 times per 1,000 words. "But" and "so" are fine in plain styles.
- **Be specific.** Every paragraph is anchored in something concrete: a number, a named system, version
  or dataset, a source, or the author's own example. A paragraph that could appear in any dissertation on
  the topic needs rewriting.
- **Structural tells to avoid** (beyond the banned phrases):
  - "not only X but also Y", "not just X but Y", "it is not merely": state the point directly;
  - reflexive lists of three ("efficient, scalable and secure"): use two when two is true;
  - a trailing significance clause (", highlighting the need for ...", ", underscoring ..."): make the
    significance its own claim, with evidence, or cut it;
  - a summing-up last sentence on every paragraph ("Overall, ...", "This highlights ..."): end on the point;
  - stacked hedges ("may potentially", "could possibly"): hedge once, where the evidence is uncertain;
  - inflated importance ("plays a crucial role", "pivotal", "in today's landscape"): say what it does;
  - signposting in the body ("This section discusses ..."): keep it for the chapter introduction;
  - bold text inside paragraphs, and dashes as punctuation.
- **The author's voice.** Use the author's own examples, judgements and ways of explaining from
  `author_input.md`, close to how they put them (in the project's person and register). `check.py` warns
  when an answered question is not visibly used.
- British spelling (organisation, analyse, behaviour), unless project.yaml says otherwise.

## Paragraph structure (a toolkit, not a mould)

Each paragraph makes one point and, taken together, a section needs these four moves:

1. **Claim:** the point, in your own words.
2. **Evidence:** what the sources or data show, often more than one source. Compare them, don't just
   list them.
3. **Analysis:** what this means for this study: agreements, contradictions, limitations and gaps.
4. **Link:** how it connects to the next point or to the research objectives.

Not every paragraph needs all four, and they need not come in that order. Applying the same four-step
shape to every paragraph is what makes a chapter feel templated. Open some paragraphs with the
evidence, a striking number, a contradiction between two studies or the author's own example, and draw
the claim from it. Let a short paragraph make a single sharp point. Put the link where it is needed
(often at the start of the next paragraph), not as a closing sentence on every paragraph. The
evaluation must be real: a comparison, a judgement of a method or limit, or a consequence for this study.
Adding "however" or "therefore" is not evaluation (`critique.py` no longer counts connectives).

In a literature review, organise by **theme**, not one source per paragraph. A good synthesis
sentence brings sources together: "Although @a and @b both report latency below 20 ms, @c
observed a 3x increase under load, suggesting...".

## Variety: required mix of elements

A chapter must not be paragraph after paragraph. Use whatever fits the content:

| Content | Use |
|---|---|
| Comparing 3 or more items on shared criteria (frameworks, tools, studies, methods) | **Table** |
| Summary of related work (author, year, method, findings, gap) | **Table** |
| Architecture, process, workflow, data flow, research design | **Figure** (diagram) |
| Quantitative results, trends, distributions | **Figure** (chart) and a table of exact values |
| Requirements, steps, criteria, objectives, research questions | **Numbered list** |
| Features, components, advantages and limitations | **Bullet list** (each item at least a phrase, not one word) |
| Argument, interpretation, critique | **Paragraphs** |

Rules:
- Use an element because the content has that shape (a comparison, a sequence, a structure), never to
  meet a quota. A long run of paragraphs is fine when it is one developing argument; check.py warns at 7
  so you can check whether part of it is really a comparison or a list in disguise.
- Every figure and table is **introduced in the text before it appears** and **discussed after it**.
  Never drop one in without comment. Vary how you introduce them, and lead with what the reader should
  notice ("Latency doubles above 50 clients (@fig:latency)") rather than the same "As shown in @fig:..."
  each time.
- Lists are introduced by a full sentence (usually ending in a colon) and their meaning is drawn out in
  the text around them. That can be the next paragraph, or a sentence that picks up the most important
  item. It does not have to be a dedicated analysis paragraph after every list.
- As a rough guide, a 5,000-word chapter has 3–6 figures, 2–5 tables and 2–5 lists. The literature
  review should include at least one summary table of related studies.

## Chapter structures (defaults)

These defaults (also in `scripts/defaults.py`) are **merged with** the project's guidelines, never
used instead of them. Run `PY scripts/guidelines.py outline <n>` to see the merged skeleton:
- **template** sections come from the guideline: always present, in the guideline's order, with its
  titles word for word (unless the spec says `title_policy: adapt`). Never drop, merge or reorder them.
- **default** sections are standard parts the guideline does not mention; add them where they fit.
- **expansion**: a short template is a floor, not a ceiling. Give each template section the depth a
  dissertation needs (2-4 subsections, evidence, a figure or table) so the chapter reaches its length.
- Put `{#sec:<id>}` (the spec id) on each template heading, and `<!-- req: <ID> -->` in the paragraph
  that meets each free-text requirement, so `check.py` and `compliance.md` can trace them.


- **Introduction:** Introduction; Background of the study; Problem statement; Aim; Objectives;
  Research questions; Justification / significance; Scope and delimitations; Limitations;
  Definition of key terms (table); Chapter summary / organisation of the study.
- **Literature review:** Introduction; Theoretical / conceptual framework (figure);
  thematic sections; Related work (summary table); Research gap; Summary.
- **Methodology:** Introduction; Research philosophy and approach; Research design (figure);
  Data collection; Tools and environment (table); Experimental setup; Evaluation metrics (table
  with formulas); Validity and reliability; Ethical considerations; Summary.
- **Design and implementation:** Requirements (functional / non-functional tables);
  System architecture (figure); Component design; Data flow / sequence (figures);
  Implementation (key code excerpts, short ones only); Testing; Summary.
- **Results and evaluation:** Introduction; Experimental environment; Results per objective
  (charts and tables from real data); Discussion against the literature; Summary.
- **Conclusion:** Summary of findings per objective; Conclusions; Contributions;
  Recommendations; Limitations; Future work.

Every chapter except the introduction opens with a short introduction linking to the previous
chapter. Every chapter closes with a summary linking to the next.

## Evidence, experiments and results (Computer Science standard)

- Methodology chapters must be **reproducible**: hardware and software versions, configurations,
  datasets, parameters, number of runs, and metrics with formulas (`$...$` LaTeX math is supported).
- Results come **only** from `output/chapters/chapter_<n>/data/` or numbers the user gives. Write analysis
  scripts that read the data and produce the charts. Report the exact values in tables. Report
  variability (mean ± SD or ranges) when there were repeated runs.
- Compare results with the literature ("This 18 ms overhead is lower than the 35 ms reported by
  @key...").
- If something is missing, write `TODO-DATA: <exact data needed and format>`. Never estimate or
  invent figures.

## Markdown conventions (the build depends on these)

```markdown
## Section title {#sec:short-id}          -> 3.1 Section title  (# is reserved; never type numbers)
### Subsection                            -> 3.1.1
#### Sub-subsection                       -> 3.1.1.1 (use sparingly)

![Descriptive caption sentence. Source: Adapted from @key.](diagrams/zta-arch.png){#fig:zta-arch width=90%}

| Framework | Year | Focus |
|---|---|---|
| NIST SP 800-207 | 2020 | Architecture |

: Comparison of Zero Trust frameworks. {#tbl:zt-frameworks}

As shown in @fig:zta-arch ...   @tbl:zt-frameworks ...   discussed in @sec:short-id ...
```

- Labels: lowercase-hyphen ids, unique across the dissertation, prefixed `fig:` `tbl:` `sec:`.
- The table caption line goes directly **after** the table (it is placed above the table in Word).
- Code excerpts: fenced blocks with a language, at most about 25 lines; full code goes in an appendix.

## Captions

Figures: follow `diagram-standard.md`, which covers picking, drawing, captioning and explaining every figure.

- Figure captions are one descriptive sentence saying what the figure shows and, where useful,
  the key takeaway: "Figure 3.2: Request flow through the policy decision point, showing where
  device posture is evaluated". Not "Architecture diagram".
- When a figure or table is based on a source, end the caption with `Source: Adapted from @key.`
  or `Source: @key.` Your own diagrams need no source line.
- Table captions describe the comparison: "Comparison of Zero Trust frameworks by scope,
  enforcement point and maturity".

## Original synthesis (what lowers similarity and raises marks)

- **Write from notes, not from sources.** Never draft with a source open; never keep a source's
  sentence structure and swap words (patchwriting). `check.py` blocks close paraphrases.
- **Lead with the argument, not the author.** "Temporal defences catch slow attacks that single-round
  filters miss [@a; @b]" synthesises; "@a proposed X. @b developed Y." only lists.
- **Group by theme, compare across sources:** where they agree, disagree, and why; which evidence is
  stronger; what it means for this study. `check.py` flags descriptive paragraphs and lists of studies.
- **Use the author's input** (`author_input.md`): their view, examples and context make the chapter
  theirs and are not found in any source.
- **Quote rarely and exactly**, short, with the page. Quotations in quotation marks are excluded from
  the similarity estimate (and Turnitin can exclude them too).
- **Re-using your earlier submissions** (proposal, coursework) counts as similarity: cite them or rewrite.
- **Keep the project's style** (`style.py show`): the same spelling, person, sentence rhythm and
  terminology in every chapter.
