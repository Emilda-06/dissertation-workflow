"""Generate config/templates/reference.docx - the Word style template every build uses.

Reads font, size, spacing and margins from config/project.yaml (format: section).
Re-run after changing those settings:  .venv/Scripts/python.exe scripts/make_template.py
"""
from __future__ import annotations

import subprocess

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor

from common import TEMPLATES, load_config, require_tool, setup_stdout


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


def main():
    setup_stdout()
    cfg = load_config()
    fmt = cfg.get("format", {})
    font = fmt.get("font", "Times New Roman")
    size = float(fmt.get("font_size", 12))
    line = float(fmt.get("line_spacing", 1.5))
    table_size = float(fmt.get("table_font_size", size))
    margins = fmt.get("margins_cm", {})

    TEMPLATES.mkdir(parents=True, exist_ok=True)
    base = TEMPLATES / "reference.docx"
    subprocess.run([require_tool("pandoc"), "-o", str(base), "--print-default-data-file", "reference.docx"],
                   check=True)
    doc = Document(str(base))
    J, C, L = WD_ALIGN_PARAGRAPH.JUSTIFY, WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT

    # document defaults
    rpr_default = doc.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr"))
    for el in rpr_default.findall(qn("w:rFonts")):
        rpr_default.remove(el)
    rpr_default.insert(0, parse_xml(f'<w:rFonts {nsdecls("w")} w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}" w:eastAsia="{font}"/>'))

    body_styles = ["Normal", "Body Text", "First Paragraph"]
    for name in body_styles:
        s = get_style(doc, name)
        set_font(s, font, size)
        para(s, J, line, 0, 6)
    for name in ("Compact",):
        s = get_style(doc, name)
        set_font(s, font, size)
        para(s, L, 1.0 if line <= 1.15 else 1.15, 0, 3)
    s = get_style(doc, "Block Text")
    set_font(s, font, size, italic=False)
    para(s, J, 1.0, 6, 6)
    s.paragraph_format.left_indent = Cm(1.27)
    s.paragraph_format.right_indent = Cm(1.27)

    # headings: H1 centred chapter titles; H2-H4 left aligned numbered sections
    h_sizes = fmt.get("heading_sizes", {1: size, 2: size, 3: size, 4: size})
    for lvl in range(1, 7):
        s = get_style(doc, f"Heading {lvl}")
        set_font(s, font, float(h_sizes.get(lvl, size)), bold=True, italic=(lvl >= 4))
        if lvl == 1:
            para(s, C, 1.5, 0, 18, keep_next=True, page_break=True)
        else:
            para(s, L, 1.5, 12, 6, keep_next=True)
    s = get_style(doc, "Front Heading")
    set_font(s, font, float(h_sizes.get(1, size)), bold=True)
    para(s, C, 1.5, 0, 18, keep_next=True)

    for name in ("Title", "Subtitle", "Author", "Date", "Abstract", "Abstract Title"):
        s = get_style(doc, name)
        set_font(s, font, size)
        para(s, C, line, 0, 6)

    # captions: centred; table caption above table, figure caption below image
    for name in ("caption", "Image Caption", "Table Caption"):
        s = get_style(doc, name)
        set_font(s, font, float(fmt.get("caption_font_size", size)), bold=False, italic=False)
        para(s, C, 1.0, 6, 12 if name != "Table Caption" else 6, keep_next=(name == "Table Caption"))
    for name in ("Figure", "Captioned Figure"):
        s = get_style(doc, name)
        para(s, C, 1.0, 6, 0, keep_next=True)

    s = get_style(doc, "Bibliography")
    set_font(s, font, size)
    para(s, L, line, 0, 8)
    s.paragraph_format.left_indent = Cm(1.27)
    s.paragraph_format.first_line_indent = Cm(-1.27)

    for lvl in range(1, 4):
        s = get_style(doc, f"TOC {lvl}")
        set_font(s, font, size, bold=(lvl == 1))
        para(s, L, 1.15, 0, 4)
        s.paragraph_format.left_indent = Cm(0.6 * (lvl - 1))
    s = get_style(doc, "table of figures")
    set_font(s, font, size)
    para(s, L, 1.15, 0, 4)
    s = get_style(doc, "TOC Heading")
    set_font(s, font, size, bold=True)
    para(s, C, 1.5, 0, 12)

    for name in ("Hyperlink",):
        try:
            hs = doc.styles[name]
            hs.font.color.rgb = RGBColor(0, 0, 0)
            hs.font.underline = False
        except KeyError:
            pass
    for name in ("Footnote Text",):
        s = get_style(doc, name)
        set_font(s, font, 10)

    # table style: full grid, bold shaded header row that repeats across pages
    styles_el = doc.styles.element
    for st in styles_el.findall(qn("w:style")):
        if st.get(qn("w:styleId")) == "Table":
            styles_el.remove(st)
    styles_el.append(parse_xml(TABLE_STYLE.replace("{font}", font).replace("{size}", str(int(table_size * 2)))))

    for sec in doc.sections:
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.top_margin = Cm(margins.get("top", 2.54))
        sec.bottom_margin = Cm(margins.get("bottom", 2.54))
        sec.left_margin = Cm(margins.get("left", 2.54))
        sec.right_margin = Cm(margins.get("right", 2.54))

    doc.save(str(base))
    print(f"wrote {base}  ({font} {size:g}pt, line spacing {line:g}, justified body, centred H1)")


if __name__ == "__main__":
    main()
