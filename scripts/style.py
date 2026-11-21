"""The project's writing style: chosen once per project, saved in style.yaml, applied to every chapter.

Each dissertation keeps one consistent voice (spelling, person, formality, sentence rhythm, hedging,
connectives, terminology), and different projects can have different, deliberately chosen styles.
Settings the department's guidelines state (e.g. "third person", "UK English") are applied automatically.

Usage:
  style.py presets                       the available starting points
  style.py init [--preset P] [--spelling british|american] [--person third|first-plural|first-singular]
  style.py show                          the profile as a short brief for the writer
  style.py init ... --from-sample FILE [--from-sample FILE] --own-work
                                         base the profile on the author's OWN earlier writing (their voice)
  style.py voice FILE [FILE ...] --own-work   add / replace the voice sample of an existing profile
  style.py check <n> | all               measure chapters against the profile (warnings)
  style.py terms                         record the terminology already used, so later chapters stay consistent
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

import yaml

from chapterdoc import blocks, classify
from common import (chapter_file, die, existing_chapters, find_citekeys, init_cli, load_config, project,
                    read_front_matter, strip_code)

PRESETS = {
    "formal-analytical": {
        "description": "Formal and evaluative: balanced sentences, careful hedging, frequent comparison.",
        "sentence_length": {"target": 22, "min_avg": 17, "max_avg": 27, "max": 45},
        "rhythm": {"min_cv": 0.35},
        "paragraph_sentences": [4, 8], "voice": "balanced", "hedging": "moderate",
        "connectives": ["however", "in contrast", "consequently", "this suggests", "taken together",
                        "by comparison", "nevertheless"],
        "narrative_citation_share": [0.2, 0.5],
    },
    "concise-technical": {
        "description": "Direct and technical: shorter sentences, active voice, precise terms, little hedging.",
        "sentence_length": {"target": 17, "min_avg": 13, "max_avg": 21, "max": 35},
        "rhythm": {"min_cv": 0.35},
        "paragraph_sentences": [3, 6], "voice": "active", "hedging": "low",
        "connectives": ["therefore", "as a result", "for example", "in practice", "by contrast"],
        "narrative_citation_share": [0.1, 0.4],
    },
    "discursive": {
        "description": "Reflective and argumentative: longer paragraphs that build a case, more narrative citation.",
        "sentence_length": {"target": 24, "min_avg": 19, "max_avg": 30, "max": 50},
        "rhythm": {"min_cv": 0.4},
        "paragraph_sentences": [5, 9], "voice": "balanced", "hedging": "high",
        "connectives": ["yet", "arguably", "it follows that", "on the other hand", "in this light",
                        "more importantly"],
        "narrative_citation_share": [0.35, 0.7],
    },
    "plain-academic": {
        "description": "Plain English: clear, short to medium sentences, everyday words where possible.",
        "sentence_length": {"target": 19, "min_avg": 14, "max_avg": 23, "max": 38},
        "rhythm": {"min_cv": 0.38},
        "paragraph_sentences": [3, 7], "voice": "active", "hedging": "moderate",
        "connectives": ["but", "so", "for example", "also", "as a result", "in short"],
        "narrative_citation_share": [0.15, 0.5],
    },
}

# phrases that read as filler or machine-generated, whatever the style
AVOID_ALWAYS = ["delve", "tapestry", "in today's fast-paced world", "in the ever-evolving", "it is important to note",
                "it is worth noting", "plays a pivotal role", "a testament to", "navigate the complexities",
                "in the realm of", "unlock the potential", "game-changer", "cutting-edge", "seamlessly",
                "furthermore, it is", "in conclusion, it can be said", "a myriad of", "embark on", "multifaceted",
                "underscores the importance", "paves the way", "robust and scalable", "holistic approach"]

BRIT_AM = [("analyse", "analyze"), ("analysed", "analyzed"), ("analysing", "analyzing"), ("behaviour", "behavior"),
           ("centre", "center"), ("colour", "color"), ("defence", "defense"), ("favour", "favor"),
           ("honour", "honor"), ("labour", "labor"), ("licence", "license"), ("modelling", "modeling"),
           ("modelled", "modeled"), ("optimise", "optimize"), ("optimised", "optimized"),
           ("optimisation", "optimization"), ("organisation", "organization"), ("organise", "organize"),
           ("prioritise", "prioritize"), ("programme", "program"), ("realise", "realize"),
           ("recognise", "recognize"), ("standardise", "standardize"), ("summarise", "summarize"),
           ("utilise", "utilize"), ("utilisation", "utilization"), ("visualise", "visualize"),
           ("visualisation", "visualization"), ("minimise", "minimize"), ("maximise", "maximize"),
           ("characterise", "characterize"), ("emphasise", "emphasize"), ("authorise", "authorize"),
           ("authorisation", "authorization"), ("categorise", "categorize"), ("generalise", "generalize"),
           ("travelling", "traveling"), ("labelled", "labeled"), ("labelling", "labeling"),
           ("catalogue", "catalog"), ("fulfil", "fulfill"), ("enrol", "enroll"), ("ageing", "aging")]
PERSON_WORDS = {"first-singular": ["i", "me", "my", "mine"], "first-plural": ["we", "us", "our", "ours"]}
CONTRACTION = re.compile(r"\b\w+(?:n't|'re|'ve|'ll|'d|'m)\b", re.I)
PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?\w+(?:ed|en)\b", re.I)


def path():
    return project().style_file


def load() -> dict | None:
    return yaml.safe_load(path().read_text(encoding="utf-8")) if path().exists() else None


def from_guidelines() -> dict:
    """Settings the project's guidelines state explicitly."""
    found = {}
    g = project().build / "guidelines"
    text = " ".join(f.read_text(encoding="utf-8", errors="replace") for f in g.glob("*.md")).lower() if g.exists() else ""
    if re.search(r"third[- ]person", text):
        found["person"] = "third"
    elif re.search(r"first[- ]person plural|use [\"']?we[\"']?", text):
        found["person"] = "first-plural"
    elif re.search(r"first[- ]person", text):
        found["person"] = "first-singular"
    if re.search(r"\b(british|uk) english\b", text):
        found["spelling"] = "british"
    elif re.search(r"\b(american|us) english\b", text):
        found["spelling"] = "american"
    return found


HEDGE_WORDS = re.compile(r"\b(?:may|might|could|perhaps|possibly|likely|unlikely|suggests?|appears?|seems?|"
                         r"arguably|tends? to|indicates?)\b", re.I)
SAMPLE_MIN_WORDS = 500


def read_sample(f) -> str:
    """Plain text of a sample file, one paragraph per blank-line block (.md .txt .docx .pdf).
    Used only for measuring, never copied. PDF lines are joined per page (paragraphs are not reliable there)."""
    import guidelines
    f = Path(f)
    suf = f.suffix.lower()
    if suf == ".docx":
        entries, _ = guidelines.read_docx(f)
        return "\n\n".join(e["text"] for e in entries if not e.get("level"))
    if suf == ".pdf":
        entries, _ = guidelines.read_pdf(f)
        pages: dict = {}
        for e in entries:
            pages.setdefault(e.get("page"), []).append(e["text"])
        return "\n\n".join(" ".join(v) for v in pages.values()) + "\n\n<!--pdf-->"
    return f.read_text(encoding="utf-8", errors="replace")


def sample_paragraphs(text: str) -> list[str]:
    out = []
    for b in re.split(r"\n\s*\n", text):
        b = " ".join(b.split())
        if len(b.split()) >= 15 and not re.match(r"^(#|\||[-*+] |\d+[.)] |!\[|>)", b):
            out.append(b)
    return out


def voice_profile(texts: list[str]) -> dict:
    """Measurable features of the author's own writing: rhythm, connectives, openings, hedging, phrasing."""
    import naturalness
    paras = [p for t in texts for p in sample_paragraphs(t)]
    sents = [s for p in paras for s in naturalness.sentences(p)]
    lens = [len(naturalness.words(s)) for s in sents]
    text = " ".join(paras)
    nwords = len(naturalness.words(text))
    if not lens or nwords < SAMPLE_MIN_WORDS:
        die(f"the sample has only {nwords} words of running prose; give at least {SAMPLE_MIN_WORDS} "
            "(2,000+ is better) of the author's own writing")
    low = f" {text.lower()} "
    plain = ["but", "so", "because", "although", "though", "while", "instead", "still", "that said", "even so",
             "looking back", "in practice", "at the same time", "on balance"]
    conn = {c: len(re.findall(rf"(?<![a-z]){re.escape(c)}(?![a-z])", low))
            for c in dict.fromkeys(naturalness.CONNECTIVES + plain)}
    conn = sorted(((c, n) for c, n in conn.items() if n), key=lambda x: -x[1])
    openers: dict[str, int] = {}
    for s in sents:
        w = naturalness.first_word(s)
        if w and w not in naturalness.STOP_START:
            openers[w] = openers.get(w, 0) + 1
    mean = statistics.mean(lens)
    sd = statistics.pstdev(lens) if len(lens) > 1 else 0.0
    per_k = 1000 / nwords
    psents = [len(naturalness.sentences(p)) for t in texts if "<!--pdf-->" not in t
              for p in sample_paragraphs(t)]
    return {
        "words": nwords, "sentences": len(sents),
        "sentence_mean": round(mean, 1), "sentence_sd": round(sd, 1), "cv": round(sd / mean, 2) if mean else 0,
        "paragraph_sentences_median": int(statistics.median(psents)) if psents else 0,
        "connectives": [c for c, _ in conn[:8]],
        "connectives_per_1000": round(sum(n for _, n in conn) * per_k, 1),
        "openers": [w for w, _ in sorted(openers.items(), key=lambda x: -x[1])[:6]],
        "hedges_per_1000": round(len(HEDGE_WORDS.findall(text)) * per_k, 1),
        "passive_share": round(len(PASSIVE.findall(text)) / max(1, len(sents)), 2),
        "first_person": len(re.findall(r"\b(?:I|me|my|we|our|us)\b", text)),
        "short_share": round(sum(1 for ln in lens if ln <= 10) / len(lens), 2),
        "long_share": round(sum(1 for ln in lens if ln >= 30) / len(lens), 2),
    }


def apply_voice(profile: dict, sample: dict, files: list[str]) -> dict:
    """Tune the profile towards the author's measured voice. Person and spelling stay as the guidelines and
    the profile say (the sample may be a different genre); the limits keep it academic."""
    mean = sample["sentence_mean"]
    sl = dict(profile["sentence_length"])
    sl["target"] = int(round(mean))
    sl["min_avg"] = max(10, int(round(mean - 4)))
    sl["max_avg"] = int(round(mean + 4))
    sl["max"] = max(sl.get("max", 35), min(60, int(round(mean + 2.5 * sample["sentence_sd"]))))
    profile["sentence_length"] = sl
    profile["rhythm"] = {"min_cv": round(min(0.6, max(0.3, sample["cv"] - 0.05)), 2)}
    if sample["paragraph_sentences_median"] >= 2:
        med = sample["paragraph_sentences_median"]
        profile["paragraph_sentences"] = [max(2, med - 2), med + 2]
    if len(sample["connectives"]) >= 3:
        profile["connectives"] = sample["connectives"][:7]
    h = sample["hedges_per_1000"]
    profile["hedging"] = "low" if h < 4 else "moderate" if h < 9 else "high"
    profile["voice"] = "active" if sample["passive_share"] < 0.25 else "balanced"
    profile["voice_sample"] = {"files": files, "measured": datetime.now().isoformat(timespec="seconds"),
                               "confirmed_own_work": True, **sample}
    return profile


def save(profile: dict) -> None:
    path().write_text("# Writing style for this project (style.py). Edit freely; every chapter is checked "
                      "against it.\n" + yaml.safe_dump(profile, sort_keys=False, allow_unicode=True),
                      encoding="utf-8")


def sample_from_args(files: list[str], own_work: bool) -> tuple[dict, list[str]]:
    if not own_work:
        die("a voice sample must be the author's OWN writing (no AI drafting or paraphrasing tools). Ask the "
            "author, then confirm with --own-work")
    paths = []
    for f in files:
        fp = Path(f)
        if not fp.is_absolute() and not fp.exists():
            fp = project().root / f
        if not fp.exists():
            die(f"sample file not found: {f}")
        paths.append(fp)
    sample = voice_profile([read_sample(fp) for fp in paths])
    return sample, [project().rel(fp) for fp in paths]


def voice_summary(s: dict, files: list[str]) -> str:
    small = " (small sample: 2,000+ words gives a steadier profile)" if s["words"] < 2000 else ""
    return (f"voice sample from {', '.join(files)}: {s['words']} words{small}; sentences {s['sentence_mean']} ± "
            f"{s['sentence_sd']} (variation {s['cv']}); connectives {', '.join(s['connectives'][:5]) or 'few'}; "
            f"hedging {s['hedges_per_1000']}/1000 words; openings: {', '.join(s['openers'][:5]) or '-'}")


def cmd_voice(a, cfg):
    p = load()
    if p is None:
        die("no style.yaml yet: style.py init --from-sample FILE --own-work")
    sample, files = sample_from_args(a.files, a.own_work)
    save(apply_voice(p, sample, files))
    print(voice_summary(sample, files))


def cmd_init(a, cfg):
    if path().exists() and not a.force:
        die(f"{project().rel(path())} exists (use --force to replace it)")
    if a.preset not in PRESETS:
        die(f"unknown preset '{a.preset}' ({', '.join(PRESETS)})")
    g = from_guidelines()
    lang = str((cfg.get("references") or {}).get("style", "")).lower()
    profile = {
        "version": 1, "created": datetime.now().isoformat(timespec="seconds"), "preset": a.preset,
        **{k: v for k, v in PRESETS[a.preset].items()},
        "rhythm": dict(PRESETS[a.preset].get("rhythm") or {"min_cv": 0.35}),
        "spelling": a.spelling or g.get("spelling") or ("american" if "apa" in lang else "british"),
        "person": a.person or g.get("person") or "third",
        "contractions": False,
        "avoid_phrases": list(AVOID_ALWAYS),
        "terminology": {},
        "notes": "",
        "from_guidelines": g,
    }
    sample = files = None
    if getattr(a, "from_sample", None):
        sample, files = sample_from_args(a.from_sample, a.own_work)
        profile = apply_voice(profile, sample, files)
    save(profile)
    print(f"wrote {project().rel(path())} (preset {a.preset}, {profile['spelling']} spelling, "
          f"{profile['person']} person" + (f"; from guidelines: {g}" if g else "") + ")")
    if sample:
        print(voice_summary(sample, files))


def brief(p: dict) -> str:
    sl = p["sentence_length"]
    person = {"third": "third person only (no I/we/our)", "first-plural": "'we' allowed; avoid 'I'",
              "first-singular": "'I' allowed for your own decisions"}[p["person"]]
    lines = [f"Writing style ({p['preset']}): {p.get('description', '')}",
             f"- Spelling: {p['spelling']} English; {person}; no contractions." if not p.get("contractions")
             else f"- Spelling: {p['spelling']} English; {person}.",
             f"- Sentences average about {sl['target']} words (chapter average {sl['min_avg']}-{sl['max_avg']}; none "
             f"over {sl['max']}), but VARY them: some short ({max(6, round(sl['target'] * 0.55))} words or fewer) for "
             f"key points, some long ({round(sl['target'] * 1.4)}+) where reasoning connects; never four of the same "
             f"length in a row (variation of at least {(p.get('rhythm') or {}).get('min_cv', 0.35)}).",
             f"- Paragraphs usually {p['paragraph_sentences'][0]}-{p['paragraph_sentences'][1]} sentences; let the "
             "point decide, a two-sentence paragraph is fine.",
             f"- Voice: {p['voice']}; hedging: {p['hedging']} (hedge once, never 'may potentially').",
             f"- Connectives to draw on, sparingly and varied: {', '.join(p.get('connectives', []))}. Most sentences "
             "need none; no connective more than about 2-3 times per 1,000 words; do not open paragraphs with one by habit.",
             f"- Narrative citations ('Smith (2021) argues') in about "
             f"{int(p['narrative_citation_share'][0] * 100)}-{int(p['narrative_citation_share'][1] * 100)}% of citations."]
    if p.get("terminology"):
        lines.append("- Terminology: " + "; ".join(f"'{k}' (not {', '.join(v)})" for k, v in p["terminology"].items()))
    vs = p.get("voice_sample")
    if vs:
        lines.append(f"- AUTHOR'S OWN VOICE (measured from {vs['words']} words of their earlier writing): sentences "
                     f"{vs['sentence_mean']} ± {vs['sentence_sd']} words; their connectives: "
                     f"{', '.join(vs['connectives'][:6]) or 'few'}; they often open with: "
                     f"{', '.join(vs['openers'][:5]) or '-'}; {int(vs.get('short_share', 0) * 100)}% of their "
                     f"sentences are 10 words or fewer and {int(vs.get('long_share', 0) * 100)}% are 30 or more; "
                     f"hedging {vs['hedges_per_1000']}/1000 words. Match this rhythm, register and sentence habits "
                     "in the project's person and spelling. Take nothing else from the sample: no sentences, "
                     "phrases or topic words (re-using earlier work counts as similarity).")
    if p.get("notes"):
        lines.append(f"- Notes: {p['notes']}")
    lines.append(f"- Never: {', '.join(p.get('avoid_phrases', [])[:12])} ...")
    lines.append("- Also avoid: 'not only ... but also', reflexive lists of three, ending sentences with ', highlighting / "
                 "underscoring ...', ending paragraphs with a summing-up sentence, dashes, and inflated words (crucial, "
                 "pivotal, landscape). Anchor claims in numbers, names, sources or the author's own examples "
                 "(naturalness.py checks all of this).")
    return "\n".join(lines)


def prose_text(body: str) -> list[str]:
    out = []
    for b in blocks(strip_code(body)):
        if classify(b) == "paragraph":
            b = re.sub(r"<!--.*?-->|\{[^}]*\}", " ", b, flags=re.S)
            out.append(b)
    return out


def sentences_of(par: str) -> list[str]:
    clean = re.sub(r"\[[^\]]*@[^\]]*\]", "", par)
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(@])", clean) if len(s.split()) >= 3]


def measure(body: str) -> dict:
    paras = prose_text(body)
    sents = [s for p in paras for s in sentences_of(p)]
    lens = [len(s.split()) for s in sents]
    text = " ".join(paras)
    low = f" {text.lower()} "
    cites = re.findall(r"\[[^\]]*@[^\]]+\]|(?<![\w\[])@[A-Za-z][\w:.\-]*", re.sub(r"@(?:fig|tbl|sec|app):[\w\-]+", "",
                                                                                   text))
    narrative = sum(1 for c in cites if not c.startswith("["))
    return {
        "sentences": len(sents), "avg_sentence": round(statistics.mean(lens), 1) if lens else 0,
        "lens": lens, "paragraph_sentences": [len(sentences_of(p)) for p in paras],
        "british": sorted({b for b, a in BRIT_AM if re.search(rf"\b{b}\b", low)}),
        "american": sorted({a for b, a in BRIT_AM if re.search(rf"\b{a}\b", low)}),
        "first_singular": len(re.findall(r"\b(?:I|me|my|mine)\b", text)),
        "first_plural": len(re.findall(r"\b(?:we|We|us|our|Our|ours)\b", text)),
        "contractions": sorted(set(m.group(0) for m in CONTRACTION.finditer(text)))[:8],
        "passive_share": round(len(PASSIVE.findall(text)) / max(1, len(sents)), 2),
        "narrative_share": round(narrative / len(cites), 2) if cites else None,
        "text": low,
    }


def check_body(body: str, p: dict) -> list[str]:
    m = measure(body)
    if not m["sentences"]:
        return []
    w = []
    sl = p["sentence_length"]
    if not sl["min_avg"] <= m["avg_sentence"] <= sl["max_avg"]:
        w.append(f"average sentence length {m['avg_sentence']} words; the project style is {sl['min_avg']}-{sl['max_avg']}")
    too_long = [ln for ln in m["lens"] if ln > sl["max"]]
    if too_long:
        w.append(f"{len(too_long)} sentence(s) over {sl['max']} words; split them")
    lo, hi = p["paragraph_sentences"]
    # short paragraphs are a legitimate choice; only one-sentence and very long ones are flagged
    off = [n for n in m["paragraph_sentences"] if n and (n < 2 or n > hi + 2)]
    if len(off) > max(2, len(m["paragraph_sentences"]) // 4):
        w.append(f"{len(off)} paragraph(s) are a single sentence or longer than {hi + 2} sentences "
                 f"(the style's usual range is {lo}-{hi})")
    wrong = m["american"] if p["spelling"] == "british" else m["british"]
    if wrong:
        w.append(f"{p['spelling']} spelling expected; found: {', '.join(wrong[:8])}")
    if p["person"] == "third" and (m["first_singular"] or m["first_plural"]):
        w.append(f"third person expected; found {m['first_singular'] + m['first_plural']} first-person word(s) "
                 "(I/we/our)")
    elif p["person"] == "first-plural" and m["first_singular"]:
        w.append(f"'we' style expected; found {m['first_singular']} use(s) of I/me/my")
    if not p.get("contractions") and m["contractions"]:
        w.append(f"contractions in formal text: {', '.join(m['contractions'])}")
    bad = [ph for ph in p.get("avoid_phrases", []) if ph.lower() in m["text"]]
    if bad:
        w.append(f"phrases to avoid: {', '.join(bad)}")
    for term, variants in (p.get("terminology") or {}).items():
        used = [v for v in variants if re.search(rf"\b{re.escape(v.lower())}\b", m["text"])]
        if used:
            w.append(f"terminology: use '{term}' (found {', '.join(used)})")
    if p["voice"] == "active" and m["passive_share"] > 0.5:
        w.append(f"many passive constructions ({m['passive_share']} per sentence); the style prefers active voice")
    ns, (nlo, nhi) = m["narrative_share"], p["narrative_citation_share"]
    if ns is not None and len(find_citekeys(body)) >= 6 and not nlo - 0.1 <= ns <= nhi + 0.1:
        w.append(f"{int(ns * 100)}% narrative citations; the style aims for {int(nlo * 100)}-{int(nhi * 100)}%")
    vs = p.get("voice_sample")
    if vs and m["sentences"] >= 12 and len(m["lens"]) > 1 and m["avg_sentence"]:
        cv = statistics.pstdev(m["lens"]) / m["avg_sentence"]
        if cv < vs["cv"] - 0.12:
            w.append(f"voice: the author's own writing varies sentence length more (variation {vs['cv']}) than this "
                     f"chapter ({round(cv, 2)}); match their rhythm")
    return w


def check_chapter(n: int) -> list[str]:
    p = load()
    if p is None:
        return ["no writing style for this project yet (style.py init): chapters may not read consistently"]
    _, body = read_front_matter(chapter_file(n))
    return [f"style: {x}" for x in check_body(body, p)]


def consistency() -> list[str]:
    """Chapters of one project should sound like one author."""
    avgs = {}
    for n in existing_chapters():
        _, body = read_front_matter(chapter_file(n))
        m = measure(body)
        if m["sentences"] >= 10:
            avgs[n] = m["avg_sentence"]
    if len(avgs) >= 2 and max(avgs.values()) - min(avgs.values()) > 7:
        return [f"style: average sentence length differs a lot between chapters ({avgs}); "
                "align them so the dissertation reads as one voice"]
    return []


VARIANT_RE = re.compile(r"\b([a-z]{1,})[- ]([a-z]{3,})\b")


def cmd_terms(a, cfg):
    """Record the first-used form of terms written in several ways (e-voting / e voting / evoting)."""
    p = load()
    if p is None:
        die("no style.yaml yet (style.py init)")
    counts: dict[str, dict[str, int]] = {}
    for n in existing_chapters():
        _, body = read_front_matter(chapter_file(n))
        text = " ".join(prose_text(body)).lower()
        for m in VARIANT_RE.finditer(text):
            a1, b1 = m.group(1), m.group(2)
            if a1 in ("a", "an", "the", "and", "of", "to", "in", "for", "is", "are", "was", "with", "on", "as", "by",
                      "be", "it", "or", "at", "this", "that", "its", "we", "i"):
                continue
            key = a1 + b1
            for form in (f"{a1}-{b1}", f"{a1} {b1}", key):
                c = len(re.findall(rf"\b{re.escape(form)}\b", text))
                if c:
                    counts.setdefault(key, {})[form] = counts.setdefault(key, {}).get(form, 0) + c
    term = dict(p.get("terminology") or {})
    added = []
    for key, forms in counts.items():
        if len(forms) >= 2 and not any(k in term for k in forms):
            preferred = max(forms, key=forms.get)
            term[preferred] = sorted(f for f in forms if f != preferred)
            added.append(f"{preferred} (not {', '.join(term[preferred])})")
    p["terminology"] = term
    path().write_text("# Writing style for this project (style.py). Edit freely; every chapter is checked "
                      "against it.\n" + yaml.safe_dump(p, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print("terminology recorded: " + ("; ".join(added) if added else "nothing new"))


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("presets")
    i = sub.add_parser("init"); i.add_argument("--preset", default="formal-analytical")
    i.add_argument("--spelling", choices=["british", "american"])
    i.add_argument("--person", choices=["third", "first-plural", "first-singular"])
    i.add_argument("--force", action="store_true")
    i.add_argument("--from-sample", action="append", metavar="FILE",
                   help="the author's own earlier writing (repeatable): .md .txt .docx .pdf")
    i.add_argument("--own-work", action="store_true", help="the author confirmed the sample is their own writing")
    v = sub.add_parser("voice"); v.add_argument("files", nargs="+"); v.add_argument("--own-work", action="store_true")
    sub.add_parser("show")
    c = sub.add_parser("check"); c.add_argument("chapter")
    sub.add_parser("terms")
    a = ap.parse_args()
    if a.cmd == "presets":
        for k, v in PRESETS.items():
            print(f"{k:<18} {v['description']}")
        return
    cfg = load_config()
    if a.cmd == "init":
        cmd_init(a, cfg)
    elif a.cmd == "show":
        p = load()
        print(brief(p) if p else "no style.yaml yet (style.py init)")
    elif a.cmd == "terms":
        cmd_terms(a, cfg)
    elif a.cmd == "voice":
        cmd_voice(a, cfg)
    else:
        nums = existing_chapters() if a.chapter == "all" else [int(a.chapter)]
        warnings = [f"chapter {n}: {w}" for n in nums for w in check_chapter(n)] + consistency()
        print("\n".join(warnings) or "style: consistent with the project profile")
        sys.exit(0)


if __name__ == "__main__":
    main()
