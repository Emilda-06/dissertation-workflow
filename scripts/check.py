"""Quality gate for a chapter (or appendix): citations, references, figures, tables, structure, variety,
the project's guideline requirements (requirements/spec.yaml) and integrity checks.

Usage:
  check.py <chapter-number> [--json] [--no-integrity]
  check.py <appendix-letter>               e.g. check.py A
  check.py all

Exit code 0 = pass (warnings may still be printed), 2 = blocking errors that must be fixed before build.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import author_input
import critique
import guidelines
import integrity
import naturalness
import style
from chapterdoc import FIG_DEF, REF_USE, SEC_DEF, TBL_DEF, blocks, classify, word_count
from common import (appendix_file, chapter_dir, chapter_file, existing_appendices, existing_chapters,
                    find_citekeys, init_cli, load_config, load_library, load_verification, project,
                    read_front_matter)
from refs import fingerprint

PLACEHOLDER = re.compile(r"TODO-DATA|TODO-CHECK|\[\[CHECK|XX+%|\?\?\?")


def citation_checks(body: str, cfg: dict, n, lib: dict, ver: dict, errors: list, warnings: list) -> list[str]:
    refcfg = cfg.get("references", {})
    min_year = refcfg.get("min_year", 2016)
    target = refcfg.get("target_recent_share", 80)
    keys = find_citekeys(body)
    uniq = sorted(set(keys))
    for k in uniq:
        if k not in lib:
            errors.append(f"citation @{k} is not in the reference library")
            continue
        v = ver.get(k, {})
        st = v.get("status", "unchecked")
        if st == "retracted":
            errors.append(f"citation @{k} is RETRACTED; remove it and cite another source")
        elif st != "verified":
            errors.append(f"citation @{k} is not verified (status: {st})")
        elif v.get("fingerprint") and v["fingerprint"] != fingerprint(lib[k]):
            errors.append(f"citation @{k} was edited after it was verified; run refs.py verify --keys {k}")
    old = [k for k in uniq if k in lib and (ver.get(k, {}).get("year") or 9999) < min_year]
    old_unmarked = [k for k in old if not ver.get(k, {}).get("foundational")]
    if old_unmarked:
        warnings.append(f"pre-{min_year} sources ({', '.join('@' + k for k in old_unmarked)}): allowed, but prefer a "
                        f"recent source where one exists, or note why with refs.py mark-foundational")
    if uniq and 100 * (len(uniq) - len(old)) / len(uniq) < target:
        warnings.append(f"only {round(100 * (len(uniq) - len(old)) / len(uniq))}% of sources are from {min_year} "
                        f"onwards (target {target}%); add more recent sources")
    dois = {}
    for k in uniq:
        d = (lib.get(k) or {}).get("DOI")
        if d:
            if d.lower() in dois:
                warnings.append(f"@{k} and @{dois[d.lower()]} are the same paper (same DOI); use one key")
            dois[d.lower()] = k
    return keys


def structure_checks(body: str, folder: Path, errors: list, warnings: list) -> dict:
    figs = FIG_DEF.findall(body)
    fig_ids = [f[2] for f in figs]
    tbl_ids = [t for _, t in TBL_DEF.findall(body)]
    sec_ids = SEC_DEF.findall(body)
    defined = set(fig_ids) | set(tbl_ids) | set(sec_ids)
    alldef = fig_ids + tbl_ids + sec_ids
    for dup in sorted({x for x in alldef if alldef.count(x) > 1}):
        errors.append(f"label {dup} is defined more than once")
    for cap, path, fid in figs:
        if not (folder / path).exists():
            errors.append(f"figure {fid}: image file '{path}' not found (render the diagram first)")
        if len(cap.split()) < 5:
            warnings.append(f"figure {fid}: caption is too short to be descriptive")
    uses = REF_USE.findall(body)
    for u in sorted(set(uses)):
        if u not in defined and not u.startswith("app:"):
            errors.append(f"@{u} is referenced but never defined")
    for d in sorted(set(tbl_ids)):
        if d not in uses:
            warnings.append(f"{d} is never referred to in the text (add 'as shown in @{d}')")

    # every figure introduced before it appears and explained after it (diagram-standard.md)
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
    for c in re.findall(r"^:\s+(.+)$", body, re.M):
        if "#tbl:" not in c:
            warnings.append(f"table caption without label: '{c[:60]}'")

    heads = re.findall(r"^(#{1,6})\s+(.+)$", re.sub(r"```.*?```", "", body, flags=re.S), re.M)
    if any(len(h) == 1 for h, _ in heads):
        errors.append("use '##' for sections; '#' is reserved for the auto-generated chapter title")
    for h, t in heads:
        if re.match(r"^\d+(\.\d+)*\s", t):
            errors.append(f"heading '{t[:50]}' contains a manual number; numbers are added automatically")
    if any(len(h) > 4 for h, _ in heads):
        warnings.append("headings deeper than #### (x.x.x.x) are hard to read; flatten the structure")
    for m in sorted(set(PLACEHOLDER.findall(body))):
        warnings.append(f"placeholder '{m}' still in text (needs real data or checking)")
    return {"figs": figs, "tbl_ids": tbl_ids}


def variety_checks(body: str, meta: dict, keys: list, uniq: list, ver: dict, cfg: dict, s: dict,
                   warnings: list) -> dict:
    min_year = cfg.get("references", {}).get("min_year", 2016)
    bl = blocks(body)
    kinds = [classify(b) for b in bl]
    paras = [b for b, k in zip(bl, kinds) if k == "paragraph"]
    run = longest = 0
    for k in kinds:
        run = run + 1 if k == "paragraph" else (run if k == "heading" else 0)
        longest = max(longest, run)
    words = word_count(body)
    uncited = [p for p in paras if not find_citekeys(p) and not REF_USE.search(p) and len(p.split()) > 60]
    long_paras = [p for p in paras if len(p.split()) > 220]
    stats = {
        "words": words, "paragraphs": len(paras), "figures": len(s["figs"]), "tables": len(s["tbl_ids"]),
        "lists": kinds.count("list"), "citations": len(keys), "unique_sources": len(uniq),
        "recent_share": round(100 * sum(1 for k in uniq if (ver.get(k, {}).get("year") or 0) >= min_year)
                              / len(uniq)) if uniq else 0,
        "since": min_year, "longest_paragraph_run": longest, "uncited_long_paragraphs": len(uncited),
    }
    if longest > 6:
        warnings.append(f"{longest} plain paragraphs in a row; if part of it compares items, lists steps or describes a "
                        "structure, show that as a table, list or figure (do not add one just to break the text)")
    if words > 1500 and stats["figures"] + stats["tables"] < 2:
        warnings.append("fewer than 2 figures/tables for a chapter of this length")
    if long_paras:
        warnings.append(f"{len(long_paras)} paragraph(s) over 220 words; split them")
    if uncited and meta.get("type", "") in ("literature", "introduction", "methodology"):
        starts = "; ".join("'" + " ".join(u.split()[:7]) + " ...'" for u in uncited[:5])
        warnings.append(f"{len(uncited)} substantial paragraph(s) with no citation; check claims are supported: {starts}")
    return stats


def check_chapter(n: int, cfg: dict, run_integrity: bool = True) -> dict:
    meta, body = read_front_matter(chapter_file(n))
    lib, ver = load_library(), load_verification()
    errors, warnings = [], []
    keys = citation_checks(body, cfg, n, lib, ver, errors, warnings)
    uniq = sorted(set(keys))
    s = structure_checks(body, chapter_dir(n), errors, warnings)
    meta.setdefault("type", (cfg.get("chapters", {}).get(n) or {}).get("type", ""))
    stats = variety_checks(body, meta, keys, uniq, ver, cfg, s, warnings)

    # guideline / template requirements
    g = guidelines.evaluate(n, cfg, body)
    errors += g["errors"]
    warnings += g["warnings"]
    need = g.get("min_references") or (cfg.get("chapters", {}).get(n) or {}).get("min_references")
    if need and len(uniq) < need:
        warnings.append(f"only {len(uniq)} distinct sources; the chapter guideline requires at least {need}")
    stats["requirements_met"] = f"{sum(r['met'] for r in g['rows'])}/{len(g['rows'])}"

    if run_integrity:
        e, w = integrity.run_all(n, body, meta.get("type", ""), lib)
        errors += e
        warnings += w

    # critical depth, the project's writing style, and the author's own input
    w, depth = critique.warnings_for(body, meta.get("type", ""))
    warnings += w
    stats["descriptive_share"] = depth["descriptive_share"]
    stats["synthesis_share"] = depth["synthesis_share"]
    warnings += style.check_chapter(n)
    w, nat = naturalness.warnings_for(body, style.load())
    warnings += w
    stats["sentence_variation"] = nat.get("cv")
    warnings += author_input.chapter_warnings(n, body)
    return {"chapter": n, "errors": errors, "warnings": warnings, "stats": stats}


def check_appendix(letter: str, cfg: dict) -> dict:
    path = appendix_file(letter)
    _, body = read_front_matter(path)
    lib, ver = load_library(), load_verification()
    errors, warnings = [], []
    keys = citation_checks(body, cfg, letter, lib, ver, errors, warnings)
    s = structure_checks(body, path.parent, errors, warnings)
    stats = {"words": word_count(body), "figures": len(s["figs"]), "tables": len(s["tbl_ids"]),
             "unique_sources": len(set(keys)), "paragraphs": 0, "lists": 0, "recent_share": 0,
             "since": cfg.get("references", {}).get("min_year", 2016), "requirements_met": "-"}
    return {"chapter": f"appendix {letter}", "errors": errors, "warnings": warnings, "stats": stats}


def report(res: dict) -> None:
    s = res["stats"]
    print(f"== {str(res['chapter']).title() if isinstance(res['chapter'], str) else 'Chapter ' + str(res['chapter'])} ==")
    print(f"  {s['words']} words | {s['paragraphs']} paragraphs | {s['figures']} figures | {s['tables']} tables | "
          f"{s['lists']} lists | {s['unique_sources']} sources ({s['recent_share']}% from {s['since']} onwards)"
          f" | guideline requirements met {s.get('requirements_met', '-')}"
          + (f" | descriptive {int(s['descriptive_share'] * 100)}% / synthesis {int(s['synthesis_share'] * 100)}%"
             if 'descriptive_share' in s else ""))
    for e in res["errors"]:
        print(f"  ERROR   {e}")
    for w in res["warnings"]:
        print(f"  warning {w}")
    print("  PASS" if not res["errors"] else f"  FAIL ({len(res['errors'])} blocking error(s))")


def main():
    init_cli()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("chapter")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-integrity", action="store_true", help="skip copy/quote/data checks (faster)")
    args = p.parse_args()
    cfg = load_config()
    if args.chapter == "all":
        results = [check_chapter(n, cfg, not args.no_integrity) for n in existing_chapters()]
        results += [check_appendix(a, cfg) for a in existing_appendices()]
    elif re.fullmatch(r"[A-Za-z]", args.chapter):
        if not appendix_file(args.chapter).exists():
            p.error(f"{appendix_file(args.chapter)} does not exist")
        results = [check_appendix(args.chapter.upper(), cfg)]
    else:
        n = int(args.chapter)
        if not chapter_file(n).exists():
            p.error(f"{project().rel(chapter_file(n))} does not exist")
        results = [check_chapter(n, cfg, not args.no_integrity)]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            report(r)
    sys.exit(2 if any(r["errors"] for r in results) else 0)


if __name__ == "__main__":
    main()
