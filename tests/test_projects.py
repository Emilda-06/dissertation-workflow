"""Step 1: projects are isolated, selectable and versioned."""
from __future__ import annotations

import subprocess

import pytest
import yaml

import common
import project as project_mod
from conftest import add_verified_source, make_project, run_script


def test_number_words_and_slugs():
    assert common.number_word(1) == "one"
    assert common.number_word(13) == "thirteen"
    assert common.number_word(21) == "twenty-one"
    assert common.chapter_slug(21) == "chapter_twenty_one"
    assert all(common.WORD_NUMBERS[common.chapter_slug(n).removeprefix("chapter_")] == n for n in range(1, 100))
    with pytest.raises(ValueError):
        common.number_word(100)


def test_active_project_resolution_order(projects_dir, monkeypatch):
    make_project(projects_dir, "alpha")
    assert common.active_slug() == "alpha"                    # the only project
    make_project(projects_dir, "beta")
    assert common.active_slug() is None                       # ambiguous
    with pytest.raises(SystemExit):
        common.project()
    (projects_dir / ".active").write_text("beta")
    assert common.project().slug == "beta"                    # .active file
    monkeypatch.setenv("DISSERTATION_PROJECT", "alpha")
    assert common.project().slug == "alpha"                   # env beats .active
    common.select_project("beta")
    assert common.project().slug == "beta"                    # --project beats env


def test_init_cli_strips_project_option(projects_dir):
    argv = ["x.py", "show", "--project", "gamma", "1"]
    common.init_cli(argv)
    assert argv == ["x.py", "show", "1"] and common.active_slug() == "gamma"
    argv = ["x.py", "--project=delta"]
    common.init_cli(argv)
    assert argv == ["x.py"] and common.active_slug() == "delta"


def test_unknown_project_is_an_error(projects_dir):
    make_project(projects_dir, "alpha")
    common.select_project("nope")
    with pytest.raises(SystemExit):
        common.project()


def test_libraries_do_not_leak_between_projects(projects_dir):
    make_project(projects_dir, "alpha")
    make_project(projects_dir, "beta")
    common.select_project("alpha")
    add_verified_source(common.project(), key="onlyalpha2020x")
    assert "onlyalpha2020x" in common.load_library()
    common.select_project("beta")
    assert "onlyalpha2020x" not in common.load_library()
    assert common.load_verification() == {}


def test_template_override(proj):
    assert proj.template("crossref.yaml") == common.SHARED_TEMPLATES / "crossref.yaml"
    proj.templates.mkdir(exist_ok=True)
    (proj.templates / "crossref.yaml").write_text("x: 1")
    assert proj.template("crossref.yaml") == proj.templates / "crossref.yaml"


def test_project_cli_new_list_use_commit(projects_dir):
    r = run_script("project.py", "new", "thesis-a", "--title", "First", projects_dir=projects_dir, check=True)
    assert "created" in r.stdout
    run_script("project.py", "new", "thesis-b", "--title", "Second", projects_dir=projects_dir, check=True)
    out = run_script("project.py", "list", projects_dir=projects_dir, check=True).stdout
    assert "* thesis-b" in out and "thesis-a" in out
    run_script("project.py", "use", "thesis-a", projects_dir=projects_dir, check=True)
    assert run_script("project.py", "current", projects_dir=projects_dir).stdout.strip() == "thesis-a"
    cfg = yaml.safe_load((projects_dir / "thesis-a" / "config" / "project.yaml").read_text())
    assert cfg["project"]["title"] == "First" and cfg["zotero"]["collection"] == "thesis-a"
    (projects_dir / "thesis-a" / "docs" / "past_work" / "proposal.md").write_text("# Proposal")
    r = run_script("project.py", "commit", "add proposal", projects_dir=projects_dir, check=True)
    log = subprocess.run(["git", "-C", str(projects_dir / "thesis-a"), "log", "--format=%s"],
                         capture_output=True, text=True).stdout
    assert "add proposal" in log and "project created" in log
    assert "nothing to commit" in run_script("project.py", "commit", "again", projects_dir=projects_dir).stdout
    assert run_script("project.py", "new", "Bad Name!", projects_dir=projects_dir).returncode != 0


def test_new_project_from_existing_copies_department_material(projects_dir):
    run_script("project.py", "new", "first", "--title", "First thesis", projects_dir=projects_dir, check=True)
    first = projects_dir / "first"
    (first / "docs" / "guidelines" / "handbook.md").write_text("# Chapter 1 Introduction\nText")
    (first / "config" / "cover_template.docx").write_bytes(b"fake")
    run_script("project.py", "new", "second", "--from", "first", projects_dir=projects_dir, check=True)
    second = projects_dir / "second"
    assert (second / "docs" / "guidelines" / "handbook.md").exists()
    assert (second / "config" / "cover_template.docx").exists()
    cfg = yaml.safe_load((second / "config" / "project.yaml").read_text())
    assert cfg["project"]["title"] != "First thesis"          # personal details are not copied


def test_migrate_legacy_layout(tmp_path, monkeypatch, projects_dir):
    root = tmp_path / "wf"
    (root / "config" / "guidelines").mkdir(parents=True)
    (root / "output" / "chapters" / "chapter_one").mkdir(parents=True)
    (root / "references").mkdir()
    (root / "config" / "project.yaml").write_text(yaml.safe_dump({"project": {"title": "Old Thesis Title"},
                                                                  "chapters": {1: {"title": "Intro"}}}))
    (root / "config" / "guidelines" / "rules.pdf").write_bytes(b"%PDF")
    (root / "config" / "guidelines" / ".gitkeep").write_text("")
    (root / "output" / "chapters" / "chapter_one" / "chapter.md").write_text("---\nchapter: 1\n---\n\n## Hi\n")
    (root / "references" / "references.json").write_text("[]")
    monkeypatch.setattr(project_mod, "ROOT", root)
    monkeypatch.setattr(project_mod, "SHARED_CONFIG", root / "config")
    monkeypatch.setattr(common, "SHARED_CONFIG", root / "config")
    monkeypatch.setattr(project_mod, "legacy_layout", lambda: (root / "config" / "project.yaml").exists())

    class A:
        name = None
    project_mod.cmd_migrate(A())
    p = common.Project(projects_dir / "old-thesis-title")
    assert p.config_file.exists() and not (root / "config" / "project.yaml").exists()
    assert (p.guidelines / "rules.pdf").exists() and not (root / "config" / "guidelines").exists()
    assert (p.chapters / "chapter_one" / "chapter.md").exists()
    assert p.library.exists()
    assert (projects_dir / ".active").read_text().strip() == "old-thesis-title"
    assert yaml.safe_load(p.config_file.read_text())["zotero"]["collection"] == "old-thesis-title"


def test_state_cli_validates_and_locks(projects_dir):
    make_project(projects_dir, "alpha")
    run_script("state.py", "start", "1", "new", "write it", projects_dir=projects_dir, check=True)
    r = run_script("state.py", "start", "1", "new", "again", projects_dir=projects_dir)
    assert r.returncode == 3 and "in progress" in r.stderr
    assert run_script("state.py", "done", "1", "bogus", projects_dir=projects_dir).returncode != 0
    run_script("state.py", "done", "1", "plan", "ok", projects_dir=projects_dir, check=True)
    run_script("state.py", "done", "1", "plan", "twice", projects_dir=projects_dir, check=True)
    out = run_script("state.py", "show", "1", projects_dir=projects_dir, check=True).stdout
    assert "done: plan" in out and "next: research" in out
    run_script("state.py", "start", "1", "edit", "fresh", "--force", projects_dir=projects_dir, check=True)
    run_script("state.py", "finish", "1", projects_dir=projects_dir, check=True)
    assert "finished" in run_script("state.py", "show", "1", projects_dir=projects_dir).stdout


def test_versions(tmp_path):
    for k in (1, 2, 10):
        (tmp_path / f"chapter_one_v{k}.docx").write_text("")
    (tmp_path / "chapter_one_v2_changes.docx").write_text("")
    assert common.next_version(tmp_path, "chapter_one").name == "chapter_one_v11.docx"
    assert common.latest_version(tmp_path, "chapter_one").name == "chapter_one_v10.docx"
    assert [p.name for p in common.all_versions(tmp_path, "chapter_one")][-1] == "chapter_one_v10.docx"


def test_citekeys_ignore_code_crossrefs_and_emails():
    text = "See [@smith2020a; @lee2021b] and @fig:arch. Mail a@b.com. `@notakey` ```\n@nokey2\n```"
    assert common.find_citekeys(text) == ["smith2020a", "lee2021b"]


def test_grid_tables_realigned():
    t = "+---+---+\n| a | b |\n+===+===+\n| long cell | x |\n+---+---+"
    out = common.realign_grid_tables(t).splitlines()
    assert len({len(line) for line in out}) == 1


def test_every_command_announces_its_project(projects_dir):
    make_project(projects_dir, "alpha", title="First thesis")
    make_project(projects_dir, "beta", title="Second thesis")
    (projects_dir / ".active").write_text("alpha")
    r = run_script("state.py", "show", projects_dir=projects_dir, check=True)
    assert "== Project: alpha - First thesis  [set with project.py use] ==" in r.stderr
    r = run_script("state.py", "show", "--project", "beta", projects_dir=projects_dir, check=True)
    assert "== Project: beta - Second thesis  [--project] ==" in r.stderr
    assert "the active project is 'alpha'; this command uses 'beta'" in r.stderr
    r = run_script("check.py", "1", "--json", "--project", "beta", projects_dir=projects_dir)
    assert "== Project: beta" not in r.stdout                  # stdout stays machine-readable


def test_list_and_use_are_explicit(projects_dir):
    make_project(projects_dir, "alpha", title="First thesis")
    make_project(projects_dir, "beta", title="Second thesis")
    run_script("project.py", "use", "alpha", projects_dir=projects_dir, check=True)
    out = run_script("project.py", "use", "beta", projects_dir=projects_dir, check=True).stdout
    assert "switched active project: alpha -> beta (Second thesis)" in out
    out = run_script("project.py", "list", projects_dir=projects_dir, check=True).stdout
    assert "* beta" in out and "  alpha" in out and "0/6" in out and "active project (set with project.py use)" in out
