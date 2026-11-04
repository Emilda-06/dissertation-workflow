# Production-hardening roadmap

Branch: `feature/production-hardening`. One commit (or more) per step; every step ships with tests
under `tests/` (run with `.venv/Scripts/python.exe -m pytest`).

## Step 1 - Multiple projects, isolated and versioned

Problem: every path was a module constant rooted at the repo (`common.py`), so one dissertation per
checkout; the "commit before/after every run" rule committed nothing because all student work is
git-ignored; Zotero pull imported the user's whole library.

Design
- Each dissertation lives in `projects/<slug>/` with its own git repository:
  ```
  projects/<slug>/
    project.yaml  cover.docx|pdf
    guidelines/  existing/  feedback/
    templates/              per-project overrides (generated reference.docx, custom .csl)
    output/chapters/chapter_<word>/...   output/appendices/appendix_<x>/...   output/dissertation/...
    references/             references.json, verification.json, zotero.json, zotero_sync.json
    .build/                 intermediates (git-ignored inside the project repo)
  ```
- Shared at the root: `scripts/`, the skill, default templates in `config/templates/`,
  `config/project.example.yaml`, `.env` (personal API settings).
- Active project resolution (first match wins): `--project <slug>` on any script,
  `DISSERTATION_PROJECT` env var, `projects/.active`, the only project if exactly one exists.
- `common.Project` object replaces the module constants; `common.project()` returns the active one.
- `scripts/project.py new | list | use | current | migrate | commit | log`:
  `new` scaffolds + `git init`; `migrate` moves the legacy single-project layout into
  `projects/<slug>/` (history preserved as the first commit); `commit "<msg>"` snapshots the project
  repo (replaces the root `git add -A` in the skill).
- Zotero isolation: `zotero.collection` in project.yaml. Pull uses Better BibTeX's collection
  export (only that collection); push refuses to send items into a different collection than the
  one selected in Zotero (writes an import file instead).
- Zotero is only required by commands that use it (add/verify/research/import/build/sync), not by
  `list/show/find/check/status`.
- Chapters beyond 12 (number words up to 99) and appendices (`appendices:` in project.yaml).
- State: validated stage names, a lock to stop two sessions running the same chapter, `show 0` fix.
- Menu: "Switch / create project"; every report names the active project.

## Step 2 - Template (guideline) intelligence

Problem: guidelines were linked only by typed filenames, never read by code, one-file-per-chapter
was assumed, a template *replaced* the default structure (so short templates gave thin chapters),
nothing was enforced, and one department's rules were hard-coded in `diagram-standard.md`.

Design (`scripts/guidelines.py`)
- `scan`: converts every file in `guidelines/` (.docx/.pdf/.md/.txt) to text with page/heading
  markers (cache in `.build/guidelines/`), fingerprints it (sha256), detects Word *format* templates
  (styles, little text), splits multi-chapter documents at chapter boundaries and maps each part to
  the chapter plan by number ("Chapter 2", "Chapter Two", "Chapter II"), title and type keywords,
  with a confidence score. Names of files do not matter. Result: `guidelines/manifest.json`.
- `map <file> <part> <chapter|general|ignore>`: manual override (stored, survives re-scans).
- `show <n>`: the exact guideline text that applies to chapter n (its parts + general parts).
- `spec.yaml`: structured requirements per chapter (sections with order/level/required, elements
  such as "use case diagram", word range, min references) + document-level rules. Every requirement
  has a `source` (file, page/heading, short quote). `validate` checks the schema and that each quote
  really occurs in the guideline text (no invented requirements); `status` flags a stale spec when a
  guideline file changed; `approve` records user approval.
- `outline <n>`: merged skeleton = template sections (floor, order kept, `origin: template`)
  + chapter-type defaults the template does not cover (`origin: default`, from `scripts/defaults.py`)
  + room for AI expansion (`origin: expansion`). Short templates get expanded, never replaced.
- `check.py` enforces the spec: missing mandatory section / required element = ERROR; wrong order,
  length outside range = warning; min references from the spec.
- `compliance <n>`: `compliance.md` requirement -> section number, for the report and supervisor.
- Department-specific lines removed from the shared skill; format templates become the base of the
  generated reference.docx.

## Step 3 - Source verification hardening
- Manual (no-DOI) sources: the URL must be reachable AND its page/PDF must contain the title.
- Title match compares against title + subtitle with strict scorers (no subset passes).
- Cache invalidated when title/author/year/DOI/URL change (fingerprint stored).
- Retraction check: Crossref `updated-by` (retraction/withdrawal) and OpenAlex `is_retracted`;
  status `retracted` blocks the build.

## Step 4 - Configuration that actually works
- `references.style` selects the CSL (harvard, apa, ieee bundled; or a path; per-project override).
- `project.current_topic_source` used by `context.py <n>` (deterministic context bundle: project,
  aims/objectives/RQs from the topic source, chapter plan, guideline text, spec, other chapters).
- reference.docx regenerated automatically per project when `format:` or a format template changes.
- `format.paper` (A4/Letter), footer font/size from config, cover placeholders filled in body,
  tables, headers, footers and text boxes while keeping run formatting.

## Step 5 - Tests, CI, pinned dependencies
- pytest suite for every module (network mocked); GitHub Actions on Windows and Ubuntu.
- `requirements.txt` pinned, `requirements-dev.txt`; doctor checks pandoc / pandoc-crossref match;
  `doctor.py --fix` installs Python/Node deps and downloads matching pandoc + pandoc-crossref.

## Step 6 - Integrity checks and supervisor redline
- `scripts/integrity.py` (used by `check.py`): verbatim/near-verbatim overlap with downloaded full
  texts; direct quotes `"..." [@key, p. N]` must appear on that page of the source; numbers in
  results chapters must be traceable to `data/`.
- Every build snapshots `chapter.md` next to the docx; `build.py redline <n>` produces a
  tracked-changes Word document (Word Compare) or a marked-up diff document without Word.
- `pipeline.py finish <n>` runs diagrams -> check -> verify -> build -> state deterministically;
  `status.py` dashboard (text and HTML).
- Research: response cache, parallel sources, optional Semantic Scholar API key.

## Step 7 - Cross-platform and Word-optional builds
- `format.finalizer: auto | word | libreoffice | none`. Without Word: TOC/lists set to update on
  open, cover rendered as an image (LibreOffice/pypdfium2), PDF via LibreOffice.
- No hard-coded `.venv/Scripts`; hook and permissions work with `.venv/bin` too; `start.sh`.
- PDF/A export option for submission portals.
