"""Automatic integrity checks used by check.py (rules 2, 3 and 4 in CLAUDE.md).

1. Copying:   sentences that repeat downloaded full texts word for word (or nearly) outside quotation marks.
2. Quotes:    a direct quote "..." [@key, p. N] must appear in that source's full text (on page N if known).
3. Data:      in results chapters, reported numbers should be traceable to files in data/.

Usage (stand-alone):  integrity.py <n>
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from chapterdoc import blocks, classify
from common import (chapter_dir, chapter_file, init_cli, load_config, load_library, normalize_title, project,
                    read_front_matter, strip_code)

SHINGLE = 8                 # words per shingle
COPY_WARN = 0.5             # share of a sentence's shingles found in one source
COPY_ERROR = 0.8
MIN_SENTENCE_WORDS = 12
QUOTE_RE = re.compile(r"[\"“]([^\"”]{8,600})[\"”]\s*\[(?:[^\]]*?)@([\w:.#$%&\-+?<>~/]+)(?:,\s*(pp?\.?\s*[\d]+(?:\s*[–\-]\s*\d+)?))?[^\]]*\]")
NUM_RE = re.compile(r"(?<![\w.@:/#-])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?<![\w.@:/#-])[-+]?\d+(?:\.\d+)?%?")


def words(text: str) -> list[str]:
    return normalize_title(text).split()


def shingles(ws: list[str], n: int = SHINGLE) -> list[int]:
    return [hash(" ".join(ws[i:i + n])) for i in range(len(ws) - n + 1)]


def safe_name(doi: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", doi.lower())


def fulltext_files() -> list[Path]:
    root = project().chapters
    return sorted(root.glob("chapter_*/research/fulltext/*.txt")) if root.exists() else []


def fulltext_for_key(key: str, lib: dict) -> str | None:
    doi = (lib.get(key) or {}).get("DOI")
    if not doi:
        return None
    name = safe_name(doi) + ".txt"
    for f in fulltext_files():
        if f.name == name:
            return f.read_text(encoding="utf-8", errors="replace")
    return None


def prose(body: str) -> str:
    """Paragraph and list text without code, quotes in quotation marks, citations and markup."""
    out = []
    for b in blocks(strip_code(body)):
        if classify(b) not in ("paragraph", "list"):
            continue
        b = re.sub(r"[\"“][^\"”]{0,600}[\"”]", " ", b)          # quoted text is allowed to match
        b = re.sub(r"\[[^\]]*@[^\]]*\]|@[\w:.\-]+", " ", b)
        b = re.sub(r"<!--.*?-->", " ", b, flags=re.S)
        out.append(b)
    return "\n\n".join(out)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(])|\n\s*\n", text) if s.strip()]


def copy_check(body: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    index: dict[int, set[str]] = {}
    for f in fulltext_files():
        ws = words(f.read_text(encoding="utf-8", errors="replace"))
        for h in shingles(ws):
            index.setdefault(h, set()).add(f.stem)
    if not index:
        return errors, warnings
    for s in sentences(prose(body)):
        ws = words(s)
        if len(ws) < MIN_SENTENCE_WORDS:
            continue
        sh = shingles(ws)
        per_source: dict[str, int] = {}
        for h in sh:
            for src in index.get(h, ()):
                per_source[src] = per_source.get(src, 0) + 1
        if not per_source:
            continue
        src, hits = max(per_source.items(), key=lambda kv: kv[1])
        share = hits / len(sh)
        start = " ".join(s.split()[:9])
        if share >= COPY_ERROR:
            errors.append(f"sentence copied from a source ({share:.0%} identical to {src}): '{start} ...' - "
                          "rewrite it in your own words, or quote it with a page number")
        elif share >= COPY_WARN:
            warnings.append(f"sentence very close to a source ({share:.0%} overlap with {src}): '{start} ...'")
    return errors, warnings


def page_of(text: str, needle: str) -> list[int]:
    pages = []
    for m in re.finditer(r"\[page (\d+)\]\n(.*?)(?=\n\[page \d+\]|\Z)", text, re.S):
        if needle in normalize_title(m.group(2)):
            pages.append(int(m.group(1)))
    return pages


def quote_check(body: str, lib: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    for m in QUOTE_RE.finditer(strip_code(body)):
        quote, key, page = m.group(1), m.group(2).rstrip(".,;"), m.group(3)
        q = normalize_title(quote)
        if len(q.split()) < 3:
            continue
        short = (quote[:50] + "...") if len(quote) > 50 else quote
        if not page:
            warnings.append(f"direct quote '{short}' [@{key}] has no page number (write [@{key}, p. N])")
        text = fulltext_for_key(key, lib)
        if text is None:
            warnings.append(f"quote '{short}' [@{key}]: no full text downloaded, so it cannot be confirmed "
                            "(research.py fulltext), check it against the source yourself")
            continue
        if q not in normalize_title(text):
            errors.append(f"quote '{short}' was not found in the full text of @{key}; quote the source exactly")
            continue
        if page:
            n = int(re.search(r"\d+", page).group())
            found = page_of(text, q)
            if found and n not in found:
                warnings.append(f"quote '{short}' [@{key}, {page}] is on PDF page {', '.join(map(str, found))}; "
                                "check the page number (journals print their own page numbers)")
    return errors, warnings


def to_float(tok: str) -> float | None:
    try:
        return float(tok.replace(",", "").rstrip("%"))
    except ValueError:
        return None


def data_values(n: int) -> list[float]:
    vals: list[float] = []
    d = chapter_dir(n) / "data"
    if not d.exists():
        return vals
    for f in d.rglob("*"):
        if f.suffix.lower() not in (".csv", ".tsv", ".txt", ".json", ".md", ".dat"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if f.suffix.lower() == ".json":
            try:
                text = json.dumps(json.loads(text))
            except ValueError:
                pass
        for tok in NUM_RE.findall(text):
            v = to_float(tok)
            if v is not None:
                vals.append(v)
    return vals


def traceable(tok: str, vals: list[float]) -> bool:
    v = to_float(tok)
    if v is None:
        return True
    decimals = len(tok.rstrip("%").split(".")[1]) if "." in tok else 0
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    for x in vals:
        if abs(x - v) <= tol:
            return True
        if tok.endswith("%") and (abs(x * 100 - v) <= tol):
            return True
    return False


def data_check(n: int, body: str, chapter_type: str) -> tuple[list[str], list[str]]:
    if chapter_type != "results":
        return [], []
    vals = data_values(n)
    text = "\n\n".join(b for b in blocks(strip_code(body)) if classify(b) in ("paragraph", "list", "table"))
    text = re.sub(r"\[[^\]]*@[^\]]*\]|@[\w:.\-]+|\{[^}]*\}|!\[.*?\]\([^)]*\)", " ", text)
    numbers = []
    for tok in NUM_RE.findall(text):
        v = to_float(tok)
        if v is None:
            continue
        if not ("." in tok or tok.endswith("%") or abs(v) >= 100) or (1900 <= v <= 2100 and "." not in tok):
            continue                    # small counts and years are not measurements
        numbers.append(tok)
    if not numbers:
        return [], []
    if not vals:
        return [], [f"results chapter reports {len(numbers)} measured value(s) but {project().rel(chapter_dir(n) / 'data')}"
                    " has no data files; add the data (rule 2) or mark gaps with TODO-DATA"]
    missing = sorted({t for t in numbers if not traceable(t, vals)}, key=numbers.index)
    if missing:
        return [], [f"{len(missing)} reported number(s) not found in data/ (derived values? save them from the "
                    f"analysis script, e.g. data/summary.csv): {', '.join(missing[:12])}"
                    + (" ..." if len(missing) > 12 else "")]
    return [], []


def run_all(n: int, body: str, chapter_type: str, lib: dict | None = None) -> tuple[list[str], list[str]]:
    lib = load_library() if lib is None else lib
    errors, warnings = [], []
    for e, w in (copy_check(body), quote_check(body, lib), data_check(n, body, chapter_type)):
        errors += e
        warnings += w
    return errors, warnings


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("n", type=int)
    a = ap.parse_args()
    cfg = load_config()
    meta, body = read_front_matter(chapter_file(a.n))
    typ = meta.get("type") or (cfg["chapters"].get(a.n) or {}).get("type", "")
    errors, warnings = run_all(a.n, body, typ)
    for e in errors:
        print(f"ERROR   {e}")
    for w in warnings:
        print(f"warning {w}")
    print("PASS" if not errors else f"FAIL ({len(errors)})")
    raise SystemExit(2 if errors else 0)


if __name__ == "__main__":
    main()
