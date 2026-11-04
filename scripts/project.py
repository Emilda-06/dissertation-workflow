"""Manage dissertation projects. Each one lives in projects/<name>/ with its own git history.

Usage:
  project.py new <name> [--title "..."] [--from <existing-project>]   create a project (and make it active)
  project.py list                                                     all projects (* = active)
  project.py use <name>                                               make a project active
  project.py current                                                  print the active project
  project.py migrate [<name>]                                         move the old single-project layout in
  project.py commit "<message>"                                       snapshot the active project (git)
  project.py log [-n 15]                                              recent snapshots
"""
from __future__ import annotations

import argparse
import shutil
import subprocess

import yaml

from common import (ACTIVE_FILE, PROJECTS, ROOT, SHARED_CONFIG, SLUG_RE, Project, active_slug, die, init_cli,
                    legacy_layout, list_projects, project, slugify)

PROJECT_GITIGNORE = """\
# Generated per project by the dissertation workflow
.build/
references/zotero.json
# downloaded PDFs can be large and are often copyright material; the extracted .txt files are kept
output/chapters/*/research/fulltext/*.pdf
~$*
*.tmp
"""

SUBDIRS = ("guidelines", "existing", "feedback", "templates", "output/chapters", "output/appendices",
           "output/dissertation/docs", "output/dissertation/front_matter", "references", "requirements", ".build")


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
    (p.existing / "NOTES.md").exists() or (p.existing / "NOTES.md").write_text(
        "# Notes about my earlier work\n\nWhat is in this folder and what should be reused or ignored.\n",
        encoding="utf-8")


def commit(p: Project, message: str) -> str:
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


def cmd_new(args):
    slug = check_slug(args.name)
    p = Project(PROJECTS / slug)
    if p.root.exists() and any(p.root.iterdir()):
        die(f"{p.root} already exists")
    scaffold(p)
    if args.from_project:
        src = Project(PROJECTS / args.from_project)
        if not src.config_file.exists():
            die(f"project '{args.from_project}' not found")
        cfg = yaml.safe_load(src.config_file.read_text(encoding="utf-8")) or {}
        for d in ("templates", "guidelines"):            # department material is often shared
            if (src.root / d).exists():
                shutil.copytree(src.root / d, p.root / d, dirs_exist_ok=True)
        for f in ("cover.docx", "cover.pdf"):
            if (src.root / f).exists():
                shutil.copy2(src.root / f, p.root / f)
    else:
        cfg = yaml.safe_load((SHARED_CONFIG / "project.example.yaml").read_text(encoding="utf-8")) or {}
    cfg.setdefault("project", {})
    if args.title:
        cfg["project"]["title"] = args.title
    cfg.setdefault("zotero", {})["collection"] = args.zotero_collection or slug
    write_yaml(p.config_file, cfg)
    init_repo(p)
    print(f"created {p.rel(p.root)}  (git: {commit(p, 'project created')})")
    set_active(slug)
    print(f"active project: {slug}")
    print(f"next: fill in {p.rel(p.config_file)}; in Zotero create a collection named "
          f"'{cfg['zotero']['collection']}' for this dissertation's sources.")


def write_yaml(path, cfg):
    header = ("# Dissertation settings for this project (see config/project.example.yaml for every option).\n")
    path.write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")


def cmd_list(args):
    act = active_slug()
    found = list_projects()
    if not found:
        print("no projects yet - create one with: project.py new <name> --title \"...\"")
        if legacy_layout():
            print("(an old single-project setup was found in config/ - move it with: project.py migrate <name>)")
        return
    for s in found:
        cfg = yaml.safe_load((PROJECTS / s / "project.yaml").read_text(encoding="utf-8")) or {}
        title = (cfg.get("project") or {}).get("title", "")
        print(f"{'*' if s == act else ' '} {s:<24} {title}")


def cmd_use(args):
    slug = check_slug(args.name)
    if slug not in list_projects():
        die(f"no project '{slug}'. Known: {', '.join(list_projects()) or 'none'}")
    set_active(slug)
    print(f"active project: {slug}")


def cmd_current(args):
    s = active_slug()
    if not s:
        die("no active project (project.py list / use <name>)")
    print(s)


LEGACY_MOVES = [
    # (old path relative to ROOT, new path relative to the project root)
    ("config/project.yaml", "project.yaml"),
    ("config/cover.docx", "cover.docx"),
    ("config/cover.pdf", "cover.pdf"),
    ("config/guidelines", "guidelines"),
    ("config/existing", "existing"),
    ("config/feedback", "feedback"),
    ("output/chapters", "output/chapters"),
    ("output/dissertation/docs", "output/dissertation/docs"),
    ("output/dissertation/front_matter", "output/dissertation/front_matter"),
    ("references", "references"),
]


def cmd_migrate(args):
    if not legacy_layout():
        die("nothing to migrate: config/project.yaml does not exist")
    cfg = yaml.safe_load((SHARED_CONFIG / "project.yaml").read_text(encoding="utf-8")) or {}
    slug = check_slug(args.name or slugify((cfg.get("project") or {}).get("title", "dissertation")))
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
                shutil.move(str(item), str(dst / item.name))
                moved.append(f"{old}/{item.name}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(old)
    for old, _ in LEGACY_MOVES:                        # remove legacy folders that are now empty
        src = ROOT / old
        if src.is_dir() and not any(x.name != ".gitkeep" for x in src.iterdir()):
            shutil.rmtree(src, ignore_errors=True)
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


def cmd_commit(args):
    p = project()
    if not (p.root / ".git").exists():
        init_repo(p)
    print(f"[{p.slug}] {commit(p, args.message)}")


def cmd_log(args):
    p = project()
    r = git(p, "log", f"-{args.n}", "--format=%h %ad %s", "--date=format:%Y-%m-%d %H:%M")
    print(r.stdout.strip() or "no history yet")


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new"); n.add_argument("name"); n.add_argument("--title")
    n.add_argument("--from", dest="from_project", help="copy templates, guidelines, cover and settings")
    n.add_argument("--zotero-collection")
    sub.add_parser("list")
    u = sub.add_parser("use"); u.add_argument("name")
    sub.add_parser("current")
    m = sub.add_parser("migrate"); m.add_argument("name", nargs="?")
    c = sub.add_parser("commit"); c.add_argument("message")
    lg = sub.add_parser("log"); lg.add_argument("-n", type=int, default=15)
    args = ap.parse_args()
    {"new": cmd_new, "list": cmd_list, "use": cmd_use, "current": cmd_current, "migrate": cmd_migrate,
     "commit": cmd_commit, "log": cmd_log}[args.cmd](args)


if __name__ == "__main__":
    main()
