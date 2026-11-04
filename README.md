# Dissertation workflow

A [Claude Code](https://claude.com/claude-code) pipeline for writing a Computer Science dissertation.
Chapters are written in Markdown, backed by **verified, real sources**, and built into formatted
Word documents with a cover page, table of contents, numbered figures and tables, and a reference
list in your department's style (Harvard, APA, IEEE or any CSL file). One installation can hold
**several dissertations**, each in its own folder with its own history.

You talk to it in plain language ("write chapter 2", "my supervisor says the problem statement is
vague") or pick from a menu. It plans the chapter, searches the literature, verifies every
reference, writes, draws diagrams, runs a quality check and builds a new numbered `.docx` version.

## What it does

- **Several dissertations, kept apart:** every project lives in `projects/<name>/` with its own
  settings, guidelines, chapters, reference library, Zotero collection and git history.
- **Your department's templates, followed and expanded:** drop guideline or template files into the
  project's `guidelines/` folder with *any* names. The pipeline works out which chapter each part
  belongs to (one file per chapter or one big handbook), turns them into checkable requirements that
  quote the guideline, keeps every required section in order, and expands short templates to full
  dissertation depth. `check.py` blocks a build that misses a required section or figure.
- **Research:** searches OpenAlex, Semantic Scholar and Crossref, and downloads legal
  open-access full texts through Unpaywall.
- **References you can trust:** sources are added by DOI, so the metadata comes from the DOI registry and is never typed from memory.
  Each one is checked against Crossref or OpenAlex (title, author, year and retraction status), and
  re-checked whenever its details change. Synced with the project's Zotero collection.
- **Diagrams:** Mermaid, draw.io and matplotlib sources are rendered to 300 dpi PNG.
- **Quality gate:** `check.py` checks citations, cross-references, images, headings, recency, the
  guideline requirements, sentences copied from sources, direct quotes against the source text, and
  whether reported results can be traced to your data.
- **Word output:** pandoc plus pandoc-crossref; Microsoft Word (if installed) fills in the cover,
  contents and lists, page numbers and PDF / PDF-A. Without Word it still builds (LibreOffice or a
  plain .docx). Every build is a new version (`_v1`, `_v2`, ...). Appendices follow the references.
- **Revisions:** supervisor feedback (typed, pasted, a file, or Word comments) is applied and logged;
  the supervisor gets a "changes made" table and a tracked-changes version.
- **Status at a glance:** `status.py` (or `--html`) shows words against target, sources,
  requirements met, TODO-DATA items, versions and unanswered feedback for every chapter.
- **Your rules:** the pipeline never invents sources, data or results. Missing data is marked
  `TODO-DATA`.

## Requirements

Built and tested on **Windows 10/11**, with tests running on Windows and Linux. Microsoft Word gives
the best final document (cover, roman/arabic page numbers, filled contents, tracked changes); without it,
LibreOffice fills the contents and makes the PDF / PDF-A (arabic page numbers throughout), or a plain .docx
is produced whose contents fill in when it is opened.

### System tools

| Tool | Version tested | Used for | Install |
|---|---|---|---|
| [Claude Code](https://claude.com/claude-code) | latest | runs the pipeline (the `/dissertation` skill) | see website |
| Python | 3.12+ (tested 3.14) | all pipeline scripts | `winget install Python.Python.3.12` |
| Node.js | 20+ (tested 24) | Mermaid diagram rendering | `winget install OpenJS.NodeJS.LTS` |
| Git | any | version history before and after each run | `winget install Git.Git` |
| [pandoc](https://github.com/jgm/pandoc/releases) | 3.13 | Markdown to Word conversion | put `pandoc.exe` in `tools\` |
| [pandoc-crossref](https://github.com/lierdakil/pandoc-crossref/releases) | 0.3.26 (built for pandoc 3.13; must match) | figure, table and section numbering | put `pandoc-crossref.exe` in `tools\` |
| [draw.io desktop](https://www.drawio.com/) | any | rendering `.drawio` diagrams | `winget install JGraph.Draw` |
| [Zotero 7](https://www.zotero.org/) | 7.x | reference library (optional per project; open while it is used) | `winget install DigitalScholar.Zotero` |
| [Better BibTeX for Zotero](https://github.com/retorquere/zotero-better-bibtex/releases) | latest | lets the pipeline talk to Zotero | Zotero > Tools > Plugins > install the `.xpi` |
| Microsoft Word | 2016+ (optional) | best final document: fields, contents, cover, PDF/A, tracked changes | Microsoft 365 / Office |
| LibreOffice | any (optional) | contents, PDF and PDF/A when Word is not installed | libreoffice.org (per-user install works; it runs with its own profile, never yours) |

### Python packages (`requirements.txt`, pinned; `requirements-dev.txt` adds pytest)

| Package | Tested | Used for |
|---|---|---|
| `python-docx` | 1.2.0 | reading and writing Word files (cover, template, import) |
| `pyyaml` | 6.0.3 | reading `project.yaml` and guideline specs |
| `requests` | 2.34.2 | OpenAlex, Semantic Scholar, Crossref, Unpaywall and Zotero APIs |
| `rapidfuzz` | 3.14.6 | fuzzy title matching when verifying references |
| `pypdf` | 6.21.2 | extracting text from downloaded open-access PDFs |
| `pypdfium2` | 5.14.0 | PDF rendering (cover page from PDF, previews) |
| `matplotlib` | 3.11.2 | charts and Gantt diagrams |
| `seaborn` | 0.13.2 | statistical charts for results chapters |
| `pandas` | 3.1.0 | loading experiment data (CSV) |
| `numpy` | 2.5.4 | numerical work for charts and results |

### Node packages (`package.json`)

| Package | Tested | Used for |
|---|---|---|
| `@mermaid-js/mermaid-cli` | 12.0.0 | renders `.mmd` diagrams to PNG (`mmdc`) |

### Online services (all free, no account needed)

| Service | Needs |
|---|---|
| OpenAlex, Crossref | nothing (an email gives faster "polite pool" access) |
| Semantic Scholar | nothing (used anonymously) |
| Unpaywall | an email address (`CONTACT_EMAIL` in `.env`) |

## Setup

### Option A: let Claude Code set it up for you

There are no secrets in this project. `.env` only holds your email address and two optional
settings, so Claude Code can do the whole setup for you. Clone the repository and open Claude Code
in the folder:

```
git clone https://github.com/Emilda-06/dissertation-workflow.git
cd dissertation-workflow
claude
```

Then paste this prompt:

> Set up this workflow on my machine by following README.md and SETUP.md:
> 1. Install any missing system tools with winget (Python, Node.js, Git, draw.io, Zotero).
> 2. Create the Python venv in `.venv`, install `requirements.txt`, and run `npm install`.
> 3. Create a `tools\` folder and download the latest Windows builds of pandoc, a matching
>    pandoc-crossref, and the Zotero Better BibTeX `.xpi` from their GitHub releases.
> 4. Copy `.env.example` to `.env` and ask me for my email address for `CONTACT_EMAIL`.
> 5. Ask me for a short project name and my dissertation title, run
>    `scripts/project.py new <name> --title "<title>"`, then fill `projects/<name>/project.yaml` with
>    my name, student ID, programme, department, faculty, university, supervisor and chapter plan.
> 6. Tell me how to install Better BibTeX in Zotero, then run `scripts/doctor.py` and fix
>    anything that isn't `OK`.

Claude Code will ask for permission before installing anything. The only manual steps are
installing the Better BibTeX plugin inside Zotero (two clicks) and, if you want one, saving your
university's cover page as `projects\<name>\cover.docx`.

> A SessionStart hook starts Zotero each time Claude Code opens. Until the venv and Zotero are
> installed it shows an error at startup. You can ignore that during setup.

### Option B: set it up by hand

```bat
git clone https://github.com/Emilda-06/dissertation-workflow.git
cd dissertation-workflow

:: 1. Python and Node dependencies
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
npm install

:: 2. Your private settings and your first project
copy .env.example .env
.venv\Scripts\python scripts\project.py new my-thesis --title "My dissertation title" 
```

Then:

1. **`tools\`**: create the folder and put `pandoc.exe`, `pandoc-crossref.exe` and
   `zotero-better-bibtex.xpi` in it (links in the table above).
2. **`.env`**: set `CONTACT_EMAIL` to your own email address. See the comments in `.env.example`.
3. **`projects\my-thesis\project.yaml`**: fill in your details and chapter plan. In Zotero, create a
   collection with the name shown by `project.py new` (each dissertation uses its own collection).
4. **Zotero**: open Zotero, go to *Tools > Plugins*, install `tools\zotero-better-bibtex.xpi` and restart Zotero.
5. **Optional:**
   - `projects\my-thesis\cover.docx`: your university's cover page with `{{TITLE}}`, `{{STUDENT_NAME}}` and similar placeholders.
   - `projects\my-thesis\guidelines\`: department guidelines or chapter templates (any file names).
   - `projects\my-thesis\existing\`: earlier drafts, plus a `NOTES.md` saying what each file is.
   - `projects\my-thesis\feedback\`: supervisor feedback.
6. **Check:** `.venv\Scripts\python.exe scripts\doctor.py` (`--fix` installs the Python and Node
   packages and prints exact download steps for pandoc). Every required line should show `OK`.

**Coming from the single-project version?** Run `.venv\Scripts\python.exe scripts\project.py migrate <name>`.
It moves `config/project.yaml`, your documents, `output/` and `references/` into `projects/<name>/`
and starts its git history.

[SETUP.md](SETUP.md) has more detail on each step, including the full list of cover placeholders.

## Using it

- **Double-click `start.cmd`**, or run `claude "/dissertation"`. A menu opens:
  *Write a new chapter / Revise a chapter / Build full dissertation / Status, setup or switch project*.
- Or just say what you want in Claude Code. Shortcuts:

| Command | Does |
|---|---|
| `/dissertation new <n>` | write chapter n from scratch |
| `/dissertation edit <n> <change>` | revise chapter n (feedback typed, pasted or as a file path) |
| `/dissertation combine` | build the full dissertation in one document |
| `/dissertation status` | progress of every chapter and anything left to set up |
| `/dissertation project <name>` | switch to (or create) another dissertation |

Finished documents appear in `projects\<name>\output\chapters\chapter_<n>\docs\` and
`projects\<name>\output\dissertation\docs\`.
Don't edit the `.docx` files by hand. Ask for changes and a new version is built.

## Project layout

```
config/
  project.example.yaml   template for every project's project.yaml
  templates/             shared defaults: Word styles, Harvard/APA/IEEE CSL, crossref, Mermaid, matplotlib
projects/                your dissertations (git-ignored here; each has its own git repository)
  <name>/                project.yaml, cover, guidelines/, existing/, feedback/, requirements/,
                         templates/, output/, references/
scripts/                 pipeline tools (see CLAUDE.md)
tests/                   automated tests (python -m pytest)
.claude/                 the /dissertation skill and the SessionStart hook
tools/                   pandoc, pandoc-crossref, Better BibTeX (downloaded, git-ignored)
```

`CLAUDE.md` describes every script and the pipeline's rules in full; `docs/ROADMAP.md` explains the design.

## Development

```
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

The tests never touch your real projects (each runs in a temporary folder) and never call the
internet. Builds are tested end to end when pandoc and pandoc-crossref are in `tools\`.
GitHub Actions runs the tests on Windows and Linux.

## Privacy

Everything personal stays on your machine and is git-ignored:

- `.env`
- everything in `projects/` (settings, cover, guidelines, feedback, drafts, chapters, references)

Each project has its own local git repository. If you push one anywhere, use a **private** remote.
Don't push it here.
