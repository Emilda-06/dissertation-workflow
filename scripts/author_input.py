"""The author's own input for a chapter: views, findings, disagreements, examples and context.

A chapter built on the author's own thinking is better and is genuinely theirs. Before drafting, the
assistant asks these questions and records the answers here; context.py shows them to the writer, and
check.py warns when they are missing.

Usage:
  author_input.py init <n>       create output/chapters/chapter_<n>/author_input.md with questions for the chapter type
  author_input.py show <n>       print the questions and answers
  author_input.py status <n>     how many questions are answered (exit 2 if none)
"""
from __future__ import annotations

import argparse
import re
import sys

from common import chapter_dir, die, init_cli, load_config, project

COMMON = [
    ("why", "Why does this chapter matter to your project, in your own words?"),
    ("view", "What is your own view or argument for this chapter (what should a reader take away)?"),
]
QUESTIONS = {
    "introduction": [
        ("origin", "What made you choose this problem (an experience, a course, a workplace, a news story)?"),
        ("context", "What local or practical context should the reader know (country, organisation, users)?"),
        ("who", "Who is affected by the problem, and what happens if it is not solved?"),
    ],
    "literature": [
        ("agree", "Which studies do you find most convincing, and why?"),
        ("disagree", "Where do you disagree with the literature, or think a study's method is weak?"),
        ("gap", "What gap did you notice that your project addresses, in one or two sentences?"),
    ],
    "methodology": [
        ("choices", "Why did you choose your method over the alternatives you considered?"),
        ("practical", "What practical constraints shaped it (time, hardware, data access, ethics approval)?"),
        ("changes", "Did anything change from your original plan, and why?"),
    ],
    "design": [
        ("decisions", "Which design decisions were hardest, and what were the trade-offs?"),
        ("problems", "What went wrong during implementation and how did you solve it?"),
        ("tools", "Why these tools, languages or platforms rather than others?"),
    ],
    "results": [
        ("surprise", "Which results surprised you, and how do you explain them?"),
        ("meaning", "What do the results mean for the people or system affected?"),
        ("weakness", "What would you do differently if you ran the experiments again?"),
    ],
    "conclusion": [
        ("learned", "What is the most important thing you learned from the project?"),
        ("contribution", "What is genuinely new or useful in what you did?"),
        ("next", "What would you do next with more time or resources?"),
    ],
}
ANSWER_PLACEHOLDER = "(your answer)"


def path(n: int):
    return chapter_dir(n) / "author_input.md"


def parse(text: str) -> list[tuple[str, str, str]]:
    """(id, question, answer) for every '## [id] question' block."""
    out = []
    for m in re.finditer(r"^## \[([\w\-]+)\] (.+?)\n(.*?)(?=^## \[|\Z)", text, re.S | re.M):
        ans = m.group(3).strip()
        out.append((m.group(1), m.group(2).strip(), "" if ans in ("", ANSWER_PLACEHOLDER) else ans))
    return out


def status(n: int) -> tuple[int, int]:
    """(answered, total) - (0, 0) when no file exists."""
    p = path(n)
    if not p.exists():
        return 0, 0
    qs = parse(p.read_text(encoding="utf-8"))
    return sum(1 for _, _, a in qs if a), len(qs)


def cmd_init(n: int, cfg: dict) -> None:
    p = path(n)
    if p.exists():
        die(f"{project().rel(p)} already exists")
    typ = (cfg["chapters"].get(n) or {}).get("type", "")
    qs = COMMON + QUESTIONS.get(typ, [])
    lines = [f"# Author input - chapter {n}", "",
             "Your own thinking for this chapter. Short answers are fine; notes, not prose.", ""]
    for qid, q in qs:
        lines += [f"## [{qid}] {q}", "", ANSWER_PLACEHOLDER, ""]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {project().rel(p)} ({len(qs)} questions)")


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "show", "status"])
    ap.add_argument("n", type=int)
    a = ap.parse_args()
    cfg = load_config()
    if a.cmd == "init":
        cmd_init(a.n, cfg)
    elif a.cmd == "show":
        if not path(a.n).exists():
            die(f"no author input yet: author_input.py init {a.n}")
        for qid, q, ans in parse(path(a.n).read_text(encoding="utf-8")):
            print(f"[{qid}] {q}\n    {ans or '(not answered)'}")
    else:
        done, total = status(a.n)
        print(f"chapter {a.n}: {done}/{total} question(s) answered" if total else f"chapter {a.n}: no author input")
        sys.exit(0 if done else 2)


if __name__ == "__main__":
    main()
