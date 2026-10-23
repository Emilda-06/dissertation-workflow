"""Pipeline progress per chapter, so an interrupted run can resume where it stopped.

Usage:
  state.py show [<n>]                       (all chapters if n omitted)
  state.py start <n> <mode> "<request>"     mode: new | edit
  state.py done <n> <stage> ["note"]        stage: plan research verify write diagrams check build report
  state.py finish <n>
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from common import chapter_dir, ensure_chapter_dirs, existing_chapters, save_json, setup_stdout

STAGES = {
    "new": ["plan", "research", "verify", "write", "diagrams", "check", "build", "report"],
    "edit": ["plan", "research", "verify", "write", "diagrams", "check", "build", "report"],
}


def path(n):
    return chapter_dir(n) / "state.json"


def load(n):
    p = path(n)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def show(n):
    s = load(n)
    if not s:
        print(f"chapter {n}: no pipeline run recorded")
        return
    run = s.get("current") or (s.get("history") or [{}])[-1]
    done = [d["stage"] for d in run.get("done", [])]
    todo = [x for x in STAGES.get(run.get("mode", "new"), []) if x not in done]
    status = "IN PROGRESS" if s.get("current") else "finished"
    print(f"chapter {n}: {status} | mode={run.get('mode')} | started {run.get('started')}")
    print(f"  request: {run.get('request', '')[:150]}")
    print(f"  done: {', '.join(done) or '-'}")
    if s.get("current"):
        print(f"  next: {todo[0] if todo else 'finish'}  (remaining: {', '.join(todo) or '-'})")


def main():
    setup_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show"); s.add_argument("n", type=int, nargs="?")
    st = sub.add_parser("start"); st.add_argument("n", type=int); st.add_argument("mode", choices=list(STAGES))
    st.add_argument("request")
    d = sub.add_parser("done"); d.add_argument("n", type=int); d.add_argument("stage"); d.add_argument("note", nargs="?", default="")
    f = sub.add_parser("finish"); f.add_argument("n", type=int)
    a = p.parse_args()
    now = datetime.now().isoformat(timespec="seconds")
    if a.cmd == "show":
        for n in ([a.n] if a.n else existing_chapters()):
            show(n)
        return
    ensure_chapter_dirs(a.n)
    s = load(a.n)
    if a.cmd == "start":
        if s.get("current"):
            s.setdefault("history", []).append({**s["current"], "abandoned": now})
        s["current"] = {"mode": a.mode, "request": a.request, "started": now, "done": []}
    elif a.cmd == "done":
        if not s.get("current"):
            raise SystemExit("no run in progress; use 'start' first")
        s["current"]["done"].append({"stage": a.stage, "at": now, "note": a.note})
    elif a.cmd == "finish":
        if s.get("current"):
            s.setdefault("history", []).append({**s.pop("current"), "finished": now})
    save_json(path(a.n), s)
    show(a.n)


if __name__ == "__main__":
    main()
