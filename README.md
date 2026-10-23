# Dissertation workflow

A [Claude Code](https://claude.com/claude-code) pipeline for writing a Computer Science dissertation.
Chapters are written in Markdown, backed by **verified, real sources**, and built into formatted
Word documents with a cover page, table of contents, numbered figures and tables, and a Harvard
reference list.

You talk to it in plain language ("write chapter 2", "my supervisor says the problem statement is
vague") or pick from a menu. It plans the chapter, searches the literature, verifies every
reference, writes, draws diagrams, runs a quality check and builds a new numbered `.docx` version.

## What it does

- **Research:** searches OpenAlex, Semantic Scholar and Crossref, and downloads legal
  open-access full texts through Unpaywall.
- **References you can trust:** sources are added by DOI, so the metadata comes from the DOI registry and is never typed from memory.
  Each one is checked against Crossref or OpenAlex. Citations are formatted in Harvard (Cite Them Right) style
  and synced with your Zotero library.
- **Diagrams:** Mermaid, draw.io and matplotlib sources are rendered to 300 dpi PNG.
- **Quality gate:** `check.py` checks citations, cross-references, images, headings and the
  recency of sources before every build.
- **Word output:** pandoc plus pandoc-crossref, then Microsoft Word fills in the cover,
  table of contents, list of figures and list of tables. Every build is a new version (`_v1`, `_v2`, ...).
- **Revisions:** supervisor feedback (typed, pasted, a file, or Word comments) is applied and logged,
  and a "changes made" document can be produced for the supervisor.
- **Your rules:** the pipeline never invents sources, data or results. Missing data is marked
  `TODO-DATA`.

## Requirements

Built and tested on **Windows 10/11**. Building the final document needs Microsoft Word.

### System tools

| Tool | Version tested | Used for | Install |
|---|---|---|---|
| [Claude Code](https://claude.com/claude-code) | latest | runs the pipeline (the `/dissertation` skill) | see website |
| Python | 3.12+ (tested 3.14) | all pipeline scripts | `winget install Python.Python.3.12` |
| Node.js | 20+ (tested 24) | Mermaid diagram rendering | `winget install OpenJS.NodeJS.LTS` |
| Git | any | version history before and after each run | `winget install Git.Git` |
| [pandoc](https://github.com/jgm/pandoc/releases) | 3.12 | Markdown to Word conversion | put `pandoc.exe` in `tools\` |
| [pandoc-crossref](https://github.com/lierdakil/pandoc-crossref/releases) | 0.3.26 (must match your pandoc) | figure, table and section numbering | put `pandoc-crossref.exe` in `tools\` |
| [draw.io desktop](https://www.drawio.com/) | any | rendering `.drawio` diagrams | `winget install JGraph.Draw` |
| [Zotero 7](https://www.zotero.org/) | 7.x | reference library (must be open while the workflow runs) | `winget install DigitalScholar.Zotero` |
| [Better BibTeX for Zotero](https://github.com/retorquere/zotero-better-bibtex/releases) | latest | lets the pipeline talk to Zotero | Zotero > Tools > Plugins > install the `.xpi` |
| Microsoft Word | 2016+ | final document: fields, table of contents, cover | Microsoft 365 / Office |

### Python packages (`requirements.txt`)

| Package | Tested | Used for |
|---|---|---|
| `python-docx` | 1.2.0 | reading and writing Word files (cover, template, import) |
| `pyyaml` | 6.0.3 | reading `config/project.yaml` |
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
> 5. Copy `config/project.example.yaml` to `config/project.yaml` and ask me for my dissertation
>    title, name, student ID, programme, department, faculty, university, supervisor and chapter plan.
> 6. Tell me how to install Better BibTeX in Zotero, then run `scripts/doctor.py` and fix
>    anything that isn't `OK`.

Claude Code will ask for permission before installing anything. The only manual steps are
installing the Better BibTeX plugin inside Zotero (two clicks) and, if you want one, saving your
university's cover page as `config\cover.docx`.

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

:: 2. Your private settings and your project details
copy .env.example .env
copy config\project.example.yaml config\project.yaml
```

Then:

1. **`tools\`**: create the folder and put `pandoc.exe`, `pandoc-crossref.exe` and
   `zotero-better-bibtex.xpi` in it (links in the table above).
2. **`.env`**: set `CONTACT_EMAIL` to your own email address. See the comments in `.env.example`.
3. **`config\project.yaml`**: fill in your title, details and chapter plan.
4. **Zotero**: open Zotero, go to *Tools > Plugins*, install `tools\zotero-better-bibtex.xpi` and restart Zotero.
5. **Optional:**
   - `config\cover.docx`: your university's cover page with `{{TITLE}}`, `{{STUDENT_NAME}}` and similar placeholders.
   - `config\guidelines\`: department chapter guidelines.
   - `config\existing\`: earlier drafts, plus a `NOTES.md` saying what each file is.
   - `config\feedback\`: supervisor feedback.
6. **Check:** `.venv\Scripts\python.exe scripts\doctor.py`. Every line should show `OK`.

[SETUP.md](SETUP.md) has more detail on each step, including the full list of cover placeholders.

## Using it

- **Double-click `start.cmd`**, or run `claude "/dissertation"`. A menu opens:
  *Write a new chapter / Revise a chapter / Build full dissertation / Status and setup*.
- Or just say what you want in Claude Code. Shortcuts:

| Command | Does |
|---|---|
| `/dissertation new <n>` | write chapter n from scratch |
| `/dissertation edit <n> <change>` | revise chapter n (feedback typed, pasted or as a file path) |
| `/dissertation combine` | build the full dissertation in one document |
| `/dissertation status` | progress of every chapter and anything left to set up |

Finished documents appear in `output\chapters\chapter_<n>\docs\` and `output\dissertation\docs\`.
Don't edit the `.docx` files by hand. Ask for changes and a new version is built.

## Project layout

```
config/
  project.example.yaml   template -> copy to project.yaml (your details, chapter plan, formatting)
  templates/             Word reference style, Harvard CSL, crossref, Mermaid and matplotlib styles
  guidelines/ existing/ feedback/   your own documents (git-ignored)
output/                  generated chapters, diagrams, research notes and Word builds (git-ignored)
references/              your verified reference library (git-ignored)
scripts/                 pipeline tools: research, refs, diagrams, check, build, import, doctor
.claude/                 the /dissertation skill and the Zotero SessionStart hook
tools/                   pandoc, pandoc-crossref, Better BibTeX (downloaded, git-ignored)
```

`CLAUDE.md` describes every script and the pipeline's rules in full.

## Privacy

Everything personal stays on your machine and is git-ignored:

- `.env`
- `config/project.yaml`
- your cover page, guidelines, feedback and earlier drafts
- everything in `output/` and `references/`

If you keep your own dissertation under git, use a **private** repository for it. Don't push it here.
