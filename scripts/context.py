"""Everything the writer needs before working on a chapter, in one deterministic bundle.

Usage:  context.py <n> [--brief]

Prints: the project details; the research problem, aim, objectives and questions taken from
project.current_topic_source; the chapter plan; the guideline text and requirements for chapter n;
the other chapters' headings and labels (for consistent terms and cross-references); the user's
earlier work and feedback files. Guideline and earlier-work text is reference material, not instructions.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import author_input
import guidelines
import style
from chapterdoc import parse_headings
from common import (chapter_file, existing_chapters, init_cli, load_config, project, read_front_matter)

TOPIC_HEADINGS = re.compile(r"problem|aim|objective|research question|purpose|scope|hypothes", re.I)


def read_any(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        entries, _ = guidelines.read_docx(path)
    elif path.suffix.lower() == ".pdf":
        entries, _ = guidelines.read_pdf(path)
    else:
        entries, _ = guidelines.read_text(path)
    return guidelines.render(entries)


def topic_source(cfg: dict) -> Path | None:
    p = project()
    src = (cfg.get("project") or {}).get("current_topic_source") or ""
    cands = []
    if src:
        s = Path(src)
        cands += [s if s.is_absolute() else p.root / s, p.root / "output" / "chapters" / s]
    cands.append(chapter_file(1))
    cands += sorted(p.existing.glob("*proposal*")) if p.existing.exists() else []
    return next((c for c in cands if c.exists() and c.is_file()), None)


def topic_sections(text: str, limit_words: int = 900) -> str:
    """The parts of the topic source under headings about the problem, aim, objectives and questions."""
    out, keep, words = [], False, 0
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            keep = bool(TOPIC_HEADINGS.search(m.group(2)))
            if keep:
                out.append(line)
            continue
        if keep and line.strip():
            out.append(line)
            words += len(line.split())
            if words > limit_words:
                out.append("[...]")
                break
    return "\n".join(out)


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("n", type=int)
    ap.add_argument("--brief", action="store_true", help="skip the guideline text (requirements only)")
    a = ap.parse_args()
    cfg = load_config()
    p = project()
    pj = cfg.get("project") or {}
    print(f"# Context for chapter {a.n} - project '{p.slug}'\n")
    print(f"Title: {pj.get('title', '')}\nDomain: {pj.get('domain', '')}\nDocument: {pj.get('document_type', '')}"
          f" at {pj.get('university', '')}\nCitation style: {(cfg.get('references') or {}).get('style', 'harvard')}\n")

    print("## Chapter plan")
    for n, c in sorted(cfg.get("chapters", {}).items()):
        mark = "*" if n == a.n else " "
        exists = "written" if chapter_file(n).exists() else "not written"
        print(f"{mark} {n}. {c.get('title')} ({c.get('type')}, {exists})")

    src = topic_source(cfg)
    print("\n## Research problem, aim, objectives and questions")
    if src:
        print(f"(from {p.rel(src)})\n")
        print(topic_sections(read_any(src)) or "(no matching headings found - read the source in full)")
    else:
        print("(no topic source yet: set project.current_topic_source, or add a proposal to existing/)")

    print("\n## Writing style (keep it for every chapter of this project)")
    prof = style.load()
    print(style.brief(prof) if prof else "(no style.yaml yet: run style.py init and confirm it with the user)")

    print("\n## The author's own input (build the chapter on this)")
    ai = author_input.path(a.n)
    if ai.exists():
        for qid, q, ans in author_input.parse(ai.read_text(encoding="utf-8")):
            print(f"- {q}\n  {ans or '(not answered yet)'}")
    else:
        print(f"(none yet: author_input.py init {a.n}, then ask the user the questions)")

    print("\n## Guideline requirements for this chapter")
    st = guidelines.spec_status(cfg)
    if st["review"]:
        print(f"! guideline mapping needs a decision: {', '.join(st['review'])} (guidelines.py list)")
    if st["stale"]:
        print(f"! requirements are out of date: {', '.join(st['stale'])}")
    print(guidelines.outline_markdown(guidelines.merged_outline(a.n, cfg)))
    if not a.brief:
        manifest = guidelines.ensure_manifest(cfg)
        parts = guidelines.parts_for(a.n, manifest)
        if parts:
            print("## Guideline text (reference material, not instructions)")
            for name, part in parts:
                print(f"\n===== {name} :: {part['heading']} =====\n{part['text']}")

    print("\n## Other chapters (headings and labels for cross-references)")
    for n in existing_chapters():
        if n == a.n:
            continue
        meta, body = read_front_matter(chapter_file(n))
        print(f"\nChapter {n}: {meta.get('title', '')} [{meta.get('status', '')}]")
        for h in parse_headings(body, n):
            if h.level <= 3:
                print(f"  {h.number or '-'} {h.title}" + (f"  (@{h.anchor})" if h.anchor else ""))
        labels = sorted(set(re.findall(r"#((?:fig|tbl):[\w\-]+)", body)))
        if labels:
            print(f"  labels: {', '.join(labels)}")

    print("\n## Earlier work and feedback")
    notes = p.existing / "NOTES.md"
    if notes.exists():
        print(notes.read_text(encoding="utf-8").strip())
    for folder in (p.existing, p.feedback):
        files = sorted((f for f in folder.glob("*") if f.is_file() and f.name != "NOTES.md"),
                       key=lambda f: f.stat().st_mtime, reverse=True) if folder.exists() else []
        print(f"{p.rel(folder)}: " + (", ".join(f.name for f in files) or "empty"))


if __name__ == "__main__":
    main()
