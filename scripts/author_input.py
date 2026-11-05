"""The author's own input for a chapter: views, findings, disagreements, examples and context.

A chapter built on the author's own thinking is better and is genuinely theirs. Before drafting, the
assistant asks these questions and records the answers here; context.py shows them to the writer, and
check.py warns when they are missing, too short, or not visibly used in the chapter.

This is the part of a chapter no model could have written: the author's experience, judgement and way of
explaining things. Answers can be short notes, a story, or a pasted transcript of a voice memo.

Usage:
  author_input.py init <n>       create output/chapters/chapter_<n>/author_input.md with questions for the chapter type
  author_input.py show <n>       print the questions and answers
  author_input.py status <n>     answered / thin answers / not yet used in the chapter (exit 2 if none answered)
  author_input.py add <n> "<question>" [--answer "<text>" | --file notes.txt] [--id ID]
                                 add a follow-up question, or paste notes / a voice-memo transcript
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from common import chapter_dir, chapter_file, die, init_cli, load_config, project, read_front_matter

COMMON = [
    ("why", "Why does this chapter matter to your project, in your own words?"),
    ("view", "What is your own view or argument for this chapter (what should a reader take away)?"),
    ("example", "Give one concrete example, case or moment from your own experience or work that illustrates it."),
    ("explain", "How would you explain the main idea of this chapter to a friend outside the field, in two or "
                "three sentences?"),
]
QUESTIONS = {
    "introduction": [
        ("origin", "What made you choose this problem (an experience, a course, a workplace, a news story)?"),
        ("context", "What local or practical context should the reader know (country, organisation, users)?"),
        ("who", "Who is affected by the problem, and what happens if it is not solved?"),
        ("stake", "What would people in your context do differently if this problem were solved?"),
    ],
    "literature": [
        ("agree", "Which studies do you find most convincing, and why?"),
        ("disagree", "Where do you disagree with the literature, or think a study's method is weak?"),
        ("gap", "What gap did you notice that your project addresses, in one or two sentences?"),
        ("surprise", "Did anything you read surprise you or change your mind? What, and why?"),
        ("debate", "Where do the studies disagree with each other, and which side do you lean towards?"),
    ],
    "methodology": [
        ("choices", "Why did you choose your method over the alternatives you considered?"),
        ("practical", "What practical constraints shaped it (time, hardware, data access, ethics approval)?"),
        ("changes", "Did anything change from your original plan, and why?"),
        ("rejected", "Which alternative did you seriously consider and reject, and what tipped the decision?"),
    ],
    "design": [
        ("decisions", "Which design decisions were hardest, and what were the trade-offs?"),
        ("problems", "What went wrong during implementation and how did you solve it?"),
        ("tools", "Why these tools, languages or platforms rather than others?"),
        ("proud", "Which part of the design or code are you most pleased with, and why?"),
    ],
    "results": [
        ("surprise", "Which results surprised you, and how do you explain them?"),
        ("meaning", "What do the results mean for the people or system affected?"),
        ("weakness", "What would you do differently if you ran the experiments again?"),
        ("expected", "What did you expect before running the experiments, and how did the results compare?"),
    ],
    "conclusion": [
        ("learned", "What is the most important thing you learned from the project?"),
        ("contribution", "What is genuinely new or useful in what you did?"),
        ("next", "What would you do next with more time or resources?"),
        ("advice", "What would you tell someone starting a similar project tomorrow?"),
    ],
}
ANSWER_PLACEHOLDER = "(your answer)"
THIN_WORDS = 8
STOPWORDS = set("""a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having he
her here hers him his how i if in into is it its itself just like me more most my myself no nor not now of off on once
only or other our ours out over own same she should so some such than that the their theirs them then there these they
this those through to too under until up very was we were what when where which while who whom why will with would you
your yours really think thing things much many lot quite something still even every well make made get got use used
using want wanted need needed maybe""".split())


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


def thin(answer: str) -> bool:
    return 0 < len(answer.split()) < THIN_WORDS


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z][a-z\-]{3,}", text.lower()) if w not in STOPWORDS}


def reflected(answer: str, chapter_text: str) -> bool:
    """Does the chapter visibly draw on this answer? (enough of its content words, stemmed, appear in it)."""
    words = _stems(answer)
    if len(words) < 3:
        return True
    return len(words & _stems(chapter_text)) / len(words) >= 0.35


def usage(n: int, body: str | None = None) -> dict:
    """Answered questions, thin answers, and answered questions the chapter does not visibly use."""
    p = path(n)
    if not p.exists():
        return {"total": 0, "answered": 0, "thin": [], "unused": []}
    qs = parse(p.read_text(encoding="utf-8"))
    if body is None:
        f = chapter_file(n)
        body = read_front_matter(f)[1] if f.exists() else ""
    answered = [(i, a) for i, _, a in qs if a]
    return {"total": len(qs), "answered": len(answered),
            "thin": [i for i, a in answered if thin(a)],
            "unused": [i for i, a in answered if body.strip() and not reflected(a, body)]}


def chapter_warnings(n: int, body: str) -> list[str]:
    u = usage(n, body)
    if not u["total"]:
        return [f"no author input recorded for this chapter (author_input.py init {n}): build the chapter on the "
                "author's own views, findings and context"]
    if not u["answered"]:
        return [f"author input questions are unanswered (author_input.py show {n})"]
    w = []
    if u["answered"] < min(3, u["total"]):
        w.append(f"author input: only {u['answered']}/{u['total']} questions answered; the author's examples and "
                 "judgements are what make the chapter theirs (ask the rest, or paste notes / a voice-memo "
                 f"transcript with author_input.py add {n})")
    if u["thin"]:
        w.append(f"author input: very short answer(s) to [{', '.join(u['thin'])}]; ask a follow-up "
                 f"(author_input.py add {n} \"<follow-up question>\")")
    if len(u["unused"]) > max(1, u["answered"] // 3):
        w.append(f"author input: the chapter does not visibly use the answers to [{', '.join(u['unused'])}]; "
                 "build the author's views, examples and context into the argument")
    return w


def cmd_init(n: int, cfg: dict) -> None:
    p = path(n)
    if p.exists():
        die(f"{project().rel(p)} already exists")
    typ = (cfg["chapters"].get(n) or {}).get("type", "")
    qs = COMMON + QUESTIONS.get(typ, [])
    lines = [f"# Author input - chapter {n}", "",
             "Your own thinking for this chapter. Short notes are fine, a story is better; you can also paste a "
             "transcript of yourself talking it through.", ""]
    for qid, q in qs:
        lines += [f"## [{qid}] {q}", "", ANSWER_PLACEHOLDER, ""]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {project().rel(p)} ({len(qs)} questions)")


def cmd_add(n: int, question: str, answer: str, qid: str | None) -> None:
    p = path(n)
    if not p.exists():
        die(f"no author input yet: author_input.py init {n}")
    text = p.read_text(encoding="utf-8")
    existing = {i for i, _, _ in parse(text)}
    if qid and qid in existing:
        die(f"[{qid}] already exists in {project().rel(p)}")
    if not qid:
        k = 1
        while f"followup-{k}" in existing:
            k += 1
        qid = f"followup-{k}"
    if not re.fullmatch(r"[\w\-]+", qid):
        die("the id may only contain letters, digits, '_' and '-'")
    question = " ".join(question.split())
    p.write_text(text.rstrip() + f"\n\n## [{qid}] {question}\n\n{answer.strip() or ANSWER_PLACEHOLDER}\n",
                 encoding="utf-8")
    print(f"added [{qid}] to {project().rel(p)}" + ("" if answer.strip() else " (unanswered)"))


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "show", "status", "add"])
    ap.add_argument("n", type=int)
    ap.add_argument("question", nargs="?", help="add: the follow-up question, or a heading for pasted notes")
    ap.add_argument("--answer", default="")
    ap.add_argument("--file", help="add: read the answer from a text file (notes, a voice-memo transcript)")
    ap.add_argument("--id", help="add: a short id for the question")
    a = ap.parse_args()
    cfg = load_config()
    if a.cmd == "init":
        cmd_init(a.n, cfg)
    elif a.cmd == "add":
        if not a.question:
            die('add needs a question, e.g. author_input.py add 2 "Why did you distrust study X?"')
        ans = Path(a.file).read_text(encoding="utf-8", errors="replace") if a.file else a.answer
        cmd_add(a.n, a.question, ans, a.id)
    elif a.cmd == "show":
        if not path(a.n).exists():
            die(f"no author input yet: author_input.py init {a.n}")
        for qid, q, ans in parse(path(a.n).read_text(encoding="utf-8")):
            print(f"[{qid}] {q}\n    {ans or '(not answered)'}" + ("   <- short: ask a follow-up" if thin(ans) else ""))
    else:
        u = usage(a.n)
        if not u["total"]:
            print(f"chapter {a.n}: no author input")
        else:
            print(f"chapter {a.n}: {u['answered']}/{u['total']} question(s) answered"
                  + (f"; short answers: {', '.join(u['thin'])}" if u["thin"] else "")
                  + (f"; not yet used in the chapter: {', '.join(u['unused'])}" if u["unused"] else ""))
        sys.exit(0 if u["answered"] else 2)


if __name__ == "__main__":
    main()
