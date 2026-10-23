"""Check that every tool the workflow needs is installed and working.

Usage:  .venv/Scripts/python.exe scripts/doctor.py
"""
from __future__ import annotations

import importlib
import subprocess

import requests

from common import CONFIG, TEMPLATES, contact_email, find_tool, load_config, setup_stdout


def version(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else "ok"
    except Exception as e:
        return f"error: {e}"


def main():
    setup_stdout()
    cfg = load_config(require_project=False)
    rows = []

    def add(name, ok, detail, fix=""):
        rows.append((name, ok, detail, fix))

    for tool, args, fix in [
        ("pandoc", ["--version"], "see README: tools/pandoc.exe"),
        ("pandoc-crossref", ["--version"], "see README: tools/pandoc-crossref.exe"),
        ("mmdc", ["--version"], "npm install (in the workflow folder)"),
        ("drawio", ["--version"], "winget install JGraph.Draw"),
        ("git", ["--version"], "winget install Git.Git"),
    ]:
        path = find_tool(tool)
        add(tool, bool(path), version([path] + args) if path else "not found", fix)

    for mod in ("docx", "yaml", "requests", "rapidfuzz", "pypdf", "matplotlib", "seaborn", "pandas", "pypdfium2"):
        try:
            m = importlib.import_module(mod)
            add(f"python: {mod}", True, getattr(m, "__version__", "ok"))
        except ImportError:
            add(f"python: {mod}", False, "missing", ".venv/Scripts/pip install -r requirements.txt")

    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$w=New-Object -ComObject Word.Application; $v=$w.Version; $w.Quit(); $v"],
                       capture_output=True, text=True)
    add("Microsoft Word", r.returncode == 0 and r.stdout.strip() != "", f"version {r.stdout.strip()}" if r.returncode == 0 else "COM unavailable")

    zpath = find_tool("zotero")
    try:
        running = requests.get(f"http://127.0.0.1:{cfg['local']['zotero_port']}/connector/ping", timeout=3).status_code == 200
    except requests.RequestException:
        running = False
    add("Zotero", bool(zpath), ("running" if running else "installed, not running") if zpath else "not found",
        "winget install DigitalScholar.Zotero")
    try:
        bbt = requests.post(f"http://127.0.0.1:{cfg['local']['zotero_port']}/better-bibtex/json-rpc",
                            json={"jsonrpc": "2.0", "method": "api.ready", "params": []}, timeout=3).status_code == 200
    except requests.RequestException:
        bbt = False
    add("Better BibTeX", bbt, "responding" if bbt else ("unknown (start Zotero)" if not running else "not installed"),
        "Zotero > Tools > Plugins > install tools/zotero-better-bibtex.xpi")

    for f, fix in [(TEMPLATES / "reference.docx", "python scripts/make_template.py"),
                   (TEMPLATES / "harvard-cite-them-right.csl", "download Harvard CSL"),
                   (TEMPLATES / "crossref.yaml", ""),
                   (CONFIG / "project.yaml", "copy config/project.example.yaml to config/project.yaml")]:
        add(f"file: {f.relative_to(CONFIG.parent)}", f.exists(), "present" if f.exists() else "missing", fix)
    cover = next((p for p in (CONFIG / "cover.docx", CONFIG / "cover.pdf") if p.exists()), None)
    add("cover page", bool(cover), cover.name if cover else "missing", "put your cover at config/cover.docx")
    add("contact email (Unpaywall/OpenAlex)", bool(contact_email(cfg)), contact_email(cfg) or "not set",
        "set CONTACT_EMAIL in .env")

    width = max(len(r[0]) for r in rows)
    for name, ok, detail, fix in rows:
        print(f"{'OK ' if ok else '-- '} {name:<{width}}  {detail}" + (f"   -> {fix}" if not ok and fix else ""))
    missing = [r for r in rows if not r[1]]
    print(f"\n{len(rows) - len(missing)}/{len(rows)} OK")


if __name__ == "__main__":
    main()
