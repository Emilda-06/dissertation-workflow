"""The author's own voice (style voice sample), your-turn rewrites (ownership.py) and provenance / AI-use statement."""
from __future__ import annotations

import json

import yaml

import ownership
import provenance
import style
from conftest import add_verified_source, run_script, write_chapter

ESSAY_PARAS = [
    "When I started my placement at the water utility, I assumed the network was the weak point. It was not. "
    "The real problem was that nobody knew which gateways were still running the old firmware, and nobody had "
    "time to check them one by one.",
    "So I built a small inventory script. It was crude, but it worked, and within a week we had found eleven "
    "devices that had not been patched since they were installed. That changed how I think about security: "
    "the boring parts matter more than the clever ones.",
    "I think the literature sometimes misses this point. Papers on intrusion detection report impressive accuracy "
    "on clean datasets, but in practice the data is messy, labels are missing and the people who should act on "
    "an alert are busy with something else.",
    "That does not mean the research is useless. It means the evaluation should include the people and the "
    "processes, not only the model. A detector that is right 99 percent of the time is still a burden if every "
    "false alarm takes an hour to investigate.",
    "Looking back, the most useful thing I learned was to ask simple questions first. Which devices do we have? "
    "Who looks after them? What happens when one fails? Only then does it make sense to ask which model to use.",
    "My view now is that small organisations need tools that fit their routines. They do not need another "
    "dashboard. They need a short list of the three things to fix this week, and a way to check that they were fixed.",
]


def write_essay(proj, repeat=3):
    text = "# Reflective report\n\n" + "\n\n".join(ESSAY_PARAS * repeat) + "\n"
    f = proj.existing / "reflective_report.md"
    f.write_text(text, encoding="utf-8")
    return f


# ---------------------------------------------------------------- voice sample
def test_voice_sample_requires_confirmation_and_tunes_profile(proj, projects_dir):
    write_essay(proj)
    r = run_script("style.py", "init", "--from-sample", "existing/reflective_report.md", projects_dir=projects_dir)
    assert r.returncode != 0 and "--own-work" in (r.stdout + r.stderr)
    run_script("style.py", "init", "--from-sample", "existing/reflective_report.md", "--own-work",
               projects_dir=projects_dir, check=True)
    p = style.load()
    vs = p["voice_sample"]
    assert vs["confirmed_own_work"] and vs["words"] > 500 and vs["files"]
    assert p["sentence_length"]["target"] == round(vs["sentence_mean"])
    assert p["person"] == "third"                         # the sample's "I" never overrides the project's person
    assert "AUTHOR'S OWN VOICE" in style.brief(p)
    assert "water utility" not in style.brief(p) and "phrases" not in vs   # topic words never carried over
    assert any(c in vs["connectives"] for c in ("but", "so"))


def test_voice_sample_too_short(proj, projects_dir):
    (proj.existing / "short.md").write_text(ESSAY_PARAS[0], encoding="utf-8")
    run_script("style.py", "init", projects_dir=projects_dir, check=True)
    r = run_script("style.py", "voice", "existing/short.md", "--own-work", projects_dir=projects_dir)
    assert r.returncode != 0 and "at least" in (r.stdout + r.stderr)


def test_voice_rhythm_warning(proj, projects_dir):
    write_essay(proj)
    run_script("style.py", "init", "--from-sample", "existing/reflective_report.md", "--own-work",
               projects_dir=projects_dir, check=True)
    p = style.load()
    flat = "## A\n\n" + " ".join(["The system logs every request to the central server for review."] * 14) + "\n"
    assert any(w.startswith("voice:") for w in style.check_body(flat, p))


# ---------------------------------------------------------------- your turn
CHAPTER = """## Introduction

Edge devices in small utilities are rarely patched, and the published defences mostly assume a well-run network with staff who respond to alerts quickly and reliably every time [@smith2021edge]. This chapter reviews that work against the conditions found in practice at small organisations.

## Research gap {#sec:gap}

Unlike the large-network studies, this project evaluates detection where staff time is the limiting factor. Few studies measure the cost of a false alarm, and none of those reviewed tested on hardware slower than a Raspberry Pi 4 [@smith2021edge; @khan2022federated]. This gap matters because a detector that is accurate but noisy is unusable for a two-person team.

Both strands of work assume clean labels, which is questionable for operational data where most events are never labelled at all. The evaluation in this study therefore uses partially labelled logs from a real deployment rather than a benchmark dataset alone [@khan2022federated].
"""


def setup_chapter(proj):
    add_verified_source(proj)
    add_verified_source(proj, key="khan2022federated", doi="10.3390/electronics11152393", year=2022)
    write_chapter(proj, 2, CHAPTER)


def test_pick_and_apply_your_turn(proj, projects_dir):
    setup_chapter(proj)
    run_script("ownership.py", "pick", "2", "--count", "2", projects_dir=projects_dir, check=True)
    data = json.loads(ownership.jpath(2).read_text(encoding="utf-8"))
    assert len(data["picked"]) == 2 and all("gap" in p["section"].lower() for p in data["picked"])
    yt = ownership.tpath(2).read_text(encoding="utf-8")
    assert "### Your version" in yt and "[p1]" in yt
    mine = ("What I wanted to know is whether detection still works when nobody has time to chase alerts. "
            "The studies I read do not measure that cost, and none ran on anything slower than a Raspberry Pi 4 "
            "[@smith2021edge; @khan2022federated].")
    bad = "This cites a source I typed myself [@made2024up]."
    yt = yt.replace(ownership.PLACEHOLDER, mine, 1).replace(ownership.PLACEHOLDER, bad, 1)
    ownership.tpath(2).write_text(yt, encoding="utf-8")
    r = run_script("ownership.py", "apply", "2", projects_dir=projects_dir)
    assert r.returncode == 2 and "applied [p1]" in r.stdout and "NOT applied [p2]" in r.stdout
    body = (proj.chapters / "chapter_two" / "chapter.md").read_text(encoding="utf-8")
    assert mine in body and "made2024up" not in body
    assert "Both strands of work assume clean labels" in body
    st = run_script("ownership.py", "status", "2", projects_dir=projects_dir, check=True)
    assert "1/2" in st.stdout
    ev = provenance.load(2)["events"]
    assert ev and ev[-1]["type"] == "your-turn" and ev[-1]["changed"] > 0.5


# ---------------------------------------------------------------- provenance
def test_provenance_records_assistant_and_author(proj, projects_dir):
    setup_chapter(proj)
    run_script("provenance.py", "record-begin", "2", "new", "write chapter 2", projects_dir=projects_dir, check=True)
    run_script("provenance.py", "record-finish", "2", "--build", "chapter_two_v1.docx", projects_dir=projects_dir,
               check=True)
    assert provenance.baseline_path(2).exists()
    f = proj.chapters / "chapter_two" / "chapter.md"
    f.write_text(f.read_text(encoding="utf-8").replace(
        "This chapter reviews that work",
        "In my placement I saw eleven unpatched gateways in one week. This chapter reviews that work"),
        encoding="utf-8")
    r = run_script("provenance.py", "scan", "2", projects_dir=projects_dir, check=True)
    assert "author edits recorded" in r.stdout
    s = provenance.summary(2)
    assert s["assistant_runs"] == 1 and s["author_edit_sessions"] == 1 and s["author_words_changed"] >= 10
    assert run_script("provenance.py", "scan", "2", projects_dir=projects_dir, check=True).stdout.startswith(
        "chapter 2: no new")
    run_script("provenance.py", "log", projects_dir=projects_dir, check=True)
    log = (proj.dissertation / "provenance.md").read_text(encoding="utf-8")
    assert "assistant drafted the chapter" in log and "author edited by hand" in log


def test_statement_draft_is_honest_and_held_back(proj, projects_dir):
    assert run_script("provenance.py", "statement", projects_dir=projects_dir).returncode != 0   # no chapters yet
    setup_chapter(proj)
    (proj.build / "guidelines").mkdir(parents=True, exist_ok=True)
    (proj.build / "guidelines" / "g.md").write_text(
        "Students must declare any use of generative AI tools in a signed statement.", encoding="utf-8")
    run_script("provenance.py", "record-begin", "2", "new", "x", projects_dir=projects_dir, check=True)
    run_script("provenance.py", "record-finish", "2", projects_dir=projects_dir, check=True)
    run_script("provenance.py", "statement", projects_dir=projects_dir, check=True)
    f = proj.dissertation / "front_matter" / provenance.STATEMENT
    text = f.read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---")[1])
    assert meta["reviewed"] is False
    assert "Claude" in text and "draft and revise" in text and "TODO-CHECK" in text
    assert "not yet been substantially edited" in text            # no hand edits -> no claim of them
    assert "generative AI tools" in text                          # the department rule is quoted for checking
    assert "approved the plan" not in text                        # no outline.md: not claimed
    assert "TODO-CHECK: no author input was recorded" in text
    assert run_script("provenance.py", "statement", projects_dir=projects_dir).returncode != 0
    import build
    assert build.dissertation_front_pages() == []                 # unreviewed: left out of the dissertation
    f.write_text(text.replace("reviewed: false", "reviewed: true"), encoding="utf-8")
    assert len(build.dissertation_front_pages()) == 1


def test_pipeline_begin_records_hand_edits(proj, projects_dir):
    setup_chapter(proj)
    run_script("provenance.py", "record-finish", "2", projects_dir=projects_dir, check=True)
    f = proj.chapters / "chapter_two" / "chapter.md"
    f.write_text(f.read_text(encoding="utf-8") + "\nA paragraph the author added by hand about their own placement "
                 "experience and what it taught them.\n", encoding="utf-8")
    run_script("pipeline.py", "begin", "2", "edit", "supervisor comments", projects_dir=projects_dir, check=True)
    types = [e["type"] for e in provenance.load(2)["events"]]
    assert types[-2:] == ["author-edit", "assistant-run-start"]
