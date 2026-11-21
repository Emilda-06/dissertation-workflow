"""Generate the active project's Word style template: projects/<name>/templates/reference.docx.

Reads font, size, spacing, margins and paper size from project.yaml (format: section). If the project
has a university Word *formatting* template (format.template in project.yaml, or a .docx in guidelines/
detected as a formatting template), its styles are the starting point and are kept as they are; only
styles pandoc needs and the template lacks are added (set format.override_template: true to apply the
format: settings on top anyway).

build.py regenerates the template automatically whenever these inputs change. Manual run:
  python scripts/make_template.py [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor

from common import SHARED_TEMPLATES, die, init_cli, load_config, project, require_tool

PAPER = {"a4": (21.0, 29.7), "letter": (21.59, 27.94)}
HASH_FILE = ".reference.hash"
CREATED: set[str] = set()


def set_font(style, name: str, size: float | None = None, bold=None, italic=None):
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = parse_xml(f"<w:rFonts {nsdecls('w')}/>")
        rpr.insert(0, fonts)
    for attr in list(fonts.attrib):
        if "Theme" in attr or "theme" in attr:
            del fonts.attrib[attr]
    for a in ("ascii", "hAnsi", "cs", "eastAsia"):
        fonts.set(qn(f"w:{a}"), name)
    f = style.font
    if size:
        f.size = Pt(size)
        szcs = rpr.find(qn("w:szCs"))
        if szcs is None:
            szcs = parse_xml(f"<w:szCs {nsdecls('w')}/>")
            rpr.append(szcs)
        szcs.set(qn("w:val"), str(int(size * 2)))
    if bold is not None:
        f.bold = bold
    if italic is not None:
        f.italic = italic
    f.color.rgb = RGBColor(0, 0, 0)


def para(style, align=None, line=1.5, before=0, after=6, first_indent=None, keep_next=None, page_break=None):
    pf = style.paragraph_format
    if align is not None:
        pf.alignment = align
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE if line != 1 else WD_LINE_SPACING.SINGLE
    pf.line_spacing = line
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    if first_indent is not None:
        pf.first_line_indent = first_indent
    if keep_next is not None:
        pf.keep_with_next = keep_next
    if page_break is not None:
        pf.page_break_before = page_break


def get_style(doc, name, kind=WD_STYLE_TYPE.PARAGRAPH, base="Normal"):
    try:
        return doc.styles[name]
    except KeyError:
        s = doc.styles.add_style(name, kind)
        if kind == WD_STYLE_TYPE.PARAGRAPH and base:
            s.base_style = doc.styles[base]
        CREATED.add(name)
        return s


TABLE_STYLE = f"""
<w:style {nsdecls('w')} w:type="table" w:default="1" w:styleId="Table">
  <w:name w:val="Table"/><w:basedOn w:val="TableNormal"/><w:uiPriority w:val="59"/><w:qFormat/>
  <w:pPr><w:spacing w:before="40" w:after="40" w:line="240" w:lineRule="auto"/><w:jc w:val="left"/></w:pPr>
  <w:rPr><w:rFonts w:ascii="{{font}}" w:hAnsi="{{font}}" w:cs="{{font}}" w:eastAsia="{{font}}"/><w:sz w:val="{{size}}"/><w:szCs w:val="{{size}}"/></w:rPr>
  <w:tblPr>
    <w:jc w:val="center"/>
    <w:tblBorders>
      <w:top w:val="single" w:sz="6" w:space="0" w:color="000000"/>
      <w:left w:val="single" w:sz="6" w:space="0" w:color="000000"/>
      <w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/>
      <w:right w:val="single" w:sz="6" w:space="0" w:color="000000"/>
      <w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>
      <w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/>
    </w:tblBorders>
    <w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar>
  </w:tblPr>
  <w:tblStylePr w:type="firstRow">
    <w:pPr><w:keepNext/></w:pPr>
    <w:rPr><w:b/><w:bCs/></w:rPr>
    <w:tblPr/>
    <w:trPr><w:tblHeader/></w:trPr>
    <w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="D9D9D9"/><w:vAlign w:val="center"/></w:tcPr>
  </w:tblStylePr>
</w:style>"""


def format_template(cfg: dict) -> Path | None:
    """The university formatting template for this project, if any."""
    p = project()
    fmt = cfg.get("format", {}) or {}
    if fmt.get("template"):
        t = Path(fmt["template"])
        t = t if t.is_absolute() else p.root / t
        if not t.exists():
            die(f"format.template {t} not found")
        return t
    if p.manifest.exists():
        for name, rec in json.loads(p.manifest.read_text(encoding="utf-8")).get("files", {}).items():
            if rec.get("kind") == "format" and (p.guidelines / name).exists():
                return p.guidelines / name
    return None


def inputs_hash(cfg: dict) -> str:
    fmt = cfg.get("format", {}) or {}
    tpl = format_template(cfg)
    basis = {"format": fmt, "template": hashlib.sha256(tpl.read_bytes()).hexdigest() if tpl else None,
             "script": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()


def reference_path() -> Path:
    return project().templates / "reference.docx"


def ensure_reference(cfg: dict, force: bool = False, quiet: bool = True) -> Path:
    """Regenerate the project's reference.docx when its inputs changed. A reference.docx you placed in
    templates/ yourself (no hash file next to it) is never overwritten unless force=True."""
    out = reference_path()
    hfile = out.parent / HASH_FILE
    want = inputs_hash(cfg)
    if out.exists() and not hfile.exists() and not force:
        return out                                   # user-provided template
    if out.exists() and hfile.exists() and hfile.read_text().strip() == want and not force:
        return out
    generate(cfg, out)
    hfile.write_text(want, encoding="utf-8")
    if not quiet:
        print(f"wrote {project().rel(out)}")
    return out


def clear_body(doc) -> None:
    body = doc.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def add_page_footer(sec, font: str, size: float) -> None:
    """Centred PAGE field in the footer (used when Word does not finalise the document)."""
    footer = sec.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    for r in list(p.runs):
        r._element.getparent().remove(r._element)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for xml in ('<w:r %s><w:fldChar w:fldCharType="begin"/></w:r>',
                '<w:r %s><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>',
                '<w:r %s><w:fldChar w:fldCharType="separate"/></w:r>',
                '<w:r %s><w:t>1</w:t></w:r>',
                '<w:r %s><w:fldChar w:fldCharType="end"/></w:r>'):
        p._p.append(parse_xml(xml % nsdecls("w")))
    for r in p.runs:
        r.font.name = font
        r.font.size = Pt(size)


def generate(cfg: dict, out: Path) -> Path:
    CREATED.clear()
    fmt = cfg.get("format", {}) or {}
    font = fmt.get("font", "Times New Roman")
    size = float(fmt.get("font_size", 12))
    line = float(fmt.get("line_spacing", 1.5))
    table_size = float(fmt.get("table_font_size", size))
    margins = fmt.get("margins_cm", {}) or {}
    paper = PAPER.get(str(fmt.get("paper", "A4")).lower(), PAPER["a4"])
    out.parent.mkdir(parents=True, exist_ok=True)

    university = format_template(cfg)
    respect = bool(university) and not fmt.get("override_template", False)
    if university:
        doc = Document(str(university))
        clear_body(doc)
    elif (SHARED_TEMPLATES / "reference.docx").exists():
        doc = Document(str(SHARED_TEMPLATES / "reference.docx"))      # shared default (pandoc styles)
    else:
        subprocess.run([require_tool("pandoc"), "-o", str(out), "--print-default-data-file", "reference.docx"],
                       check=True)
        doc = Document(str(out))
    J, C, L = WD_ALIGN_PARAGRAPH.JUSTIFY, WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT

    def styled(name, kind=WD_STYLE_TYPE.PARAGRAPH, base="Normal"):
        """The style to format, or None when an existing university style must be left alone."""
        s = get_style(doc, name, kind, base)
        return None if respect and name not in CREATED else s

    if not respect:
        rpr_default = doc.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr"))
        for el in rpr_default.findall(qn("w:rFonts")):
            rpr_default.remove(el)
        rpr_default.insert(0, parse_xml(f'<w:rFonts {nsdecls("w")} w:ascii="{font}" w:hAnsi="{font}" '
                                        f'w:cs="{font}" w:eastAsia="{font}"/>'))

    for name in ("Normal", "Body Text", "First Paragraph"):
        if (s := styled(name)) is not None:
            set_font(s, font, size)
            para(s, J, line, 0, 6)
    if (s := styled("Compact")) is not None:
        set_font(s, font, size)
        para(s, L, 1.0 if line <= 1.15 else 1.15, 0, 3)
    # code blocks / pseudocode: never justified (Normal is), single spaced, keep the monospace font
    if (s := styled("Source Code")) is not None:
        para(s, L, 1.0, 0, 8)
        s.paragraph_format.keep_together = True
    if (s := styled("Block Text")) is not None:
        set_font(s, font, size, italic=False)
        para(s, J, 1.0, 6, 6)
        s.paragraph_format.left_indent = Cm(1.27)
        s.paragraph_format.right_indent = Cm(1.27)

    # headings: H1 centred chapter titles; H2-H4 left aligned numbered sections
    h_sizes = {int(k): v for k, v in (fmt.get("heading_sizes") or {}).items()}
    for lvl in range(1, 7):
        if (s := styled(f"Heading {lvl}")) is not None:
            set_font(s, font, float(h_sizes.get(lvl, size)), bold=True, italic=(lvl >= 4))
            if lvl == 1:
                para(s, C, 1.5, 0, 18, keep_next=True, page_break=True)
            else:
                para(s, L, 1.5, 12, 6, keep_next=True)
    if (s := styled("Front Heading")) is not None:
        set_font(s, font, float(h_sizes.get(1, size)), bold=True)
        para(s, C, 1.5, 0, 18, keep_next=True)

    for name in ("Title", "Subtitle", "Author", "Date", "Abstract", "Abstract Title"):
        if (s := styled(name)) is not None:
            set_font(s, font, size)
            para(s, C, line, 0, 6)

    # captions: centred; table caption above table, figure caption below image
    for name in ("caption", "Image Caption", "Table Caption"):
        if (s := styled(name)) is not None:
            set_font(s, font, float(fmt.get("caption_font_size", size)), bold=False, italic=False)
            para(s, C, 1.0, 6, 12 if name != "Table Caption" else 6, keep_next=(name == "Table Caption"))
    for name in ("Figure", "Captioned Figure"):
        if (s := styled(name)) is not None:
            para(s, C, 1.0, 6, 0, keep_next=True)

    if (s := styled("Bibliography")) is not None:
        set_font(s, font, size)
        para(s, L, line, 0, 8)
        s.paragraph_format.left_indent = Cm(1.27)
        s.paragraph_format.first_line_indent = Cm(-1.27)

    for lvl in range(1, 4):
        if (s := styled(f"TOC {lvl}")) is not None:
            set_font(s, font, size, bold=(lvl == 1))
            para(s, L, 1.15, 0, 4)
            s.paragraph_format.left_indent = Cm(0.6 * (lvl - 1))
    if (s := styled("table of figures")) is not None:
        set_font(s, font, size)
        para(s, L, 1.15, 0, 4)
    if (s := styled("TOC Heading")) is not None:
        set_font(s, font, size, bold=True)
        para(s, C, 1.5, 0, 12)

    if not respect:
        try:
            hs = doc.styles["Hyperlink"]
            hs.font.color.rgb = RGBColor(0, 0, 0)
            hs.font.underline = False
        except KeyError:
            pass
    if (s := styled("Footnote Text")) is not None:
        set_font(s, font, 10)

    # table style: full grid, bold shaded header row that repeats across pages
    styles_el = doc.styles.element
    has_table = any(st.get(qn("w:styleId")) == "Table" for st in styles_el.findall(qn("w:style")))
    if not (respect and has_table):
        for st in styles_el.findall(qn("w:style")):
            if st.get(qn("w:styleId")) == "Table":
                styles_el.remove(st)
        styles_el.append(parse_xml(TABLE_STYLE.replace("{font}", font).replace("{size}", str(int(table_size * 2)))))

    if not respect:
        for sec in doc.sections:
            sec.page_width, sec.page_height = Cm(paper[0]), Cm(paper[1])
            sec.top_margin = Cm(margins.get("top", 2.54))
            sec.bottom_margin = Cm(margins.get("bottom", 2.54))
            sec.left_margin = Cm(margins.get("left", 2.54))
            sec.right_margin = Cm(margins.get("right", 2.54))
    footer_font = fmt.get("footer_font", font)
    footer_size = float(fmt.get("footer_font_size", size))
    for sec in doc.sections:
        if not respect or not any(p.text.strip() for p in sec.footer.paragraphs):
            add_page_footer(sec, footer_font, footer_size)
    # Word and LibreOffice refresh the contents / lists when the document is opened
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        settings.append(parse_xml(f'<w:updateFields {nsdecls("w")} w:val="true"/>'))
    doc.save(str(out))
    return out


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    out = ensure_reference(cfg, force=args.force, quiet=False)
    tpl = format_template(cfg)
    fmt = cfg.get("format", {}) or {}
    print(f"{project().rel(out)}: " + (f"based on {tpl.name}" if tpl else
          f"{fmt.get('font', 'Times New Roman')} {fmt.get('font_size', 12)}pt, line spacing "
          f"{fmt.get('line_spacing', 1.5)}, paper {fmt.get('paper', 'A4')}"))


if __name__ == "__main__":
    main()
