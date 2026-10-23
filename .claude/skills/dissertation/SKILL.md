---
name: dissertation
description: Dissertation pipeline. Writes a new chapter end to end (plan, research, verify sources, write, diagrams, quality check, build Word document), edits an existing chapter from supervisor or user feedback given in chat, pasted, or as a file, or combines chapters into one Word document. Use whenever the user asks to write, revise, fix, improve, extend or build any dissertation chapter, including plain-language requests like "my supervisor says...".
argument-hint: (optional) new <n> | edit <n> <feedback> | combine | status
---

# Dissertation pipeline

Arguments: `$ARGUMENTS`

Read `CLAUDE.md` (rules) first.

## Menu (when there are no arguments, or the request is vague)

The user should never need to remember commands. If `$ARGUMENTS` is empty, or the user says
something like "start", "menu", "hi" or "what can you do", silently run `PY scripts/state.py show`
and `PY scripts/doctor.py`, then ask with the **AskUserQuestion** tool. Don't print the menu as
plain text.

**Question 1: "What would you like to do?"** (header: `Task`)
| Option | Description |
|---|---|
| Write a new chapter | Research, write, add diagrams, check and build a chapter from scratch |
| Revise a chapter | Apply changes from your supervisor or from you |
| Build full dissertation | Combine all chapters into one Word document with cover, contents and references |
| Status and setup | See each chapter's progress, versions, and anything still to set up |

**Question 2, asked straight after Question 1 (only for Write or Revise): "Which chapter?"** (header: `Chapter`)
- Build the options from `config/project.yaml` as `"<n>. <title>"`.
  - For *Write*, list chapters that don't have a `chapter.md` yet.
  - For *Revise*, list chapters that do.
  - Show at most 4. The user can pick "Other" and type a number.
- If only one chapter fits, still ask, so the user can confirm.

**Question 3, Revise only: "How will you give the changes?"** (header: `Feedback`)
| Option | Description |
|---|---|
| I'll type or paste it | Wait for the next message, then use it as the feedback |
| File in config/feedback | List the files there (newest first) and let the user pick, or use the only one |
| Comments in a Word file | The user returns a chapter .docx with comments or tracked changes. Read it with `tools/pandoc.exe <file> -t markdown --track-changes=all` and treat each comment as a concern |
| Fix the checker's warnings | Run `check.py <n>` and address every warning |

**Combine only: "Which output?"** (header: `Output`): `Word only` / `Word and PDF`.

**Status and setup:** summarise in a short table:
- each chapter: whether it exists, its latest docx version, word count from `check.py`, and any run in progress;
- every `--` line from `doctor.py`, with the exact fix (see `SETUP.md`).

Then ask whether they want to do something else (Question 1 again).

Then run the matching mode below. If `$ARGUMENTS` was given, skip the menu:

| Input | Mode |
|---|---|
| `new <n>` | **NEW**: write chapter n from scratch |
| `edit <n> ...`, or any request to change, fix or add to a chapter | **EDIT** |
| `combine` | **COMBINE** |
| `status` | the Status and setup summary above |

If `doctor.py` shows a missing tool that the chosen task needs (for example no cover page before a
build, or no CONTACT_EMAIL before research), say so in one line and carry on if possible:
research still works without an email, and builds still work without a cover.

`PY` below means `.venv/Scripts/python.exe` (Bash tool, from the workflow root).

## Before any mode

0. Run `PY scripts/ensure_zotero.py`. It starts Zotero if it is closed. If it fails, stop and tell
   the user to open Zotero. Never continue without it (workflow rule).
1. Run `PY scripts/state.py show <n>`. If a run is **IN PROGRESS** for this chapter, tell the user
   and resume from the next unfinished stage. Don't restart.
2. Run `git add -A && git commit -qm "before: <mode> chapter <n>" || true`.
3. Load context:
   - `config/project.yaml`: title, chapter plan, chapter `type` and `guideline`.
   - The chapter guideline in `config/guidelines/` (named in project.yaml, or any file whose name
     mentions this chapter). **The guideline's required sections override the default structure.**
   - `config/existing/` (read `NOTES.md` there first): the proposal and earlier chapters. Use them for the research problem,
     aim, objectives, research questions, scope and terminology, so the new chapter is consistent.
     Read them; do not copy from them.
   - Other chapters' `chapter.md`, to keep terminology, objectives and cross-references consistent.

Record each finished stage with `PY scripts/state.py done <n> <stage> "<short note>"`.

---

## NEW mode

`PY scripts/state.py start <n> new "<user request>"`

### Stage 1: plan (the only stop for user approval)
Write `output/chapters/chapter_<word>/outline.md`:
- each `##` and `###` section with 1–2 lines on its purpose, mapped to the guideline's requirements
  and the research objectives;
- the planned figures (type and tool), tables, and bullet or numbered lists, spread across the
  chapter (see writing-guide.md, "Variety");
- 4–8 search queries for the research stage;
- target length (from the guideline; otherwise introduction 3,000–4,000 words, literature review
  6,000–8,000, methodology 4,000–5,000, design 5,000–7,000, results 5,000–7,000, conclusion
  2,000–3,000).

Show the outline to the user briefly and **ask for approval or changes**. After approval, run every
other stage without stopping.

### Stage 2: research
Follow `research-guide.md`. For each query, run `PY scripts/research.py search "<query>" --chapter <n>`.
Shortlist the strongest sources. For each one you'll cite, try
`research.py fulltext --chapter <n> --doi <doi>` and read the extracted text (relevant pages) or
at least the abstract. Write `research/notes.md`: per source, the key claims you'll use with page
numbers, the method or evidence, limitations, and the section where it will be used. Aim for
roughly 1 distinct source per 150–250 words of a literature chapter, fewer for others.

### Stage 3: verify
Add shortlisted sources with `PY scripts/refs.py add --doi <doi> <doi> ...`. Use
`add-manual` only for standards, RFCs or official reports without a DOI. It runs verification
automatically. Drop anything not `VERIFIED`; never fix a mismatch by editing metadata to fit.
Prefer 2016-onwards sources (target 80% or more). A pre-2016 source is fine when it is the best or original
source; record why with `refs.py mark-foundational <key> "<reason>"`.
Then run `PY scripts/refs.py sync-zotero` so the verified sources also appear in the user's Zotero
(it's skipped with a note if Zotero is closed). Sources the user saved in Zotero are pulled automatically
at build time. Before citing one of those, run `refs.py verify --keys <key>`.

### Stage 4: write
Write `output/chapters/chapter_<word>/chapter.md` following `writing-guide.md` and `harvard-guide.md`.
Front matter:
```yaml
---
chapter: <n>
title: <Title from project.yaml>
type: <type>
status: draft
---
```
Start directly with `## Introduction`. The chapter title heading and all numbers are generated.
For every figure, follow `diagram-standard.md` part C: introduce it, place it, then explain it.
Every planned figure must match the catalogue in part A.
Write section by section and save as you go (long chapters may need several writes).

### Stage 5: diagrams
Create each planned figure following `diagram-standard.md` in `output/chapters/chapter_<word>/diagrams/`, then run
`PY scripts/diagrams.py <n>`. **Look at every rendered PNG** (Read tool) and fix overlapping text,
clipping or unreadable labels before moving on.

### Stage 6: check
`PY scripts/check.py <n>`. Fix every ERROR. Fix warnings unless there's a clear reason not to.
Then run `PY scripts/refs.py verify --chapter <n>`. Then do a self-review pass and fix what you
find:
- every factual claim is supported by a cited source that says it;
- each guideline requirement and each objective the chapter must address is covered;
- the writing follows writing-guide.md (plain English, terms defined, no filler, no
  AI-typical phrasing);
- a varied mix of paragraphs, tables, figures and lists, with no long walls of text.

### Stage 7: build
`PY scripts/build.py chapter <n>` (add `--pdf` if the user wants a PDF). If Word is holding the file
open, ask the user to close it.

### Stage 8: report
`PY scripts/state.py finish <n>`, then `git add -A && git commit -qm "chapter <n>: new draft v<k>"`.
Tell the user, briefly:
- the output path;
- word count, figures, tables and sources (from check.py);
- `TODO-DATA` items they need to supply;
- anything you were unsure about.

---

## EDIT mode

`PY scripts/state.py start <n> edit "<the feedback, summarised>"`

The feedback may be typed in chat, pasted text, a file in `config/feedback/`, or a path the user
gives. Read files fully (.docx: use pandoc to convert to text; .pdf: Read tool). For a supervisor
document covering several chapters, only take the comments meant for this chapter, and mention
the others.

If `output/chapters/chapter_<word>/chapter.md` does not exist but the chapter is in `config/existing/`, import it
first: `PY scripts/import_docx.py "<file>" <n>`. Read `import_report.md` and fix what it lists
(unlinked references: find them with research.py or refs.py; unconverted citations: convert
them by hand; captions).

### Stage 1: plan
Break the feedback into numbered, specific concerns. For each one, name the section(s) affected
and the planned fix. **Only ask the user if a concern is genuinely ambiguous.** Otherwise continue.

### Stages 2–3: research and verify (only if needed)
Run them only when a concern needs new evidence (e.g. "needs more recent sources", "support this
claim", "compare more frameworks").

### Stage 4: write
Change only what the concerns require. Keep the rest of the chapter word for word. Keep labels
(`{#fig:..}`, `{#tbl:..}`, `{#sec:..}`) stable so cross-references survive.

### Stages 5–7: diagrams, check, build
Same as NEW mode. The build creates the next version (v2, v3, ...), so earlier versions are kept.

### Stage 8: report
Add an entry to `output/chapters/chapter_<word>/revisions.md` (create it if missing):

```markdown
## Revision <k> - <date> (chapter_<word>_v<k>.docx)
Source: <supervisor feedback file / chat request>

| # | Concern raised | How it was addressed | Section(s) |
|---|---|---|---|
| 1 | ... | ... | 2.3, 2.4 |
```

Then run `PY scripts/build.py changes <n>`, `state.py finish`, and commit
`git commit -qm "chapter <n>: revision v<k> - <summary>"`.
Show the user the concern table and the output paths.

---

## COMBINE mode

1. Run `PY scripts/check.py all`. Report problems, fix them if the user agrees, or build anyway with
   `--force` if they want a draft.
2. If `output/dissertation/front_matter/` is empty, offer to draft `01-declaration.md`, `02-abstract.md`
   (written last: 250–350 words summarising problem, method, results, conclusion) and
   `03-acknowledgements.md`. Each file has front matter `title: ABSTRACT` and so on.
3. Run `PY scripts/build.py combine [--chapters 1 2 3] [--pdf]`.
4. Commit and report the path.
