"""Natural prose: rhythm, openings, connective budget, paragraph shape, structural tells, specificity;
critique no longer rewarding connectives; author input follow-ups and use; style brief."""
from __future__ import annotations

import author_input
import critique
import naturalness
import style
from common import load_config
from conftest import run_script, write_chapter

ROBOTIC = """## Background

Edge computing plays a crucial role in modern industrial systems and their security. Moreover, the number of connected devices continues to grow very rapidly each year. Furthermore, these devices are often deployed in remote and unprotected locations. Additionally, attackers can exploit these devices to disrupt critical services. Overall, this highlights the importance of securing edge devices.

Federated learning offers a promising approach to training models on distributed data. Moreover, it allows devices to keep their raw data local and private. Furthermore, it reduces the need to transfer large datasets to the cloud. However, it introduces new risks such as poisoning attacks from clients. Overall, this underscores the need for robust and efficient defences.

Poisoning attacks are not only difficult to detect but also costly to recover from in practice. Moreover, attackers can manipulate model updates in subtle and gradual ways. Furthermore, existing defences often assume that most clients are honest and reliable. Additionally, many defences are evaluated only in simulated environments, highlighting a gap in the research landscape.

This section discusses the main defence strategies proposed in the literature so far. Moreover, robust aggregation methods aim to limit the influence of malicious updates. Furthermore, anomaly detection methods try to identify suspicious clients during training. Additionally, reputation systems track client behaviour across many training rounds. Overall, these approaches offer a comprehensive, scalable, and effective foundation for future work.
"""

NATURAL = """## Background

Factories now run thousands of small devices at the network edge. A 2023 survey counted 14.4 billion connected IoT devices, and the share deployed outside a data centre keeps rising [@smith2021edge]. That matters for security. A sensor bolted to a pump in a remote substation has no guard, often no patching schedule, and a power budget measured in milliwatts.

Federated learning moves training to those devices instead of shipping raw data to the cloud. The appeal is obvious for privacy. The catch is less obvious: every client now writes directly into the shared model, and a single compromised gateway can steer it [@khan2022federated].

Most published defences assume an honest majority. Krum and trimmed-mean aggregation both break down once roughly a third of clients collude, and neither was tested on hardware slower than a Raspberry Pi 4 [@a2020x; @b2021y]. In the placement where this project started, half the gateways shared one firmware image, so a single exploit would have compromised all of them at once.

Slow poisoning is harder still. An attacker who shifts each update by 1 or 2 percent stays inside the statistical bounds that anomaly detectors use, and after 200 rounds the model has drifted anyway. Only two of the eleven studies reviewed in @tbl:related measured this.
"""


def kinds(warnings):
    return {w.split(":")[1].strip() for w in warnings}


def test_robotic_text_flagged_on_every_dimension():
    w, m = naturalness.warnings_for(ROBOTIC, None)
    assert {"rhythm", "openings", "connectives", "shape", "tells", "specificity"} <= kinds(w)
    assert m["cv"] < 0.35 and m["connective_open_share"] > 0.5 and m["closer_share"] > 0.5
    assert m["negative_parallel"] and m["trailing_ing"] and m["inflated"]
    assert any("moreover" in x for x in w)


def test_natural_text_passes():
    w, m = naturalness.warnings_for(NATURAL, None)
    assert w == [] and m["cv"] >= 0.35 and not m["generic_paragraphs"]


def test_short_text_is_not_judged():
    assert naturalness.warnings_for("## A\n\nOne sentence here. Another one follows.\n", None)[0] == []


def test_sentence_splitting_keeps_abbreviations():
    s = naturalness.sentences("Models (e.g. Krum) fail, as Smith et al. show in Fig. 3. A second sentence follows.")
    assert len(s) == 2


def test_style_profile_sets_rhythm_threshold():
    strict = {"rhythm": {"min_cv": 0.6}, "sentence_length": {"target": 20}}
    w, _ = naturalness.warnings_for(NATURAL, strict)
    assert any("rhythm: sentence lengths are very even" in x for x in w)


def test_formulaic_figure_framing():
    body = "## R\n\n" + "\n\n".join(
        f"As shown in @fig:f{i}, the value {i} rises steadily over {i * 10} runs on the Pi 4 board. "
        f"The {i}th run took {i * 3} ms. Results were stable."
        for i in range(1, 6))
    m = naturalness.analyse(body)
    assert m["formulaic_frames"] and m["formulaic_frames"][0][1] == 5


def test_critique_does_not_reward_connectives():
    stuffed = ("## Review\n\n@a2020x proposed a model for edge devices. However, @b2021y developed a tool for "
               "the same task. Moreover, @c2022z presented a method. Therefore, @d2020x used a dataset.\n\n"
               "@e2021y introduced a protocol. Thus, @f2022z designed a framework. Moreover, @a2020x used it.\n\n"
               "@b2021y presented a system. However, @c2022z developed a model. Therefore, @d2020x applied it.\n")
    w, res = critique.warnings_for(stuffed, "literature")
    assert res["descriptive_share"] == 1.0
    assert any("adding 'however' or 'therefore' does not count" in x for x in w)
    assert any("leans on connectives" in x for x in w)


def test_critique_counts_kinds_not_repeats():
    assert critique.evaluative_hits("However, however, therefore, moreover, thus.") == 0
    assert critique.evaluative_hits("Unlike @a, it was tested only in simulation, a gap for this study.") == 3


def test_author_input_add_thin_and_unused(proj, projects_dir):
    write_chapter(proj, 2, "## Intro\n\nKrum aggregation fails when gateways share firmware images, as seen on the "
                           "placement at the water utility.\n")
    run_script("author_input.py", "init", "2", projects_dir=projects_dir, check=True)
    r = run_script("author_input.py", "add", "2", "What happened at the water utility?", "--answer",
                   "Half the gateways shared one firmware image at the water utility placement, so one exploit hit all.",
                   projects_dir=projects_dir, check=True)
    assert "followup-1" in r.stdout
    notes = proj.root / "memo.txt"
    notes.write_text("Talking it through: I never trusted simulated benchmarks, quantum networking blockchain "
                     "metaverse orchestration.", encoding="utf-8")
    run_script("author_input.py", "add", "2", "Voice memo", "--file", str(notes), "--id", "memo",
               projects_dir=projects_dir, check=True)
    p = author_input.path(2)
    p.write_text(p.read_text(encoding="utf-8").replace("(your answer)", "Yes.", 1), encoding="utf-8")
    u = author_input.usage(2)
    assert u["answered"] == 3 and u["thin"] == ["why"]
    assert "followup-1" not in u["unused"] and "memo" in u["unused"]
    assert run_script("author_input.py", "add", "2", "dup", "--id", "memo", projects_dir=projects_dir).returncode != 0
    st = run_script("author_input.py", "status", "2", projects_dir=projects_dir)
    assert "short answers: why" in st.stdout and "memo" in st.stdout


def test_check_reports_voice_warnings(proj, projects_dir):
    write_chapter(proj, 2, ROBOTIC)
    import check
    res = check.check_chapter(2, load_config(), run_integrity=False)
    assert any(w.startswith("voice: rhythm") for w in res["warnings"])
    assert res["stats"]["sentence_variation"] < 0.35
    r = run_script("naturalness.py", "2", projects_dir=projects_dir, check=True)
    assert "sentences to revise" in r.stdout and "[summing-up closer]" in r.stdout


def test_style_brief_mentions_rhythm_and_budget(proj, projects_dir):
    run_script("style.py", "init", "--preset", "discursive", projects_dir=projects_dir, check=True)
    p = style.load()
    assert p["rhythm"]["min_cv"] == 0.4
    b = style.brief(p)
    assert "VARY" in b and "per 1,000 words" in b and "not only" in b


def test_two_sentence_paragraphs_are_fine_for_style(proj):
    p = style.PRESETS["formal-analytical"] | {"spelling": "british", "person": "third", "avoid_phrases": []}
    body = "## A\n\n" + "\n\n".join("Krum fails under collusion at 33 percent. The Pi 4 run confirms it." for _ in range(8))
    assert not any("paragraph(s)" in x for x in style.check_body(body, p))
