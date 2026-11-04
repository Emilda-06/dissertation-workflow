"""Step 2: guidelines are found, mapped to chapters without special file names, and enforced."""
from __future__ import annotations

import yaml
from docx import Document

import guidelines as g
from common import load_config
from conftest import write_chapter


def handbook(path):
    d = Document()
    d.add_heading("Final Year Project Handbook", 0)
    d.add_paragraph("All chapters must be written in the third person and use Harvard referencing throughout.")
    d.add_paragraph("Chapter 1 Introduction ........ 3")                    # table of contents line
    d.add_heading("CHAPTER ONE: INTRODUCTION", 1)
    for h, t in [("Background of the study", "Describe the context of the problem in detail."),
                 ("Statement of the problem", "State the problem clearly with evidence."),
                 ("Objectives", "List the main and specific objectives of the project.")]:
        d.add_heading(h, 2)
        d.add_paragraph(t)
    d.add_heading("Chapter 2 - Literature Review", 1)
    d.add_paragraph("Chapter 2 should review at least twenty sources and include a use case diagram of the system.")
    d.add_heading("CHAPTER III: SYSTEM ANALYSIS AND DESIGN", 1)
    d.add_paragraph("Describe the feasibility study and the proposed architecture with a deployment diagram.")
    d.save(str(path))


def test_number_parsing():
    assert g.parse_number("III") == 3 and g.parse_number("twenty-one") == 21 and g.parse_number("7") == 7
    assert g.parse_number("x") == 10 and g.parse_number("banana") is None


def test_handbook_is_split_and_mapped(proj):
    handbook(proj.guidelines / "anything at all.docx")
    m = g.scan(load_config(), quiet=True)
    parts = m["files"]["anything at all.docx"]["parts"]
    by_heading = {p["heading"]: p for p in parts}
    assert by_heading["(before the first chapter)"]["chapter"] == "general"           # has a real rule
    assert by_heading["CHAPTER ONE: INTRODUCTION"]["chapter"] == 1
    assert by_heading["CHAPTER ONE: INTRODUCTION"]["status"] == "auto"
    assert by_heading["Chapter 2 - Literature Review"]["chapter"] == 2
    # "Chapter 2 should review ..." is a sentence, not a new chapter boundary
    assert len(parts) == 4
    third = by_heading["CHAPTER III: SYSTEM ANALYSIS AND DESIGN"]
    assert third["chapter"] == 4 and third["status"] == "review"                     # numbering differs from plan
    assert "numbering differs" in third["reason"]


def test_single_chapter_files_mapped_by_name_or_content(proj):
    (proj.guidelines / "ch2 rules.md").write_text("Write about earlier systems and compare them carefully.\n")
    (proj.guidelines / "notes.txt").write_text("Chapter five should report the measured results in tables.\n")
    (proj.guidelines / "lit.txt").write_text("# Literature Review\nUse recent journal articles.\n")
    (proj.guidelines / "style.txt").write_text("Use one and a half line spacing everywhere in the document.\n")
    m = g.scan(load_config(), quiet=True)
    first = {name: rec["parts"][0] for name, rec in m["files"].items()}
    assert first["ch2 rules.md"]["chapter"] == 2 and first["ch2 rules.md"]["status"] == "auto"
    assert first["notes.txt"]["chapter"] == 5 and first["notes.txt"]["status"] == "review"
    assert first["lit.txt"]["chapter"] == 2
    assert first["style.txt"]["chapter"] == "general"


def test_manual_mapping_survives_rescan(proj):
    (proj.guidelines / "notes.txt").write_text("Some guidance that names no chapter in particular at all.\n")
    g.scan(load_config(), quiet=True)
    proj.requirements.mkdir(exist_ok=True)
    proj.mapping.write_text(yaml.safe_dump({"notes.txt": {"*": 3}}))
    m = g.scan(load_config(), quiet=True)
    p = m["files"]["notes.txt"]["parts"][0]
    assert p["chapter"] == 3 and p["status"] == "manual"


def test_format_template_detected(proj):
    d = Document()
    d.add_paragraph("Body")
    d.save(str(proj.guidelines / "University Template.docx"))
    m = g.scan(load_config(), quiet=True)
    assert m["files"]["University Template.docx"]["kind"] == "format"


def spec_with_intro(proj, extra=None):
    H = "handbook.docx"
    spec = {"version": 1, "approved": None, "sources": {}, "document": {"requirements": []}, "chapters": {
        1: {"title_policy": "exact", "sections": [
            {"id": "background", "title": "Background of the study", "level": 2, "required": True,
             "source": {"file": H, "quote": "Describe the context of the problem"}},
            {"id": "problem", "title": "Statement of the problem", "level": 2, "required": True,
             "aliases": ["problem statement"], "source": {"file": H, "quote": "State the problem clearly"}},
            {"id": "objectives", "title": "Objectives", "level": 2, "required": True,
             "source": {"file": H, "quote": "main and specific objectives"}}],
            "elements": [], "requirements": []},
        2: {"elements": [{"id": "use-case", "kind": "figure", "match": ["use case"], "min": 1, "required": True,
                          "source": {"file": H, "quote": "include a use case diagram"}}],
            "requirements": [{"id": "R1", "text": "Third person", "source": {"file": H, "quote": "written in the third person"}}]},
    }}
    if extra:
        extra(spec)
    proj.requirements.mkdir(exist_ok=True)
    g.save_spec(spec)
    return spec


def test_validate_rejects_invented_requirements(proj):
    handbook(proj.guidelines / "handbook.docx")
    cfg = load_config()
    spec = spec_with_intro(proj)
    errors, _ = g.validate(spec, cfg)
    assert errors == []
    spec["chapters"][2]["requirements"].append(
        {"id": "R2", "text": "x", "source": {"file": "handbook.docx", "quote": "must compare blockchain ledgers"}})
    spec["chapters"][1]["sections"].append({"id": "Bad Id", "title": "", "source": {}})
    errors, _ = g.validate(spec, cfg)
    assert any("quote not found" in e for e in errors)
    assert any("id must be" in e for e in errors) and any("needs source" in e for e in errors)


def test_approve_then_stale_when_guideline_changes(proj):
    handbook(proj.guidelines / "handbook.docx")
    cfg = load_config()
    spec_with_intro(proj)
    g.cmd_approve(None, cfg)
    st = g.spec_status(cfg)
    assert st["approved"] and not st["stale"]
    d = Document(str(proj.guidelines / "handbook.docx"))
    d.add_paragraph("New rule added later by the department for every chapter of the work.")
    d.save(str(proj.guidelines / "handbook.docx"))
    assert g.spec_status(cfg)["stale"] == ["handbook.docx"]


def test_outline_keeps_template_and_expands(proj):
    handbook(proj.guidelines / "handbook.docx")
    spec_with_intro(proj)
    o = g.merged_outline(1, load_config())
    titles = [(s["title"], s["origin"]) for s in o["sections"]]
    tmpl = [t for t, origin in titles if origin == "template"]
    assert tmpl == ["Background of the study", "Statement of the problem", "Objectives"]      # order kept
    assert titles[0] == ("Introduction", "default")                                          # default added first
    names = [t for t, _ in titles]
    assert "Problem statement" not in names                                                  # covered by template
    assert names.index("Aim") > names.index("Statement of the problem")                      # sensible position
    assert names.index("Aim") < names.index("Objectives")
    md = g.outline_markdown(o)
    assert "expand each one" in md and "[expansion]" in md


def test_evaluate_enforces_sections_order_elements_and_markers(proj):
    handbook(proj.guidelines / "handbook.docx")
    spec_with_intro(proj)
    cfg = load_config()
    body = ("## Introduction\n\nText.\n\n## Statement of the problem\n\nText.\n\n"
            "## Background of the study\n\nText.\n")
    res = g.evaluate(1, cfg, body)
    assert any("'Objectives' is missing" in e for e in res["errors"])
    assert any("template's order" in w for w in res["warnings"])
    good = ("## Introduction\n\nText.\n\n## Background of the study\n\nText.\n\n"
            "## Problem statement {#sec:problem}\n\nText.\n\n## Objectives\n\nText.\n")
    res = g.evaluate(1, cfg, good)
    assert res["errors"] == []
    assert not any("template's order" in w for w in res["warnings"])
    ch2 = ("## Review\n\nWe compare systems. <!-- req: R1 -->\n\n"
           "![Architecture of the platform and its main parts.](diagrams/a.png){#fig:arch}\n")
    res = g.evaluate(2, cfg, ch2)
    assert any("use case" in e for e in res["errors"])
    assert not any("R1" in w for w in res["warnings"])
    ch2_ok = ch2.replace("Architecture of the platform", "Use case diagram of the platform")
    assert g.evaluate(2, cfg, ch2_ok)["errors"] == []


def test_check_uses_spec(proj):
    handbook(proj.guidelines / "handbook.docx")
    spec_with_intro(proj)
    write_chapter(proj, 1, "## Introduction\n\nShort text here.\n")
    import check
    res = check.check_chapter(1, load_config(), run_integrity=False)
    assert sum("is missing" in e for e in res["errors"]) == 3
    assert res["stats"]["requirements_met"] == "0/3"


def test_cli_scan_list_show(proj, projects_dir):
    from conftest import run_script
    handbook(proj.guidelines / "handbook.docx")
    out = run_script("guidelines.py", "scan", projects_dir=projects_dir, check=True).stdout
    assert "REVIEW" in out and "chapter 1 (Introduction)" in out
    show = run_script("guidelines.py", "show", "1", projects_dir=projects_dir, check=True).stdout
    assert "Background of the study" in show and "not instructions" in show
    assert "SYSTEM ANALYSIS" not in show


def test_outline_says_when_guideline_is_not_recorded_yet(proj):
    handbook(proj.guidelines / "handbook.docx")
    g.scan(load_config(), quiet=True)
    md = g.outline_markdown(g.merged_outline(1, load_config()))
    assert "requirements are not recorded yet" in md
    md6 = g.outline_markdown(g.merged_outline(6, load_config()))
    assert "No chapter-specific template" in md6
