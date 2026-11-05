"""Writing quality: patchwriting, own earlier work, notes, similarity report, author input, style, depth, defence."""
from __future__ import annotations

import yaml

import author_input
import critique
import integrity
import style
import textsim
from common import load_config
from conftest import add_verified_source, run_script, write_chapter

SOURCE = ("[page 2]\nThe quality and the confidentiality of the data must be secured before being used for training "
          "in industry 5.0. Edge computing offers preventive analytics, which allows for the early identification of "
          "hardware failures and mitigation by empowering workers to make informed decisions.\n")


def setup_source(proj):
    add_verified_source(proj, key="khan2022federated", doi="10.3390/electronics11152393")
    d = proj.chapters / "chapter_two" / "research" / "fulltext"
    d.mkdir(parents=True, exist_ok=True)
    (d / "10_3390_electronics11152393.txt").write_text(SOURCE, encoding="utf-8")


def test_stemming_and_synonyms():
    assert textsim.canon("utilised") == textsim.canon("used") == textsim.canon("uses")
    assert textsim.canon("protected") == textsim.canon("secured")
    assert textsim.canon("demonstrates") == textsim.canon("shows")


def test_patchwriting_detected_own_words_not(proj):
    setup_source(proj)
    c = textsim.build_corpus()
    patch = "The quality and the privacy of the information must be protected before being utilised for training in Industry 5.0."
    m = textsim.best_match(patch, c)
    assert m and m.kind == "paraphrase" and m.score >= 0.85 and m.source == "@khan2022federated" and m.page == 2
    own = "Industrial deployments therefore need guarantees about data integrity before any of it reaches training."
    assert textsim.best_match(own, c) is None
    e, w = integrity.copy_check(patch + " [@khan2022federated]", c)
    assert e and "close paraphrase" in e[0]


def test_quoted_text_is_not_flagged(proj):
    setup_source(proj)
    body = ('As argued, "The quality and the confidentiality of the data must be secured before being used for '
            'training in industry 5.0" [@khan2022federated, p. 2].')
    assert textsim.scan_text(body)[0] == []


def test_own_earlier_work_flagged(proj):
    (proj.existing / "proposal.md").write_text(
        "Slow poisoning attacks on constrained edge devices remain largely unevaluated in the published literature "
        "on federated defences.\n", encoding="utf-8")
    body = ("Slow poisoning attacks on constrained edge devices remain largely unevaluated in the published "
            "literature on federated defences.")
    matches, _ = textsim.scan_text(body)
    assert matches and matches[0].kind == "own"
    e, w = integrity.classify_matches(matches)
    assert not e and "earlier work" in w[0]


def test_notes_must_be_own_words(proj):
    setup_source(proj)
    notes = proj.chapters / "chapter_two" / "research" / "notes.md"
    notes.write_text("### @khan2022federated\n- Claims: The quality and the confidentiality of the data must be "
                     "secured before being used for training in industry 5.0.\n", encoding="utf-8")
    _, w = integrity.notes_check(2)
    assert w and "notes.md" in w[0]
    notes.write_text("### @khan2022federated\n- Claim: training data in factories needs integrity checks first.\n",
                     encoding="utf-8")
    assert integrity.notes_check(2) == ([], [])


def test_similarity_report(proj, projects_dir):
    setup_source(proj)
    write_chapter(proj, 2, "## Introduction\n\nThe quality and the privacy of the information must be protected "
                           "before being utilised for training in Industry 5.0 [@khan2022federated]. Our own sentence "
                           "about something completely different follows here with enough words.\n")
    r = run_script("similarity.py", "2", "--html", projects_dir=projects_dir, check=True)
    assert "1 close paraphrase" in r.stdout
    rep = (proj.chapters / "chapter_two" / "similarity_report.md").read_text(encoding="utf-8")
    assert "Estimated similarity" in rep and "@khan2022federated" in rep and "Fix:" in rep
    assert (proj.chapters / "chapter_two" / "similarity_report.html").exists()
    assert run_script("similarity.py", "4", projects_dir=projects_dir).returncode == 1


def test_author_input_cycle(proj, projects_dir):
    write_chapter(proj, 2, "## Intro\n\nText.\n")
    run_script("author_input.py", "init", "2", projects_dir=projects_dir, check=True)
    assert author_input.status(2) == (0, 9)
    assert run_script("author_input.py", "status", "2", projects_dir=projects_dir).returncode == 2
    p = author_input.path(2)
    p.write_text(p.read_text(encoding="utf-8").replace("(your answer)", "My view.", 1), encoding="utf-8")
    assert author_input.status(2) == (1, 9)
    import check
    res = check.check_chapter(2, load_config(), run_integrity=False)
    assert any("only 1/9" in w for w in res["warnings"]) and any("very short" in w for w in res["warnings"])
    text = p.read_text(encoding="utf-8")
    for _ in range(3):
        text = text.replace("(your answer)", "Text matters here because the chapter text is what readers see first.", 1)
    p.write_text(text, encoding="utf-8")
    res = check.check_chapter(2, load_config(), run_integrity=False)
    assert not any("only " in w and "answered" in w for w in res["warnings"])


def test_style_profiles_differ_per_project_and_are_enforced(proj, projects_dir):
    from conftest import make_project
    make_project(projects_dir, "beta")
    run_script("style.py", "init", "--project", "alpha", projects_dir=projects_dir, check=True)
    run_script("style.py", "init", "--preset", "concise-technical", "--spelling", "american", "--project", "beta",
               projects_dir=projects_dir, check=True)
    a = yaml.safe_load(proj.style_file.read_text())
    b = yaml.safe_load((projects_dir / "beta" / "config" / "style.yaml").read_text())
    assert a["spelling"] == "british" and b["spelling"] == "american"
    assert a["sentence_length"] != b["sentence_length"]
    body = ("## Intro\n\nWe analyze the systems and it is important to note that they don't agree. "
            "The second sentence is ordinary. The third sentence is ordinary too. The fourth sentence ends it.\n")
    w = style.check_body(body, a)
    assert any("british spelling" in x for x in w) and any("third person" in x for x in w)
    assert any("contractions" in x for x in w) and any("phrases to avoid" in x for x in w)


def test_style_reads_guideline_person(proj):
    (proj.build / "guidelines").mkdir(parents=True, exist_ok=True)
    (proj.build / "guidelines" / "h.md").write_text("Write in the first person plural throughout. Use UK English.")
    assert style.from_guidelines() == {"person": "first-plural", "spelling": "british"}


def test_terminology_learned(proj, projects_dir):
    run_script("style.py", "init", projects_dir=projects_dir, check=True)
    write_chapter(proj, 1, "## Intro\n\nThe e-voting system is new. An e-voting pilot ran. Later e voting spread.\n")
    run_script("style.py", "terms", projects_dir=projects_dir, check=True)
    p = style.load()
    assert p["terminology"] == {"e-voting": ["e voting"]}
    assert any("terminology" in x for x in style.check_body("## A\n\nThe e voting system works well enough.\n", p))


def test_critical_depth():
    descriptive = ("## Review\n\n@a2020x proposed a model. @b2021y developed a tool. @c2022z presented a method.\n\n"
                   "@d2020x used a dataset for the study.\n\n@e2021y introduced a protocol for the study.\n\n"
                   "@f2022z designed a framework for the study.\n")
    w, res = critique.warnings_for(descriptive, "literature")
    assert any("lists studies" in x for x in w) and any("in a row" in x for x in w)
    critical = ("## Review\n\nUnlike @a2020x, @b2021y tested the method on real devices, which makes its results "
                "more convincing for this study [@c2022z].\n\nHowever, both assume trusted data [@a2020x; @b2021y].\n\n"
                "This suggests a gap that few studies address [@c2022z; @a2020x].\n")
    w, res = critique.warnings_for(critical, "literature")
    assert w == [] and res["synthesis_share"] >= 0.6


def test_defence_brief(proj, projects_dir):
    setup_source(proj)
    write_chapter(proj, 2, "## Introduction\n\nIndustrial training data needs integrity checks first "
                           "[@khan2022federated]. However, few studies test this on small devices [@smith2021edge].\n")
    add_verified_source(proj)
    r = run_script("defence.py", "2", projects_dir=projects_dir, check=True)
    brief = (proj.chapters / "chapter_two" / "defence_brief.md").read_text(encoding="utf-8")
    assert "Key claims" in brief and "@khan2022federated" in brief and "Likely questions" in brief
    assert "abstract only" in brief and "@smith2021edge" in brief and "wrote" in r.stdout


def test_paraphrase_with_many_synonym_swaps(proj):
    d = proj.chapters / "chapter_two" / "research" / "fulltext"
    d.mkdir(parents=True, exist_ok=True)
    (d / "x.txt").write_text("[page 1]\nThe combination of increasing global smartphone penetration and recent advances "
                             "in computer vision made possible by deep learning has paved the way for smartphone-assisted "
                             "disease diagnosis.\n", encoding="utf-8")
    c = textsim.build_corpus()
    swapped = ("The mixture of growing worldwide smartphone penetration and recent progress in computer vision enabled "
               "by deep learning has opened the way for smartphone-assisted disease diagnosis.")
    m = textsim.best_match(swapped, c)
    assert m and m.kind == "paraphrase" and m.score >= 0.85
    own = ("Cheap phones and better image models now make it realistic for farmers to check a leaf in the field "
           "rather than wait for an expert.")
    assert textsim.best_match(own, c) is None
