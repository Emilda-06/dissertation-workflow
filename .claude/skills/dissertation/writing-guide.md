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
- British spelling (organisation, analyse, behaviour), unless project.yaml says otherwise.

## Paragraph structure (claim → evidence → analysis → link)

1. **Claim:** the paragraph's point, in your own words.
2. **Evidence:** what the sources show, often more than one source. Compare them, don't just
   list them.
3. **Analysis:** what this means for this study. Note agreements, contradictions, limitations
   and gaps.
4. **Link:** connect to the next point or to the research objectives.

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
- No more than about 5 paragraphs in a row without a table, figure or list. check.py warns at 7.
- Every figure and table is **introduced in the text before it appears** ("@fig:zta-arch shows...")
  and **discussed after it**. Never drop one in without comment.
- Lists are introduced by a full sentence ending in a colon, and followed by a paragraph
  of analysis.
- A typical 5,000-word chapter has 3–6 figures, 2–5 tables and 2–5 lists. The literature review
  should include at least one summary table of related studies.

## Chapter structures (default; a guideline in config/guidelines/ overrides these)

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
