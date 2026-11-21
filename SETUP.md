# Setting up the workflow

This repository contains only the pipeline. Your dissertations live in `projects\<name>\`, each with
its own local git history; nothing personal is ever committed to this repository.
Run `.venv\Scripts\python.exe scripts\doctor.py` at any time to see what's still missing
(`OK` = done, `--` = still to do). Or open the assistant and choose **Status and setup**.

## 1. Install the tools (Windows)

| Tool | How |
|---|---|
| Python 3.11+ | `winget install Python.Python.3.12` |
| Node.js | `winget install OpenJS.NodeJS.LTS` |
| Git | `winget install Git.Git` |
| draw.io desktop | `winget install JGraph.Draw` |
| Zotero 7 | `winget install DigitalScholar.Zotero` |
| Microsoft Word | optional but recommended (cover, contents, page numbers, PDF/A, tracked changes) |
| LibreOffice | optional: PDFs on machines without Word |
| Claude Code | https://claude.com/claude-code |

Then, in this folder:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
npm install
```

Create a `tools\` folder and put these in it (it is git-ignored):

- `pandoc.exe` from https://github.com/jgm/pandoc/releases (Windows zip)
- `pandoc-crossref.exe` from https://github.com/lierdakil/pandoc-crossref/releases (a build matching your pandoc version)
- `zotero-better-bibtex.xpi` from https://github.com/retorquere/zotero-better-bibtex/releases

## 2. Your project: set it up from your own files

```
.venv\Scripts\python scripts\project.py new my-thesis --title "My dissertation title" ^
    --cover "path\to\cover page.docx" --guidelines "path\to\handbook or folder" ^
    --past-work "path\to\proposal and drafts" --feedback "path\to\supervisor comments.docx"
```

Every option is optional and file names don't matter. This creates `projects\my-thesis\` (its own git
history) and makes it the active project:

```
projects\my-thesis\
  config\   project.yaml, style.yaml, cover_template.docx, templates\, requirements\
  docs\     your files as given: cover\, guidelines\, past_work\ (+ NOTES.md), feedback\
  output\   chapters\, appendices\, dissertation\, references\
```

- **Cover:** kept in `docs\cover\` and turned into `config\cover_template.docx`: your title, name, student
  number, supervisor, programme, department, faculty, university and date become placeholders that fill
  themselves in on every build. Values found on the cover fill `config\project.yaml`. A PDF cover is
  rebuilt as a clean page (a .docx cover keeps the original design exactly); an image is used as-is.
- **Guidelines:** scanned and mapped to your chapters (see 2b).
- **Past work:** listed in `docs\past_work\NOTES.md`; a proposal is used for your aim and objectives;
  finished chapters (one per file, or a whole draft) are imported into `output\chapters\` - never
  overwriting a chapter already there.

Add more at any time: `project.py add --cover ... --guidelines ... --past-work ... --feedback ...`;
see what a project has with `project.py info`. Then check `config\project.yaml`: name, student ID, programme, department, university, supervisor, chapter plan and
citation style (`harvard`, `apa`, `ieee` or a `.csl` file in the project's `templates\`).

More dissertations: run `project.py new <another-name>` (add `--from my-thesis` to copy the department
guidelines, cover and templates). Switch with `project.py use <name>`, see them all with
`project.py list`. Every script also accepts `--project <name>`.

Moving from the old single-project layout (`config\project.yaml`)? Run `project.py migrate <name>`.

## 2b. Department guidelines and templates (optional)

Give the files your department gives you (a handbook, chapter templates, marking guides) with
`--guidelines` (files or a folder); they are kept in `docs\guidelines\`. **Any file names work**: one file
per chapter, or one handbook for all chapters. They are scanned straight away: the chapter parts are
found and mapped to your chapter plan (it asks you only when unsure), then each requirement is recorded
with a quote from the guideline in `config\requirements\spec.yaml` for you to approve. A Word file that is only a formatting
template (styles, little text) is detected and used for the document's styles.

## 3. Private settings: `.env`

```
copy .env.example .env
```

Set `CONTACT_EMAIL` to your own email address. Unpaywall needs it to find free full texts, and OpenAlex
and Crossref use it for faster, more reliable access. It is sent only to those three services.

## 4. Cover page

Give your cover with `--cover` (step 2); it is turned into a template automatically. To adjust it, open
`config\cover_template.docx` in Word. These placeholders can be used anywhere (text, tables, text boxes,
headers); they are filled from `config\project.yaml` on every build:
`{{TITLE}}`, `{{STUDENT_NAME}}`, `{{STUDENT_ID}}`, `{{PROGRAMME}}`, `{{SUPERVISOR}}`, `{{DEPARTMENT}}`,
`{{FACULTY}}`, `{{UNIVERSITY}}`, `{{DOCUMENT}}`, `{{DATE}}` (month and year of the build), `{{YEAR}}`,
and any other field under `project:` in upper case.
Without a cover, documents are built without one.

## 5. Your existing work (optional)

Give it with `--past-work` (step 2) or later with `project.py add --past-work <files or folder>`:
a proposal, finished chapters (one per file) or a whole draft. Everything is kept in
`docs\past_work\` and listed in its `NOTES.md` (add a line saying what to reuse or ignore); finished
chapters are imported into the workflow. Supervisor feedback goes in with `--feedback` (or paste it in
chat).

## 6. Zotero

1. Open Zotero, go to **Tools > Plugins** and install `tools\zotero-better-bibtex.xpi`.
2. In **Settings > Advanced**, make sure "Allow other applications on this computer to communicate
   with Zotero" is enabled.

The pipeline talks to Zotero directly:
- each project uses **its own Zotero collection** (`zotero.collection` in project.yaml, set to the
  project name by `project.py new`). Create that collection in Zotero;
- verified sources are **pushed** into that collection (the pipeline refuses, and writes an import
  file instead, if a different collection is selected in the Zotero window);
- only that collection is **pulled** at every build, so anything you save into it (e.g. with the Zotero
  Connector) becomes citable once it is verified. Other projects' items never leak in.

Zotero is started automatically when the assistant opens and before runs and builds. A project that
does not use Zotero can set `zotero.enabled: false`. No Zotero account is required.

## 7. Check

Run `.venv\Scripts\python.exe scripts\doctor.py`. All lines should show `OK`.

## Accounts summary

| Service | Account? | Cost |
|---|---|---|
| Claude (Claude Code) | yes | your plan |
| Unpaywall / OpenAlex / Crossref | no account, email only | free |
| Semantic Scholar | no account or key (used anonymously) | free |
| Zotero | optional (only for cloud backup or sync) | free |
| GitHub | not needed (Git works locally) | |

## Using it

- **Double-click `start.cmd`** in this folder. Claude Code opens with a menu:
  *Write a new chapter / Revise a chapter / Build full dissertation / Status and setup*.
- Or open Claude Code in this folder and just say what you want ("my supervisor says the
  problem statement is vague"). It works out the rest.
- Finished documents: `projects\<name>\output\chapters\chapter_<n>\docs\chapter_<n>_vX.docx` and
  `projects\<name>\output\dissertation\docs\dissertation_vX.docx`. Never edit these by hand; ask for changes instead,
  and a new version is built.
