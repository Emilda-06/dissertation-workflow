"""Pipeline progress per chapter, so an interrupted run can resume where it stopped.

Usage:
  state.py show [<n>]                                 (all chapters if n omitted)
  state.py start <n> <mode> "<request>" [--force]     mode: new | edit   (--force abandons a run in progress)
  state.py done <n> <stage> ["note"]                  stage: plan research verify write diagrams check build report
  state.py finish <n>
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from common import chapter_dir, die, ensure_chapter_dirs, existing_chapters, init_cli, project, save_json

STAGES = {
    "new": ["plan", "research", "verify", "write", "diagrams", "check", "build", "report"],
    "edit": ["plan", "research", "verify", "write", "diagrams", "check", "build", "report"],
}
ALL_STAGES = sorted({s for v in STAGES.values() for s in v})


def path(n):
    return chapter_dir(n) / "state.json"


def load(n):
    p = path(n)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def chapters_with_state() -> list[int]:
    return sorted(set(existing_chapters()) | {n for n in range(1, 100) if path(n).exists()})


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
    init_cli()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show"); s.add_argument("n", type=int, nargs="?")
    st = sub.add_parser("start"); st.add_argument("n", type=int); st.add_argument("mode", choices=list(STAGES))
    st.add_argument("request"); st.add_argument("--force", action="store_true")
    d = sub.add_parser("done"); d.add_argument("n", type=int); d.add_argument("stage", choices=ALL_STAGES)
    d.add_argument("note", nargs="?", default="")
    f = sub.add_parser("finish"); f.add_argument("n", type=int)
    a = p.parse_args()
    now = datetime.now().isoformat(timespec="seconds")
    project()                                    # resolves (and announces) the project before anything else
    if a.cmd == "show":
        nums = [a.n] if a.n is not None else chapters_with_state()
        if not nums:
            print("no chapters yet")
        for n in nums:
            show(n)
        return
    ensure_chapter_dirs(a.n)
    s = load(a.n)
    if a.cmd == "start":
        if s.get("current"):
            if not a.force:
                die(f"chapter {a.n} already has a run in progress (mode={s['current'].get('mode')}, started "
                    f"{s['current'].get('started')}). Resume it, or pass --force to abandon it and start again.", 3)
            s.setdefault("history", []).append({**s["current"], "abandoned": now})
        s["current"] = {"mode": a.mode, "request": a.request, "started": now, "done": []}
    elif a.cmd == "done":
        if not s.get("current"):
            die("no run in progress; use 'start' first")
        if a.stage not in STAGES[s["current"]["mode"]]:
            die(f"'{a.stage}' is not a stage of mode {s['current']['mode']}")
        s["current"]["done"] = [x for x in s["current"]["done"] if x["stage"] != a.stage]
        s["current"]["done"].append({"stage": a.stage, "at": now, "note": a.note})
    elif a.cmd == "finish":
        if s.get("current"):
            s.setdefault("history", []).append({**s.pop("current"), "finished": now})
    save_json(path(a.n), s)
    show(a.n)


if __name__ == "__main__":
    main()
