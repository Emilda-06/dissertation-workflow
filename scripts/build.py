"""Build Word documents from the active project's Markdown.

Usage:
  build.py chapter <n> [--no-cover] [--pdf] [--pdfa] [--force] [--no-zotero]
        -> output/chapters/chapter_<n>/docs/chapter_<n>_v<k>.docx  (+ chapter_<n>_v<k>.md source snapshot)
  build.py combine [--chapters 1 2 3] [--no-appendices] [--pdf] [--pdfa] [--force] [--no-zotero]
        -> output/dissertation/docs/dissertation_v<k>.docx
  build.py changes <n>          -> chapter_<n>_v<k>_changes.docx (the revisions.md table, for the supervisor)
  build.py redline <n> [--from <k>] [--to <k>]
        -> chapter_<n>_v<k>_tracked.docx: tracked changes between two versions (Word Compare; without Word,
           a marked-up difference document built from the source snapshots)

Every document gets: cover page, table of contents, list of figures, list of tables (hyperlinked),
numbered headings (x.x.x), numbered captions, citations in the project's style and a reference list.
Appendices (output/appendices/appendix_<x>/appendix.md) follow the reference list in combined builds.

Finishing (format.finalizer in project.yaml): auto | word | libreoffice | none.
  word         Microsoft Word fills the contents/lists, inserts the cover, numbers pages (roman/arabic), PDF.
  libreoffice  PDF through LibreOffice; contents update when the .docx is opened.
  none         .docx only; contents update when the document is opened.
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from common import (IS_WINDOWS, NUMBER_WORDS, ROOT, SHARED_TEMPLATES, all_versions, appendix_file,
                    appendix_letter, chapter_dir, chapter_file, chapter_slug, chapter_title, die, ensure_zotero,
                    existing_appendices, existing_chapters, find_tool, init_cli, latest_version, load_config,
                    load_library, next_version, project, read_front_matter, realign_grid_tables, require_tool,
                    save_json)
from make_template import ensure_reference

CSL_STYLES = {"harvard": "harvard-cite-them-right.csl", "apa": "apa.csl", "ieee": "ieee.csl"}
PAPER_TWIPS = {"a4": (11906, 16838), "letter": (12240, 15840)}


# ---------------------------------------------------------------- settings

def csl_path(cfg: dict) -> Path:
    style = str((cfg.get("references") or {}).get("style") or "harvard").strip()
    if style.lower().endswith(".csl"):
        for base in (project().root, project().templates, SHARED_TEMPLATES):
            if (base / style).exists():
                return base / style
        die(f"citation style file '{style}' not found (put it in {project().rel(project().templates)})")
    low = style.lower()
    for key, fname in CSL_STYLES.items():
        if key in low:
            return project().template(fname)
    die(f"unknown citation style '{style}': use harvard, apa, ieee or a .csl file name")


def paper(cfg: dict) -> tuple[int, int]:
    return PAPER_TWIPS.get(str((cfg.get("format") or {}).get("paper", "A4")).lower(), PAPER_TWIPS["a4"])


_WORD_OK: bool | None = None


def word_available() -> bool:
    global _WORD_OK
    if _WORD_OK is None:
        _WORD_OK = False
        if IS_WINDOWS:
            try:
                r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                    "$w=New-Object -ComObject Word.Application; $w.Quit(); 'ok'"],
                                   capture_output=True, text=True, timeout=90)
                _WORD_OK = r.returncode == 0 and "ok" in r.stdout
            except (OSError, subprocess.TimeoutExpired):
                _WORD_OK = False
    return _WORD_OK


def finalizer(cfg: dict) -> str:
    want = str((cfg.get("format") or {}).get("finalizer", "auto")).lower()
    if want == "word" and not word_available():
        die("format.finalizer is 'word' but Microsoft Word is not available (set it to auto, libreoffice or none)")
    if want == "libreoffice" and not find_tool("soffice"):
        die("format.finalizer is 'libreoffice' but LibreOffice (soffice) was not found")
    if want in ("word", "libreoffice", "none"):
        return want
    if word_available():
        return "word"
    return "libreoffice" if find_tool("soffice") else "none"


# ---------------------------------------------------------------- markdown preprocessing

def number_document(path: Path, prefix: str, heading: str, attrs: str, folder: Path) -> tuple[str, dict]:
    """Markdown with the title heading, literal x.x.x heading numbers and resolved @sec references."""
    meta, body = read_front_matter(path)
    body = realign_grid_tables(body)
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
            num = ".".join([prefix] + [str(c) for c in counters[:i + 1]])
            if (sid := re.search(r"\{[^}]*#(sec:[\w\-]+)", text)):
                sec_numbers[sid.group(1)] = num
            line = f"{m.group(1)} {num} {text}"
        out.append(line)
    body = "\n".join(out)

    def sec_link(mm):
        sid = mm.group(1)
        return f"[Section {sec_numbers[sid]}](#{sid})" if sid in sec_numbers else mm.group(0)

    body = re.sub(r"\[@(sec:[\w\-]+)\]", sec_link, body)
    body = re.sub(r"(?<![\w#])@(sec:[\w\-]+)", sec_link, body)
    body = re.sub(r"<!--\s*req:[^>]*-->", "", body)          # requirement markers are for check.py only
    # image paths relative to the project root so chapters can be combined
    rel = folder.relative_to(project().root).as_posix()
    body = re.sub(r"(!\[.*?\]\()(?!/|[A-Za-z]:|https?:|output/)([^)\s]+)", rf"\g<1>{rel}/\g<2>", body)
    return f"# {heading} {{{attrs}}}\n\n{body.strip()}\n", meta


def number_chapter(n: int, cfg: dict) -> tuple[str, dict]:
    meta, _ = read_front_matter(chapter_file(n))
    title = (meta.get("title") or chapter_title(cfg, n)).upper()
    word = NUMBER_WORDS[n].upper()
    return number_document(chapter_file(n), str(n), f"CHAPTER {word}: {title}",
                           f'#sec:chapter{n} label="{n}"', chapter_dir(n))


def number_appendix(letter: str, cfg: dict) -> tuple[str, dict]:
    letter = appendix_letter(letter)
    meta, _ = read_front_matter(appendix_file(letter))
    apps = cfg.get("appendices") or {}
    title = (meta.get("title") or (apps.get(letter) or {}).get("title") or "").upper()
    head = f"APPENDIX {letter}" + (f": {title}" if title else "")
    return number_document(appendix_file(letter), letter, head, f'#app:{letter.lower()} label="{letter}"',
                           appendix_file(letter).parent)


def field(instr: str, placeholder: str) -> str:
    return ("```{=openxml}\n"
            f'<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r><w:r><w:instrText xml:space="preserve"> {instr} </w:instrText></w:r>'
            f'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>{placeholder}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>\n```\n')


PAGE_BREAK = '```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```\n'


def section_break(cfg: dict) -> str:
    m = (cfg.get("format") or {}).get("margins_cm", {}) or {}
    tw = lambda cm: int(round(float(cm) * 567))
    w, h = paper(cfg)
    return ("```{=openxml}\n<w:p><w:pPr><w:sectPr><w:type w:val=\"nextPage\"/>"
            f'<w:pgSz w:w="{w}" w:h="{h}"/>'
            f'<w:pgMar w:top="{tw(m.get("top", 2.54))}" w:right="{tw(m.get("right", 2.54))}" '
            f'w:bottom="{tw(m.get("bottom", 2.54))}" w:left="{tw(m.get("left", 2.54))}" '
            'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:pPr></w:p>\n```\n')


def front_heading(text: str) -> str:
    return f'::: {{custom-style="Front Heading"}}\n{text}\n:::\n'


def front_matter(cfg: dict, extra_pages: list[str], sections: bool) -> str:
    """Front pages, contents and lists. With Word, the front matter is its own section (roman numbers)."""
    parts = []
    for page in extra_pages:
        parts += [page, PAGE_BREAK]
    parts += [front_heading("TABLE OF CONTENTS"), field(r'TOC \o "1-3" \h \z \u', "Table of contents"), PAGE_BREAK,
              front_heading("LIST OF FIGURES"), field(r'TOC \h \z \t "Image Caption,1"', "List of figures"), PAGE_BREAK,
              front_heading("LIST OF TABLES"), field(r'TOC \h \z \t "Table Caption,1"', "List of tables"),
              section_break(cfg) if sections else PAGE_BREAK]
    return "\n".join(parts)


def dissertation_front_pages() -> list[str]:
    pages = []
    for f in sorted((project().dissertation / "front_matter").glob("*.md")):
        meta, body = read_front_matter(f)
        title = (meta.get("title") or f.stem.split("-", 1)[-1].replace("_", " ")).upper()
        pages.append(f"# {title} {{.unnumbered}}\n\n{body.strip()}\n")
    return pages


# ---------------------------------------------------------------- cover

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Z_]+)\s*\}\}")


def cover_values(cfg: dict, document_label: str) -> dict[str, str]:
    p = cfg.get("project", {}) or {}
    vals = {k.upper(): str(v) for k, v in p.items() if isinstance(v, (str, int, float))}
    vals.update({
        "TITLE": p.get("title", ""), "STUDENT_NAME": p.get("student_name", ""),
        "STUDENT_ID": str(p.get("student_id", "")), "PROGRAMME": p.get("programme", ""),
        "DEPARTMENT": p.get("department", ""), "FACULTY": p.get("faculty", ""),
        "UNIVERSITY": p.get("university", ""), "SUPERVISOR": p.get("supervisor", ""),
        "DATE": date.today().strftime("%B %Y"), "YEAR": str(date.today().year), "DOCUMENT": document_label,
    })
    return vals


def _paragraphs(root):
    return root.iter(qn("w:p"))


def _own_texts(p_el):
    """w:t elements that belong to this paragraph (not to a text box nested inside it)."""
    out = []
    for t in p_el.iter(qn("w:t")):
        anc = t.getparent()
        while anc is not None and anc.tag != qn("w:p"):
            anc = anc.getparent()
        if anc is p_el:
            out.append(t)
    return out


def replace_in_paragraph(p_el, values: dict[str, str]) -> int:
    """Replace {{KEY}} even when Word split it over several runs; formatting of the first run is kept."""
    ts = _own_texts(p_el)
    full = "".join(t.text or "" for t in ts)
    matches = [m for m in PLACEHOLDER_RE.finditer(full) if m.group(1) in values]
    for m in reversed(matches):
        start, end = m.span()
        pos, first, last = 0, None, None
        offsets = []
        for i, t in enumerate(ts):
            ln = len(t.text or "")
            offsets.append(pos)
            if first is None and start < pos + ln:
                first = i
            if end <= pos + ln and last is None:
                last = i
            pos += ln
        if first is None or last is None:
            continue
        ft, lt = ts[first], ts[last]
        before = (ft.text or "")[:start - offsets[first]]
        after = (lt.text or "")[end - offsets[last]:]
        if first == last:
            ft.text = before + values[m.group(1)] + after
        else:
            ft.text = before + values[m.group(1)]
            for t in ts[first + 1:last]:
                t.text = ""
            lt.text = after
        for t in (ft, lt):
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return len(matches)


def fill_placeholders(src: Path, out: Path, values: dict[str, str]) -> int:
    """Fill {{PLACEHOLDERS}} in the body, tables, text boxes, headers and footers of a .docx."""
    doc = Document(str(src))
    count = 0
    parts = [doc.part] + [rel.target_part for rel in doc.part.rels.values()
                          if rel.reltype.endswith(("/header", "/footer"))]
    for part in parts:
        for p_el in list(_paragraphs(part.element)):
            count += replace_in_paragraph(p_el, values)
    doc.save(str(out))
    return count


def lo_profile_arg() -> str:
    """LibreOffice runs with the workflow's own profile (never the user's; see lo_finalize.py)."""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return f"-env:UserInstallation={(base / 'dissertation-workflow' / 'libreoffice-profile').as_uri()}"


def docx_to_png(docx: Path, out: Path) -> Path | None:
    soffice = find_tool("soffice")
    if not soffice:
        return None
    pdf_dir = out.parent
    subprocess.run([soffice, lo_profile_arg(), "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(docx)],
                   capture_output=True, timeout=180)
    pdf = pdf_dir / (docx.stem + ".pdf")
    return pdf_to_png(pdf, out) if pdf.exists() else None


def pdf_to_png(pdf: Path, out: Path) -> Path:
    import pypdfium2 as pdfium
    page = pdfium.PdfDocument(str(pdf))[0]
    page.render(scale=200 / 72).to_pil().save(str(out))
    return out


def prepare_cover(cfg: dict, document_label: str, mode: str) -> tuple[str, str]:
    """Returns (kind, path) where kind is 'docx', 'image' or ''."""
    if not (cfg.get("format") or {}).get("cover", True):
        return "", ""
    p = project()
    p.build.mkdir(parents=True, exist_ok=True)
    docx, pdf = p.root / "cover.docx", p.root / "cover.pdf"
    if docx.exists():
        filled = p.build / "cover_filled.docx"
        fill_placeholders(docx, filled, cover_values(cfg, document_label))
        if mode == "word":
            return "docx", str(filled)
        png = docx_to_png(filled, p.build / "cover.png")
        if png:
            return "image", str(png)
        print("note: without Word or LibreOffice the cover.docx cannot be placed; building without a cover page")
        return "", ""
    if pdf.exists():
        return "image", str(pdf_to_png(pdf, p.build / "cover.png"))
    print(f"note: no cover.docx or cover.pdf in {p.rel(p.root)} - building without a cover page")
    return "", ""


def cover_markdown(cover: tuple[str, str]) -> str:
    """Cover as the first page of the Markdown (used when Word does not insert it)."""
    kind, path = cover
    if kind != "image":
        return ""
    return f"![]({Path(path).as_posix()}){{width=100%}}\n\n{PAGE_BREAK}\n"


# ---------------------------------------------------------------- pandoc + finishing

def zotero_enabled(cfg: dict, args) -> bool:
    return (cfg.get("zotero") or {}).get("enabled", True) and not getattr(args, "no_zotero", False)


def run_pandoc(md: str, out: Path, cfg: dict, with_refs: bool = True, refs_heading: bool = True,
               pull: bool = True) -> None:
    p = project()
    p.build.mkdir(parents=True, exist_ok=True)
    if with_refs and pull:
        import refs
        refs.pull_zotero(cfg, quiet=True)      # keep this project's Zotero collection citable
    src = p.build / (out.stem + ".md")
    src.write_text(md, encoding="utf-8")
    cmd = [require_tool("pandoc"), str(src), "-o", str(out),
           "--from", "markdown+raw_attribute+fenced_divs+bracketed_spans",
           "--reference-doc", str(ensure_reference(cfg)),
           "--resource-path", str(p.root) + (";" if IS_WINDOWS else ":") + str(ROOT),
           "--lua-filter", str(p.template("table-autofit.lua"))]
    if with_refs:
        cmd += ["--filter", require_tool("pandoc-crossref"),
                "--metadata-file", str(p.template("crossref.yaml")),
                "--citeproc", "--csl", str(csl_path(cfg)),
                "-M", "link-citations=true", "-M", "lang=en-GB"]
        if refs_heading:
            cmd += ["-M", "reference-section-title=REFERENCES"]
        # one merged bibliography in which the verified pipeline entry always wins over a Zotero copy
        # of the same key (pandoc would otherwise take whichever file comes last)
        merged = [{k: v for k, v in e.items() if not k.startswith("_")} for e in load_library().values()]
        if merged:
            bib = p.build / "bibliography.json"
            save_json(bib, merged)
            cmd += ["--bibliography", str(bib)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=p.root)
    for line in (r.stderr or "").splitlines():
        if line.strip():
            print(f"  pandoc: {line}")
    if r.returncode != 0:
        die(f"pandoc failed (exit {r.returncode})")


def word_finalize(docx: Path, cover: tuple[str, str], pdf: bool, cfg: dict, pdfa: bool) -> None:
    fmt = cfg.get("format") or {}
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
           str(ROOT / "scripts" / "word_finalize.ps1"), "-Docx", str(docx),
           "-FooterFont", str(fmt.get("footer_font", fmt.get("font", "Times New Roman"))),
           "-FooterSize", str(fmt.get("footer_font_size", fmt.get("font_size", 12)))]
    kind, path = cover
    if kind == "docx":
        cmd += ["-Cover", path]
    elif kind == "image":
        cmd += ["-CoverImage", path]
    if pdf:
        cmd += ["-Pdf"]
    if pdfa:
        cmd += ["-PdfA"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    msg = (r.stdout + r.stderr).strip()
    if msg:
        print("  word: " + msg.replace("\n", "\n  word: "))
    if r.returncode != 0:
        die("Word finalisation failed - is the .docx open in Word? Close it and rebuild.")


def libreoffice_finalize(docx: Path, want_pdf: bool, pdfa: bool) -> bool:
    """Refresh contents/lists with LibreOffice (its own Python drives it) and export PDF if asked.
    Falls back to a plain conversion when LibreOffice's Python is not available."""
    soffice = Path(require_tool("soffice"))
    lo_python = next((p for p in (soffice.parent / "python.exe", soffice.parent / "python") if p.exists()), None)
    if lo_python:
        flags = (["--pdfa"] if pdfa else ["--pdf"]) if want_pdf else []
        r = subprocess.run([str(lo_python), str(ROOT / "scripts" / "lo_finalize.py"), str(docx), *flags],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        msg = (r.stdout + r.stderr).strip()
        print(f"  libreoffice: {msg[-400:]}")
        if r.returncode == 0:
            return True
    if want_pdf:
        target = 'pdf:writer_pdf_Export:{"SelectPdfVersion":{"type":"long","value":"2"}}' if pdfa else "pdf"
        r = subprocess.run([str(soffice), lo_profile_arg(), "--headless", "--convert-to", target, "--outdir", str(docx.parent),
                            str(docx)], capture_output=True, text=True, timeout=600)
        pdf = docx.with_suffix(".pdf")
        print(f"  libreoffice: {'PDF: ' + str(pdf) if pdf.exists() else (r.stderr or r.stdout).strip()[:300]}")
    return False


def finish_plan(cfg: dict, args, label: str) -> tuple[str, tuple[str, str], bool, bool]:
    mode = finalizer(cfg)
    pdfa = bool(getattr(args, "pdfa", False) or (cfg.get("format") or {}).get("pdfa"))
    want_pdf = bool(getattr(args, "pdf", False) or pdfa)
    cover = ("", "") if getattr(args, "no_cover", False) else prepare_cover(cfg, label, mode)
    return mode, cover, want_pdf, pdfa


def build_document(body_md: str, front_pages: list[str], out: Path, cfg: dict, args, label: str,
                   refs_heading: bool = True) -> str:
    mode, cover, want_pdf, pdfa = finish_plan(cfg, args, label)
    pre = "" if mode == "word" else cover_markdown(cover)
    full = pre + front_matter(cfg, front_pages, sections=(mode == "word")) + "\n" + body_md
    run_pandoc(full, out, cfg, refs_heading=refs_heading, pull=zotero_enabled(cfg, args))
    if mode == "word":
        word_finalize(out, cover, want_pdf, cfg, pdfa)
    elif mode == "libreoffice":
        if libreoffice_finalize(out, want_pdf, pdfa):
            print("  finished with LibreOffice: contents and lists filled; page numbers are arabic throughout")
        else:
            print("  finished with LibreOffice (conversion only): contents fill in when the document is opened")
    else:
        if want_pdf:
            print("  note: no Word or LibreOffice - PDF not produced (the .docx is complete)")
        print("  finished without Word: the contents and lists fill in when the document is opened "
              "(accept 'update fields'); page numbers are arabic throughout")
    return mode


def run_check(nums: list, cfg: dict) -> None:
    for n in nums:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check.py"), str(n),
                            "--project", project().slug],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(r.stdout.rstrip())
        if r.returncode == 2:
            die(f"{'chapter' if isinstance(n, int) else 'appendix'} {n} failed the quality check; fix the errors "
                "above (or pass --force to build a draft anyway)")
        if r.returncode not in (0, 2):
            die(f"check.py crashed:\n{r.stderr}")


# ---------------------------------------------------------------- commands

def cmd_chapter(args, cfg):
    n = args.n
    if not chapter_file(n).exists():
        die(f"{chapter_file(n)} does not exist")
    if zotero_enabled(cfg, args):
        ensure_zotero(cfg)
    if not args.force:
        run_check([n], cfg)
    md, meta = number_chapter(n, cfg)
    label = f"Chapter {NUMBER_WORDS[n].title()}: {(meta.get('title') or chapter_title(cfg, n)).title()}"
    out = next_version(chapter_dir(n) / "docs", chapter_slug(n))
    build_document(md, [], out, cfg, args, label)
    shutil.copy2(chapter_file(n), out.with_suffix(".md"))           # source snapshot for redlines
    print(f"\nBUILT {project().rel(out)}")


def references_block() -> str:
    return "# REFERENCES {.unnumbered}\n\n::: {#refs}\n:::\n"


def cmd_combine(args, cfg):
    nums = args.chapters or existing_chapters()
    if not nums:
        die("no chapters found")
    apps = [] if args.no_appendices else existing_appendices()
    if zotero_enabled(cfg, args):
        ensure_zotero(cfg)
    if not args.force:
        run_check(nums + apps, cfg)
    body = "\n\n".join(number_chapter(n, cfg)[0] for n in nums)
    if apps:
        body += "\n\n" + references_block() + "\n\n" + "\n\n".join(number_appendix(a, cfg)[0] for a in apps)
    out = next_version(project().dissertation / "docs", "dissertation")
    label = (cfg.get("project") or {}).get("document_type", "Dissertation")
    build_document(body, dissertation_front_pages(), out, cfg, args, label, refs_heading=not apps)
    extra = f"; appendices {', '.join(apps)}" if apps else ""
    print(f"\nBUILT {project().rel(out)}  (chapters {', '.join(map(str, nums))}{extra})")


def cmd_changes(args, cfg):
    n = args.n
    rev = chapter_dir(n) / "revisions.md"
    if not rev.exists():
        die(f"{rev} does not exist")
    latest = latest_version(chapter_dir(n) / "docs", chapter_slug(n))
    stem = latest.stem if latest else f"{chapter_slug(n)}_v0"
    out = chapter_dir(n) / "docs" / f"{stem}_changes.docx"
    run_pandoc(rev.read_text(encoding="utf-8"), out, cfg, with_refs=False)
    print(f"BUILT {project().rel(out)}")


# ---------------------------------------------------------------- redline (tracked changes)

def word_diff_markdown(old: str, new: str) -> str:
    """Paragraph-level diff with word-level marks: ~~deleted~~ and [inserted]{.underline}."""
    def paras(t):
        return [p for p in re.split(r"\n\s*\n", read_body(t)) if p.strip()]

    a, b = paras(old), paras(new)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out += b[j1:j2]
        elif op == "insert":
            out += [mark_words([], p.split()) for p in b[j1:j2]]
        elif op == "delete":
            out += [mark_words(p.split(), []) for p in a[i1:i2]]
        else:
            old_p, new_p = a[i1:i2], b[j1:j2]
            for k in range(max(len(old_p), len(new_p))):
                op_ = old_p[k].split() if k < len(old_p) else []
                np_ = new_p[k].split() if k < len(new_p) else []
                out.append(mark_words(op_, np_))
    return "\n\n".join(out) + "\n"


def mark_words(old: list[str], new: list[str]) -> str:
    def esc(ws):
        return " ".join(ws).replace("~~", "")
    if any(w.startswith(("#", "|", "+-", "![", ":")) for w in (new or old)[:1]) and old and new:
        return f"~~{esc(old)}~~\n\n{esc(new)}" if old != new else esc(new)
    parts = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if op == "equal":
            parts.append(esc(new[j1:j2]))
        if op in ("delete", "replace") and i2 > i1:
            parts.append(f"~~{esc(old[i1:i2])}~~")
        if op in ("insert", "replace") and j2 > j1:
            parts.append(f"[{esc(new[j1:j2])}]{{.underline}}")
    return " ".join(p for p in parts if p)


def read_body(text: str) -> str:
    from common import FRONT_RE
    m = FRONT_RE.match(text)
    return text[m.end():] if m else text


def cmd_redline(args, cfg):
    n = args.n
    docs = chapter_dir(n) / "docs"
    slug = chapter_slug(n)
    versions = all_versions(docs, slug)
    if len(versions) < 2 and not args.from_v:
        die("need at least two built versions to compare")
    by_num = {int(re.search(r"_v(\d+)\.docx$", v.name).group(1)): v for v in versions}
    to_v = args.to_v or max(by_num)
    from_v = args.from_v or max(k for k in by_num if k < to_v)
    if from_v not in by_num or to_v not in by_num:
        die(f"versions available: {', '.join(map(str, sorted(by_num)))}")
    out = docs / f"{slug}_v{to_v}_tracked.docx"
    if IS_WINDOWS and word_available():
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(ROOT / "scripts" / "word_compare.ps1"), "-Original", str(by_num[from_v]),
                            "-Revised", str(by_num[to_v]), "-Output", str(out)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(("  word: " + (r.stdout + r.stderr).strip()) if (r.stdout + r.stderr).strip() else "")
        if r.returncode != 0:
            die("Word compare failed - close the documents in Word and try again")
    else:
        old_md, new_md = by_num[from_v].with_suffix(".md"), by_num[to_v].with_suffix(".md")
        if not (old_md.exists() and new_md.exists()):
            die("without Word, the redline needs the source snapshots (built by this version of build.py)")
        diff = word_diff_markdown(old_md.read_text(encoding="utf-8"), new_md.read_text(encoding="utf-8"))
        head = (f"# Changes from version {from_v} to version {to_v} {{.unnumbered}}\n\n"
                "Deleted text is ~~struck through~~; new text is [underlined]{.underline}.\n\n")
        run_pandoc(head + diff, out, cfg, with_refs=False)
    print(f"BUILT {project().rel(out)}  (v{from_v} -> v{to_v})")


def main():
    init_cli()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chapter"); c.add_argument("n", type=int)
    c.add_argument("--no-cover", action="store_true")
    cb = sub.add_parser("combine"); cb.add_argument("--chapters", type=int, nargs="+")
    cb.add_argument("--no-appendices", action="store_true"); cb.add_argument("--no-cover", action="store_true")
    for sp in (c, cb):
        sp.add_argument("--pdf", action="store_true"); sp.add_argument("--pdfa", action="store_true")
        sp.add_argument("--force", action="store_true", help="build even if the quality check fails (draft)")
        sp.add_argument("--no-zotero", action="store_true", help="do not pull from Zotero for this build")
    ch = sub.add_parser("changes"); ch.add_argument("n", type=int)
    rl = sub.add_parser("redline"); rl.add_argument("n", type=int)
    rl.add_argument("--from", dest="from_v", type=int); rl.add_argument("--to", dest="to_v", type=int)
    args = p.parse_args()
    cfg = load_config()
    {"chapter": cmd_chapter, "combine": cmd_combine, "changes": cmd_changes,
     "redline": cmd_redline}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
