"""Turn a cover page into a template: the project's details are filled in on every build.

Give it the cover as you have it (Word .docx/.doc, PDF, or an image). For a Word cover it finds
  * labelled fields      "Name: Jane Doe", "Student No: ______", "Supervisor - Dr X", "Submitted by Jane"
  * values you have set  your title, name, ID ... already in project.yaml
  * the layout           the largest text is the title; "University of ...", "Department of ...",
                         "Faculty of ..." and a month/year line
and replaces each with a {{PLACEHOLDER}} (keeping fonts, bold and layout). Real values found on the cover
fill empty fields of project.yaml. PDF covers are converted to Word first (needs Microsoft Word);
otherwise, and for images, the cover is placed as a picture without filled fields.

Usage:
  cover.py make <file>      (project.py add --cover <file> runs this for you)
  cover.py show             placeholders in the current template and the values they get
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

import yaml
from docx import Document
from docx.oxml.ns import qn

from common import IS_WINDOWS, die, init_cli, load_config, project

FIELDS = ["TITLE", "STUDENT_NAME", "STUDENT_ID", "PROGRAMME", "DEPARTMENT", "FACULTY", "UNIVERSITY",
          "SUPERVISOR", "DATE", "DOCUMENT"]
YAML_KEY = {"TITLE": "title", "STUDENT_NAME": "student_name", "STUDENT_ID": "student_id", "PROGRAMME": "programme",
            "DEPARTMENT": "department", "FACULTY": "faculty", "UNIVERSITY": "university", "SUPERVISOR": "supervisor"}
LABELS = [  # (field, label pattern) - most specific first
    ("STUDENT_ID", r"(?:student|candidate|registration|reg|matric(?:ulation)?|admission|index)\.?\s*"
                   r"(?:id|no\.?|number|#)|id\s*(?:no\.?|number)"),
    ("STUDENT_NAME", r"(?:student'?s?|candidate'?s?|author'?s?)\s*(?:full\s*)?name|name\s*of\s*(?:student|candidate)"
                     r"|full\s*name|name|submitted\s*by|prepared\s*by|presented\s*by|written\s*by"),
    ("SUPERVISOR", r"(?:main\s*|academic\s*|project\s*)?supervisor(?:'s\s*name)?|supervised\s*by|advisor|lecturer"),
    ("PROGRAMME", r"programme|program|degree|course(?:\s*of\s*study)?|qualification"),
    ("DEPARTMENT", r"department|dept\.?|school"),
    ("FACULTY", r"faculty|college"),
    ("UNIVERSITY", r"university|institution"),
    ("DATE", r"date(?:\s*of\s*submission)?|submission\s*date|submitted\s*on|month\s*(?:and|&)\s*year"),
    ("TITLE", r"(?:project|dissertation|thesis|research)?\s*title|topic"),
]
LABEL_RE = [(f, re.compile(rf"^\s*({p})\s*(?:[:\-–—=]\s*|\s+(?=[_.…]))(.*)$", re.I)) for f, p in LABELS]
BY_RE = re.compile(r"^\s*(submitted|prepared|presented|written)\s+by\s+(?![:\-])(.+)$", re.I)
BLANK = re.compile(r"^[\s_.…\-\[\]()]*$")
MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|" \
         r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_LINE = re.compile(rf"^\s*(?:{MONTHS}\s*,?\s*)?(?:19|20)\d{{2}}\s*$|^\s*\d{{1,2}}\s*{MONTHS}\s*,?\s*(?:19|20)\d{{2}}\s*$",
                       re.I)
EXAMPLE_VALUES = {"Your Dissertation Title", "Your Name", "Your Student ID", "Your Degree Programme",
                  "Department of Computer Science", "Your Faculty", "Your University", "Your Supervisor", ""}


# ---------------------------------------------------------------- docx text helpers

def own_texts(p_el):
    """w:t elements belonging to this paragraph (not to a text box nested inside it)."""
    out = []
    for t in p_el.iter(qn("w:t")):
        anc = t.getparent()
        while anc is not None and anc.tag != qn("w:p"):
            anc = anc.getparent()
        if anc is p_el:
            out.append(t)
    return out


def para_text(p_el) -> str:
    return "".join(t.text or "" for t in own_texts(p_el))


def replace_span(p_el, start: int, end: int, new: str) -> None:
    """Replace characters [start, end) of the paragraph text, keeping the first run's formatting."""
    ts = own_texts(p_el)
    pos, first, last, offs = 0, None, None, []
    for i, t in enumerate(ts):
        ln = len(t.text or "")
        offs.append(pos)
        if first is None and start < pos + ln:
            first = i
        if last is None and end <= pos + ln:
            last = i
        pos += ln
    if first is None:                        # empty paragraph or span at the very end: append
        if ts:
            ts[-1].text = (ts[-1].text or "") + new
        return
    last = last if last is not None else len(ts) - 1
    ft, lt = ts[first], ts[last]
    before = (ft.text or "")[:start - offs[first]]
    after = (lt.text or "")[end - offs[last]:]
    if first == last:
        ft.text = before + new + after
    else:
        ft.text = before + new
        for t in ts[first + 1:last]:
            t.text = ""
        lt.text = after
    for t in (ft, lt):
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def font_size(p_el) -> float:
    sizes = [int(sz.get(qn("w:val"))) / 2 for sz in p_el.iter(qn("w:sz")) if sz.get(qn("w:val"), "").isdigit()]
    return max(sizes) if sizes else 0.0


def is_bold(p_el) -> bool:
    return any(b.get(qn("w:val"), "true") not in ("0", "false") for b in p_el.iter(qn("w:b")))


def all_paragraphs(doc) -> list:
    parts = [doc.part] + [rel.target_part for rel in doc.part.rels.values()
                          if rel.reltype.endswith(("/header", "/footer"))]
    out = []
    for part in parts:
        out += [p for p in part.element.iter(qn("w:p")) if para_text(p).strip()]
    return out


# ---------------------------------------------------------------- conversion

WORD_SCRIPT = r"""
param([string]$Src, [string]$Out, [string]$PidFile)
$ErrorActionPreference = 'Stop'
$before = @(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object Id)
$w = New-Object -ComObject Word.Application
$mine = Get-Process WINWORD -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | Select-Object -First 1
if ($mine) { Set-Content -Path $PidFile -Value $mine.Id }
try {
    $w.Visible = $false
    $w.DisplayAlerts = 0
    $d = $w.Documents.Open($Src, $false, $true)
    $d.SaveAs2($Out, 16)
    $d.Close($false)
} finally { $w.Quit() }
"""
PDF_WARNING_KEY = r"Software\Microsoft\Office\16.0\Word\Options"


def word_convert(src: Path, out: Path, work: Path, timeout: int = 180) -> bool:
    """Open src in a hidden Microsoft Word and save it as .docx. Word's 'convert this PDF?' prompt is switched
    off for the duration (the user's setting is restored), and only the Word process started here is ever
    stopped if it hangs."""
    import winreg
    script, pidfile = work / "convert.ps1", work / "word.pid"
    script.write_text(WORD_SCRIPT, encoding="utf-8")
    pidfile.unlink(missing_ok=True)
    old = None
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, PDF_WARNING_KEY)
        try:
            old = winreg.QueryValueEx(key, "DisableConvertPdfWarning")[0]
        except FileNotFoundError:
            old = None
        winreg.SetValueEx(key, "DisableConvertPdfWarning", 0, winreg.REG_DWORD, 1)
    except OSError:
        key = None
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                            "-Src", str(src), "-Out", str(out), "-PidFile", str(pidfile)],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0 and out.exists()
    except subprocess.TimeoutExpired:
        if pidfile.exists():
            subprocess.run(["taskkill", "/PID", pidfile.read_text().strip(), "/F"], capture_output=True)
        return False
    finally:
        if key is not None:
            if old is None:
                try:
                    winreg.DeleteValue(key, "DisableConvertPdfWarning")
                except OSError:
                    pass
            else:
                winreg.SetValueEx(key, "DisableConvertPdfWarning", 0, winreg.REG_DWORD, old)
            winreg.CloseKey(key)


def to_docx(src: Path, work: Path) -> Path | None:
    """A .docx version of the cover (PDF/.doc/.odt via Word, or LibreOffice for .doc/.odt)."""
    if src.suffix.lower() == ".docx":
        return src
    out = work / (src.stem + ".docx")
    work.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    from common import find_tool
    soffice = find_tool("soffice")
    if soffice:                                   # headless and dialog-free: preferred, also for PDFs
        import build
        cmd = [soffice, build.lo_profile_arg(), "--headless"]
        if src.suffix.lower() == ".pdf":
            cmd.append("--infilter=writer_pdf_import")
        try:
            subprocess.run(cmd + ["--convert-to", "docx", "--outdir", str(work), str(src)], capture_output=True,
                           timeout=300)
        except subprocess.TimeoutExpired:
            pass
        if out.exists():
            return out
    if IS_WINDOWS and word_convert(src, out, work):
        return out
    return None


def rebuild_flowing(src_doc, cfg: dict):
    """A clean, flowing cover from a PDF conversion: the PDF's text boxes have fixed sizes and clip longer
    values, so the text is laid out again as centred paragraphs (same order, size and weight)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt
    fmt = cfg.get("format") or {}
    font = fmt.get("font", "Times New Roman")
    doc = Document()
    for sec in doc.sections:
        m = fmt.get("margins_cm") or {}
        sec.top_margin, sec.bottom_margin = Cm(m.get("top", 2.54)), Cm(m.get("bottom", 2.54))
        sec.left_margin, sec.right_margin = Cm(m.get("left", 2.54)), Cm(m.get("right", 2.54))
    paras = [p for p in all_paragraphs(src_doc) if para_text(p).strip()]
    sizes = [font_size(p) or 12 for p in paras]
    biggest = max(sizes) if sizes else 12
    for p_el, size in zip(paras, sizes):
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(10)
        if size == biggest and size > 14:                      # air around the title
            para.paragraph_format.space_before = Pt(36)
            para.paragraph_format.space_after = Pt(36)
        run = para.add_run(para_text(p_el).strip())
        run.font.size = Pt(size)
        run.font.bold = is_bold(p_el) or size >= 13
        run.font.name = font
    return doc


def tidy_converted(doc) -> int:
    """Clean a cover converted from PDF: drop the duplicate compatibility copy of every text box, and rejoin
    lines that the PDF had wrapped (same font size, previous line not ending a sentence). Returns joins made."""
    mc = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
    for fb in list(doc.element.iter(f"{mc}Fallback")):
        fb.getparent().remove(fb)
    joins = 0
    paras = all_paragraphs(doc)
    for prev, nxt in zip(paras, paras[1:]):
        a, b = para_text(prev).rstrip(), para_text(nxt).strip()
        if not a or not b or font_size(prev) != font_size(nxt) or a.endswith((".", ":", "?", "!")):
            continue
        is_label = any(rx.match(b) for _, rx in LABEL_RE) or any(rx.match(a) for _, rx in LABEL_RE)
        if is_label or DATE_LINE.match(b) or DATE_LINE.match(a):
            continue
        # a wrapped line continues in lower case, or both are large display text (a two-line title)
        if b[0].islower() or (font_size(prev) >= 14 and not a.isupper() and not b.isupper()):
            replace_span(prev, len(para_text(prev)), len(para_text(prev)), ("" if para_text(prev).endswith(" ")
                                                                             else " ") + b)
            replace_span(nxt, 0, len(para_text(nxt)), "")
            joins += 1
    return joins


# ---------------------------------------------------------------- template making

def known_values(cfg: dict) -> dict[str, str]:
    p = cfg.get("project") or {}
    out = {}
    for field, key in YAML_KEY.items():
        v = str(p.get(key) or "").strip()
        if v and v not in EXAMPLE_VALUES and len(v) >= 3:
            out[field] = v
    return out


def templatize(doc, cfg: dict) -> dict:
    """Insert placeholders into the document. Returns a report."""
    placed: dict[str, str] = {}        # field -> original text it replaced ('' = was blank)
    found: dict[str, str] = {}         # field -> real value read from the cover
    paras = all_paragraphs(doc)
    existing = {m.group(1) for p in paras for m in re.finditer(r"\{\{\s*([A-Z_]+)\s*\}\}", para_text(p))}
    for f in existing:
        placed[f] = "(already a placeholder)"
    done = set()                       # paragraphs already handled

    def put(field, p_el, start, end, original):
        if field in placed:
            return False
        replace_span(p_el, start, end, "{{" + field + "}}")
        placed[field] = original
        done.add(p_el)
        return True

    # 1. labelled fields: "Name: Jane", "Student No: ____", "Submitted by Jane"
    for p_el in paras:
        text = para_text(p_el)
        if "{{" in text:
            continue
        m = BY_RE.match(text)
        if m and "STUDENT_NAME" not in placed:
            value = m.group(2).strip()
            if not BLANK.match(value):
                found["STUDENT_NAME"] = value
            put("STUDENT_NAME", p_el, m.start(2), len(text), value)
            continue
        for field, rx in LABEL_RE:
            m = rx.match(text)
            if not m or field in placed:
                continue
            value = m.group(2).strip()
            if BLANK.match(value):
                if value:                                   # "Student No: ________"
                    put(field, p_el, m.start(2), len(text), "")
                else:                                       # "Supervisor:" with nothing after it
                    replace_span(p_el, len(text), len(text), ("" if text.endswith(" ") else " ") +
                                 "{{" + field + "}}")
                    placed[field] = ""
                    done.add(p_el)
            else:
                found[field] = value
                put(field, p_el, m.start(2), m.start(2) + len(m.group(2).rstrip()), value)
            break
    # 2. values already in project.yaml, wherever they appear
    for field, value in known_values(cfg).items():
        if field in placed:
            continue
        for p_el in paras:
            text = para_text(p_el)
            i = text.lower().find(value.lower())
            if i >= 0 and "{{" not in text[i:i + len(value)]:
                put(field, p_el, i, i + len(value), text[i:i + len(value)])
                break
    # 3. layout: institution lines, date line, and the title (largest text)
    free = [p for p in paras if p not in done and "{{" not in para_text(p)]
    for field, rx in [("UNIVERSITY", r"\b(university|polytechnic|institute of|college of)\b"),
                      ("FACULTY", r"^\s*faculty\s+of\b"),
                      ("DEPARTMENT", r"^\s*(department|school)\s+of\b")]:
        if field in placed:
            continue
        for p_el in free:
            text = para_text(p_el).strip()
            if re.search(rx, text, re.I) and len(text.split()) <= 12 and not re.search(r"submitted|partial", text, re.I):
                found.setdefault(field, text)
                full = para_text(p_el)
                lead = len(full) - len(full.lstrip())
                put(field, p_el, lead, lead + len(text), text)
                free.remove(p_el)
                break
    if "PROGRAMME" not in placed:
        for p_el in paras:
            text = para_text(p_el)
            m = re.search(r"\b(?:degree|programme|program|award)\s+of\s+(?:the\s+)?(.+?)\s*\.?\s*$", text, re.I)
            if m and "{{" not in m.group(1) and 2 <= len(m.group(1).split()) <= 12:
                found.setdefault("PROGRAMME", m.group(1).strip())
                put("PROGRAMME", p_el, m.start(1), m.start(1) + len(m.group(1).rstrip(". ")), m.group(1).strip())
                break
    if "DATE" not in placed:
        for p_el in free:
            text = para_text(p_el)
            if DATE_LINE.match(text):
                put("DATE", p_el, 0, len(text), text.strip())
                free.remove(p_el)
                break
    if "TITLE" not in placed:
        cands = [p for p in free if len(para_text(p).split()) >= 3 and not re.search(
            r"submitted|partial|fulfil|requirement|degree|in fulfilment|declaration|copyright", para_text(p), re.I)]
        if cands:
            best = max(cands, key=lambda p: (font_size(p), is_bold(p), para_text(p).isupper(), -cands.index(p)))
            text = para_text(best)
            found.setdefault("TITLE", text.strip())
            lead = len(text) - len(text.lstrip())
            put("TITLE", best, lead, lead + len(text.strip()), text.strip())
    missing = [f for f in ("TITLE", "STUDENT_NAME", "STUDENT_ID", "SUPERVISOR", "UNIVERSITY") if f not in placed]
    return {"placed": placed, "found": found, "missing": missing}


DIFFERENT: dict[str, tuple[str, str]] = {}      # key -> (project.yaml value, value on the cover)


def prefill(cfg_path: Path, found: dict[str, str]) -> dict[str, str]:
    """Fill empty/example fields of project.yaml with real values read from the cover."""
    text = cfg_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(text) or {}
    proj = cfg.setdefault("project", {})
    changed = {}
    for field, value in found.items():
        key = YAML_KEY.get(field)
        if not key or not value or BLANK.match(value):
            continue
        current = str(proj.get(key) or "").strip()
        if current in EXAMPLE_VALUES:
            proj[key] = value
            changed[key] = value
        elif current.lower() != value.lower():
            DIFFERENT[key] = (current, value)
    if changed:
        header = "".join(ln + "\n" for ln in text.splitlines() if ln.startswith("#"))[:400]
        cfg_path.write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return changed


def make(src: Path, quiet: bool = False) -> dict:
    """Copy the cover into docs/cover/ and build config/cover_template.docx from it."""
    p = project()
    cfg = load_config()
    p.cover_dir.mkdir(parents=True, exist_ok=True)
    kept = p.cover_dir / src.name
    if src.resolve() != kept.resolve():
        shutil.copy2(src, kept)
    report = {"original": kept, "template": None, "kind": "image", "placed": {}, "found": {}, "missing": [],
              "prefilled": {}}
    if kept.suffix.lower() in (".png", ".jpg", ".jpeg"):
        report["note"] = "image cover: placed as a picture (no fields are filled)"
        if not quiet:
            print_report(report)
        return report
    docx = to_docx(kept, p.build / "cover")
    if docx is None:
        report["kind"] = "pdf-image" if kept.suffix.lower() == ".pdf" else "unsupported"
        report["note"] = ("could not convert the cover to Word (needs LibreOffice or Microsoft Word): it will be "
                          "placed as a picture. For filled fields, provide the cover as .docx")
        if not quiet:
            print_report(report)
        return report
    doc = Document(str(docx))
    if kept.suffix.lower() == ".pdf":
        report["joined"] = tidy_converted(doc)
        doc = rebuild_flowing(doc, cfg)
        report["note"] = (f"rebuilt from the PDF as a centred page in your document font - open "
                          f"{p.rel(p.cover_template)} in Word to adjust spacing or add a logo; "
                          "a .docx cover keeps the original design exactly")
    rep = templatize(doc, cfg)
    p.config_dir.mkdir(parents=True, exist_ok=True)
    doc.save(str(p.cover_template))
    report.update(rep, kind="template", template=p.cover_template)
    DIFFERENT.clear()
    report["prefilled"] = prefill(p.config_file, rep["found"])
    report["different"] = dict(DIFFERENT)
    if not quiet:
        print_report(report)
    return report


def print_report(r: dict) -> None:
    p = project()
    print(f"cover: kept {p.rel(r['original'])}")
    if r["kind"] != "template":
        print(f"cover: {r.get('note', '')}")
        return
    print(f"cover template: {p.rel(r['template'])}")
    for field, orig in r["placed"].items():
        print(f"  {{{{{field}}}}}  <- {orig!r}" if orig else f"  {{{{{field}}}}}  (blank field)")
    if r.get("note"):
        print(f"note: {r['note']}")
    if r["prefilled"]:
        print("project.yaml filled from the cover: " + ", ".join(f"{k} = {v!r}" for k, v in r["prefilled"].items()))
    for key, (mine, theirs) in (r.get("different") or {}).items():
        print(f"note: project.yaml has {key} = {mine!r} but the cover shows {theirs!r} - the cover will now show "
              f"the project.yaml value; change it there if the cover was right")
    if r["missing"]:
        print(f"not found on the cover: {', '.join(r['missing'])} - if the cover should show them, type "
              f"{{{{NAME}}}} where they go in {p.rel(r['template'])} (or ignore if the cover has no such field)")


def cmd_show(cfg: dict) -> None:
    p = project()
    if not p.cover_template.exists():
        print("no cover template yet (project.py add --cover <file>)")
        return
    import build
    values = build.cover_values(cfg, "Dissertation")
    names = sorted({m.group(1) for para in all_paragraphs(Document(str(p.cover_template)))
                    for m in re.finditer(r"\{\{\s*([A-Z_]+)\s*\}\}", para_text(para))})
    print(f"{p.rel(p.cover_template)}:")
    for n in names:
        print(f"  {{{{{n}}}}} -> {values.get(n, '(no value: set it in project.yaml)')!r}")


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make"); m.add_argument("file")
    sub.add_parser("show")
    a = ap.parse_args()
    if a.cmd == "make":
        src = Path(a.file).expanduser().resolve()
        if not src.exists():
            die(f"{src} not found")
        make(src)
    else:
        cmd_show(load_config())


if __name__ == "__main__":
    main()
