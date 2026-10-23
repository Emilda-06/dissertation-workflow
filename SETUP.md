# Setting up the workflow

This repository contains only the pipeline. Your own details, documents, chapters and references
are created locally and are git-ignored, so nothing personal is ever committed.
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
| Microsoft Word | needed for the final build step (fields, table of contents, cover) |
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

## 2. Your details: `config\project.yaml`

```
copy config\project.example.yaml config\project.yaml
```

Fill in your title, name, student ID, programme, department, university, supervisor and chapter plan.
If your department gives chapter guidelines, put them in `config\guidelines\` and name them in the
`guideline:` field of each chapter.

## 3. Private settings: `.env`

```
copy .env.example .env
```

Set `CONTACT_EMAIL` to your own email address. Unpaywall needs it to find free full texts, and OpenAlex
and Crossref use it for faster, more reliable access. It is sent only to those three services.

## 4. Cover page: `config\cover.docx` (optional)

Make your university's cover page in Word and save it as `config\cover.docx`. Use these placeholders;
they are filled from `config\project.yaml` on every build:
`{{TITLE}}`, `{{STUDENT_NAME}}`, `{{STUDENT_ID}}`, `{{PROGRAMME}}`, `{{SUPERVISOR}}`, `{{DEPARTMENT}}`,
`{{FACULTY}}`, `{{UNIVERSITY}}`, `{{DOCUMENT}}`, `{{DATE}}` (month and year of the build).
Without a cover, documents are built without one.

## 5. Your existing work (optional)

- `config\existing\`: an earlier proposal or draft chapters (.docx). Add a short `NOTES.md` saying
  what each file is. The assistant can import a Word chapter into the workflow.
- `config\feedback\`: supervisor feedback files (feedback can also be pasted in chat).

## 6. Zotero

1. Open Zotero, go to **Tools > Plugins** and install `tools\zotero-better-bibtex.xpi`.
2. In **Settings > Advanced**, make sure "Allow other applications on this computer to communicate
   with Zotero" is enabled.

The pipeline talks to Zotero directly:
- verified sources are **pushed** into Zotero (into whichever collection is selected in Zotero);
- your Zotero library is **pulled** at every build, so anything you save in Zotero
  (e.g. with the Zotero Connector browser extension) becomes citable once it is verified.

**Rule:** Zotero must be open while the workflow runs. It is started automatically when the
assistant opens, and before any research, reference or build step. No Zotero account is required.

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
- Finished documents: `output\chapters\chapter_<n>\docs\chapter_<n>_vX.docx` and
  `output\dissertation\docs\dissertation_vX.docx`. Never edit these by hand; ask for changes instead,
  and a new version is built.
