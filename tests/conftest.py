"""Shared fixtures: every test works in its own temporary projects folder, never in projects/."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
os.environ["DISSERTATION_SKIP_ZOTERO"] = "1"

import common  # noqa: E402
import project as project_mod  # noqa: E402

PLAN = {
    1: {"title": "Introduction", "type": "introduction"},
    2: {"title": "Literature Review", "type": "literature"},
    3: {"title": "Methodology", "type": "methodology"},
    4: {"title": "System Design and Implementation", "type": "design"},
    5: {"title": "Testing, Results and Evaluation", "type": "results"},
    6: {"title": "Conclusion and Recommendations", "type": "conclusion"},
}


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    d = tmp_path / "projects"
    d.mkdir()
    for mod in (common, project_mod):
        monkeypatch.setattr(mod, "PROJECTS", d)
        monkeypatch.setattr(mod, "ACTIVE_FILE", d / ".active")
    monkeypatch.setenv("DISSERTATION_PROJECTS_DIR", str(d))
    monkeypatch.delenv("DISSERTATION_PROJECT", raising=False)
    common.select_project(None)
    yield d
    common.select_project(None)


def make_project(projects_dir: Path, slug: str = "alpha", title: str = "Edge AI Security", **extra) -> common.Project:
    p = common.Project(projects_dir / slug)
    project_mod.scaffold(p)
    cfg = {"project": {"title": title, "student_name": "Test Student", "university": "Test University",
                       "document_type": "Dissertation"},
           "chapters": PLAN, "references": {"style": "harvard", "min_year": 2016, "target_recent_share": 80},
           "format": {"font": "Times New Roman", "font_size": 12, "finalizer": "none"},
           "zotero": {"enabled": False}}
    for k, v in extra.items():
        cfg[k] = v
    p.config_file.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


@pytest.fixture
def proj(projects_dir):
    p = make_project(projects_dir)
    common.select_project(p.slug)
    return p


def run_script(script: str, *args: str, projects_dir: Path, check: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "DISSERTATION_PROJECTS_DIR": str(projects_dir), "DISSERTATION_SKIP_ZOTERO": "1",
           "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=ROOT)
    if check and r.returncode != 0:
        raise AssertionError(f"{script} {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def write_chapter(p: common.Project, n: int, body: str, **meta) -> Path:
    d = p.chapters / common.chapter_slug(n)
    for sub in ("docs", "diagrams", "research/fulltext", "data"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    m = {"chapter": n, "title": PLAN.get(n, {}).get("title", f"Chapter {n}"),
         "type": PLAN.get(n, {}).get("type", ""), "status": "draft", **meta}
    common.write_front_matter(d / "chapter.md", m, body)
    return d / "chapter.md"


def add_verified_source(p: common.Project, key="smith2021edge", doi="10.1000/xyz1", year=2021,
                        title="Edge intelligence security survey") -> dict:
    from refs import fingerprint
    e = {"id": key, "type": "article-journal", "title": title, "author": [{"family": "Smith", "given": "A"}],
         "issued": {"date-parts": [[year]]}, "DOI": doi}
    lib = common.load_json_list(p.library) + [e]
    common.save_json(p.library, lib)
    ver = common.load_verification()
    ver[key] = {"status": "verified", "issues": [], "fingerprint": fingerprint(e), "year": year,
                "recent": year >= 2016}
    common.save_json(p.verification, ver)
    return e
