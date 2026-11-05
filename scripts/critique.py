"""Critical depth: does the chapter evaluate and synthesise sources, or only describe them one by one?

Signals (heuristic, reported as warnings):
  * descriptive paragraphs: cite sources and report what they did ("X (2021) proposed ...") without any
    evaluation, comparison or link to this study;
  * source-by-source summaries: several paragraphs in a row, each about a single different source;
  * low synthesis: few paragraphs that bring two or more sources together.

Usage:  critique.py <n>
"""
from __future__ import annotations

import argparse
import re

from chapterdoc import blocks, classify
from common import chapter_file, find_citekeys, init_cli, load_config, read_front_matter, strip_code

# Evaluation is measured by *kinds* of critical move, not by how many marker words a paragraph contains.
# Bare connectives ("however", "therefore", "thus", "moreover") are deliberately NOT evidence of evaluation:
# counting them rewarded sprinkling them in, which is exactly what makes prose read as machine-written.
EVALUATION_KINDS = {
    "comparison": ["whereas", "in contrast", "by contrast", "unlike", "compared with", "compared to", "similarly",
                   "likewise", "consistent with", "inconsistent with", "contradict", "agree", "disagree",
                   "outperform", "more effective", "less effective", "higher than", "lower than", "than the",
                   "differ", "both ", "neither", "same conclusion", "the other"],
    "judgement": ["limitation", "limited", "weakness", "strength", "fails to", "does not", "did not", "only ",
                  "overlook", "ignore", "assume", "assumption", "questionable", "convincing", "unconvincing",
                  "unclear", "debate", "trade-off", "drawback", "advantage", "disadvantage", "small sample",
                  "tested only", "simulat", "biased", "generalis", "generaliz", "reliable", "weaker", "stronger",
                  "flawed", "untested", "evaluated"],
    "implication": ["this study", "this project", "the present study", "this research", "this dissertation",
                    "gap", "relevant to", "important because", "matters because", "it remains", "remains unclear",
                    "few studies", "little is known", "not yet", "implies that", "suggests that", "means that",
                    "for this work"],
}
DISCOURSE_MARKERS = ["however", "moreover", "furthermore", "additionally", "therefore", "thus", "consequently",
                     "as a result", "hence", "notably", "importantly", "this suggests", "overall"]
EVALUATIVE = [m for ms in EVALUATION_KINDS.values() for m in ms]  # kept for other modules
REPORTING = re.compile(r"\b(propos|present|develop|introduc|describ|us(?:e|ed|ing)\b|employ|implement|examin|"
                       r"investigat|stud(?:y|ied)|found|show|report|conduct|design|focus|apply|appl(?:y|ied))", re.I)
CHECKED_TYPES = {"literature": 0.4, "introduction": 0.6, "methodology": 0.6, "design": 0.7, "results": 0.6}


def paragraphs(body: str) -> list[str]:
    return [re.sub(r"<!--.*?-->", "", b, flags=re.S) for b in blocks(strip_code(body)) if classify(b) == "paragraph"]


def _low(par: str) -> str:
    return " " + re.sub(r"\[[^\]]*@[^\]]*\]", " ", par.lower()) + " "


def evaluation_kinds(par: str) -> set[str]:
    """Which kinds of critical move the paragraph makes (comparison, judgement, implication)."""
    low = _low(par)
    return {k for k, ms in EVALUATION_KINDS.items() if any(m in low for m in ms)}


def evaluative_hits(par: str) -> int:
    """Number of distinct kinds of evaluation (0-3). Repeating a marker, or adding connectives, adds nothing."""
    return len(evaluation_kinds(par))


def marker_count(par: str) -> int:
    low = _low(par)
    return sum(len(re.findall(rf"(?<![a-z]){re.escape(m)}(?![a-z])", low)) for m in DISCOURSE_MARKERS)


def analyse(body: str) -> dict:
    cited = []
    for p in paragraphs(body):
        keys = sorted(set(find_citekeys(p)))
        if not keys:
            continue
        sents = [s for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]
        reporting = sum(1 for s in sents if REPORTING.search(s) and find_citekeys(s))
        ev = evaluative_hits(p)
        # "X proposed ... Y developed ... Z presented ...": one study per sentence, nothing connecting them
        leads = [find_citekeys(s)[0] for s in sents if re.match(r"\s*@", s) and find_citekeys(s)]
        is_list = ev == 0 and len(set(leads)) >= 3
        markers = marker_count(p)
        cited.append({"text": p, "keys": keys, "evaluative": ev, "list": is_list, "markers": markers,
                      "padded": markers >= 3 and markers >= len(sents) * 0.6 and ev <= 1,
                      "descriptive": ev == 0 and reporting >= max(1, len(sents) // 2)})
    runs, run = [], []
    for c in cited:
        if len(c["keys"]) == 1 and (not run or c["keys"][0] not in run[-1]["keys"]):
            run.append(c)
        else:
            if len(run) >= 3:
                runs.append(run)
            run = [c] if len(c["keys"]) == 1 else []
    if len(run) >= 3:
        runs.append(run)
    n = len(cited)
    return {"cited_paragraphs": n,
            "descriptive": [c for c in cited if c["descriptive"]],
            "lists": [c for c in cited if c["list"]],
            "padded": [c for c in cited if c["padded"]],
            "descriptive_share": round(sum(c["descriptive"] for c in cited) / n, 2) if n else 0.0,
            "synthesis_share": round(sum(len(c["keys"]) >= 2 for c in cited) / n, 2) if n else 0.0,
            "summary_runs": runs}


def warnings_for(body: str, chapter_type: str) -> tuple[list[str], dict]:
    limit = CHECKED_TYPES.get(chapter_type)
    res = analyse(body)
    if limit is None or res["cited_paragraphs"] < 3:
        return [], res
    w = []
    if res["descriptive_share"] > limit:
        starts = "; ".join("'" + " ".join(c["text"].split()[:7]) + " ...'" for c in res["descriptive"][:3])
        w.append(f"depth: {int(res['descriptive_share'] * 100)}% of cited paragraphs only describe sources "
                 f"(limit {int(limit * 100)}%): add evaluation - compare them, judge their methods or limits, and "
                 f"say what it means for this study (adding 'however' or 'therefore' does not count): {starts}")
    for c in res["lists"]:
        w.append(f"depth: a paragraph lists studies one after another ({', '.join('@' + k for k in c['keys'])}) "
                 f"without comparing them: '{' '.join(c['text'].split()[:7])} ...' - say how they relate, which "
                 "is stronger and why, and what that means for this study")
    for c in res["padded"][:3]:
        w.append(f"depth: a paragraph leans on connectives ({c['markers']} of however / moreover / therefore ...) but "
                 f"makes little real comparison or judgement: '{' '.join(c['text'].split()[:7])} ...' - connectives "
                 "do not make an argument; say how the sources differ, which is stronger and why")
    for r in res["summary_runs"]:
        w.append(f"depth: {len(r)} paragraphs in a row each summarise one source "
                 f"({', '.join('@' + c['keys'][0] for c in r)}): organise by theme and compare the studies")
    if chapter_type == "literature" and res["synthesis_share"] < 0.3:
        w.append(f"depth: only {int(res['synthesis_share'] * 100)}% of cited paragraphs bring two or more sources "
                 "together; synthesise (agreement, disagreement, trends) rather than list")
    return w, res


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("n", type=int)
    a = ap.parse_args()
    cfg = load_config()
    meta, body = read_front_matter(chapter_file(a.n))
    typ = meta.get("type") or (cfg["chapters"].get(a.n) or {}).get("type", "")
    w, res = warnings_for(body, typ)
    print(f"cited paragraphs {res['cited_paragraphs']} | descriptive {int(res['descriptive_share'] * 100)}% | "
          f"synthesis {int(res['synthesis_share'] * 100)}%")
    print("\n".join(w) or "depth: OK")


if __name__ == "__main__":
    main()
