"""Dashboard of the active project: every chapter's progress, length, sources, requirements and versions.

Usage:  status.py [--html] [--all-projects]
  --html          also write projects/<name>/output/status.html (open it in a browser)
  --all-projects  one line per project
"""
from __future__ import annotations

import argparse
import html
import re
from datetime import datetime

import check
import guidelines
from common import (chapter_dir, chapter_file, chapter_slug, init_cli, latest_version, list_projects,
                    load_config, project, read_front_matter, select_project)
from defaults import defaults_for


def chapter_row(n: int, cfg: dict) -> dict:
    plan = cfg["chapters"].get(n) or {}
    row = {"n": n, "title": plan.get("title", f"Chapter {n}"), "type": plan.get("type", ""), "exists": False}
    sp = chapter_dir(n) / "state.json"
    if sp.exists():
        import json
        cur = json.loads(sp.read_text(encoding="utf-8")).get("current")
        row["run"] = f"{cur['mode']} in progress" if cur else ""
    if not chapter_file(n).exists():
        return row
    meta, body = read_front_matter(chapter_file(n))
    res = check.check_chapter(n, cfg, run_integrity=False)
    s = res["stats"]
    target = (((guidelines.load_spec() or {}).get("chapters") or {}).get(n) or {}).get("words") \
        or plan.get("words") or defaults_for(row["type"])["words"]
    latest = latest_version(chapter_dir(n) / "docs", chapter_slug(n))
    fb = [f for f in project().feedback.glob("*") if f.is_file() and latest and f.stat().st_mtime > latest.stat().st_mtime
          and re.search(rf"(ch(apter)?[\s_\-]*0?{n}\b)", f.name, re.I)] if project().feedback.exists() else []
    rep = chapter_dir(n) / "similarity_report.md"
    sim = re.search(r"Estimated similarity: ([\d.]+)%", rep.read_text(encoding="utf-8")) if rep.exists() else None
    row.update({"similarity": f"{sim.group(1)}%" if sim else "-", "exists": True, "status": meta.get("status", ""), "words": s["words"], "target": target,
                "sources": s["unique_sources"], "recent": s["recent_share"], "figures": s["figures"],
                "tables": s["tables"], "requirements": s.get("requirements_met", "-"),
                "todo": len(re.findall(r"TODO-DATA", body)), "errors": len(res["errors"]),
                "warnings": len(res["warnings"]), "version": latest.name if latest else "-",
                "new_feedback": [f.name for f in fb]})
    return row


def text_report(rows: list[dict], cfg: dict) -> str:
    p = project()
    out = [f"Project: {p.slug} - {(cfg.get('project') or {}).get('title', '')}", ""]
    hdr = (f"{'#':>2} {'Chapter':<34} {'Words / target':<18} {'Src':>4} {'Rec%':>4} {'Req':>6} {'TODO':>4} "
           f"{'Err':>3} {'Sim':>6}  Version")
    out += [hdr, "-" * len(hdr)]
    for r in rows:
        if not r["exists"]:
            out.append(f"{r['n']:>2} {r['title'][:34]:<34} not written" + (f"  ({r.get('run')})" if r.get("run") else ""))
            continue
        wt = f"{r['words']:,} / {r['target'][0]:,}-{r['target'][1]:,}"
        out.append(f"{r['n']:>2} {r['title'][:34]:<34} {wt:<18} {r['sources']:>4} {r['recent']:>4} "
                   f"{r['requirements']:>6} {r['todo']:>4} {r['errors']:>3} {r['similarity']:>6}  {r['version']}"
                   + (f"  ({r['run']})" if r.get("run") else "")
                   + (f"  NEW FEEDBACK: {', '.join(r['new_feedback'])}" if r["new_feedback"] else ""))
    st = guidelines.spec_status(cfg)
    out += ["", "Guidelines: " + ("no spec" if not st["exists"] else ("approved" if st["approved"] else "spec NOT approved"))
            + (f"; STALE ({', '.join(st['stale'])})" if st["stale"] else "")
            + (f"; {len(st['review'])} mapping decision(s) needed" if st["review"] else "")]
    return "\n".join(out)


def html_report(rows: list[dict], cfg: dict) -> str:
    p = project()
    title = html.escape((cfg.get("project") or {}).get("title", p.slug))
    trs = []
    for r in rows:
        if not r["exists"]:
            trs.append(f"<tr class='muted'><td>{r['n']}</td><td>{html.escape(r['title'])}</td>"
                       f"<td colspan='7'>not written {html.escape(r.get('run') or '')}</td></tr>")
            continue
        lo, hi = r["target"]
        pct = min(100, round(100 * r["words"] / lo)) if lo else 0
        trs.append(
            f"<tr><td>{r['n']}</td><td>{html.escape(r['title'])}<div class='sub'>{html.escape(r['status'])}</div></td>"
            f"<td><div class='bar'><span style='width:{pct}%'></span></div>{r['words']:,} / {lo:,}-{hi:,}</td>"
            f"<td>{r['sources']} ({r['recent']}% recent)</td><td>{r['figures']} / {r['tables']}</td>"
            f"<td>{r['requirements']}</td><td class='{'bad' if r['todo'] else ''}'>{r['todo']}</td>"
            f"<td class='{'bad' if r['errors'] else ''}'>{r['errors']} / {r['warnings']}</td>"
            f"<td>{html.escape(r['version'])}{'<div class=bad>new feedback</div>' if r['new_feedback'] else ''}</td></tr>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Dissertation status</title>
<style>
:root{{--bg:#fff;--fg:#1b1b1b;--muted:#6b6b6b;--line:#e3e3e3;--accent:#2f6fde;--bad:#c0392b}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16181c;--fg:#e8e8e8;--muted:#9a9a9a;--line:#2c2f36;--accent:#6ea0ff;--bad:#ff7b6b}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px}}
h1{{font-size:20px;margin:0 0 4px}} .sub,.muted{{color:var(--muted);font-size:13px}}
.wrap{{max-width:1100px;margin:auto;overflow-x:auto}} table{{border-collapse:collapse;width:100%;margin-top:16px}}
th,td{{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;color:var(--muted)}} .bad{{color:var(--bad);font-weight:600}}
.bar{{height:6px;background:var(--line);border-radius:3px;margin-bottom:4px;min-width:90px}}
.bar span{{display:block;height:6px;background:var(--accent);border-radius:3px}}
</style></head><body><div class="wrap"><h1>{title}</h1>
<div class="sub">Project {html.escape(p.slug)} - generated {datetime.now():%Y-%m-%d %H:%M}</div>
<table><tr><th>#</th><th>Chapter</th><th>Words / target</th><th>Sources</th><th>Fig / Tab</th>
<th>Guideline req.</th><th>TODO-DATA</th><th>Errors / warnings</th><th>Latest version</th></tr>
{''.join(trs)}</table></div></body></html>"""


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--all-projects", action="store_true")
    a = ap.parse_args()
    if a.all_projects:
        for slug in list_projects():
            select_project(slug)
            cfg = load_config()
            rows = [chapter_row(n, cfg) for n in sorted(cfg["chapters"])]
            written = [r for r in rows if r["exists"]]
            words = sum(r["words"] for r in written)
            print(f"{slug:<24} {len(written)}/{len(rows)} chapters, {words:,} words  "
                  f"{(cfg.get('project') or {}).get('title', '')}")
        return
    cfg = load_config()
    rows = [chapter_row(n, cfg) for n in sorted(cfg["chapters"])]
    print(text_report(rows, cfg))
    if a.html:
        out = project().output / "status.html"
        out.write_text(html_report(rows, cfg), encoding="utf-8")
        print(f"\nwrote {project().rel(out)}")


if __name__ == "__main__":
    main()
