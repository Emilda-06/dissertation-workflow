"""Step 6: copying, quotes and data traceability."""
from __future__ import annotations

import common
import integrity
from conftest import add_verified_source, write_chapter

SOURCE = ("[page 1]\nIntroduction to the paper.\n[page 2]\nEdge devices are increasingly targeted by adversaries "
          "who exploit weak authentication mechanisms in constrained hardware platforms deployed at scale.\n")


def setup_source(proj):
    add_verified_source(proj)
    d = proj.chapters / "chapter_one" / "research" / "fulltext"
    d.mkdir(parents=True, exist_ok=True)
    (d / "10_1000_xyz1.txt").write_text(SOURCE, encoding="utf-8")


def test_copied_sentence_is_an_error_quoted_is_fine(proj):
    setup_source(proj)
    copied = ("Edge devices are increasingly targeted by adversaries who exploit weak authentication mechanisms "
              "in constrained hardware platforms deployed at scale [@smith2021edge].")
    e, w = integrity.copy_check(copied)
    assert e and "copied from a source" in e[0]
    quoted = f'"{copied[:-21]}" [@smith2021edge, p. 2].'
    assert integrity.copy_check(quoted) == ([], [])
    own = "Attackers increasingly focus on small connected devices because their login checks are often weak."
    assert integrity.copy_check(own) == ([], [])


def test_quotes_checked_against_full_text(proj):
    setup_source(proj)
    lib = common.load_library()
    ok = '"exploit weak authentication mechanisms" [@smith2021edge, p. 2]'
    assert integrity.quote_check(ok, lib) == ([], [])
    wrong_page = '"exploit weak authentication mechanisms" [@smith2021edge, p. 1]'
    e, w = integrity.quote_check(wrong_page, lib)
    assert not e and "PDF page 2" in w[0]
    invented = '"attackers love unpatched firmware" [@smith2021edge, p. 2]'
    assert "not found" in integrity.quote_check(invented, lib)[0][0]
    no_page = '"exploit weak authentication mechanisms" [@smith2021edge]'
    assert "no page number" in integrity.quote_check(no_page, lib)[1][0]


def test_results_numbers_traceable_to_data(proj):
    write_chapter(proj, 5, "x")
    data = proj.chapters / "chapter_five" / "data"
    (data / "runs.csv").write_text("run,latency_ms,accuracy\n1,18.42,0.9312\n2,19.10,0.9420\n")
    body = ("Latency was 18.4 ms in the first run and accuracy reached 93.1% while a third run gave 77.7 ms. "
            "The study ran in 2024 with 3 devices.")
    _, w = integrity.data_check(5, body, "results")
    assert w and "77.7" in w[0] and "18.4" not in w[0] and "93.1%" not in w[0] and "2024" not in w[0]
    assert integrity.data_check(5, body, "literature") == ([], [])


def test_results_without_data_files_warns(proj):
    write_chapter(proj, 5, "x")
    _, w = integrity.data_check(5, "The mean latency was 18.42 ms.", "results")
    assert w and "no data files" in w[0]
