"""Defence brief: what you must be able to explain about a chapter in a viva or supervisor meeting.

Usage:  defence.py <n>   -> output/chapters/chapter_<n>/defence_brief.md

Contains: the chapter's argument in outline; every key claim with the sources behind it (and whether you
have the full text, so you know what you can speak to); the figures and tables you must explain; the
weak spots the checks found; and likely examiner questions for this chapter. The assistant can add
model answers below each question; you should rehearse them in your own words.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime

import critique
import integrity
from chapterdoc import figures, parse_headings, tables
from common import (chapter_dir, chapter_file, find_citekeys, init_cli, load_config, load_library,
                    load_verification, project, read_front_matter)

QUESTIONS = {
    "introduction": [
        "Why is this problem worth solving, and for whom?",
        "How did you arrive at these objectives, and how will you know each one is met?",
        "What is deliberately outside the scope of the study, and why?",
        "Which single source best shows that the problem is real?",
    ],
    "literature": [
        "Which three studies are closest to your work, and how does your work differ from each?",
        "How did you search for and select the literature? What might you have missed?",
        "Where do the studies disagree, and whose view do you find more convincing?",
        "What exactly is the gap, and how do you know nobody has filled it?",
    ],
    "methodology": [
        "Why this method rather than the main alternative?",
        "How do you ensure validity and reliability? What threatens them?",
        "Could someone reproduce your study from this chapter alone?",
        "What ethical issues arose and how were they handled?",
    ],
    "design": [
        "Why this architecture? What alternatives did you reject and why?",
        "Which requirement was hardest to meet, and how did the design address it?",
        "How did you test that the implementation matches the design?",
        "What would change if the system had to scale ten times?",
    ],
    "results": [
        "Which result is the strongest evidence for your conclusion?",
        "How confident are you in the numbers? What is the variability?",
        "How do your results compare with the literature, and why do they differ?",
        "What result surprised you, and what explains it?",
    ],
    "conclusion": [
        "What is your main contribution, in one sentence?",
        "Which objective was met least well, and why?",
        "What are the main limitations, and how do they affect your conclusions?",
        "What should the next study do?",
    ],
}


def safe(doi: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", doi.lower())


def key_claims(body: str, heads) -> list[tuple[str, str, list[str]]]:
    """(section, claim sentence, keys) for every cited sentence."""
    out = []
    lines = body.splitlines()
    for p in critique.paragraphs(body):
        cited = [s for s in re.split(r"(?<=[.!?])\s+", p) if find_citekeys(s)]
        if not cited:
            continue
        first = p.splitlines()[0]
        idx = next((i for i, ln in enumerate(lines) if first[:40] and first[:40] in ln), 0)
        h = None
        for x in heads:
            if x.line <= idx:
                h = x
        for sent in cited:
            clean = re.sub(r"\s*\[[^\]]*@[^\]]*\]", "", sent).strip()
            out.append((f"{h.number} {h.title}" if h else "", clean, sorted(set(find_citekeys(sent)))))
    return out


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("n", type=int)
    a = ap.parse_args()
    cfg = load_config()
    n = a.n
    meta, body = read_front_matter(chapter_file(n))
    typ = meta.get("type") or (cfg["chapters"].get(n) or {}).get("type", "")
    heads = parse_headings(body, n)
    lib, ver = load_library(), load_verification()
    have_full = {f.stem for f in project().chapters.glob("chapter_*/research/fulltext/*.txt")}

    lines = [f"# Defence brief - Chapter {n}: {meta.get('title', '')}", "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M}. Rehearse the answers in your own words.", "",
             "## The argument in outline", ""]
    lines += [f"{'  ' * (h.level - 2)}- {h.number or ''} {h.title}" for h in heads if h.level <= 3]

    lines += ["", "## Key claims and the evidence behind them", "",
              "| Section | Claim | Sources | Full text read? |", "|---|---|---|---|"]
    for sec, claim, keys in key_claims(body, heads)[:40]:
        full = ["yes" if (lib.get(k, {}).get("DOI") and safe(lib[k]["DOI"]) in have_full) else "abstract only"
                for k in keys]
        lines.append(f"| {sec} | {claim[:160].replace('|', '/')} | {', '.join('@' + k for k in keys)} | "
                     f"{', '.join(full)} |")

    figs, tbls = figures(body), tables(body)
    if figs or tbls:
        lines += ["", "## Figures and tables you must be able to explain", ""]
        lines += [f"- **{fid}**: {cap} - what does it show, how is it read, why is it here?" for cap, _, fid in figs]
        lines += [f"- **{tid}**: {cap} - where do the values come from, what is the main pattern?" for cap, tid in tbls]

    weak = []
    w, res = critique.warnings_for(body, typ)
    weak += [x.replace("depth: ", "") for x in w]
    e, w2 = integrity.copy_check(body)
    weak += e + w2
    old = [k for k in sorted(set(find_citekeys(body))) if (ver.get(k, {}).get("year") or 9999) <
           (cfg.get("references") or {}).get("min_year", 2016)]
    if old:
        weak.append(f"older sources you may be asked to justify: {', '.join('@' + k for k in old)}")
    abstract_only = sorted({k for _, _, keys in key_claims(body, heads) for k in keys
                            if not (lib.get(k, {}).get("DOI") and safe(lib[k]["DOI"]) in have_full)})
    if abstract_only:
        weak.append(f"claims rest on sources you have only the abstract of: {', '.join('@' + k for k in abstract_only)}"
                    " - read them or be ready to say what the abstract supports")
    if "TODO-DATA" in body:
        weak.append("TODO-DATA items remain: you will be asked where these results are")
    lines += ["", "## Weak spots to prepare for", ""] + ([f"- {x}" for x in weak] or ["- none found by the checks"])

    qs = list(QUESTIONS.get(typ, []))
    for cap, _, fid in figs[:2]:
        qs.append(f"Walk me through {fid} ('{cap[:60]}').")
    if res.get("descriptive"):
        qs.append("You describe several studies; what is your own evaluation of them?")
    for k in (abstract_only[:2] if abstract_only else []):
        qs.append(f"What method did @{k} use, and how far can its findings be trusted?")
    lines += ["", "## Likely questions", ""] + [f"{i}. {q}\n   - Answer: " for i, q in enumerate(qs, 1)]
    out = chapter_dir(n) / "defence_brief.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {project().rel(out)} ({len(qs)} questions, {len(weak)} weak spot(s))")


if __name__ == "__main__":
    main()
