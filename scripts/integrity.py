"""Automatic integrity checks used by check.py (rules 2, 3 and 4 in CLAUDE.md).

1. Copying:   sentences that repeat a source word for word, closely paraphrase it (same structure with
              synonyms swapped), or re-use the author's own earlier work, outside quotation marks;
              research notes that copy their sources.
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

COPY_ERROR = 0.8            # share of a sentence's 8-word sequences found in one source
QUOTE_RE = re.compile(r"[\"“]([^\"”]{8,600})[\"”]\s*\[(?:[^\]]*?)@([\w:.#$%&\-+?<>~/]+)(?:,\s*(pp?\.?\s*[\d]+(?:\s*[–\-]\s*\d+)?))?[^\]]*\]")
NUM_RE = re.compile(r"(?<![\w.@:/#-])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?<![\w.@:/#-])[-+]?\d+(?:\.\d+)?%?")


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


PARA_WARN = 0.7             # close paraphrase (same structure, synonyms swapped)
PARA_ERROR = 0.85


def classify_matches(matches) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    for m in matches:
        start = " ".join(m.sentence.split()[:9])
        where = f"{m.source}" + (f", p. {m.page}" if m.page else "")
        if m.kind == "own":
            warnings.append(f"sentence repeats your earlier work ({m.score:.0%}, {where}): '{start} ...' - Turnitin "
                            "flags re-used text from your own submissions: cite the earlier work or rewrite it")
        elif m.kind == "verbatim":
            msg = (f"sentence copied from a source ({m.score:.0%} identical to {where}): '{start} ...' - rewrite it "
                   "from your notes, or quote it exactly with a page number")
            (errors if m.score >= COPY_ERROR else warnings).append(msg)
        else:
            msg = (f"sentence is a close paraphrase of {where} ({m.score:.0%} same structure and wording): "
                   f"'{start} ...' - re-express the idea from your notes in your own structure, or quote it")
            (errors if m.score >= PARA_ERROR else warnings).append(msg)
    return errors, warnings


def copy_check(body: str, corpus=None) -> tuple[list[str], list[str]]:
    """Verbatim copying, close paraphrase (patchwriting) and re-use of the author's earlier work."""
    import textsim
    matches, _ = textsim.scan_text(body, corpus, threshold=PARA_WARN)
    return classify_matches(matches)


def notes_check(n: int, corpus=None) -> tuple[list[str], list[str]]:
    """research/notes.md must be in the author's own words, so the chapter written from it is too."""
    import textsim
    notes = chapter_dir(n) / "research" / "notes.md"
    if not notes.exists():
        return [], []
    text = re.sub(r"^#+.*$|@[\w:.\-]+|\[[^\]]*\]|[\"“][^\"”]{0,300}[\"”]", " ", notes.read_text(encoding="utf-8"),
                  flags=re.M)
    lines = [re.sub(r"^\s*[-*]\s*(\w[\w /]*:)?", "", ln).strip() for ln in text.splitlines()]
    corpus = corpus if corpus is not None else textsim.build_corpus(include_own=False)
    flagged = []
    for ln in lines:
        if len(ln.split()) < 8:
            continue
        m = textsim.best_match(ln, corpus, threshold=PARA_WARN)
        if m and m.kind != "own":
            flagged.append(f"'{' '.join(ln.split()[:8])} ...' ({m.source})")
    if not flagged:
        return [], []
    return [], [f"{len(flagged)} line(s) in research/notes.md copy or closely paraphrase a source: rewrite them as "
                f"short points in your own words, so the chapter is written from your understanding: "
                + "; ".join(flagged[:4]) + (" ..." if len(flagged) > 4 else "")]


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
    import textsim
    corpus = textsim.build_corpus()
    for e, w in (copy_check(body, corpus), notes_check(n, corpus), quote_check(body, lib),
                 data_check(n, body, chapter_type)):
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
