"""Manage dissertation projects. Each lives in projects/<name>/ with its own git history:

  projects/<name>/
    config/   project.yaml, style.yaml, cover_template.docx, templates/, requirements/
    docs/     what you hand in, kept as given: cover/, guidelines/, past_work/, feedback/
    output/   chapters/, appendices/, dissertation/, references/

Give it your files and it puts each in place and sets it up:
  --cover F          kept in docs/cover/ and turned into config/cover_template.docx ({{PLACEHOLDERS}})
  --guidelines F|DIR kept in docs/guidelines/, scanned and mapped to chapters (any file names)
  --past-work F|DIR  kept in docs/past_work/ and listed in NOTES.md; finished chapters found in it
                     (one file per chapter, or a whole draft) are imported into output/chapters/
  --feedback F|DIR   kept in docs/feedback/

Usage:
  project.py new <name> --title "..." [--cover F] [--guidelines F ...] [--past-work F ...] [--feedback F ...]
                 [--from <project>] [--no-import]
  project.py setup <name> [same options]     create the project if needed, otherwise add to it
  project.py add [--cover F] [--guidelines F ...] [--past-work F ...] [--feedback F ...] [--no-import]
  project.py info                            what the active project has: settings, documents, chapters
  project.py list | use <name> | current
  project.py migrate [<name>]                move the old single-project layout (config/project.yaml) in
  project.py commit "<message>" | log [-n 15]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

from common import (ACTIVE_FILE, PROJECTS, ROOT, SHARED_CONFIG, SLUG_RE, Project, active_slug, active_source,
                    chapter_file, die, init_cli, legacy_layout, list_projects, load_config, project, project_title,
                    select_project, slugify)

PROJECT_GITIGNORE = """\
# Generated per project by the dissertation workflow
.build/
output/references/zotero.json
# downloaded PDFs can be large and are often copyright material; the extracted .txt files are kept
output/chapters/*/research/fulltext/*.pdf
~$*
*.tmp
"""

SUBDIRS = ("config/templates", "config/requirements", "docs/cover", "docs/guidelines", "docs/past_work",
           "docs/feedback", "output/chapters", "output/appendices", "output/dissertation/docs",
           "output/dissertation/front_matter", "output/references", ".build")
DOC_TYPES = {".docx", ".doc", ".pdf", ".md", ".txt", ".odt", ".rtf", ".png", ".jpg", ".jpeg", ".pptx", ".xlsx",
             ".csv"}
PERSONAL = ("title", "student_name", "student_id", "supervisor")


def git(p: Project, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(p.root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def init_repo(p: Project) -> None:
    (p.root / ".gitignore").write_text(PROJECT_GITIGNORE, encoding="utf-8")
    if not (p.root / ".git").exists():
        git(p, "init", "-q", check=True)
    if not git(p, "config", "user.name").stdout.strip():
        # fall back to a neutral identity only when the user has none configured globally
        git(p, "config", "user.name", "dissertation-workflow")
        git(p, "config", "user.email", "dissertation-workflow@localhost")


def scaffold(p: Project) -> None:
    for sub in SUBDIRS:
        (p.root / sub).mkdir(parents=True, exist_ok=True)
    notes = p.past_work / "NOTES.md"
    if not notes.exists():
        notes.write_text("# My earlier work\n\nWhat each file is, and what should be reused or ignored.\n\n"
                         "## Files\n", encoding="utf-8")


def commit(p: Project, message: str) -> str:
    if not (p.root / ".git").exists():
        init_repo(p)
    git(p, "add", "-A")
    r = git(p, "commit", "-q", "-m", message)
    if r.returncode != 0:
        if "nothing to commit" in (r.stdout + r.stderr):
            return "nothing to commit"
        die(f"git commit failed: {(r.stdout + r.stderr).strip()}")
    return git(p, "rev-parse", "--short", "HEAD").stdout.strip()


def set_active(slug: str) -> None:
    PROJECTS.mkdir(exist_ok=True)
    ACTIVE_FILE.write_text(slug + "\n", encoding="utf-8")


def check_slug(name: str) -> str:
    slug = name.strip().lower()
    if not SLUG_RE.match(slug):
        die(f"invalid project name '{name}': use lower-case letters, digits, '-' or '_' (max 64)")
    return slug


def write_yaml(path, cfg):
    header = ("# Dissertation settings for this project (see config/project.example.yaml for every option).\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------------- adding documents

def expand(paths: list[str] | None) -> list[Path]:
    """Files named directly, and the documents inside named folders (not recursive into hidden ones)."""
    out = []
    for raw in paths or []:
        src = Path(os.path.expandvars(raw.strip().strip('"'))).expanduser()
        if not src.exists():
            die(f"not found: {src}")
        if src.is_dir():
            out += sorted(f for f in src.rglob("*") if f.is_file() and f.suffix.lower() in DOC_TYPES
                          and not f.name.startswith(("~$", ".")) and not any(x.startswith(".") for x in f.parts))
        else:
            out.append(src)
    return out


def place(src: Path, folder: Path) -> Path:
    """Copy src into folder; a different file with the same name gets a numbered name."""
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / src.name
    if dst.exists():
        if dst.read_bytes() == src.read_bytes():
            return dst
        k = 2
        while (folder / f"{src.stem} ({k}){src.suffix}").exists():
            k += 1
        dst = folder / f"{src.stem} ({k}){src.suffix}"
    shutil.copy2(src, dst)
    return dst


def add_cover(p: Project, src: Path) -> str:
    import cover
    r = cover.make(src, quiet=True)
    cover.print_report(r)
    return f"cover {src.name}"


def add_guidelines(p: Project, files: list[Path]) -> str:
    for f in files:
        place(f, p.guidelines)
        print(f"guideline: {f.name} -> {p.rel(p.guidelines)}")
    import guidelines
    print()
    guidelines.scan(load_config())
    return f"{len(files)} guideline file(s)"


def docx_body(path: Path):
    from docx import Document
    doc = Document(str(path))
    return doc, list(doc.element.body.iterchildren())


def detect_chapters(path: Path, plan: dict[int, dict]) -> tuple[str, list[dict]]:
    """('chapters' | 'proposal' | 'other', parts). A part: {chapter, start, end, heading} in body-element
    indices of a .docx. One chapter per file, or a whole draft split at its chapter headings."""
    import guidelines
    from docx.text.paragraph import Paragraph
    if path.suffix.lower() != ".docx":
        return "other", []
    doc, body = docx_body(path)
    heads, refs_at = [], None
    for i, el in enumerate(body):
        if el.tag.rsplit("}", 1)[-1] != "p":
            continue
        para = Paragraph(el, doc)
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name if para.style is not None else ""
        level = int(m.group(1)) if (m := re.match(r"Heading (\d)", style)) else (1 if style == "Title" else None)
        entry = {"text": text, "level": level, "page": None}
        b = guidelines.chapter_boundary(entry)
        if b:
            heads.append((i, b[0], b[1], text))
        elif re.fullmatch(r"(references?|reference list|bibliography)", text, re.I) and (level or len(text) < 30):
            refs_at = i
    name = path.stem.replace("_", " ").replace("-", " ")
    first_text = " ".join(Paragraph(e, doc).text for e in body[:15] if e.tag.endswith("}p"))
    if not heads:
        m = re.search(r"\b(?:chapter|chap|ch)\s*(\d{1,2}|[ivx]{1,5})\b", name, re.I)
        n = guidelines.parse_number(m.group(1)) if m else None
        if n is None:
            t = guidelines.match_title(name, plan)
            n = t[0] if t and t[1] >= 0.85 else None
        if n:
            return "chapters", [{"chapter": n, "start": 0, "end": len(body), "heading": f"(whole file: {path.name})"}]
        if re.search(r"proposal", name + " " + first_text, re.I):
            return "proposal", []
        return "other", []
    parts = []
    for k, (i, num, rest, text) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else (refs_at if refs_at and refs_at > i else len(body))
        n = num if num in plan else None
        if n is None and rest:
            t = guidelines.match_title(rest, plan)
            n = t[0] if t else None
        if n:
            parts.append({"chapter": n, "start": i, "end": end, "heading": text, "refs": refs_at})
    return ("chapters" if parts else "other"), parts


def split_part(path: Path, part: dict, out: Path) -> Path:
    """A copy of the .docx that keeps only one chapter (plus the reference list, so citations resolve)."""
    doc, body = docx_body(path)
    keep = set(range(part["start"], part["end"]))
    if part.get("refs") is not None:
        keep |= set(range(part["refs"], len(body)))
    for i, el in enumerate(body):
        if i not in keep and not el.tag.endswith("}sectPr"):
            el.getparent().remove(el)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out


def import_chapter(p: Project, src: Path, n: int, label: str) -> bool:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "import_docx.py"), str(src), str(n),
                        "--project", p.slug, "--source-label", label], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "DISSERTATION_QUIET": "1"})
    for line in (r.stdout or "").splitlines():
        if line.strip().startswith(("Imported", "references linked", "review")):
            print(f"    {line.strip()}")
    if r.returncode != 0:
        print(f"    import failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.returncode == 0


def add_past_work(p: Project, files: list[Path], do_import: bool) -> str:
    cfg = load_config()
    plan = {k: v for k, v in (cfg.get("chapters") or {}).items() if isinstance(k, int)}
    notes = p.past_work / "NOTES.md"
    lines, imported = [], []
    for f in files:
        dst = place(f, p.past_work)
        kind, parts = detect_chapters(dst, plan)
        what = {"proposal": "proposal", "other": "earlier work"}.get(kind, "")
        if kind == "chapters":
            what = "chapter(s) " + ", ".join(str(x["chapter"]) for x in parts)
        print(f"past work: {f.name} -> {p.rel(p.past_work)}  [{what}]")
        status = []
        for part in parts:
            n = part["chapter"]
            if chapter_file(n).exists():
                status.append(f"chapter {n}: already in the workflow (not overwritten)")
                print(f"    chapter {n}: already in the workflow - left as it is")
                continue
            if not do_import:
                status.append(f"chapter {n}: found (import with project.py add --past-work ... )")
                continue
            whole = part["heading"].startswith("(whole file")
            src = dst if whole else split_part(dst, part, p.build / "import" / f"{dst.stem}_chapter{n}.docx")
            print(f"    importing chapter {n} ({part['heading'][:60]}) ...")
            label = f"docs/past_work/{dst.name}" + ("" if whole else f" ({part['heading'][:60]})")
            if import_chapter(p, src, n, label):
                imported.append(n)
                status.append(f"chapter {n}: imported into output/chapters")
        lines.append(f"- `{dst.name}` - {what}; added {date.today():%Y-%m-%d}"
                     + (f" ({'; '.join(status)})" if status else ""))
        if kind == "proposal" and not str((cfg.get("project") or {}).get("current_topic_source", "")).startswith(
                "docs/past_work"):
            set_topic_source(p, f"docs/past_work/{dst.name}", only_if_default=True)
    with notes.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return f"{len(files)} past-work file(s)" + (f", imported chapter(s) {', '.join(map(str, imported))}"
                                                if imported else "")


def set_topic_source(p: Project, rel: str, only_if_default: bool) -> None:
    cfg = yaml.safe_load(p.config_file.read_text(encoding="utf-8")) or {}
    cur = (cfg.get("project") or {}).get("current_topic_source", "")
    ch1 = p.chapters / "chapter_one" / "chapter.md"
    if only_if_default and cur and not (cur.endswith("chapter_one/chapter.md") and not ch1.exists()):
        return
    cfg.setdefault("project", {})["current_topic_source"] = rel
    write_yaml(p.config_file, cfg)
    print(f"    research problem/aim/objectives will be read from {rel} (until chapter 1 exists)")


def add_feedback(p: Project, files: list[Path]) -> str:
    for f in files:
        place(f, p.feedback)
        print(f"feedback: {f.name} -> {p.rel(p.feedback)}")
    return f"{len(files)} feedback file(s)"


def add_documents(p: Project, a) -> list[str]:
    done = []
    if getattr(a, "cover", None):
        src = expand([a.cover])
        if len(src) != 1:
            die("--cover takes one file")
        done.append(add_cover(p, src[0]))
        print()
    if getattr(a, "guidelines", None):
        done.append(add_guidelines(p, expand(a.guidelines)))
        print()
    if getattr(a, "past_work", None):
        done.append(add_past_work(p, expand(a.past_work), not a.no_import))
        print()
    if getattr(a, "feedback", None):
        done.append(add_feedback(p, expand(a.feedback)))
    return done


# ---------------------------------------------------------------- commands

def create(slug: str, a) -> Project:
    p = Project(PROJECTS / slug)
    if p.root.exists() and any(p.root.iterdir()):
        die(f"project '{slug}' already exists (use: project.py add ... --project {slug})")
    scaffold(p)
    if a.from_project:
        src = Project(PROJECTS / a.from_project)
        if not src.config_file.exists():
            die(f"project '{a.from_project}' not found")
        cfg = yaml.safe_load(src.config_file.read_text(encoding="utf-8")) or {}
        example = (yaml.safe_load((SHARED_CONFIG / "project.example.yaml").read_text(encoding="utf-8")) or {})
        for k in PERSONAL:                       # department settings are shared; personal details are not
            cfg.setdefault("project", {})[k] = (example.get("project") or {}).get(k, "")
        for sub in ("config/templates", "config/requirements", "docs/guidelines", "docs/cover"):
            if (src.root / sub).exists():
                shutil.copytree(src.root / sub, p.root / sub, dirs_exist_ok=True)
        if src.cover_template.exists():
            shutil.copy2(src.cover_template, p.cover_template)
    else:
        cfg = yaml.safe_load((SHARED_CONFIG / "project.example.yaml").read_text(encoding="utf-8")) or {}
    cfg.setdefault("project", {})
    if a.title:
        cfg["project"]["title"] = a.title
    cfg.setdefault("zotero", {})["collection"] = a.zotero_collection or slug
    write_yaml(p.config_file, cfg)
    init_repo(p)
    commit(p, "project created")
    set_active(slug)
    select_project(slug)
    print(f"created project '{slug}' in {p.rel(p.root)} (now the active project)")
    return p


def cmd_new(a):
    slug = check_slug(a.name)
    p = create(slug, a)
    finish_setup(p, a, "set up")


def cmd_setup(a):
    slug = check_slug(a.name)
    if slug in list_projects():
        select_project(slug)
        set_active(slug)
        p = project()
        print(f"project '{slug}' exists - adding to it")
    else:
        p = create(slug, a)
    finish_setup(p, a, "set up")


def cmd_add(a):
    p = project()
    if not any(getattr(a, k, None) for k in ("cover", "guidelines", "past_work", "feedback")):
        die("nothing to add: give --cover, --guidelines, --past-work or --feedback")
    finish_setup(p, a, "added")


def finish_setup(p: Project, a, verb: str) -> None:
    done = add_documents(p, a)
    if done:
        print(f"\n[{p.slug}] {verb}: {'; '.join(done)} (git: {commit(p, verb + ': ' + '; '.join(done))})")
    print()
    info(p)


def count(folder: Path, pattern="*") -> list[Path]:
    return sorted(f for f in folder.glob(pattern) if f.is_file() and f.name not in ("NOTES.md", ".gitkeep")) \
        if folder.exists() else []


def info(p: Project) -> None:
    cfg = load_config()
    pj = cfg.get("project") or {}
    missing = [k for k in ("title", "student_name", "student_id", "supervisor", "university")
               if str(pj.get(k) or "").startswith("Your ") or not pj.get(k)]
    print(f"Project '{p.slug}': {pj.get('title', '')}")
    print(f"  folder        {p.rel(p.root)}")
    print(f"  details       {pj.get('student_name', '')} ({pj.get('student_id', '')}), {pj.get('university', '')}"
          + (f"   still to fill in config/project.yaml: {', '.join(missing)}" if missing else ""))
    print(f"  citation      {(cfg.get('references') or {}).get('style', 'harvard')}; Zotero collection "
          f"'{(cfg.get('zotero') or {}).get('collection', '')}'")
    cov = count(p.cover_dir)
    print("  cover         " + (f"template {p.rel(p.cover_template)} (from {cov[0].name if cov else '?'})"
                                if p.cover_template.exists() else
                                (f"{cov[0].name} (placed as a picture)" if cov else "none (add --cover <file>)")))
    g = count(p.guidelines)
    spec = "approved" if p.spec.exists() and "approved: 20" in p.spec.read_text(encoding="utf-8") else \
        ("not approved" if p.spec.exists() else "no requirements yet")
    print(f"  guidelines    {len(g)} file(s){': ' + ', '.join(f.name for f in g) if g else ' (add --guidelines)'}"
          + (f"; requirements {spec}" if g else ""))
    w = count(p.past_work)
    print(f"  past work     {len(w)} file(s){': ' + ', '.join(f.name for f in w) if w else ''}")
    print(f"  feedback      {len(count(p.feedback))} file(s)")
    print(f"  style         {'config/style.yaml' if p.style_file.exists() else 'not chosen yet (style.py init)'}")
    from common import WORD_NUMBERS
    chs = sorted((d.name for d in p.chapters.glob("chapter_*") if (d / "chapter.md").exists()),
                 key=lambda x: WORD_NUMBERS.get(x.removeprefix("chapter_"), 99))
    print(f"  chapters      {len(chs)}/{len(cfg.get('chapters') or {})} written"
          + (f": {', '.join(chs)}" if chs else ""))


def cmd_info(a):
    info(project())


def cmd_list(a):
    act, how = active_source()
    found = list_projects()
    if not found:
        print("no projects yet - create one with: project.py new <name> --title \"...\" [--cover F --guidelines F "
              "--past-work F]")
        if legacy_layout():
            print("(an old single-project setup was found in config/ - move it with: project.py migrate <name>)")
        return
    print(f"  {'PROJECT':<24} {'CHAPTERS':<9} {'LAST CHANGE':<17} TITLE")
    for s_ in found:
        root = PROJECTS / s_
        f = root / "config" / "project.yaml"
        cfg = yaml.safe_load((f if f.exists() else root / "project.yaml").read_text(encoding="utf-8")) or {}
        title = (cfg.get("project") or {}).get("title", "")
        written = len(list((root / "output" / "chapters").glob("chapter_*/chapter.md")))
        planned = len(cfg.get("chapters") or {})
        last = git(Project(root), "log", "-1", "--format=%ad", "--date=format:%Y-%m-%d %H:%M").stdout.strip()
        print(f"{'*' if s_ == act else ' '} {s_:<24} {f'{written}/{planned}':<9} {last or '-':<17} {title}")
    if act:
        print(f"\n* = active project ({how}). Switch with: project.py use <name>")
    else:
        print("\nno active project: choose one with project.py use <name>")


def cmd_use(a):
    slug = check_slug(a.name)
    if slug not in list_projects():
        die(f"no project '{slug}'. Known: {', '.join(list_projects()) or 'none'}")
    before = ACTIVE_FILE.read_text(encoding="utf-8").strip() if ACTIVE_FILE.exists() else ""
    set_active(slug)
    title = project_title(slug)
    if before and before != slug:
        print(f"switched active project: {before} -> {slug}" + (f" ({title})" if title else ""))
    else:
        print(f"active project: {slug}" + (f" ({title})" if title else ""))
    if os.environ.get("DISSERTATION_PROJECT") and os.environ["DISSERTATION_PROJECT"] != slug:
        print(f"note: DISSERTATION_PROJECT={os.environ['DISSERTATION_PROJECT']} is set in this shell and still "
              "wins over the active project")


def cmd_current(a):
    s = active_slug()
    if not s:
        die("no active project (project.py list / use <name>)")
    print(s)


LEGACY_MOVES = [
    # (old path relative to ROOT, new path relative to the project root)
    ("config/project.yaml", "config/project.yaml"),
    ("config/cover.docx", "docs/cover/cover.docx"),
    ("config/cover.pdf", "docs/cover/cover.pdf"),
    ("config/guidelines", "docs/guidelines"),
    ("config/existing", "docs/past_work"),
    ("config/feedback", "docs/feedback"),
    ("output/chapters", "output/chapters"),
    ("output/dissertation/docs", "output/dissertation/docs"),
    ("output/dissertation/front_matter", "output/dissertation/front_matter"),
    ("references", "output/references"),
]


def cmd_migrate(a):
    if not legacy_layout():
        die("nothing to migrate: config/project.yaml does not exist")
    cfg = yaml.safe_load((SHARED_CONFIG / "project.yaml").read_text(encoding="utf-8")) or {}
    slug = check_slug(a.name or slugify((cfg.get("project") or {}).get("title", "dissertation")))
    p = Project(PROJECTS / slug)
    if p.root.exists() and any(p.root.iterdir()):
        die(f"{p.root} already exists; pass another name")
    scaffold(p)
    moved = []
    for old, new in LEGACY_MOVES:
        src, dst = ROOT / old, p.root / new
        if not src.exists():
            continue
        if src.is_dir():
            for item in src.iterdir():
                if item.name == ".gitkeep":
                    continue
                dst.mkdir(parents=True, exist_ok=True)
                target = dst / item.name
                if target.exists() and target.is_file():
                    target.unlink()                      # scaffold files (NOTES.md) give way to the user's
                shutil.move(str(item), str(target))
                moved.append(f"{old}/{item.name}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(old)
    for old, _ in LEGACY_MOVES:                        # remove legacy folders that are now empty
        src = ROOT / old
        if src.is_dir() and not any(x.name != ".gitkeep" for x in src.iterdir()):
            shutil.rmtree(src, ignore_errors=True)
    if (p.cover_dir / "cover.docx").exists():
        shutil.copy2(p.cover_dir / "cover.docx", p.cover_template)      # it already had placeholders
    cfg = yaml.safe_load(p.config_file.read_text(encoding="utf-8")) or {}
    cfg.setdefault("zotero", {}).setdefault("collection", slug)
    write_yaml(p.config_file, cfg)
    if (ROOT / ".build").exists():
        shutil.rmtree(ROOT / ".build", ignore_errors=True)
    init_repo(p)
    sha = commit(p, "imported from the single-project layout")
    set_active(slug)
    print(f"migrated {len(moved)} item(s) into {p.rel(p.root)} (git: {sha}); active project: {slug}")
    for m in moved:
        print(f"  {m}")


def cmd_commit(a):
    p = project()
    if not (p.root / ".git").exists():
        init_repo(p)
    print(f"[{p.slug}] {commit(p, a.message)}")


def cmd_log(a):
    p = project()
    r = git(p, "log", f"-{a.n}", "--format=%h %ad %s", "--date=format:%Y-%m-%d %H:%M")
    print(r.stdout.strip() or "no history yet")


def add_doc_args(sp, creating: bool) -> None:
    sp.add_argument("--cover", help="cover page (.docx, .doc, .pdf or image)")
    sp.add_argument("--guidelines", nargs="+", metavar="F", help="guideline files or folders")
    sp.add_argument("--past-work", nargs="+", metavar="F", help="earlier proposal / chapters / drafts")
    sp.add_argument("--feedback", nargs="+", metavar="F", help="supervisor feedback files")
    sp.add_argument("--no-import", action="store_true", help="do not import chapters found in past work")
    if creating:
        sp.add_argument("--title")
        sp.add_argument("--from", dest="from_project", help="copy department material from another project")
        sp.add_argument("--zotero-collection")


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new"); n.add_argument("name"); add_doc_args(n, True)
    s = sub.add_parser("setup"); s.add_argument("name"); add_doc_args(s, True)
    ad = sub.add_parser("add"); add_doc_args(ad, False)
    sub.add_parser("info")
    sub.add_parser("list")
    u = sub.add_parser("use"); u.add_argument("name")
    sub.add_parser("current")
    m = sub.add_parser("migrate"); m.add_argument("name", nargs="?")
    c = sub.add_parser("commit"); c.add_argument("message")
    lg = sub.add_parser("log"); lg.add_argument("-n", type=int, default=15)
    a = ap.parse_args()
    {"new": cmd_new, "setup": cmd_setup, "add": cmd_add, "info": cmd_info, "list": cmd_list, "use": cmd_use,
     "current": cmd_current, "migrate": cmd_migrate, "commit": cmd_commit, "log": cmd_log}[a.cmd](a)


if __name__ == "__main__":
    main()
