"""Build Word documents from the chapter Markdown.

Usage:
  build.py chapter <n> [--no-cover] [--pdf]   -> output/chapters/chapter_<n>/docs/chapter_<n>_v<k>.docx
  build.py combine [--chapters 1 2 3] [--pdf] -> output/dissertation/docs/dissertation_v<k>.docx
  build.py changes <n>                         -> output/chapters/chapter_<n>/docs/chapter_<n>_v<k>_changes.docx (from revisions.md)

Every document gets: cover page, table of contents, list of figures, list of tables (all hyperlinked),
numbered headings (x.x.x), numbered figure/table captions, Harvard citations and a reference list.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from common import (ensure_zotero, CONFIG, DISSERTATION, LIBRARY, NUMBER_WORDS, ROOT, TEMPLATES, ZOTERO_EXPORT, chapter_dir, chapter_file,
                    realign_grid_tables,
                    chapter_slug, chapter_title, die, existing_chapters, latest_version, load_config,
                    load_json_list, next_version, read_front_matter, require_tool, setup_stdout)

BUILD = ROOT / ".build"


# ---------------------------------------------------------------- markdown preprocessing

def number_chapter(n: int, cfg: dict) -> tuple[str, dict]:
    """Return chapter markdown with chapter title, literal x.x.x heading numbers and resolved @sec refs."""
    meta, body = read_front_matter(chapter_file(n))
    body = realign_grid_tables(body)
    title = (meta.get("title") or chapter_title(cfg, n)).upper()
    counters = [0, 0, 0, 0]
    sec_numbers: dict[str, str] = {}
    out, in_code = [], False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^(#{2,5})\s+(.*)$", line)
        if m:
            level, text = len(m.group(1)), m.group(2)
            if "{-}" in text or ".unnumbered" in text:
                out.append(line)
                continue
            i = level - 2
            counters[i] += 1
            for j in range(i + 1, len(counters)):
                counters[j] = 0
            num = ".".join([str(n)] + [str(c) for c in counters[:i + 1]])
            if (sid := re.search(r"\{[^}]*#(sec:[\w\-]+)", text)):
                sec_numbers[sid.group(1)] = num
            line = f"{m.group(1)} {num} {text}"
        out.append(line)
    body = "\n".join(out)
    word = NUMBER_WORDS[n].upper()

    def sec_link(mm):
        sid = mm.group(1)
        return f"[Section {sec_numbers[sid]}](#{sid})" if sid in sec_numbers else mm.group(0)

    body = re.sub(r"\[@(sec:[\w\-]+)\]", sec_link, body)
    body = re.sub(r"(?<![\w#])@(sec:[\w\-]+)", sec_link, body)
    # image paths relative to the workflow root so chapters can be combined
    slug = chapter_slug(n)
    rel = chapter_dir(n).relative_to(ROOT).as_posix()          # output/chapters/chapter_one
    body = re.sub(r"(!\[.*?\]\()(?!/|[A-Za-z]:|https?:|output/)([^)\s]+)", rf"\g<1>{rel}/\g<2>", body)
    heading = f'# CHAPTER {word}: {title} {{#sec:chapter{n} label="{n}"}}'
    return f"{heading}\n\n{body.strip()}\n", meta


def field(instr: str, placeholder: str) -> str:
    return ("```{=openxml}\n"
            f'<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> {instr} </w:instrText></w:r>'
            f'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>{placeholder}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>\n```\n')


PAGE_BREAK = '```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```\n'


def section_break(cfg: dict) -> str:
    m = cfg.get("format", {}).get("margins_cm", {})
    tw = lambda cm: int(round(float(cm) * 567))
    return ("```{=openxml}\n<w:p><w:pPr><w:sectPr><w:type w:val=\"nextPage\"/>"
            '<w:pgSz w:w="11906" w:h="16838"/>'
            f'<w:pgMar w:top="{tw(m.get("top", 2.54))}" w:right="{tw(m.get("right", 2.54))}" '
            f'w:bottom="{tw(m.get("bottom", 2.54))}" w:left="{tw(m.get("left", 2.54))}" '
            'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:pPr></w:p>\n```\n')


def front_heading(text: str) -> str:
    return f'::: {{custom-style="Front Heading"}}\n{text}\n:::\n'


def front_matter(cfg: dict, extra_pages: list[str]) -> str:
    parts = []
    for page in extra_pages:
        parts += [page, PAGE_BREAK]
    parts += [front_heading("TABLE OF CONTENTS"), field(r'TOC \o "1-3" \h \z \u', "Table of contents"), PAGE_BREAK,
              front_heading("LIST OF FIGURES"), field(r'TOC \h \z \t "Image Caption,1"', "List of figures"), PAGE_BREAK,
              front_heading("LIST OF TABLES"), field(r'TOC \h \z \t "Table Caption,1"', "List of tables"),
              section_break(cfg)]
    return "\n".join(parts)


def dissertation_front_pages() -> list[str]:
    pages = []
    for f in sorted((DISSERTATION / "front_matter").glob("*.md")):
        meta, body = read_front_matter(f)
        title = (meta.get("title") or f.stem.split("-", 1)[-1].replace("_", " ")).upper()
        pages.append(f"# {title} {{.unnumbered}}\n\n{body.strip()}\n")
    return pages


# ---------------------------------------------------------------- cover

PLACEHOLDERS = ("TITLE", "STUDENT_NAME", "STUDENT_ID", "PROGRAMME", "DEPARTMENT", "FACULTY", "UNIVERSITY",
                "SUPERVISOR", "DATE", "DOCUMENT")


def prepare_cover(cfg: dict, document_label: str) -> tuple[str, str]:
    """Returns (kind, path) where kind is 'docx', 'image' or ''."""
    if not cfg.get("format", {}).get("cover", True):
        return "", ""
    docx, pdf = CONFIG / "cover.docx", CONFIG / "cover.pdf"
    BUILD.mkdir(exist_ok=True)
    if docx.exists():
        from docx import Document
        p = cfg.get("project", {})
        values = {
            "TITLE": p.get("title", ""), "STUDENT_NAME": p.get("student_name", ""),
            "STUDENT_ID": p.get("student_id", ""), "PROGRAMME": p.get("programme", ""),
            "DEPARTMENT": p.get("department", ""), "FACULTY": p.get("faculty", ""), "UNIVERSITY": p.get("university", ""),
            "SUPERVISOR": p.get("supervisor", ""), "DATE": date.today().strftime("%B %Y"),
            "DOCUMENT": document_label,
        }
        doc = Document(str(docx))
        paragraphs = list(doc.paragraphs)
        for t in doc.tables:
            for row in t.rows:
                for cell in row.cells:
                    paragraphs += cell.paragraphs
        for para in paragraphs:
            if "{{" not in para.text:
                continue
            text = para.text
            for k in PLACEHOLDERS:
                text = text.replace("{{" + k + "}}", str(values[k]))
            if text != para.text and para.runs:
                para.runs[0].text = text
                for r in para.runs[1:]:
                    r.text = ""
        out = BUILD / "cover_filled.docx"
        doc.save(str(out))
        return "docx", str(out)
    if pdf.exists():
        import pypdfium2 as pdfium
        page = pdfium.PdfDocument(str(pdf))[0]
        out = BUILD / "cover.png"
        page.render(scale=200 / 72).to_pil().save(str(out))
        return "image", str(out)
    print("note: no config/cover.docx or config/cover.pdf - building without a cover page")
    return "", ""


# ---------------------------------------------------------------- pandoc + word

def run_pandoc(md: str, out: Path, cfg: dict, with_refs: bool = True) -> None:
    BUILD.mkdir(exist_ok=True)
    if with_refs:
        import refs
        refs.pull_zotero(cfg, quiet=True)      # keep Zotero additions citable (skipped if Zotero is closed)
    src = BUILD / (out.stem + ".md")
    src.write_text(md, encoding="utf-8")
    cmd = [require_tool("pandoc"), str(src), "-o", str(out),
           "--from", "markdown+raw_attribute+fenced_divs+bracketed_spans",
           "--reference-doc", str(TEMPLATES / "reference.docx"),
           "--resource-path", str(ROOT),
           "--lua-filter", str(TEMPLATES / "table-autofit.lua")]
    if with_refs:
        cmd += ["--filter", require_tool("pandoc-crossref"),
                "--metadata-file", str(TEMPLATES / "crossref.yaml"),
                "--citeproc", "--csl", str(TEMPLATES / "harvard-cite-them-right.csl"),
                "-M", "link-citations=true", "-M", "reference-section-title=REFERENCES", "-M", "lang=en-GB"]
        for bib in (LIBRARY, ZOTERO_EXPORT):
            if bib.exists() and load_json_list(bib):
                cmd += ["--bibliography", str(bib)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    warn = [l for l in (r.stderr or "").splitlines() if l.strip()]
    for l in warn:
        print(f"  pandoc: {l}")
    if r.returncode != 0:
        die(f"pandoc failed (exit {r.returncode})")


def word_finalize(docx: Path, cover: tuple[str, str], pdf: bool) -> None:
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
           str(ROOT / "scripts" / "word_finalize.ps1"), "-Docx", str(docx)]
    kind, path = cover
    if kind == "docx":
        cmd += ["-Cover", path]
    elif kind == "image":
        cmd += ["-CoverImage", path]
    if pdf:
        cmd += ["-Pdf"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    msg = (r.stdout + r.stderr).strip()
    if msg:
        print("  word: " + msg.replace("\n", "\n  word: "))
    if r.returncode != 0:
        die("Word finalisation failed - is the .docx open in Word? Close it and rebuild.")


def run_check(nums: list[int]) -> None:
    for n in nums:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check.py"), str(n)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(r.stdout.rstrip())
        if r.returncode == 2:
            die(f"chapter {n} failed the quality check; fix the errors above (or pass --force to build a draft anyway)")


# ---------------------------------------------------------------- commands

def cmd_chapter(args, cfg):
    n = args.n
    if not chapter_file(n).exists():
        die(f"{chapter_file(n)} does not exist")
    if not args.force:
        run_check([n])
    md, meta = number_chapter(n, cfg)
    label = f"Chapter {NUMBER_WORDS[n].title()}: {(meta.get('title') or chapter_title(cfg, n)).title()}"
    full = front_matter(cfg, []) + "\n" + md
    slug = chapter_slug(n)
    out = next_version(chapter_dir(n) / "docs", slug)
    run_pandoc(full, out, cfg)
    word_finalize(out, prepare_cover(cfg, label) if not args.no_cover else ("", ""), args.pdf)
    print(f"\nBUILT {out.relative_to(ROOT)}")


def cmd_combine(args, cfg):
    nums = args.chapters or existing_chapters()
    if not nums:
        die("no chapters found")
    if not args.force:
        run_check(nums)
    body = "\n\n".join(number_chapter(n, cfg)[0] for n in nums)
    full = front_matter(cfg, dissertation_front_pages()) + "\n" + body
    out = next_version(DISSERTATION / "docs", "dissertation")
    run_pandoc(full, out, cfg)
    word_finalize(out, prepare_cover(cfg, cfg.get("project", {}).get("document_type", "Dissertation")), args.pdf)
    print(f"\nBUILT {out.relative_to(ROOT)}  (chapters {', '.join(map(str, nums))})")


def cmd_changes(args, cfg):
    n = args.n
    rev = chapter_dir(n) / "revisions.md"
    if not rev.exists():
        die(f"{rev} does not exist")
    latest = latest_version(chapter_dir(n) / "docs", chapter_slug(n))
    stem = latest.stem if latest else f"{chapter_slug(n)}_v0"
    out = chapter_dir(n) / "docs" / f"{stem}_changes.docx"
    run_pandoc(rev.read_text(encoding="utf-8"), out, cfg, with_refs=False)
    print(f"BUILT {out.relative_to(ROOT)}")


def main():
    setup_stdout()
    cfg = load_config()
    ensure_zotero(cfg)            # workflow rule: Zotero must be open
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chapter"); c.add_argument("n", type=int)
    c.add_argument("--no-cover", action="store_true"); c.add_argument("--pdf", action="store_true")
    c.add_argument("--force", action="store_true", help="build even if the quality check fails (draft)")
    cb = sub.add_parser("combine"); cb.add_argument("--chapters", type=int, nargs="+")
    cb.add_argument("--pdf", action="store_true"); cb.add_argument("--force", action="store_true")
    ch = sub.add_parser("changes"); ch.add_argument("n", type=int)
    args = p.parse_args()
    {"chapter": cmd_chapter, "combine": cmd_combine, "changes": cmd_changes}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
