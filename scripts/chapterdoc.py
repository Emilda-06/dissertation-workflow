"""Parsing helpers shared by check.py, build.py and guidelines.py (headings, figures, tables, blocks)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{2,6})\s+(.*?)\s*$")
ATTR_RE = re.compile(r"\s*\{([^}]*)\}\s*$")
FIG_DEF = re.compile(r"!\[(.*?)\]\(([^)\s]+)[^)]*\)\{[^}]*#(fig:[\w\-]+)")
TBL_DEF = re.compile(r"^:\s+(.*?)\{[^}]*#(tbl:[\w\-]+)", re.M)
SEC_DEF = re.compile(r"^#{2,6}\s.*\{[^}]*#(sec:[\w\-]+)", re.M)
REF_USE = re.compile(r"(?<![\w#])@((?:fig|tbl|sec|app):[\w\-]+)")
REQ_MARK = re.compile(r"<!--\s*req:\s*([\w\-, ]+?)\s*-->")


@dataclass
class Heading:
    level: int              # 2 = section (x.1), 3 = subsection (x.1.1) ...
    title: str              # text without attributes
    anchor: str | None      # 'sec:...' if labelled
    number: str | None      # '3.2.1' (None for unnumbered headings)
    line: int               # 0-based line index in the body
    classes: list[str] = field(default_factory=list)


def split_attrs(text: str) -> tuple[str, str]:
    m = ATTR_RE.search(text)
    if not m:
        return text.strip(), ""
    return text[:m.start()].strip(), m.group(1)


def parse_headings(body: str, prefix: str | int) -> list[Heading]:
    """All ## .. ###### headings outside code blocks, numbered like the build numbers them."""
    out: list[Heading] = []
    counters = [0, 0, 0, 0, 0]
    in_code = False
    for i, line in enumerate(body.splitlines()):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        title, attrs = split_attrs(m.group(2))
        anchor = (re.search(r"#(sec:[\w\-]+)", attrs) or [None, None])[1] if attrs else None
        classes = re.findall(r"\.([\w\-]+)", attrs)
        unnumbered = "-" in attrs.split() or "unnumbered" in classes or "{-}" in m.group(2)
        number = None
        if not unnumbered:
            k = level - 2
            counters[k] += 1
            for j in range(k + 1, len(counters)):
                counters[j] = 0
            number = ".".join([str(prefix)] + [str(c) for c in counters[:k + 1]])
        out.append(Heading(level, title, anchor, number, i, classes))
    return out


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


def word_count(body: str) -> int:
    return sum(len(re.sub(r"[@\[\]{}#*_]", " ", re.sub(r"<!--.*?-->", " ", b, flags=re.S)).split())
               for b in blocks(body) if classify(b) != "heading")


def figures(body: str) -> list[tuple[str, str, str]]:
    """(caption, path, id) per labelled figure."""
    return FIG_DEF.findall(body)


def tables(body: str) -> list[tuple[str, str]]:
    """(caption, id) per labelled table."""
    return [(c.strip(), t) for c, t in TBL_DEF.findall(body)]


def section_words(body: str, headings: list[Heading]) -> dict[int, int]:
    """Words under each heading (including its subsections), keyed by the heading's line index."""
    lines = body.splitlines()
    out = {}
    for idx, h in enumerate(headings):
        end = len(lines)
        for h2 in headings[idx + 1:]:
            if h2.level <= h.level:
                end = h2.line
                break
        out[h.line] = word_count("\n".join(lines[h.line + 1:end]))
    return out


def requirement_marks(body: str) -> dict[str, int]:
    """'<!-- req: R1, R2 -->' markers -> {requirement id: line index}."""
    out = {}
    for i, line in enumerate(body.splitlines()):
        for m in REQ_MARK.finditer(line):
            for rid in re.split(r"[,\s]+", m.group(1)):
                if rid:
                    out.setdefault(rid, i)
    return out


def heading_for_line(headings: list[Heading], line: int) -> Heading | None:
    cur = None
    for h in headings:
        if h.line <= line:
            cur = h
        else:
            break
    return cur
