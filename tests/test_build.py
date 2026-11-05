"""Steps 4, 6 and 7: building, templates, covers, redlines and Word-optional finishing."""
from __future__ import annotations

import shutil

import pytest
import yaml
from docx import Document

import build
import common
import make_template
from common import find_tool, load_config
from conftest import add_verified_source, run_script, write_chapter

HAVE_PANDOC = bool(find_tool("pandoc") and find_tool("pandoc-crossref"))


def test_placeholders_split_across_runs_headers_and_tables(tmp_path):
    d = Document()
    p = d.add_paragraph()
    r1 = p.add_run("Title: {{TI")
    r1.bold = True
    p.add_run("TLE}} ({{YEAR}})")
    d.add_table(rows=1, cols=1).cell(0, 0).text = "Supervisor: {{SUPERVISOR}}"
    d.sections[0].header.paragraphs[0].text = "{{UNIVERSITY}}"
    d.sections[0].footer.paragraphs[0].text = "{{UNKNOWN}} stays"
    src, out = tmp_path / "c.docx", tmp_path / "o.docx"
    d.save(str(src))
    n = build.fill_placeholders(src, out, {"TITLE": "My Study", "YEAR": "2026", "SUPERVISOR": "Dr X",
                                           "UNIVERSITY": "Uni"})
    o = Document(str(out))
    assert n == 4
    assert o.paragraphs[0].text == "Title: My Study (2026)" and o.paragraphs[0].runs[0].bold
    assert o.tables[0].cell(0, 0).text == "Supervisor: Dr X"
    assert o.sections[0].header.paragraphs[0].text == "Uni"
    assert o.sections[0].footer.paragraphs[0].text == "{{UNKNOWN}} stays"


def test_numbering_sections_and_requirement_markers(proj):
    write_chapter(proj, 2, "## Intro {#sec:intro}\n\nSee @sec:gap. <!-- req: R1 -->\n\n### Sub\n\n## Gap {#sec:gap}\n\n"
                           "![A figure caption here please.](diagrams/a.png){#fig:a}\n")
    md, meta = build.number_chapter(2, load_config())
    assert md.startswith("# CHAPTER TWO: LITERATURE REVIEW {#sec:chapter2 label=\"2\"}")
    assert "## 2.1 Intro" in md and "### 2.1.1 Sub" in md and "## 2.2 Gap" in md
    assert "[Section 2.2](#sec:gap)" in md and "req:" not in md
    assert "](output/chapters/chapter_two/diagrams/a.png)" in md


def test_appendix_numbering(proj):
    d = proj.appendices / "appendix_b"
    d.mkdir(parents=True)
    (d / "appendix.md").write_text("---\ntitle: Survey\n---\n\n## Questions\n\n### Part one\n")
    md, _ = build.number_appendix("b", load_config())
    assert md.startswith("# APPENDIX B: SURVEY {#app:b label=\"B\"}") and "## B.1 Questions" in md
    assert "### B.1.1 Part one" in md
    assert common.existing_appendices() == ["B"]


def test_citation_style_selection(proj):
    cfg = load_config()
    assert build.csl_path(cfg).name == "harvard-cite-them-right.csl"
    cfg["references"]["style"] = "IEEE"
    assert build.csl_path(cfg).name == "ieee.csl"
    cfg["references"]["style"] = "APA 7th"
    assert build.csl_path(cfg).name == "apa.csl"
    cfg["references"]["style"] = "chicago"
    with pytest.raises(SystemExit):
        build.csl_path(cfg)
    proj.templates.mkdir(exist_ok=True)
    (proj.templates / "dept.csl").write_text("<style/>")
    cfg["references"]["style"] = "dept.csl"
    assert build.csl_path(cfg) == proj.templates / "dept.csl"


def test_reference_docx_regenerates_only_when_inputs_change(proj):
    cfg = load_config()
    out = make_template.ensure_reference(cfg)
    first = out.stat().st_mtime_ns
    assert make_template.ensure_reference(cfg).stat().st_mtime_ns == first           # unchanged
    cfg["format"]["font"] = "Arial"
    cfg["format"]["paper"] = "Letter"
    make_template.ensure_reference(cfg)
    doc = Document(str(out))
    assert doc.styles["Normal"].font.name == "Arial"
    assert round(doc.sections[0].page_width.cm, 2) == 21.59
    assert "PAGE" in doc.sections[0].footer.paragraphs[0]._p.xml
    # a reference.docx you place yourself is never overwritten
    (out.parent / make_template.HASH_FILE).unlink()
    out.write_bytes(out.read_bytes())
    cfg["format"]["font"] = "Calibri"
    before = out.read_bytes()
    make_template.ensure_reference(cfg)
    assert out.read_bytes() == before


def test_university_format_template_styles_are_kept(proj):
    d = Document()
    d.styles["Normal"].font.name = "Garamond"
    d.add_paragraph("x")
    d.save(str(proj.guidelines / "uni.docx"))
    cfg = load_config()
    cfg["format"]["template"] = "guidelines/uni.docx"
    out = make_template.ensure_reference(cfg, force=True)
    doc = Document(str(out))
    assert doc.styles["Normal"].font.name == "Garamond"                 # university style respected
    assert "Image Caption" in [s.name for s in doc.styles]               # pandoc styles added
    assert not any(p.text == "x" for p in doc.paragraphs)                # body content removed


def test_word_diff_markdown():
    old = "---\nt: 1\n---\n\n## Intro\n\nThe system is slow.\n\nRemoved paragraph here.\n"
    new = "---\nt: 1\n---\n\n## Intro\n\nThe system is fast.\n\nA brand new paragraph.\n"
    md = build.word_diff_markdown(old, new)
    assert "~~slow.~~" in md and "[fast.]{.underline}" in md and "## Intro" in md


def test_finalizer_choice(proj, monkeypatch):
    cfg = load_config()
    monkeypatch.setattr(build, "word_available", lambda: False)
    monkeypatch.setattr(build, "find_tool", lambda name: None)
    cfg["format"]["finalizer"] = "auto"
    assert build.finalizer(cfg) == "none"
    cfg["format"]["finalizer"] = "word"
    with pytest.raises(SystemExit):
        build.finalizer(cfg)


@pytest.mark.skipif(not HAVE_PANDOC, reason="pandoc and pandoc-crossref are not installed")
def test_end_to_end_build_without_word(proj, projects_dir):
    add_verified_source(proj)
    body = ("## Introduction {#sec:intro}\n\nEdge security matters for many systems today [@smith2021edge].\n\n"
            "## Findings\n\nAs @tbl:t shows, the values differ between runs in a way worth noting.\n\n"
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n: Values per run in the study. {#tbl:t}\n")
    write_chapter(proj, 1, body)
    (proj.root / "project.yaml").write_text(
        (proj.root / "project.yaml").read_text().replace("finalizer: none", "finalizer: none"))
    r = run_script("build.py", "chapter", "1", "--force", "--no-zotero", projects_dir=projects_dir, check=True)
    assert "BUILT" in r.stdout
    out = proj.chapters / "chapter_one" / "docs" / "chapter_one_v1.docx"
    assert out.exists() and out.with_suffix(".md").exists()
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "CHAPTER ONE: INTRODUCTION" in text and "(Smith, 2021)" in text and "REFERENCES" in text
    # second version + redline (diff document without Word)
    write_chapter(proj, 1, body.replace("matters for many", "matters greatly for many"))
    run_script("build.py", "chapter", "1", "--force", "--no-zotero", projects_dir=projects_dir, check=True)
    cfg = yaml.safe_load(proj.config_file.read_text())
    assert cfg["format"]["finalizer"] == "none"
    monkey = run_script("build.py", "redline", "1", projects_dir=projects_dir)
    assert monkey.returncode == 0, monkey.stderr
    assert (proj.chapters / "chapter_one" / "docs" / "chapter_one_v2_tracked.docx").exists()


@pytest.mark.skipif(not HAVE_PANDOC, reason="pandoc and pandoc-crossref are not installed")
def test_combine_places_appendices_after_references(proj, projects_dir):
    add_verified_source(proj)
    write_chapter(proj, 1, "## Introduction\n\nA claim [@smith2021edge].\n")
    d = proj.appendices / "appendix_a"
    d.mkdir(parents=True)
    (d / "appendix.md").write_text("---\ntitle: Interview guide\n---\n\n## Questions\n\nText.\n")
    run_script("build.py", "combine", "--force", "--no-zotero", projects_dir=projects_dir, check=True)
    out = proj.dissertation / "docs" / "dissertation_v1.docx"
    texts = [p.text for p in Document(str(out)).paragraphs if p.text.strip()]
    i_refs = max(i for i, t in enumerate(texts) if t.startswith("REFERENCES"))
    i_app = max(i for i, t in enumerate(texts) if t.startswith("APPENDIX A"))
    assert i_refs < i_app and sum(t == "REFERENCES" for t in texts) == 1
    assert any(t.startswith("Smith, A.") for t in texts[i_refs:i_app])


def test_status_and_context_run(proj, projects_dir):
    add_verified_source(proj)
    write_chapter(proj, 1, "## Statement of the problem\n\nThe problem is real [@smith2021edge].\n\n"
                           "## Objectives\n\nTo study it.\n")
    out = run_script("status.py", "--html", projects_dir=projects_dir, check=True).stdout
    assert "Introduction" in out and "not written" in out
    assert (proj.output / "status.html").exists()
    ctx = run_script("context.py", "1", projects_dir=projects_dir, check=True).stdout
    assert "Statement of the problem" in ctx and "Outline skeleton" in ctx


def test_pipeline_begin_resumes(proj, projects_dir):
    shutil.which("git") or pytest.skip("git missing")
    import project as project_mod
    project_mod.init_repo(proj)
    write_chapter(proj, 1, "## Introduction\n\nText.\n")
    r = run_script("pipeline.py", "begin", "1", "new", "write it", projects_dir=projects_dir, check=True)
    assert "IN PROGRESS" in r.stdout
    r = run_script("pipeline.py", "begin", "1", "new", "write it", projects_dir=projects_dir, check=True)
    assert "resuming" in r.stdout


@pytest.mark.skipif(not HAVE_PANDOC, reason="pandoc and pandoc-crossref are not installed")
def test_verified_entry_wins_over_zotero_copy(proj, projects_dir):
    add_verified_source(proj)
    common.save_json(proj.zotero_export, [{"id": "smith2021edge", "type": "article-journal",
                                           "title": "Garbled zotero copy", "author": [{"family": "Smith"}],
                                           "issued": {"date-parts": [[2021]]}}])
    write_chapter(proj, 1, "## Introduction\n\nA claim [@smith2021edge].\n")
    run_script("build.py", "chapter", "1", "--force", "--no-zotero", projects_dir=projects_dir, check=True)
    text = "\n".join(p.text for p in Document(str(proj.chapters / "chapter_one" / "docs" / "chapter_one_v1.docx")).paragraphs)
    assert "Edge intelligence security survey" in text and "Garbled" not in text
