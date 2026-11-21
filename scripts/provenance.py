"""Provenance: an honest record of how each chapter was written, and a draft AI-use statement.

The pipeline records two kinds of event per chapter:
  * an assistant run (pipeline.py begin ... finish): the assistant drafted or revised the chapter; at the
    end the chapter text is saved as the "last assistant draft" baseline;
  * an author edit: at the next pipeline.py begin (or provenance.py scan), any change between the chapter
    and that baseline was made by the author by hand, and is recorded with how many words changed.
Together with the project's git snapshots, the author input, the "your turn" rewrites (ownership.py) and
the source verification, this gives a process log a student can show if their authorship is questioned,
and the facts for an accurate declaration of AI use. The statement never understates the assistant's role.

Usage:
  provenance.py scan <n>                  record author edits made since the last assistant draft
  provenance.py record-begin <n> <mode> "<request>"     (pipeline.py begin)
  provenance.py record-finish <n>                       (pipeline.py finish)
  provenance.py show <n>                  the chapter's timeline and totals
  provenance.py log                       write output/dissertation/provenance.md (all chapters + git history)
  provenance.py statement [--force]       draft front_matter/05-ai-use.md for the author to review
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from datetime import datetime

from chapterdoc import word_count
from common import (chapter_dir, chapter_file, die, existing_chapters, init_cli, load_config, load_verification,
                    project, read_front_matter, save_json)

STATEMENT = "05-ai-use.md"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_path(n: int):
    return chapter_dir(n) / "provenance.json"


def baseline_path(n: int):
    return chapter_dir(n) / "provenance_baseline.md"


def load(n: int) -> dict:
    p = log_path(n)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"events": []}


def save(n: int, data: dict) -> None:
    save_json(log_path(n), data)


def body_of(n: int) -> str:
    f = chapter_file(n)
    return read_front_matter(f)[1] if f.exists() else ""


def tokens(text: str) -> list[str]:
    return re.findall(r"\S+", re.sub(r"<!--.*?-->", " ", text, flags=re.S))


def diff_words(old: str, new: str) -> dict:
    """Words added/replaced in new, words removed from old, and changed paragraphs."""
    a, b = tokens(old), tokens(new)
    added = removed = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("replace", "insert"):
            added += j2 - j1
        if op in ("replace", "delete"):
            removed += i2 - i1
    pa = [p.strip() for p in re.split(r"\n\s*\n", old) if p.strip()]
    pb = [p.strip() for p in re.split(r"\n\s*\n", new) if p.strip()]
    changed = len(set(pb) - set(pa))
    return {"words_added": added, "words_removed": removed, "paragraphs_changed": changed, "words_now": len(b)}


def scan(n: int, quiet: bool = False) -> dict | None:
    """Record hand edits made by the author since the last assistant draft (if any)."""
    base = baseline_path(n)
    if not base.exists() or not chapter_file(n).exists():
        return None
    old, new = base.read_text(encoding="utf-8"), body_of(n)
    if old == new:
        return None
    d = diff_words(old, new)
    if not (d["words_added"] or d["words_removed"]):
        return None
    data = load(n)
    ev = {"type": "author-edit", "date": now(), **d}
    data["events"].append(ev)
    save(n, data)
    base.write_text(new, encoding="utf-8")       # the author's version is now the reference for the next diff
    if not quiet:
        print(f"chapter {n}: author edits recorded ({d['words_added']} words added or changed, "
              f"{d['words_removed']} removed, {d['paragraphs_changed']} paragraph(s))")
    return ev


def record_begin(n: int, mode: str, request: str) -> None:
    scan(n)
    data = load(n)
    data["events"].append({"type": "assistant-run-start", "date": now(), "mode": mode, "request": request[:300],
                           "words_before": word_count(body_of(n)) if chapter_file(n).exists() else 0})
    save(n, data)


def record_finish(n: int, built: str = "") -> None:
    data = load(n)
    body = body_of(n)
    start = next((e for e in reversed(data["events"]) if e["type"] == "assistant-run-start"), None)
    prev = baseline_path(n).read_text(encoding="utf-8") if baseline_path(n).exists() else ""
    d = diff_words(prev, body)
    data["events"].append({"type": "assistant-run", "date": now(), "mode": (start or {}).get("mode", ""),
                           "request": (start or {}).get("request", ""), "build": built,
                           "words_added": d["words_added"], "words_removed": d["words_removed"],
                           "words_now": d["words_now"]})
    save(n, data)
    baseline_path(n).write_text(body, encoding="utf-8")


def ownership_counts(n: int) -> tuple[int, int]:
    p = chapter_dir(n) / "ownership.json"
    if not p.exists():
        return 0, 0
    o = json.loads(p.read_text(encoding="utf-8"))
    picked = o.get("picked", [])
    return sum(1 for x in picked if x.get("rewritten")), len(picked)


def summary(n: int) -> dict:
    import author_input
    data = load(n)
    ev = data["events"]
    author = [e for e in ev if e["type"] == "author-edit"]
    runs = [e for e in ev if e["type"] == "assistant-run"]
    answered, total = author_input.status(n)
    rewritten, picked = ownership_counts(n)
    pending = None
    if baseline_path(n).exists() and chapter_file(n).exists():
        d = diff_words(baseline_path(n).read_text(encoding="utf-8"), body_of(n))
        pending = d if (d["words_added"] or d["words_removed"]) else None
    words = word_count(body_of(n)) if chapter_file(n).exists() else 0
    by_author = sum(e["words_added"] for e in author) + (pending["words_added"] if pending else 0)
    return {"chapter": n, "words": words, "assistant_runs": len(runs), "author_edit_sessions": len(author)
            + (1 if pending else 0), "author_words_changed": by_author,
            "author_share_estimate": round(min(1.0, by_author / words), 2) if words else 0.0,
            "author_input": f"{answered}/{total}", "your_turn": f"{rewritten}/{picked}",
            "first": ev[0]["date"][:10] if ev else "", "last": ev[-1]["date"][:10] if ev else "",
            "events": ev, "pending": pending}


def cmd_show(n: int) -> None:
    s = summary(n)
    print(f"chapter {n}: {s['words']} words | assistant runs {s['assistant_runs']} | author edit sessions "
          f"{s['author_edit_sessions']} ({s['author_words_changed']} words added or changed by hand, about "
          f"{int(s['author_share_estimate'] * 100)}% of the current length) | author input {s['author_input']} | "
          f"your-turn rewrites {s['your_turn']}")
    for e in s["events"]:
        print(f"  {e['date'][:16].replace('T', ' ')}  {describe(e)}")
    if s["pending"]:
        print(f"  (now)             author edits not yet recorded: {s['pending']['words_added']} words "
              "(recorded at the next pipeline.py begin, or run provenance.py scan)")


def describe(e: dict) -> str:
    t = e["type"]
    if t == "assistant-run-start":
        return f"assistant run started ({e.get('mode')}): {e.get('request', '')}"
    if t == "assistant-run":
        return (f"assistant {'drafted' if e.get('mode') == 'new' else 'revised'} the chapter: +{e['words_added']} / "
                f"-{e['words_removed']} words, {e['words_now']} words now" + (f", built {e['build']}" if e.get("build")
                                                                              else ""))
    if t == "author-edit":
        return (f"author edited by hand: +{e['words_added']} / -{e['words_removed']} words in "
                f"{e['paragraphs_changed']} paragraph(s)")
    if t == "your-turn":
        return f"author rewrote key paragraph [{e.get('id')}] ({int(e.get('changed', 0) * 100)}% different from the draft)"
    return t


def git_history(limit: int = 60) -> list[str]:
    r = subprocess.run(["git", "-C", str(project().root), "log", f"-{limit}", "--format=%h %ad %s",
                        "--date=format:%Y-%m-%d %H:%M"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.stdout.strip().splitlines() if r.returncode == 0 else []


def similarity_estimate(n: int) -> str:
    f = chapter_dir(n) / "similarity_report.md"
    if not f.exists():
        return "-"
    m = re.search(r"Estimated similarity[^\n]*?(\d+(?:\.\d+)?\s*%)", f.read_text(encoding="utf-8"))
    return m.group(1) if m else "see similarity_report.md"


def cmd_log(cfg: dict) -> None:
    p = project()
    ver = load_verification()
    lines = [f"# Process log: {(cfg.get('project') or {}).get('title', p.slug)}", "",
             f"Generated {now()[:16].replace('T', ' ')} by provenance.py. It records how each chapter was produced: "
             "when the AI assistant drafted or revised text, when the author edited by hand, the author's own "
             "input, the key paragraphs the author rewrote, and source verification. Every step is also a git "
             "snapshot in the project's history (listed at the end).", "",
             "| Chapter | Words | Assistant runs | Author edit sessions | Words changed by author | Author input | "
             "Key paragraphs rewritten | Similarity estimate |", "|---|---|---|---|---|---|---|---|"]
    sums = [summary(n) for n in existing_chapters()]
    for s in sums:
        lines.append(f"| {s['chapter']} | {s['words']} | {s['assistant_runs']} | {s['author_edit_sessions']} | "
                     f"{s['author_words_changed']} (~{int(s['author_share_estimate'] * 100)}%) | {s['author_input']} | "
                     f"{s['your_turn']} | {similarity_estimate(s['chapter'])} |")
    verified = sum(1 for v in ver.values() if v.get("status") == "verified")
    lines += ["", f"Sources: {verified} of {len(ver)} references verified against their DOI / publisher records "
              "(refs.py verify).", ""]
    for s in sums:
        lines += [f"## Chapter {s['chapter']}", ""]
        lines += [f"- {e['date'][:16].replace('T', ' ')}: {describe(e)}" for e in s["events"]] or ["- (no events recorded)"]
        if s["pending"]:
            lines.append(f"- now: author edits not yet recorded ({s['pending']['words_added']} words)")
        lines.append("")
    hist = git_history()
    if hist:
        lines += ["## Project history (git snapshots)", "", "```"] + hist + ["```", ""]
    out = p.dissertation / "provenance.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {p.rel(out)}")


def guideline_ai_rules() -> list[str]:
    """Sentences in the department's guidelines that mention AI, for the author to check the statement against."""
    g = project().build / "guidelines"
    out = []
    if not g.exists():
        return out
    rx = re.compile(r"\b(?:artificial intelligence|generative|chatgpt|large language model|LLM|AI[- ]generated|"
                    r"AI tools?|use of AI)\b", re.I)
    for f in sorted(g.glob("*.md")):
        text = " ".join(f.read_text(encoding="utf-8", errors="replace").split())
        for s in re.split(r"(?<=[.!?])\s+", text):
            if rx.search(s) and 5 <= len(s.split()) <= 80 and s not in out:
                out.append(s)
    return out[:8]


def cmd_statement(cfg: dict, force: bool) -> None:
    p = project()
    out = p.dissertation / "front_matter" / STATEMENT
    if out.exists() and not force:
        die(f"{p.rel(out)} exists (review and edit it by hand, or use --force to regenerate it)")
    chapters = existing_chapters()
    if not chapters:
        die("no chapters yet: the statement is drafted from the chapters' records")
    sums = [summary(n) for n in chapters]
    ver = load_verification()
    verified = sum(1 for v in ver.values() if v.get("status") == "verified")
    planned = all((chapter_dir(n) / "outline.md").exists() for n in chapters)
    diagrams = any(f.suffix.lower() == ".png" for n in chapters for f in (chapter_dir(n) / "diagrams").glob("*"))
    uses = ["to search for and summarise literature",
            f"to draft and revise chapter text from my own notes, answers and data ({sum(s['assistant_runs'] for s in sums)} "
            f"drafting or revision run(s) across {len(sums)} chapter(s))",
            "to check the structure and quality of the writing"] + (["to produce diagrams"] if diagrams else []) + [
            "to format the document"]
    answered = sum(int(s["author_input"].split("/")[0]) for s in sums)
    rewritten = sum(int(s["your_turn"].split("/")[0]) for s in sums)
    words = sum(s["words"] for s in sums)
    by_author = sum(s["author_words_changed"] for s in sums)
    share = round(100 * by_author / words) if words else 0
    data_dirs = [n for n in existing_chapters() if any((chapter_dir(n) / "data").glob("*"))]
    edits = (f"I edited the drafts by hand, adding or changing about {by_author:,} words (roughly {share}% of the "
             f"final text), and rewrote {rewritten} key paragraph(s) in my own words."
             if by_author or rewritten else
             "The drafts have not yet been substantially edited by hand. TODO-CHECK: revise this sentence once you "
             "have edited the chapters; do not claim edits you have not made.")
    rules = guideline_ai_rules()
    lines = ["---", "title: DECLARATION ON THE USE OF AI TOOLS", "reviewed: false", "---", "",
             "<!-- Draft generated by provenance.py from the project's records. Check every sentence is true, "
             "adjust it to your university's required wording or form, then set 'reviewed: true' above. Until then "
             "the combined dissertation leaves this page out. -->", ""]
    if rules:
        lines += ["<!-- Your department's guidelines say:"] + [f"     - {r}" for r in rules] + ["-->", ""]
    lines += [
        "In preparing this dissertation I used an AI assistant (Claude, developed by Anthropic) through a "
        "dissertation-writing workflow. I used it " + ", ".join(uses[:-1]) + ", and " + uses[-1] + ".",
        "",
        (f"The arguments, evaluations and examples are based on my own input: I answered {answered} question(s) "
         "about my views, experience and context before the chapters were drafted"
         if answered else "TODO-CHECK: no author input was recorded; describe honestly how the arguments were "
                          "developed, or answer the author-input questions first")
        + ("; I reviewed and approved the plan of each chapter. " if planned and answered else ". " if answered
           else " ")
        + ("All data and results come from my own experiments and data (kept with each chapter); the assistant "
           "only analysed them and computed summaries, and generated none. " if data_dirs else "")
        + edits,
        "",
        (f"Every source cited was retrieved from a bibliographic database and verified against its DOI or publisher "
         f"record ({verified} of {len(ver)} references); no source or quotation was invented."
         if ver and verified == len(ver) else
         f"{verified} of {len(ver)} references are verified against their DOI or publisher record. TODO-CHECK: "
         "verify or remove the others (refs.py verify) before submitting."),
        "",
        "A process log with the date of every drafting run and every hand edit, and the full version history of "
        "the project, is available on request. I take full responsibility for the content of this dissertation.",
        "",
        "TODO-CHECK: confirm this statement is accurate and meets your university's policy on AI use.",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {p.rel(out)} (draft: review it, then set 'reviewed: true' in its front matter)")
    if rules:
        print(f"the guidelines mention AI in {len(rules)} place(s); they are listed in the file for checking")


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("n", type=int)
    b = sub.add_parser("record-begin"); b.add_argument("n", type=int); b.add_argument("mode")
    b.add_argument("request", nargs="?", default="")
    f = sub.add_parser("record-finish"); f.add_argument("n", type=int); f.add_argument("--build", default="")
    sh = sub.add_parser("show"); sh.add_argument("n", type=int)
    sub.add_parser("log")
    st = sub.add_parser("statement"); st.add_argument("--force", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    if a.cmd == "scan":
        if scan(a.n) is None:
            print(f"chapter {a.n}: no new author edits since the last assistant draft")
    elif a.cmd == "record-begin":
        record_begin(a.n, a.mode, a.request)
    elif a.cmd == "record-finish":
        record_finish(a.n, a.build)
    elif a.cmd == "show":
        cmd_show(a.n)
    elif a.cmd == "log":
        cmd_log(cfg)
    else:
        cmd_statement(cfg, a.force)
    sys.exit(0)


if __name__ == "__main__":
    main()
