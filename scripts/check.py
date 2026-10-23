"""Quality gate for a chapter: citations, references, figures, tables, structure and variety.

Usage:
  check.py <chapter-number> [--json]
  check.py all

Exit code 0 = pass (warnings may still be printed), 2 = blocking errors that must be fixed before build.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

from common import (chapter_dir, chapter_file, existing_chapters, find_citekeys, load_config, load_library,
                    load_verification, read_front_matter, setup_stdout)

FIG_DEF = re.compile(r"!\[(.*?)\]\(([^)\s]+)[^)]*\)\{[^}]*#(fig:[\w\-]+)")
TBL_DEF = re.compile(r"^:\s+.*\{[^}]*#(tbl:[\w\-]+)", re.M)
SEC_DEF = re.compile(r"^#{2,6}\s.*\{[^}]*#(sec:[\w\-]+)", re.M)
REF_USE = re.compile(r"(?<![\w#])@((?:fig|tbl|sec):[\w\-]+)")
PLACEHOLDER = re.compile(r"TODO-DATA|TODO-CHECK|\[\[CHECK|XX+%|\?\?\?")


def blocks(body: str) -> list[str]:
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    return [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]


def classify(b: str) -> str:
    if b.startswith("#"):
        return "heading"
    if b.startswith("!["):
        return "figure"
    if b.startswith("|") or b.startswith("+-") or re.match(r"^:\s", b):
        return "table"
    if re.match(r"^\s*([-*+]|\d+[.)])\s", b):
        return "list"
    if b.startswith(">"):
        return "quote"
    if b.startswith(":::") or b.startswith("<!--"):
        return "other"
    return "paragraph"


def check_chapter(n: int, cfg: dict) -> dict:
    meta, body = read_front_matter(chapter_file(n))
    lib, ver = load_library(), load_verification()
    refcfg = cfg.get("references", {})
    min_year = refcfg.get("min_year", 2016)
    target = refcfg.get("target_recent_share", 80)
    errors, warnings = [], []

    # --- citations
    keys = find_citekeys(body)
    uniq = sorted(set(keys))
    for k in uniq:
        if k not in lib:
            errors.append(f"citation @{k} is not in the reference library")
        elif ver.get(k, {}).get("status") != "verified":
            errors.append(f"citation @{k} is not verified (status: {ver.get(k, {}).get('status', 'unchecked')})")
    old = [k for k in uniq if k in lib and (ver.get(k, {}).get("year") or 9999) < min_year]
    old_unmarked = [k for k in old if not ver.get(k, {}).get("foundational")]
    if old_unmarked:
        warnings.append(f"pre-{min_year} sources ({', '.join('@' + k for k in old_unmarked)}): allowed, but prefer a "
                        f"recent source where one exists, or note why with refs.py mark-foundational")
    need = (cfg.get("chapters", {}).get(n) or {}).get("min_references")
    if need and len(uniq) < need:
        warnings.append(f"only {len(uniq)} distinct sources; the chapter guideline requires at least {need}")
    if uniq and 100 * (len(uniq) - len(old)) / len(uniq) < target:
        warnings.append(f"only {round(100 * (len(uniq) - len(old)) / len(uniq))}% of sources are from {min_year} onwards "
                        f"(target {target}%); add more recent sources")
    dois = {}
    for k in uniq:
        d = (lib.get(k) or {}).get("DOI")
        if d:
            if d.lower() in dois:
                warnings.append(f"@{k} and @{dois[d.lower()]} are the same paper (same DOI); use one key")
            dois[d.lower()] = k

    # --- figures / tables / sections
    figs = FIG_DEF.findall(body)
    fig_ids = [f[2] for f in figs]
    tbl_ids = TBL_DEF.findall(body)
    sec_ids = SEC_DEF.findall(body)
    defined = set(fig_ids) | set(tbl_ids) | set(sec_ids)
    for dup in {x for x in fig_ids + tbl_ids + sec_ids if (fig_ids + tbl_ids + sec_ids).count(x) > 1}:
        errors.append(f"label {dup} is defined more than once")
    for cap, path, fid in figs:
        if not (chapter_dir(n) / path).exists():
            errors.append(f"figure {fid}: image file '{path}' not found (render the diagram first)")
        if len(cap.split()) < 5:
            warnings.append(f"figure {fid}: caption is too short to be descriptive")
    uses = REF_USE.findall(body)
    for u in sorted(set(uses)):
        if u not in defined:
            errors.append(f"@{u} is referenced but never defined")
    for d in sorted(set(tbl_ids)):
        if d not in uses:
            warnings.append(f"{d} is never referred to in the text (add 'as shown in @{d}')")

    # --- every figure introduced before it appears and explained after it (diagram-standard.md)
    bl_all = blocks(body)
    for idx, b in enumerate(bl_all):
        fm = FIG_DEF.search(b)
        if not fm or not b.startswith("!["):
            continue
        fid = fm.group(3)
        nxt = bl_all[idx + 1] if idx + 1 < len(bl_all) else ""
        if not any(f"@{fid}" in x for x in bl_all[:idx]) and f"@{fid}" not in nxt:
            errors.append(f"{fid} is not introduced in the text; refer to it (e.g. '@{fid} shows ...') just before it")
        if not nxt or classify(nxt) in ("heading", "figure", "table"):
            what = "the end of the chapter" if not nxt else f"a {classify(nxt)}"
            errors.append(f"{fid} is followed directly by {what}; add a paragraph explaining what the figure shows")
        discussed = sum(len(x.split()) for x in bl_all if f"@{fid}" in x and classify(x) in ("paragraph", "list"))
        if discussed < 40:
            errors.append(f"{fid}: the text that discusses it is only {discussed} words; explain its parts, "
                          "how to read it and what it shows (at least 40 words in paragraphs that cite @" + fid + ")")
    unlabeled_imgs = len(re.findall(r"!\[.*?\]\([^)]+\)(?!\{)", body))
    if unlabeled_imgs:
        warnings.append(f"{unlabeled_imgs} image(s) have no {{#fig:...}} label")
    caption_lines = re.findall(r"^:\s+(.+)$", body, re.M)
    for c in caption_lines:
        if "#tbl:" not in c:
            warnings.append(f"table caption without label: '{c[:60]}'")

    # --- headings
    heads = re.findall(r"^(#{1,6})\s+(.+)$", body, re.M)
    if any(len(h) == 1 for h, _ in heads):
        errors.append("use '##' for sections; '#' is reserved for the auto-generated chapter title")
    for h, t in heads:
        if re.match(r"^\d+(\.\d+)*\s", t):
            errors.append(f"heading '{t[:50]}' contains a manual number; numbers are added automatically")
    if any(len(h) > 4 for h, _ in heads):
        warnings.append("headings deeper than #### (x.x.x.x) are hard to read; flatten the structure")

    # --- placeholders
    for m in sorted(set(PLACEHOLDER.findall(body))):
        warnings.append(f"placeholder '{m}' still in text (needs real data or checking)")

    # --- variety and density
    bl = blocks(body)
    kinds = [classify(b) for b in bl]
    paras = [b for b, k in zip(bl, kinds) if k == "paragraph"]
    run = longest = 0
    for k in kinds:
        run = run + 1 if k == "paragraph" else (run if k == "heading" else 0)
        longest = max(longest, run)
    words = sum(len(re.sub(r"[@\[\]{}#*_]", " ", b).split()) for b in bl if classify(b) != "heading")
    uncited = [p for p in paras if not find_citekeys(p) and not REF_USE.search(p) and len(p.split()) > 60]
    long_paras = [p for p in paras if len(p.split()) > 220]
    stats = {
        "words": words, "paragraphs": len(paras), "figures": len(figs), "tables": len(tbl_ids),
        "lists": kinds.count("list"), "citations": len(keys), "unique_sources": len(uniq),
        "recent_share": round(100 * sum(1 for k in uniq if (ver.get(k, {}).get("year") or 0) >= min_year)
                              / len(uniq)) if uniq else 0,
        "since": min_year, "longest_paragraph_run": longest, "uncited_long_paragraphs": len(uncited),
    }
    if longest > 6:
        warnings.append(f"{longest} plain paragraphs in a row; break them up with a table, figure or list")
    if words > 1500 and stats["figures"] + stats["tables"] < 2:
        warnings.append("fewer than 2 figures/tables for a chapter of this length")
    if long_paras:
        warnings.append(f"{len(long_paras)} paragraph(s) over 220 words; split them")
    if uncited and meta.get("type", "") in ("literature", "introduction", "methodology"):
        starts = "; ".join("'" + " ".join(u.split()[:7]) + " ...'" for u in uncited[:5])
        warnings.append(f"{len(uncited)} substantial paragraph(s) with no citation; check claims are supported: {starts}")
    return {"chapter": n, "errors": errors, "warnings": warnings, "stats": stats}


def report(res: dict) -> None:
    s = res["stats"]
    print(f"== Chapter {res['chapter']} ==")
    print(f"  {s['words']} words | {s['paragraphs']} paragraphs | {s['figures']} figures | {s['tables']} tables | "
          f"{s['lists']} lists | {s['unique_sources']} sources ({s['recent_share']}% from {s['since']} onwards)")
    for e in res["errors"]:
        print(f"  ERROR   {e}")
    for w in res["warnings"]:
        print(f"  warning {w}")
    print("  PASS" if not res["errors"] else f"  FAIL ({len(res['errors'])} blocking error(s))")


def main():
    setup_stdout()
    cfg = load_config()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("chapter")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    nums = existing_chapters() if args.chapter == "all" else [int(args.chapter)]
    results = [check_chapter(n, cfg) for n in nums]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            report(r)
    sys.exit(2 if any(r["errors"] for r in results) else 0)


if __name__ == "__main__":
    main()
