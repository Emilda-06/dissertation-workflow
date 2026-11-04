"""Similarity report before submission: which sentences match a source or your earlier work, and how to fix them.

Usage:  similarity.py <n> | all [--html]

For each chapter: an estimated similarity percentage (the share of the chapter's own prose that matches a
source; quotations, citations and the reference list are excluded, as Turnitin can exclude them), the
sources it comes from, and every flagged sentence next to the source sentence it resembles.
Writes output/chapters/chapter_<n>/similarity_report.md (and similarity_report.html with --html).

The estimate covers the sources this project knows (downloaded full texts, search abstracts, your files
in existing/). Turnitin compares with far more, so treat it as a lower bound and fix every flag.
"""
from __future__ import annotations

import argparse
import html
from datetime import datetime

import integrity
import textsim
from common import (chapter_dir, chapter_file, die, existing_chapters, init_cli, load_config, project,
                    read_front_matter)

FIX = {
    "verbatim": "Rewrite the idea from your notes (not from the source), or quote it exactly with a page number.",
    "paraphrase": "Same structure as the source with words swapped. Close the source, re-express the point in your "
                  "own order, combine it with another source or your evaluation, and keep the citation.",
    "own": "Re-used from your earlier submission: cite your earlier work, or write the passage afresh.",
}


def analyse(n: int, corpus) -> dict:
    _, body = read_front_matter(chapter_file(n))
    matches, total = textsim.scan_text(body, corpus, threshold=integrity.PARA_WARN)
    flagged_words = sum(len(m.sentence.split()) for m in matches)
    by_source: dict[str, int] = {}
    for m in matches:
        by_source[m.source] = by_source.get(m.source, 0) + len(m.sentence.split())
    return {"chapter": n, "total_words": total, "flagged_words": flagged_words,
            "percent": round(100 * flagged_words / total, 1) if total else 0.0,
            "by_source": sorted(by_source.items(), key=lambda kv: -kv[1]), "matches": matches,
            "sources_known": len(corpus.docs)}


def markdown(res: dict) -> str:
    n = res["chapter"]
    lines = [f"# Similarity report - Chapter {n}", "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M}. Compared with {res['sources_known']} known source(s).", "",
             f"**Estimated similarity: {res['percent']}%** ({res['flagged_words']} of {res['total_words']} words of "
             "your own prose; quotations and citations excluded).", ""]
    if res["by_source"]:
        lines += ["| Source | Words matched | Share |", "|---|---|---|"]
        for src, w in res["by_source"]:
            lines.append(f"| {src} | {w} | {100 * w / res['total_words']:.1f}% |")
        lines.append("")
    if not res["matches"]:
        lines.append("No sentence matches a known source. Turnitin compares with more sources than this check, so "
                     "keep writing from your notes and quoting exactly.")
    for i, m in enumerate(res["matches"], 1):
        page = f", p. {m.page}" if m.page else ""
        lines += [f"## {i}. {m.kind} ({m.score:.0%}) - {m.source}{page}", "",
                  f"- **Your sentence:** {m.sentence}", f"- **Source:** {m.source_text[:400]}",
                  f"- **Fix:** {FIX[m.kind]}", ""]
    lines += ["", "_The percentage covers only the sources this project has downloaded or searched; Turnitin's "
              "database is much larger. Treat it as a lower bound._"]
    return "\n".join(lines) + "\n"


def html_page(res: dict) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(m.kind)}<br><b>{m.score:.0%}</b></td><td>{html.escape(m.sentence)}</td>"
        f"<td>{html.escape(m.source_text[:400])}<div class='sub'>{html.escape(m.source)}"
        f"{', p. ' + str(m.page) if m.page else ''}</div></td><td>{html.escape(FIX[m.kind])}</td></tr>"
        for m in res["matches"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Similarity report</title>
<style>:root{{--bg:#fff;--fg:#1b1b1b;--muted:#6b6b6b;--line:#e3e3e3;--bad:#c0392b}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16181c;--fg:#e8e8e8;--muted:#9a9a9a;--line:#2c2f36;--bad:#ff7b6b}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px}}
.wrap{{max-width:1100px;margin:auto;overflow-x:auto}} table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}}
.sub{{color:var(--muted);font-size:13px;margin-top:4px}} .big{{font-size:28px;font-weight:700}}</style></head>
<body><div class="wrap"><h1>Chapter {res['chapter']}: similarity</h1>
<div class="big">{res['percent']}%</div><div class="sub">{res['flagged_words']} of {res['total_words']} words;
{res['sources_known']} known sources; a lower bound of what Turnitin may report</div>
<table><tr><th>Type</th><th>Your sentence</th><th>Source</th><th>How to fix</th></tr>{rows or
'<tr><td colspan=4>No matches.</td></tr>'}</table></div></body></html>"""


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chapter")
    ap.add_argument("--html", action="store_true")
    a = ap.parse_args()
    load_config()
    nums = existing_chapters() if a.chapter == "all" else [int(a.chapter)]
    missing = [n for n in nums if not chapter_file(n).exists()]
    if missing:
        die(f"chapter {missing[0]} has no chapter.md in project '{project().slug}'")
    corpus = textsim.build_corpus()
    print(f"[project: {project().slug}]  compared with {len(corpus.docs)} source(s)")
    for n in nums:
        res = analyse(n, corpus)
        out = chapter_dir(n) / "similarity_report.md"
        out.write_text(markdown(res), encoding="utf-8")
        if a.html:
            (chapter_dir(n) / "similarity_report.html").write_text(html_page(res), encoding="utf-8")
        kinds = {k: sum(m.kind == k for m in res["matches"]) for k in FIX}
        print(f"chapter {n}: {res['percent']}% estimated similarity | {kinds['verbatim']} copied, "
              f"{kinds['paraphrase']} close paraphrase, {kinds['own']} from your earlier work -> {project().rel(out)}")


if __name__ == "__main__":
    main()
