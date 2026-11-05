"""Project setup from the user's own files: cover -> template, guidelines, past work, feedback, layout upgrade."""
from __future__ import annotations

import subprocess

import pytest
import yaml
from docx import Document
from docx.shared import Pt

import build
import common
import cover
import project as project_mod
from common import find_tool, load_config
from conftest import make_project, run_script

HAVE_PANDOC = bool(find_tool("pandoc"))


def cover_doc(path, lines):
    d = Document()
    for text, size, bold in lines:
        r = d.add_paragraph().add_run(text)
        if size:
            r.font.size = Pt(size)
        r.bold = bold
    d.save(str(path))
    return path


FILLED = [("UNIVERSITY OF ZIMBABWE", 16, True), ("FACULTY OF ENGINEERING", 13, True),
          ("DEPARTMENT OF COMPUTER SCIENCE", 13, True),
          ("A Lightweight Intrusion Detection System for Smart Homes", 20, True),
          ("A dissertation submitted in partial fulfilment of the requirements for the degree of BSc Honours in "
           "Computer Science", 12, False),
          ("Name: Tendai Moyo", 12, False), ("Student Number: R191234X", 12, False),
          ("Supervisor: Dr P. Chikwanha", 12, False), ("November 2026", 12, False)]


def texts(path):
    return [cover.para_text(p) for p in cover.all_paragraphs(Document(str(path)))]


def test_filled_cover_becomes_template_and_fills_project(proj, tmp_path):
    cfg = proj.config_file
    data = yaml.safe_load(cfg.read_text())
    data["project"].update({"title": "Your Dissertation Title", "student_name": "Your Name"})
    cfg.write_text(yaml.safe_dump(data))
    r = cover.make(cover_doc(tmp_path / "My cover.docx", FILLED), quiet=True)
    assert r["kind"] == "template" and set(r["placed"]) >= {"TITLE", "STUDENT_NAME", "STUDENT_ID", "SUPERVISOR",
                                                           "UNIVERSITY", "FACULTY", "DEPARTMENT", "PROGRAMME", "DATE"}
    t = texts(proj.cover_template)
    assert t[0] == "{{UNIVERSITY}}" and t[3] == "{{TITLE}}" and "Name: {{STUDENT_NAME}}" in t
    assert "degree of {{PROGRAMME}}" in t[4]
    assert (proj.cover_dir / "My cover.docx").exists()                    # original kept as given
    p = yaml.safe_load(cfg.read_text())["project"]
    assert p["student_name"] == "Tendai Moyo" and p["title"].startswith("A Lightweight")
    assert p["university"] == "Test University"                          # a value you set is never replaced
    assert "university" in r["different"]
    # formatting kept: the title run is still 20 pt and bold
    title = next(x for x in Document(str(proj.cover_template)).paragraphs if "{{TITLE}}" in x.text)
    assert title.runs[0].font.size == Pt(20) and title.runs[0].bold


def test_blank_form_cover(proj, tmp_path):
    lines = [("UNIVERSITY OF ZIMBABWE", 16, True), ("PROJECT TITLE: ______________", 14, True),
             ("Student Name: ____________", 12, False), ("Registration No: ________", 12, False),
             ("Supervisor:", 12, False), ("Date of submission: .........", 12, False)]
    r = cover.make(cover_doc(tmp_path / "blank.docx", lines), quiet=True)
    t = texts(proj.cover_template)
    assert t[1:] == ["PROJECT TITLE: {{TITLE}}", "Student Name: {{STUDENT_NAME}}", "Registration No: {{STUDENT_ID}}",
                     "Supervisor: {{SUPERVISOR}}", "Date of submission: {{DATE}}"]
    assert r["found"].get("STUDENT_NAME") is None                        # blanks are not values


def test_existing_placeholders_are_kept(proj, tmp_path):
    r = cover.make(cover_doc(tmp_path / "c.docx", [("{{TITLE}}", 18, True), ("By {{STUDENT_NAME}}", 12, False)]),
                   quiet=True)
    assert texts(proj.cover_template) == ["{{TITLE}}", "By {{STUDENT_NAME}}"]
    assert r["placed"]["TITLE"] == "(already a placeholder)"


def test_template_is_filled_at_build(proj, tmp_path):
    cover.make(cover_doc(tmp_path / "c.docx", FILLED), quiet=True)
    out = tmp_path / "filled.docx"
    build.fill_placeholders(proj.cover_template, out, build.cover_values(load_config(), "Dissertation"))
    t = texts(out)
    assert "Name: Test Student" in t and not any("{{" in x for x in t)


def test_image_cover_is_used_as_picture(proj, tmp_path):
    from PIL import Image
    img = tmp_path / "cover.png"
    Image.new("RGB", (100, 140), "white").save(img)
    r = cover.make(img, quiet=True)
    assert r["kind"] == "image" and not proj.cover_template.exists()
    assert build.prepare_cover(load_config(), "Dissertation", "none") == ("image", str(proj.cover_dir / "cover.png"))


# ---------------------------------------------------------------- documents and chapters

def chapter_docx(path, chapters, refs=True, extra_first=None):
    d = Document()
    if extra_first:
        d.add_paragraph(extra_first, style="Title")
    for heading, body in chapters:
        d.add_paragraph(heading, style="Heading 1")
        d.add_paragraph("Section", style="Heading 2")
        d.add_paragraph(body)
    if refs:
        d.add_paragraph("References", style="Heading 1")
        d.add_paragraph("Smith, J. (2020) A study of things. Journal of Things, 1(1), pp. 1-2.")
    d.save(str(path))
    return path


def test_detect_chapters(tmp_path):
    plan = {n: c for n, c in __import__("conftest").PLAN.items()}
    one = chapter_docx(tmp_path / "anything.docx", [("CHAPTER ONE: INTRODUCTION", "Intro text.")])
    kind, parts = project_mod.detect_chapters(one, plan)
    assert kind == "chapters" and [p["chapter"] for p in parts] == [1]
    full = chapter_docx(tmp_path / "draft.docx", [("Chapter 2 - Literature Review", "Lit."),
                                                  ("CHAPTER THREE: METHODOLOGY", "Method.")], extra_first="Draft")
    kind, parts = project_mod.detect_chapters(full, plan)
    assert [p["chapter"] for p in parts] == [2, 3] and parts[0]["refs"] is not None
    named = Document()
    named.add_paragraph("Some text without headings.")
    named.save(str(tmp_path / "ch4 design notes.docx"))
    assert project_mod.detect_chapters(tmp_path / "ch4 design notes.docx", plan)[1][0]["chapter"] == 4
    prop = Document()
    prop.add_paragraph("Research Proposal", style="Title")
    prop.save(str(tmp_path / "my plan.docx"))
    assert project_mod.detect_chapters(tmp_path / "my plan.docx", plan)[0] == "proposal"


def test_split_keeps_one_chapter_and_the_references(tmp_path):
    plan = __import__("conftest").PLAN
    full = chapter_docx(tmp_path / "draft.docx", [("CHAPTER TWO: LITERATURE REVIEW", "Lit text."),
                                                  ("CHAPTER THREE: METHODOLOGY", "Method text.")])
    _, parts = project_mod.detect_chapters(full, plan)
    out = project_mod.split_part(full, parts[1], tmp_path / "ch3.docx")
    t = [p.text for p in Document(str(out)).paragraphs]
    assert "CHAPTER THREE: METHODOLOGY" in t and "Method text." in t and "Lit text." not in t
    assert "References" in t and any(x.startswith("Smith") for x in t)


def test_new_with_documents_places_everything(projects_dir, tmp_path):
    src = tmp_path / "inbox"
    (src / "rules").mkdir(parents=True)
    cover_doc(src / "cover.docx", FILLED)
    (src / "rules" / "Handbook.md").write_text("# CHAPTER ONE: INTRODUCTION\n## Background\nDescribe it.\n")
    (src / "rules" / "~$lock.docx").write_text("x")                       # Word lock files are skipped
    chapter_docx(src / "Chapter 1 draft.docx", [("CHAPTER ONE: INTRODUCTION", "Intro.")], refs=False)
    (src / "supervisor.txt").write_text("Please tighten the problem statement.")
    r = run_script("project.py", "new", "thesis", "--cover", str(src / "cover.docx"), "--guidelines",
                   str(src / "rules"), "--past-work", str(src / "Chapter 1 draft.docx"), "--feedback",
                   str(src / "supervisor.txt"), "--no-import", projects_dir=projects_dir, check=True)
    p = common.Project(projects_dir / "thesis")
    assert (p.cover_dir / "cover.docx").exists() and p.cover_template.exists()
    assert (p.guidelines / "Handbook.md").exists() and not (p.guidelines / "~$lock.docx").exists()
    assert p.manifest.exists()                                            # guidelines were scanned
    assert (p.past_work / "Chapter 1 draft.docx").exists() and (p.feedback / "supervisor.txt").exists()
    notes = (p.past_work / "NOTES.md").read_text()
    assert "Chapter 1 draft.docx` - chapter(s) 1" in notes
    cfg = yaml.safe_load(p.config_file.read_text())
    assert cfg["project"]["title"].startswith("A Lightweight")           # title read from the cover
    assert "set up:" in r.stdout and "cover" in r.stdout and "chapters      0/6" in r.stdout
    log = subprocess.run(["git", "-C", str(p.root), "log", "--format=%s"], capture_output=True, text=True).stdout
    assert "set up:" in log


@pytest.mark.skipif(not HAVE_PANDOC, reason="pandoc is not installed")
def test_add_past_work_imports_chapters_and_never_overwrites(projects_dir, tmp_path):
    make_project(projects_dir, "thesis")
    full = chapter_docx(tmp_path / "full draft.docx", [("CHAPTER TWO: LITERATURE REVIEW", "Lit text here."),
                                                       ("CHAPTER THREE: METHODOLOGY", "Method text here.")],
                        refs=False)
    r = run_script("project.py", "add", "--past-work", str(full), projects_dir=projects_dir, check=True)
    p = common.Project(projects_dir / "thesis")
    ch3 = p.chapters / "chapter_three" / "chapter.md"
    assert (p.chapters / "chapter_two" / "chapter.md").exists() and ch3.exists()
    assert "docs/past_work/full draft.docx (CHAPTER THREE: METHODOLOGY)" in ch3.read_text()
    assert "Method text here." in ch3.read_text() and "Lit text here." not in ch3.read_text()
    ch3.write_text(ch3.read_text() + "\nMy own edit.\n")
    r = run_script("project.py", "add", "--past-work", str(full), projects_dir=projects_dir, check=True)
    assert "already in the workflow" in r.stdout and "My own edit." in ch3.read_text()
    assert (p.past_work / "full draft.docx").exists() and not (p.past_work / "full draft (2).docx").exists()


def test_same_name_different_file_is_kept_apart(projects_dir, tmp_path):
    make_project(projects_dir, "thesis")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "notes.txt").write_text("first")
    (b / "notes.txt").write_text("second")
    run_script("project.py", "add", "--feedback", str(a / "notes.txt"), projects_dir=projects_dir, check=True)
    run_script("project.py", "add", "--feedback", str(b / "notes.txt"), projects_dir=projects_dir, check=True)
    p = common.Project(projects_dir / "thesis")
    assert (p.feedback / "notes.txt").read_text() == "first" and (p.feedback / "notes (2).txt").read_text() == "second"


def test_setup_creates_or_adds(projects_dir, tmp_path):
    f = tmp_path / "fb.txt"
    f.write_text("x")
    run_script("project.py", "setup", "demo", "--title", "Demo", projects_dir=projects_dir, check=True)
    r = run_script("project.py", "setup", "demo", "--feedback", str(f), projects_dir=projects_dir, check=True)
    assert "exists - adding to it" in r.stdout
    assert (projects_dir / "demo" / "docs" / "feedback" / "fb.txt").exists()
    assert run_script("project.py", "add", projects_dir=projects_dir).returncode != 0      # nothing given


def test_old_layout_is_upgraded_on_first_use(projects_dir):
    root = projects_dir / "old"
    for d in ("guidelines", "existing", "references", "templates", "output/chapters/chapter_one"):
        (root / d).mkdir(parents=True)
    (root / "project.yaml").write_text(yaml.safe_dump({"project": {"title": "Old", "current_topic_source":
                                                                   "existing/proposal.docx"},
                                                       "chapters": {1: {"title": "Intro"}},
                                                       "format": {"template": "guidelines/uni.docx"}}))
    (root / "style.yaml").write_text("voice_sample: existing/report.md\n")
    (root / "cover.docx").write_bytes(b"x")
    (root / "existing" / "proposal.docx").write_bytes(b"x")
    (root / "references" / "references.json").write_text("[]")
    (root / "output/chapters/chapter_one/chapter.md").write_text("---\nchapter: 1\n---\n\n## A\n")
    common.select_project("old")
    p = common.project()
    assert p.config_file.exists() and p.style_file.exists() and p.library.exists()
    assert (p.past_work / "proposal.docx").exists() and (p.cover_dir / "cover.docx").exists()
    assert p.cover_template.exists() and not (root / "project.yaml").exists()
    cfg = p.config_file.read_text()
    assert "docs/past_work/proposal.docx" in cfg and "docs/guidelines/uni.docx" in cfg
    assert "docs/past_work/report.md" in p.style_file.read_text()
    assert common.upgrade_layout(p) == []                                 # idempotent


def test_imported_draft_is_not_self_plagiarism_but_a_proposal_is(proj):
    import textsim
    (proj.past_work / "ch1 draft.md").write_text("Smart homes now connect cameras, locks and sensors to the internet "
                                                 "and each device is a possible entry point for attackers.\n")
    (proj.past_work / "proposal.md").write_text("The aim is to design a lightweight intrusion detection system that "
                                                "runs on resource constrained smart home devices.\n")
    from conftest import write_chapter
    write_chapter(proj, 1, "## A\n\nSmart homes now connect cameras, locks and sensors to the internet and each "
                           "device is a possible entry point for attackers.\n\nThe aim is to design a lightweight "
                           "intrusion detection system that runs on resource constrained smart home devices.\n",
                  imported_from="docs/past_work/ch1 draft.md (CHAPTER ONE)")
    from common import read_front_matter
    matches, _ = textsim.scan_text(read_front_matter(proj.chapters / "chapter_one" / "chapter.md")[1])
    assert [m.source for m in matches] == ["your earlier work: proposal.md"]
