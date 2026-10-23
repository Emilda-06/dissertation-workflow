"""Import an existing Word chapter into the workflow so it can be edited and rebuilt.

Usage:
  import_docx.py <path/to/chapter.docx> <chapter-number> [--title "Literature Review"] [--overwrite]

What it does:
  1. Converts the .docx to output/chapters/chapter_<n>/chapter.md (images -> output/chapters/chapter_<n>/diagrams/imported/).
  2. Strips manual heading numbers (the build adds 1.1 / 1.1.1 automatically) and the old TOC.
  3. Reads the old reference list, finds each reference's DOI (Crossref), adds and verifies it.
  4. Converts typed Harvard citations - (Smith, 2020), Smith et al. (2021) - into linked citations.
  5. Converts "Figure 2.1: ..." / "Table 2.1: ..." captions into auto-numbered, cross-referenced ones.
  6. Writes output/chapters/chapter_<n>/import_report.md listing anything it could not resolve, for manual review.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from rapidfuzz import fuzz

from common import (ensure_zotero, NUMBER_WORDS, ROOT, chapter_dir, chapter_file, chapter_title, die, ensure_chapter_dirs,
                    entry_year, first_author_family, http_get, load_config, load_library, normalize_title,
                    realign_grid_tables, require_tool, setup_stdout, write_front_matter)
import refs

REF_HEADINGS = re.compile(r"^(references?|reference list|bibliography|works cited)$", re.I)
SURNAME = r"[A-Z][A-Za-z'À-ſ\-]+(?:\s(?:van|von|de|der|da|del|le)\s[A-Z][A-Za-z'\-]+)?"


def pandoc_import(docx: Path, chapter_folder: Path) -> str:
    r = subprocess.run([require_tool("pandoc"), str(docx), "-t",
                        "markdown-simple_tables-multiline_tables+pipe_tables-raw_html-bracketed_spans-native_spans-link_attributes",
                        "--wrap=none", "--extract-media=diagrams/imported", "--markdown-headings=atx"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=chapter_folder)
    if r.returncode != 0:
        die(r.stderr)
    return r.stdout


def clean_heading_text(t: str) -> str:
    t = re.sub(r"\{[^}]*\}\s*$", "", t)            # pandoc ids like {#introduction .unnumbered}
    t = re.sub(r"[*_]{1,3}", "", t).strip()
    return t


def split_sections(md: str, n: int):
    """Normalise headings; return (body_lines, reference_strings, removed_front, detected_title)."""
    lines = md.splitlines()
    out, refs_lines, removed, title = [], [], [], None
    in_refs = False
    started = False
    heading_re = re.compile(r"^(#{1,6})\s+(.*)$")
    bold_heading_re = re.compile(r"^\*\*(\d+(?:\.\d+)+)\s*\.?\s+(.+?)\*\*\s*$")
    # If the chapter title is a level-1 heading, unnumbered '##' headings are already sections (x.1);
    # otherwise the document's '#' headings are its sections and must move down one level.
    h1_texts = [clean_heading_text(m.group(2)) for l in lines if (m := heading_re.match(l)) and len(m.group(1)) == 1]
    shift = 0 if any(re.match(r"^chapter\b", t, re.I) for t in h1_texts) or len(h1_texts) <= 1 else 1
    for line in lines:
        m = heading_re.match(line)
        b = None if m else bold_heading_re.match(line)
        if m or b:
            text = clean_heading_text(m.group(2) if m else f"{b.group(1)} {b.group(2)}")
            plain = re.sub(r"^\d+(\.\d+)*\.?\s*", "", text).strip()
            if not plain or plain.startswith("!["):       # empty or logo-only headings from title pages
                if not started:
                    removed.append(line)
                continue
            if re.match(r"^chapter\s+(\w+)\s*[:.\-–—]?\s*(.*)$", text, re.I):
                cm = re.match(r"^chapter\s+(\w+)\s*[:.\-–—]?\s*(.*)$", text, re.I)
                title = title or (cm.group(2).strip() or None)
                started = True
                continue
            if REF_HEADINGS.match(plain):
                in_refs = True
                started = True
                continue
            if re.match(r"^(table of contents|contents|list of figures|list of tables)$", plain, re.I):
                in_refs = False
                started = False
                removed.append(line)
                continue
            in_refs = False
            numm = re.match(r"^(\d+(?:\.\d+)*)\.?\s+", text)
            if numm:
                depth = numm.group(1).count(".") + 1
                level = min(max(depth, 2), 5)
                started = True
            else:
                level = min(max(len(m.group(1)) + shift if m else 2, 2), 5)
                if not started and title is None and len(plain) < 80:
                    title = plain
                    started = True
                    continue
            out.append(f"{'#' * level} {plain}")
            continue
        if in_refs:
            if line.strip():
                refs_lines.append(line.strip())
            continue
        if not started:
            if line.strip():
                removed.append(line)
            continue
        out.append(line)
    refs_clean = [re.sub(r"^\s*(\d+[.)]|[-*])\s+", "", r) for r in refs_lines]
    refs_clean = [re.sub(r"[*_]{1,2}", "", r).replace("\\", "") for r in refs_clean if len(r) > 25]
    return out, refs_clean, removed, title


def ref_surname_year(ref: str) -> tuple[str, str]:
    m = re.match(rf"^\s*({SURNAME})", ref)
    y = re.search(r"\((\d{4}[a-z]?)\)|\b((?:19|20)\d{2}[a-z]?)\b", ref)
    return (m.group(1) if m else ""), ((y.group(1) or y.group(2)) if y else "")


def resolve_reference(ref: str, cfg: dict) -> tuple[str | None, str]:
    """Return (doi, note). Only accepts a match whose title clearly appears in the reference string."""
    m = re.search(r"\b(10\.\d{4,9}/[^\s\"<>]+)", ref)
    if m:
        return m.group(1).rstrip(".,;)"), "DOI in reference"
    r = http_get("https://api.crossref.org/works", cfg,
                 params={"query.bibliographic": ref[:400], "rows": 3, "select": "DOI,title,issued,author"})
    if r is None or r.status_code != 200:
        return None, "Crossref lookup failed"
    _, year = ref_surname_year(ref)
    norm_ref = normalize_title(ref)
    for it in r.json().get("message", {}).get("items", []):
        t = normalize_title((it.get("title") or [""])[0])
        if len(t) < 12:
            continue
        sim = fuzz.partial_ratio(t, norm_ref)
        iy = str(((it.get("issued") or {}).get("date-parts") or [[None]])[0][0])
        if sim >= 92 and (not year or year[:4] == iy or abs(int(year[:4]) - int(iy or 0)) <= 1):
            return it["DOI"], f"matched by title ({sim:.0f}%)"
    return None, "no confident match in Crossref"


def coauthor_match(key: str, names: list[str], etal: bool) -> bool:
    e = load_library().get(key) or {}
    fams = [normalize_title(a.get("family") or a.get("literal") or "") for a in (e.get("author") or [])]
    if etal:
        return len(fams) >= 3
    if len(names) == 1:
        return len(fams) == 1
    return len(fams) == len(names) and all(normalize_title(n) in fams for n in names)


def in_library(ref: str) -> str | None:
    surname, year = ref_surname_year(ref)
    norm = normalize_title(ref)
    for k, e in load_library().items():
        t = normalize_title(e.get("title") or "")
        if (normalize_title(first_author_family(e)) == normalize_title(surname) and str(entry_year(e)) == year[:4]
                and len(t) > 12 and fuzz.partial_ratio(t, norm) >= 90):
            return k
    return None


def build_author_year_index() -> dict[tuple[str, str], list[str]]:
    idx: dict[tuple[str, str], list[str]] = {}
    for k, e in load_library().items():
        fam = normalize_title(first_author_family(e))
        y = str(entry_year(e) or "")
        if fam and y:
            idx.setdefault((fam, y), []).append(k)
    return idx


def convert_citations(text: str, index, unresolved: list[str]) -> str:
    def lookup(name: str, year: str, full: str = "") -> str | None:
        keys = index.get((normalize_title(name), year[:4]))
        if not keys:
            return None
        if len(keys) == 1:
            return keys[0]
        names = re.findall(SURNAME, re.sub(r"\b(?:19|20)\d{2}[a-z]?.*$", "", full)) or [name]
        narrowed = [k for k in keys if coauthor_match(k, names, "et al" in full)]
        if len(narrowed) == 1:
            return narrowed[0]
        if len(year) == 5:                        # 2020a / 2020b -> order of keys
            i = ord(year[4]) - ord("a")
            return sorted(keys)[i] if i < len(keys) else None
        return None

    def paren(m):
        inner = m.group(1)
        parts = [p.strip() for p in inner.split(";")]
        cites = []
        for p in parts:
            pm = re.match(rf"^(?:e\.g\.,?\s*|see\s+|cf\.\s*)?({SURNAME})(?:\s*(?:,|&|and)\s*{SURNAME})*(?:\s+et\s+al\.?)?,?\s+((?:19|20)\d{{2}}[a-z]?)(?:,\s*(pp?\.\s*[\d–\-]+))?$", p)
            if not pm:
                return m.group(0)
            key = lookup(pm.group(1), pm.group(2), p)
            if not key:
                unresolved.append(p)
                return m.group(0)
            cites.append(f"@{key}" + (f", {pm.group(3)}" if pm.group(3) else ""))
        return "[" + "; ".join(cites) + "]"

    text = re.sub(r"\(([^()]*?\b(?:19|20)\d{2}[a-z]?[^()]*?)\)", paren, text)

    def narrative(m):
        key = lookup(m.group(1), m.group(2), m.group(0))
        if not key:
            unresolved.append(m.group(0))
            return m.group(0)
        return f"@{key}"

    text = re.sub(rf"\b({SURNAME})(?:\s+(?:and|&)\s+{SURNAME}|\s+et\s+al\.?)?\s+\(((?:19|20)\d{{2}}[a-z]?)\)",
                  narrative, text)
    return text


def convert_captions(lines: list[str], n: int, notes: list[str]) -> list[str]:
    """Image followed/preceded by 'Figure x.y: caption' -> labelled figure; 'Table x.y: caption' -> pandoc table caption."""
    out = list(lines)
    fig_map: dict[str, str] = {}
    tbl_map: dict[str, str] = {}
    cap_re = re.compile(r"^\s*\**\s*(Figure|Fig\.|Table)\s+(\d+[.\-]\d+)\s*[:.\-–]?\s*\**\s*(.+?)\s*\**\s*$", re.I)
    img_re = re.compile(r"^!\[(.*?)\]\(([^)]+)\)(\{[^}]*\})?\s*$")
    i = 0
    while i < len(out):
        cm = cap_re.match(out[i])
        if cm:
            kind, num, cap = cm.group(1).lower(), cm.group(2), cm.group(3).strip().rstrip(".")
            if kind.startswith("fig"):
                # nearest image within 3 non-empty lines either side
                for j in [k for k in range(i - 3, i + 4) if 0 <= k < len(out) and k != i]:
                    im = img_re.match(out[j].strip())
                    if im:
                        lab = f"fig:{n}-{len(fig_map) + 1}"
                        fig_map[num] = lab
                        out[j] = f"![{cap}.]({im.group(2)}){{#{lab} width=90%}}"
                        out[i] = ""
                        break
                else:
                    notes.append(f"caption without image: {out[i][:80]}")
            else:
                # table caption: find the next table block and put the caption after it
                for j in range(i + 1, min(i + 4, len(out))):
                    if out[j].lstrip().startswith(("|", "+-")):
                        end = j
                        while end < len(out) and out[end].strip():
                            end += 1
                        lab = f"tbl:{n}-{len(tbl_map) + 1}"
                        tbl_map[num] = lab
                        out.insert(end, "")
                        out.insert(end + 1, f": {cap}. {{#{lab}}}")
                        out[i] = ""
                        break
                else:
                    notes.append(f"table caption without a detectable table: {out[i][:80]}")
        i += 1
    text = "\n".join(out)
    for num, lab in fig_map.items():
        text = re.sub(rf"\b(?:Figure|Fig\.)\s+{re.escape(num)}\b", f"@{lab}", text)
    for num, lab in tbl_map.items():
        text = re.sub(rf"\bTable\s+{re.escape(num)}\b", f"@{lab}", text)
    leftover = re.findall(r"!\[.*?\]\([^)]+\)(?!\{)", text)
    if leftover:
        notes.append(f"{len(leftover)} image(s) had no recognisable caption; add a caption and {{#fig:...}} label")
    return text.splitlines()


def main():
    setup_stdout()
    cfg = load_config()
    ensure_zotero(cfg)            # workflow rule: Zotero must be open
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("docx")
    p.add_argument("chapter", type=int)
    p.add_argument("--title")
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    n = args.chapter
    src = Path(args.docx).resolve()
    if not src.exists():
        die(f"{src} not found")
    if chapter_file(n).exists() and not args.overwrite:
        die(f"{chapter_file(n)} already exists (use --overwrite)")
    d = ensure_chapter_dirs(n)
    md = pandoc_import(src, d)
    md = re.sub(r"\]\(<?(diagrams/imported/[^)>]+)>?\)", r"](\1)", md)
    md = re.sub(r"\{width=[^}]*\}", "", md)

    body_lines, ref_strings, removed, detected_title = split_sections(md, n)
    notes: list[str] = []

    print(f"Resolving {len(ref_strings)} references from the old reference list ...")
    report_refs = []
    for ref in ref_strings:
        key = in_library(ref)
        if key:
            report_refs.append((ref, key, "already in library"))
            continue
        doi, how = resolve_reference(ref, cfg)
        if doi:
            entry_doi = refs.clean_doi(doi)
            refs.cmd_add(argparse.Namespace(doi=[entry_doi], chapter=n), cfg)
            lib = load_library()
            key = next((k for k, e in lib.items() if (e.get("DOI") or "").lower() == entry_doi.lower()), None)
        else:
            key = None
        report_refs.append((ref, key, how if key else (how if not doi else "DOI did not resolve")))

    index = build_author_year_index()
    unresolved: list[str] = []
    body = convert_citations("\n".join(body_lines), index, unresolved)
    body_lines = convert_captions(body.splitlines(), n, notes)
    body = realign_grid_tables(re.sub(r"\n{3,}", "\n\n", "\n".join(body_lines)).strip()) + "\n"

    title = args.title or detected_title or chapter_title(cfg, n)
    title = re.sub(r"^chapter\s+\w+\s*[:.\-]?\s*", "", title, flags=re.I).strip().title()
    meta = {"chapter": n, "title": title, "type": (cfg.get("chapters", {}).get(n) or {}).get("type", ""),
            "status": "imported", "imported_from": src.name}
    write_front_matter(chapter_file(n), meta, body)

    rep = [f"# Import report - Chapter {NUMBER_WORDS[n].title()}", "",
           f"Source: `{src.name}`  ", f"Output: `chapter_{NUMBER_WORDS[n]}/chapter.md`", "",
           "## Reference list", "", "| # | Status | Key | Reference (as written) |", "|---|---|---|---|"]
    for i, (ref, key, how) in enumerate(report_refs, 1):
        status = "linked" if key else "NOT FOUND"
        rep.append(f"| {i} | {status} | {('@' + key) if key else '-'} | {ref[:160].replace('|', '/')} ({how}) |")
    rep += ["", "## In-text citations not converted", ""]
    rep += [f"- {u}" for u in sorted(set(unresolved))] or ["- none"]
    rep += ["", "## Figures and tables", ""] + ([f"- {x}" for x in notes] or ["- all captions converted"])
    rep += ["", "## Removed before first section (old title page / TOC)", ""]
    rep += [f"    {x[:120]}" for x in removed[:40]] or ["- nothing"]
    (d / "import_report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")

    linked = sum(1 for _, k, _ in report_refs if k)
    print(f"\nImported -> {chapter_file(n).relative_to(ROOT)}")
    print(f"  references linked: {linked}/{len(report_refs)} | unconverted in-text citations: {len(set(unresolved))} "
          f"| caption notes: {len(notes)}")
    print(f"  review: {(d / 'import_report.md').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
