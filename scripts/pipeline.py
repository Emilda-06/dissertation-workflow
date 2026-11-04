"""Deterministic pipeline steps, so the mechanical part of a run is identical every time.

Usage:
  pipeline.py begin <n> <new|edit> "<request>"   Zotero check, git snapshot, start or resume the run
  pipeline.py finish <n> [--pdf] [--pdfa] [--force] [--no-commit]
        diagrams -> quality check -> source verification -> build -> compliance report -> state -> git snapshot

Exit code 2 = a step failed (the output says which and what to fix); nothing after it was run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from common import ROOT, chapter_dir, chapter_file, die, ensure_zotero, init_cli, load_config, project

SCRIPTS = ROOT / "scripts"


def run(script: str, *args: str, show: bool = True) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPTS / script), *args, "--project", project().slug]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if show and (r.stdout or r.stderr).strip():
        print((r.stdout + (r.stderr if r.returncode not in (0, 2) else "")).rstrip())
    return r


def state(n: int) -> dict:
    p = chapter_dir(n) / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def done(n: int, stage: str, note: str = "") -> None:
    if state(n).get("current"):
        run("state.py", "done", str(n), stage, note, show=False)


def cmd_begin(a, cfg):
    if (cfg.get("zotero") or {}).get("enabled", True):
        ensure_zotero(cfg)
    s = state(a.n).get("current")
    if s:
        print(f"chapter {a.n} has a run IN PROGRESS (mode={s['mode']}); resuming it, not starting again.")
        run("state.py", "show", str(a.n))
        return
    run("project.py", "commit", f"before: {a.mode} chapter {a.n}")
    run("state.py", "start", str(a.n), a.mode, a.request)


def step(title: str, r: subprocess.CompletedProcess, n: int, stage: str | None, ok_codes=(0,)) -> None:
    if r.returncode not in ok_codes:
        print(f"\nSTOPPED at '{title}' (exit {r.returncode}). Fix the problems above and run pipeline.py finish {n} again.")
        sys.exit(2)
    if stage:
        done(n, stage, title)


def cmd_finish(a, cfg):
    n = a.n
    if not chapter_file(n).exists():
        die(f"{chapter_file(n)} does not exist")
    print(f"== diagrams (chapter {n}) ==")
    step("diagrams", run("diagrams.py", str(n)), n, "diagrams")
    print("\n== quality check ==")
    step("check", run("check.py", str(n)), n, None, ok_codes=(0,) if not a.force else (0, 2))
    print("\n== source verification ==")
    r = run("refs.py", "verify", "--chapter", str(n))
    step("verify", r, n, "check", ok_codes=(0,) if not a.force else (0, 2))
    if not a.no_commit:
        run("project.py", "commit", f"chapter {n}: checked", show=False)
    print("\n== build ==")
    extra = [x for x, on in (("--pdf", a.pdf), ("--pdfa", a.pdfa), ("--force", True)) if on]
    r = run("build.py", "chapter", str(n), *extra)          # already checked above
    step("build", r, n, "build")
    built = next((ln.split()[1] for ln in r.stdout.splitlines() if ln.startswith("BUILT ")), "")
    print("\n== guideline compliance ==")
    run("guidelines.py", "compliance", str(n), show=False)
    print(f"written: {project().rel(chapter_dir(n) / 'compliance.md')}")
    if (chapter_dir(n) / "revisions.md").exists() and state(n).get("current", {}).get("mode") == "edit":
        run("build.py", "changes", str(n))
        run("build.py", "redline", str(n))
    done(n, "report", built)
    run("state.py", "finish", str(n), show=False)
    if not a.no_commit:
        run("project.py", "commit", f"chapter {n}: built {Path(built).name if built else ''}".strip())
    print(f"\nDONE chapter {n}: {built}")


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("begin"); b.add_argument("n", type=int); b.add_argument("mode", choices=["new", "edit"])
    b.add_argument("request")
    f = sub.add_parser("finish"); f.add_argument("n", type=int)
    f.add_argument("--pdf", action="store_true"); f.add_argument("--pdfa", action="store_true")
    f.add_argument("--force", action="store_true"); f.add_argument("--no-commit", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    {"begin": cmd_begin, "finish": cmd_finish}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
