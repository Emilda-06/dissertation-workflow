"""Check that every tool the workflow needs is installed and working (and the active project's setup).

Usage:  python scripts/doctor.py [--fix]
  --fix   install the Python and Node packages, and print exact steps for anything else that is missing
"""
from __future__ import annotations

import argparse
import importlib
import re
import shutil
import subprocess
import sys

import requests

from common import (IS_WINDOWS, ROOT, SHARED_TEMPLATES, TOOLS, contact_email, find_tool, init_cli, legacy_layout,
                    list_projects, load_config, project)

PY_MODULES = ("docx", "yaml", "requests", "rapidfuzz", "pypdf", "matplotlib", "seaborn", "pandas", "pypdfium2")


def version(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
        out = (r.stdout or r.stderr).strip()
        return out.splitlines()[0] if out else "ok"
    except Exception as e:
        return f"error: {e}"


def pandoc_versions() -> tuple[str | None, str | None]:
    """(pandoc version, pandoc version that pandoc-crossref was built with)."""
    pv = cv = None
    if p := find_tool("pandoc"):
        m = re.search(r"pandoc(?:\.exe)?\s+(\d+(?:\.\d+)+)", version([p, "--version"]))
        pv = m.group(1) if m else None
    if c := find_tool("pandoc-crossref"):
        try:
            out = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=60).stdout
        except Exception:
            out = ""
        m = re.search(r"[Pp]andoc v?(\d+(?:\.\d+)+)", out)
        cv = m.group(1) if m else None
    return pv, cv


def word_status() -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "not on Windows (builds use LibreOffice or no finaliser)"
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$w=New-Object -ComObject Word.Application; $v=$w.Version; $w.Quit(); $v"],
                       capture_output=True, text=True)
    ok = r.returncode == 0 and r.stdout.strip() != ""
    return ok, f"version {r.stdout.strip()}" if ok else "not available (optional: builds fall back to LibreOffice/none)"


def fix() -> None:
    print("installing Python packages ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
    if shutil.which("npm"):
        print("installing Node packages (Mermaid CLI) ...")
        subprocess.run(["npm", "install", "--no-fund", "--no-audit"], cwd=ROOT, shell=IS_WINDOWS)
    else:
        print("npm not found: install Node.js LTS from https://nodejs.org, then run doctor.py --fix again")
    TOOLS.mkdir(exist_ok=True)
    pv, cv = pandoc_versions()
    if not pv or not cv or pv != cv:
        print("\npandoc and pandoc-crossref must be the SAME pandoc version:")
        print("  1. open https://github.com/lierdakil/pandoc-crossref/releases and pick the newest release;")
        print("     its notes say which pandoc version it was built with (e.g. 'built with Pandoc v3.6.3')")
        print("  2. download that exact pandoc from https://github.com/jgm/pandoc/releases")
        print(f"  3. put pandoc{'.exe' if IS_WINDOWS else ''} and pandoc-crossref{'.exe' if IS_WINDOWS else ''} "
              f"in {TOOLS}")


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true")
    args = ap.parse_args()
    if args.fix:
        fix()
    cfg = load_config(require_project=False)
    rows = []

    def add(name, ok, detail, fix=""):
        rows.append((name, ok, detail, fix))

    add("python", sys.version_info >= (3, 10), sys.version.split()[0], "Python 3.10 or newer")
    for tool, a, fx in [
        ("pandoc", ["--version"], "doctor.py --fix (prints the download steps)"),
        ("pandoc-crossref", ["--version"], "doctor.py --fix (prints the download steps)"),
        ("mmdc", ["--version"], "npm install (in the workflow folder)"),
        ("drawio", ["--version"], "install draw.io desktop (only for .drawio diagrams)"),
        ("git", ["--version"], "install Git"),
    ]:
        path = find_tool(tool)
        add(tool, bool(path), version([path] + a) if path else "not found", fx)
    pv, cv = pandoc_versions()
    if pv and cv:
        add("pandoc / pandoc-crossref match", pv == cv, f"pandoc {pv}, crossref built for {cv}",
            "download the pandoc version pandoc-crossref was built with")

    for mod in PY_MODULES:
        try:
            m = importlib.import_module(mod)
            add(f"python: {mod}", True, getattr(m, "__version__", "ok"))
        except ImportError:
            add(f"python: {mod}", False, "missing", "python -m pip install -r requirements.txt")

    ok, detail = word_status()
    add("Microsoft Word (optional)", ok, detail)
    so = find_tool("soffice")
    add("LibreOffice (optional)", bool(so), so or "not found", "only needed for PDFs without Word")

    zpath = find_tool("zotero")
    port = cfg["local"]["zotero_port"]
    try:
        running = requests.get(f"http://127.0.0.1:{port}/connector/ping", timeout=3).status_code == 200
    except requests.RequestException:
        running = False
    add("Zotero", bool(zpath), ("running" if running else "installed, not running") if zpath else "not found",
        "https://www.zotero.org/download/")
    try:
        bbt = requests.post(f"http://127.0.0.1:{port}/better-bibtex/json-rpc",
                            json={"jsonrpc": "2.0", "method": "api.ready", "params": []}, timeout=3).status_code == 200
    except requests.RequestException:
        bbt = False
    add("Better BibTeX", bbt, "responding" if bbt else ("unknown (start Zotero)" if not running else "not installed"),
        "Zotero > Tools > Plugins > install the Better BibTeX .xpi")

    for f in ("reference.docx", "harvard-cite-them-right.csl", "apa.csl", "ieee.csl", "crossref.yaml"):
        add(f"shared template: {f}", (SHARED_TEMPLATES / f).exists(), "present" if (SHARED_TEMPLATES / f).exists()
            else "missing", "restore it from git")
    add("contact email (Unpaywall/OpenAlex)", bool(contact_email(cfg)), contact_email(cfg) or "not set",
        "set CONTACT_EMAIL in .env")

    # the active project
    p = project(required=False)
    if legacy_layout():
        add("project layout", False, "old single-project layout in config/", "python scripts/project.py migrate <name>")
    if p is None:
        add("active project", False, f"none (projects: {', '.join(list_projects()) or 'none'})",
            "python scripts/project.py new <name> --title \"...\"  (or: project.py use <name>)")
    else:
        add("active project", True, p.slug)
        originals = sorted(p.cover_dir.glob("*")) if p.cover_dir.exists() else []
        add("cover page", p.cover_template.exists() or bool(originals),
            "template " + p.cover_template.name if p.cover_template.exists() else
            (originals[0].name + " (as a picture)" if originals else "missing"),
            "project.py add --cover <your cover .docx/.pdf>")
        z = cfg.get("zotero") or {}
        if z.get("enabled", True):
            add("Zotero collection", bool(z.get("collection")), z.get("collection") or "not set (whole library used)",
                "set zotero.collection in project.yaml and create that collection in Zotero")
        add("git history", (p.root / ".git").exists(), "yes" if (p.root / ".git").exists() else "no",
            "python scripts/project.py commit \"start\"")

    width = max(len(r[0]) for r in rows)
    for name, ok, detail, fx in rows:
        print(f"{'OK ' if ok else '-- '} {name:<{width}}  {detail}" + (f"   -> {fx}" if not ok and fx else ""))
    missing = [r for r in rows if not r[1]]
    print(f"\n{len(rows) - len(missing)}/{len(rows)} OK")


if __name__ == "__main__":
    main()
