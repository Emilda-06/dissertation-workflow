---
name: dissertation
description: Dissertation pipeline. Writes a new chapter end to end (plan, research, verify sources, write, diagrams, quality check, build Word document), edits an existing chapter from supervisor or user feedback given in chat, pasted, or as a file, combines chapters into one Word document, and manages several dissertation projects. Use whenever the user asks to write, revise, fix, improve, extend or build any dissertation chapter, switch or create a dissertation project, or add department guidelines/templates, including plain-language requests like "my supervisor says...".
argument-hint: (optional) new <n> | edit <n> <feedback> | combine | status | project <name>
---

# Dissertation pipeline

Arguments: `$ARGUMENTS`

Read `CLAUDE.md` (rules) first.

`PY` means the project venv's Python: `.venv/Scripts/python.exe` on Windows, `.venv/bin/python`
elsewhere (Bash tool, from the workflow root). Every script works on the **active project**; add
`--project <name>` to target another one.

**Project discipline (several dissertations share this folder):**
- Once the project for this conversation is known, pass `--project <name>` on **every** command. The
  active project (`projects/.active`) is shared by all sessions on this computer, so another session
  switching it must never redirect your work.
- Every command prints `== Project: <name> - <title> [how it was chosen] ==` first. Check it matches
  the project you mean before acting on the output; stop if it does not.
- Start every reply about the work with the project name (e.g. "**[thesis-a]** Chapter 2 built ...").
- Never copy chapters, notes, sources, guidelines or style settings from one project into another
  unless the user asks (`project.py new --from` copies department material deliberately).

## Menu (when there are no arguments, or the request is vague)

The user should never need to remember commands. If `$ARGUMENTS` is empty, or the user says
something like "start", "menu", "hi" or "what can you do", silently run `PY scripts/project.py list`,
`PY scripts/status.py` and `PY scripts/doctor.py`, then ask with the **AskUserQuestion** tool. Don't
print the menu as plain text.

If **no project exists**, first ask for a short name and the title, then run
`PY scripts/project.py new <name> --title "<title>"` (or `project.py migrate <name>` if doctor reports
the old single-project layout). If several exist and none is active, ask which one.

**Question 1: "What would you like to do in <project>?"** (header: `Task`)
| Option | Description |
|---|---|
| Write a new chapter | Research, write, add diagrams, check and build a chapter from scratch |
| Revise a chapter | Apply changes from your supervisor or from you |
| Build full dissertation | Combine all chapters (and appendices) into one Word document |
| Status, setup or switch project | Progress, guidelines, setup problems, or another dissertation |

**Question 2, straight after Question 1 (only for Write or Revise): "Which chapter?"** (header: `Chapter`)
- Build the options from the project's `project.yaml` as `"<n>. <title>"`.
  - For *Write*, list chapters that don't have a `chapter.md` yet; for *Revise*, those that do.
  - Show at most 4. The user can pick "Other" and type a number.

**Question 3, Revise only: "How will you give the changes?"** (header: `Feedback`)
| Option | Description |
|---|---|
| I'll type or paste it | Wait for the next message, then use it as the feedback |
| File in feedback/ | List the project's feedback/ files (newest first) and let the user pick |
| Comments in a Word file | A returned .docx with comments/tracked changes: `tools/pandoc <file> -t markdown --track-changes=all`; each comment is a concern |
| Fix the checker's warnings | Run `check.py <n>` and address every warning |

**Combine only: "Which output?"** (header: `Output`): `Word only` / `Word and PDF` / `PDF/A for submission`.

**Status, setup or switch project:** show `status.py` as a short table (add `--html` and give the
path if they want a page), every `--` line from `doctor.py` with its fix, and `guidelines.py status`.
For authorship, `provenance.py show <n>` gives each chapter's timeline of assistant runs and hand edits, and `ownership.py status <n>` shows which key paragraphs the author has rewritten.
Offer: switch project (`project.py use <name>`), create one, or `status.py --all-projects`.

If `$ARGUMENTS` was given, skip the menu:

| Input | Mode |
|---|---|
| `new <n>` | **NEW** |
| `edit <n> ...`, or any request to change, fix or add to a chapter | **EDIT** |
| `combine` | **COMBINE** |
| `status` | the status summary above |
| `project <name>` | switch to (or offer to create) that project |

If a tool the task needs is missing (doctor `--`), say so in one line and carry on if possible:
research works without an email; builds work without a cover, without Word (LibreOffice / none).

## Before any mode

1. `PY scripts/pipeline.py begin <n> <new|edit> "<request summarised>"`. It checks Zotero (for
   projects that use it; if it cannot start, stop and tell the user), snapshots the project's git
   history, and starts the run, or tells you a run is **IN PROGRESS**: then resume from the next
   unfinished stage (`state.py show <n>`). Don't restart.
2. **Guidelines (templates).** Run `PY scripts/guidelines.py status`.
   - New or changed files in `guidelines/` are scanned automatically. If any part is marked
     **REVIEW**, read it (`guidelines.py show <n>` / `list`) and decide the mapping yourself when the
     text makes it clear (`guidelines.py map <file> <part-id> <chapter|general|ignore>`); ask the
     user only when it is genuinely ambiguous. File names never matter.
   - If there is no `requirements/spec.yaml`, or it is stale, (re)build it: `guidelines.py spec-init`
     (once), then for each chapter read `guidelines.py show <n>` and record **only what the guideline
     says**: required sections (ids, titles, order, level), required figures/tables (`elements`, with
     a caption keyword in `match`), word range, minimum references, and other rules as
     `requirements`. Every item needs `source: {file, page, quote}` with a quote copied from the text.
     Run `guidelines.py validate` until VALID, show the user a short summary, and after they agree run
     `guidelines.py approve`.
3. **Writing style.** If the project has no `style.yaml`, ask the user (AskUserQuestion, header `Style`)
   which preset fits (`style.py presets`: formal-analytical, concise-technical, discursive,
   plain-academic) and British or American spelling, then `PY scripts/style.py init --preset <p>
   [--spelling ...]`. Settings the guidelines state (person, spelling) are applied automatically. Show
   the brief (`style.py show`) once; every chapter of this project then follows it, so the dissertation
   reads as one consistent voice. Never change another project's style.
   **The author's own voice.** Also ask whether they have earlier writing they did themselves, **without
   AI tools** (an essay, a report, coursework, a reflective log; 2,000+ words is best). If `existing/` has
   such files, name them. With the user's confirmation that it is their own work, run
   `PY scripts/style.py init --preset <p> --from-sample existing/<file> --own-work` (or
   `style.py voice <file> --own-work` for an existing profile). It measures their rhythm, connectives,
   openings, hedging and typical phrasing and tunes the profile to it, and the brief then tells the
   writer to match it. It only measures; nothing from the sample is copied. Never pass `--own-work`
   without asking, and never use AI-assisted text as a sample.
4. `PY scripts/context.py <n>`: the project details, the research problem/aim/objectives/questions,
   the chapter plan, the merged outline skeleton and the guideline text for this chapter, the other
   chapters' headings and labels, and the earlier work and feedback files. Read files in `existing/`
   it lists when relevant; use them for consistency, never copy from them.

Record each finished stage with `PY scripts/state.py done <n> <stage> "<short note>"`.

---

## NEW mode

### Stage 1a: the author's input (before planning)
`PY scripts/author_input.py init <n>`, then ask the user its questions (their view, what convinced
them, where they disagree, their context and examples). Short answers are fine; write them into
`author_input.md` exactly as given (fix only spelling). When an answer is very short (under about 8
words) or vague, ask **one** follow-up ("What made you distrust that study?", "Can you give an example
from your placement?") and record it with `author_input.py add <n> "<follow-up>" --answer "<reply>"`.
The user may instead paste notes or a transcript of a voice memo of themselves talking it through:
save it with `author_input.py add <n> "Notes in my own words" --file <file>` (or `--answer`). The chapter
is built on these answers: the argument, evaluations and examples come from the author, the sources
support them, and their own way of explaining things is kept where it fits the style. If the user
prefers to skip, note that in the file and continue (check.py will keep reminding).

### Stage 1: plan (the only stop for user approval)
Start from `PY scripts/guidelines.py outline <n>` (template + defaults + expansion). Write
`output/chapters/chapter_<word>/outline.md`:
- every `##` / `###` section with 1–2 lines on its purpose, tagged **template / default / expansion**,
  mapped to the guideline requirement and to the research objectives. Template sections keep their
  titles (unless `title_policy: adapt`) and order; a short template is expanded, never replaced;
- the planned figures (type and tool), tables and lists, including every required element;
- 4–8 search queries; the target length (from the outline skeleton).

Show the outline briefly and **ask for approval or changes**. After approval, run every other stage
without stopping.

### Stage 2: research
Follow `research-guide.md`. `PY scripts/research.py search "<query>" --chapter <n>` per query.
For each source you'll rely on, `research.py fulltext --chapter <n> --doi <doi>` and read the relevant
pages (or at least the abstract). Write `research/notes.md` (claims with pages, evidence,
limitations, section) as **short points in your own words, never sentences copied or lightly reworded
from the source** (check.py compares the notes with the sources). Exact wording you may want to quote
goes in quotation marks with its page. Roughly 1 source per 150–250 words for a literature chapter, fewer otherwise.

### Stage 3: verify
`PY scripts/refs.py add --doi <doi> ...` (`add-manual` only for standards/reports without a DOI).
Drop anything not `VERIFIED` (mismatch, failed, **retracted**); never edit metadata to make it fit.
Prefer sources from `min_year` on; justify older ones with `refs.py mark-foundational`. Then
`refs.py sync-zotero` (projects using Zotero; it refuses if the wrong collection is selected and
says what to do). Zotero items are pulled at build time; `refs.py verify --keys <key>` before citing.

### Stage 4: write
Write `chapter.md` following `writing-guide.md` and the style guide for the project's citation style
(`harvard-guide.md` covers the pandoc syntax for every style). Front matter:
```yaml
---
chapter: <n>
title: <Title from project.yaml>
type: <type>
status: draft
---
```
**Write from `research/notes.md` and `author_input.md`, never with a source open.** Follow the
project's style brief (`style.py show`). For each paragraph: make the author's point, support it with
evidence from one or more sources, evaluate (compare, judge methods and limits) and link it to this
study. Never list studies one per sentence or one per paragraph; group them by theme. Never keep a
source's sentence structure while swapping words: that is patchwriting and check.py blocks it.

Start directly with the first `##` section. Put `{#sec:<spec id>}` on every template heading and
`<!-- req: <ID> -->` where each free-text requirement is met. Mention each required element's
keyword in its caption. Write section by section and save as you go.

### Stage 5: diagrams
Create each planned figure following `diagram-standard.md`, then `PY scripts/diagrams.py <n>`.
**Look at every rendered PNG** (Read tool) and fix overlaps, clipping or unreadable labels.

### Stages 6–8: check, build, report
1. `PY scripts/check.py <n>`. Fix every ERROR (unverified/retracted/edited sources, missing template
   sections or elements, copied or closely paraphrased sentences, quotes not found in the source,
   broken labels). Fix the `depth:` warnings (descriptive paragraphs, lists of studies, low synthesis)
   and `style:` warnings. For a flagged paraphrase, rewrite the point from the notes in a new structure
   and add evaluation; never just swap more words. Run `PY scripts/similarity.py <n>` to see each
   flagged sentence next to its source. Fix
   warnings unless there's a clear reason not to. Then self-review: every claim supported by a source
   that says it; every requirement and objective covered; plain English; varied blocks.
2. **Naturalness revision pass.** Run `PY scripts/naturalness.py <n>`. It lists the `voice:` warnings
   and every sentence to revise. Revise section by section, following "Natural prose" in
   `writing-guide.md`:
   - cut throat-clearing first sentences and summing-up last sentences that only restate the point;
   - replace generic claims with the specific number, system, source or author example from the notes,
     data or `author_input.md`;
   - vary rhythm and sentence openings, and drop connectives the logic does not need;
   - rewrite the structural tells it lists (not only ... but also, trailing ", highlighting ...", lists
     of three, stacked hedges, inflated words);
   - bring in author answers flagged as not used.

   **Locked during this pass:** meaning, every claim's citation, quotations, numbers, `{#labels}`,
   `<!-- req -->` markers and template headings. Never swap synonyms to change wording, and never add
   errors or odd word choices to look "human": this pass is about writing better. Then run `check.py <n>`
   again; the integrity checks must still pass.
3. `PY scripts/pipeline.py finish <n> [--pdf]`: diagrams → check → verify → build → compliance →
   state → git snapshot. If it stops, fix what it reports and run it again. If Word holds the file
   open, ask the user to close it.
4. `finish` also writes `similarity_report.md` (estimated similarity against the known sources and
   your earlier work, a lower bound of what Turnitin may show) and `defence_brief.md` (key claims and
   evidence, figures to explain, weak spots, likely examiner questions). Add short model answers under
   the questions in the brief, based on the chapter and the author's input.
5. Tell the user briefly: project and output path; words/figures/tables/sources (check.py); guideline
   requirements met (`compliance.md`); estimated similarity; the defence brief; `TODO-DATA` items they
   must supply; anything unsure. Suggest they rehearse the defence brief in their own words.

### Stage 9: your turn (the author rewrites the key paragraphs)
Run `PY scripts/ownership.py pick <n>`. It chooses the 3–5 paragraphs that carry the argument (the gap,
the key evaluation, the position, the conclusions) and writes them to `your_turn.md` with space for the
author's version. Tell the user these are the paragraphs an examiner is most likely to ask about, and
that rewriting them in their own words makes the chapter genuinely theirs. It is optional but strongly
recommended. When they say they have done it, or paste their versions in chat (write those into
`your_turn.md` under "Your version" exactly as given, fixing only spelling):
1. `PY scripts/pipeline.py begin <n> edit "author's own rewrites of key paragraphs"`;
2. `PY scripts/ownership.py apply <n>` (it refuses versions that cite sources not in the library, and keeps
   the rest of the chapter untouched);
3. `check.py <n>`. Fix only real errors in their paragraphs (a missing citation, a broken label). **Never
   "polish" the author's rewritten paragraphs** with the naturalness pass: they are their voice;
4. `pipeline.py finish <n>`.

Any hand edits the author makes to `chapter.md` between runs are recorded automatically as their edits at
the next `pipeline.py begin` (`provenance.py show <n>`). That only works if every assistant change goes
through begin/finish, so never edit a chapter outside a run.

---

## EDIT mode

The feedback may be typed, pasted, a file in the project's `feedback/`, or a path. Read files fully
(.docx via pandoc, .pdf with Read). For a document covering several chapters, take only this
chapter's comments and mention the others.

If `chapter.md` does not exist but the chapter is in `existing/`, import it first:
`PY scripts/import_docx.py "<file>" <n>`, then fix what `import_report.md` lists.

### Stage 1: plan
Break the feedback into numbered, specific concerns, each with the affected section(s) and fix.
Check each fix against the guideline requirements (`context.py <n> --brief`): never remove or rename
a template section to satisfy feedback without telling the user. Only ask if genuinely ambiguous.

### Stages 2–3: research and verify (only if a concern needs new evidence)

### Stage 4: write
Change only what the concerns require. Keep the rest word for word, and keep labels stable.

### Stages 5–8
Run `naturalness.py <n>` and apply the naturalness revision pass to the **changed sections only** (the rest stays word for word).

Add an entry to `revisions.md` (create it if missing):

```markdown
## Revision <k> - <date> (chapter_<word>_v<k>.docx)
Source: <supervisor feedback file / chat request>

| # | Concern raised | How it was addressed | Section(s) |
|---|---|---|---|
| 1 | ... | ... | 2.3, 2.4 |
```

Then `PY scripts/pipeline.py finish <n>`. In edit mode it also builds the "changes made" document
and a **tracked-changes** version against the previous build (`build.py redline <n>`).
Show the user the concern table and the output paths (new version, changes, tracked changes).

---

## COMBINE mode

1. `PY scripts/check.py all` (chapters and appendices). Report problems; fix them if the user agrees,
   or build a draft with `--force` if they want one.
2. If the project's `output/dissertation/front_matter/` is empty, offer to draft `01-declaration.md`,
   `02-abstract.md` (written last; follow the guideline's abstract rules if the spec has them,
   otherwise 250–350 words) and `03-acknowledgements.md` (and `04-abbreviations.md` if useful). Each
   has front matter `title: ABSTRACT` and so on.
3. **AI-use statement and process log.** Run `PY scripts/provenance.py log`, which writes
   `output/dissertation/provenance.md`: every drafting run, every hand edit, the author input, the
   key-paragraph rewrites, source verification and the git history. If
   `front_matter/05-ai-use.md` does not exist, run `PY scripts/provenance.py statement`. It drafts a
   declaration from those records and lists any AI rules found in the department's guidelines. Show the
   user the draft and tell them:
   - many universities require a declaration of AI use, so they must check it against their own policy;
   - every sentence must be true, so they should never let it understate how the assistant was used;
   - the page stays out of the combined document until they set `reviewed: true` in its front matter.

   Never set `reviewed: true` yourself, and never soften the statement's description of the assistant's
   role. Suggest they keep `provenance.md` in case their authorship is ever questioned; AI detectors are
   known to flag human writing, especially by non-native English writers.
4. `PY scripts/project.py commit "before: combine"`, then
   `PY scripts/build.py combine [--chapters 1 2 3] [--pdf | --pdfa]`.
5. `PY scripts/project.py commit "dissertation v<k>"` and report the path.
