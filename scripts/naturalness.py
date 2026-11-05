"""Naturalness of the prose: does the chapter read like a person wrote it, or like a template?

This is about writing quality, not about beating AI detectors. Every signal below is a habit that makes
academic text flat and predictable, whoever wrote it. The fix is always better writing (a specific
number instead of a generic claim, a short sentence after a long one, a paragraph that starts with the
evidence), never word-swapping or adding randomness.

Signals (all warnings, never blocking):
  rhythm        sentence lengths too uniform (low variation, runs of same-length sentences, no short or
                long sentences), paragraphs all the same size
  openings      the same first word again and again, too many sentences opening with a connective
  connectives   one connective used far more than the others (a budget, not a preferred list)
  shape         most paragraphs end with a summarising / signposting sentence; formulaic introductions of
                figures and tables; "This chapter / section ..." signposting
  tells         patterns typical of machine text: "not only ... but also", stacked groups of three,
                trailing ", highlighting ..." clauses, em-dashes, stacked hedges, inflated-importance and
                excess vocabulary, bold text inside paragraphs
  specificity   paragraphs with no number, name, citation or concrete term (generic claims)

Usage:
  naturalness.py <n> | all [--json]      metrics and every flagged sentence, for the revision pass
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter

from chapterdoc import blocks, classify
from common import (chapter_file, existing_chapters, find_citekeys, init_cli, load_config, read_front_matter,
                    strip_code)

# ---------------------------------------------------------------- word lists
CONNECTIVES = [
    "however", "moreover", "furthermore", "additionally", "in addition", "consequently", "therefore", "thus",
    "hence", "as a result", "overall", "notably", "importantly", "crucially", "ultimately", "nevertheless",
    "nonetheless", "in contrast", "by contrast", "similarly", "likewise", "conversely", "in particular",
    "specifically", "indeed", "accordingly", "subsequently", "in summary", "in conclusion", "taken together",
    "on the other hand", "for example", "for instance", "in short", "in essence", "this suggests",
    "it follows that", "in this light", "more importantly", "arguably", "by comparison", "yet", "also",
]
# words whose frequency jumped in academic text after LLMs (Kobak et al. 2024) and Wikipedia's
# "Signs of AI writing" word list; weight 2 = strong signal, 1 = fine once, suspicious in bulk
EXCESS_VOCAB = {
    "delve": 2, "delves": 2, "delving": 2, "tapestry": 2, "realm": 2, "testament": 2, "showcase": 2,
    "showcasing": 2, "showcases": 2, "underscore": 2, "underscores": 2, "underscoring": 2, "meticulous": 2,
    "meticulously": 2, "commendable": 2, "intricate": 2, "intricacies": 2, "unwavering": 2, "vibrant": 2,
    "garnered": 2, "boasts": 2, "bolster": 2, "bolstering": 2, "elevate": 2, "unparalleled": 2, "noteworthy": 2,
    "invaluable": 2, "pivotal": 2, "paramount": 2, "groundbreaking": 2, "transformative": 2, "ever-evolving": 2,
    "landscape": 1, "crucial": 1, "crucially": 1, "vital": 1, "notably": 1, "seamless": 1, "seamlessly": 1,
    "leverage": 1, "leveraging": 1, "harness": 1, "harnessing": 1, "foster": 1, "fostering": 1, "nuanced": 1,
    "multifaceted": 1, "comprehensive": 1, "profound": 1, "navigate": 1, "navigating": 1, "endeavour": 1,
    "endeavor": 1, "embark": 1, "streamline": 1, "empower": 1, "empowering": 1, "holistic": 1, "synergy": 1,
    "robust": 1, "insights": 1, "enhance": 1, "enhancing": 1, "utilise": 1, "utilize": 1, "myriad": 1,
    "plethora": 1,
}
INFLATED = re.compile(r"\b(?:plays? an? (?:key|crucial|vital|pivotal|significant|important|central) role|"
                      r"(?:is|are|remains?) (?:crucial|vital|essential|paramount|pivotal) (?:for|to|in)|"
                      r"cannot be overstated|of paramount importance|a (?:key|critical) (?:aspect|component|factor)|"
                      r"in today'?s|rapidly evolving|ever[- ]changing|digital age|"
                      r"(?:has|have) (?:revolutioni[sz]ed|transformed) (?:the|how))", re.I)
NEG_PARALLEL = re.compile(r"\bnot only\b[^.;]{1,120}\bbut (?:also)?\b|\bnot just\b[^.;]{1,80}\bbut\b|"
                          r"\bit is not (?:merely|simply|just|only)\b|\bis not about\b[^.;]{1,60}\bit is about\b|"
                          r"\brather than (?:merely|simply|just)\b", re.I)
TRAILING_ING = re.compile(r",\s+(?:thereby\s+|thus\s+)?(?:highlighting|underscoring|emphasi[sz]ing|showcasing|"
                          r"reflecting|demonstrating|illustrating|signalling|signaling|reinforcing|ensuring|"
                          r"paving the way|contributing to|marking|cementing|solidifying|enabling|fostering)\b[^.]*\.",
                          re.I)
TRIPLE = re.compile(r"\b(\w{3,}), (\w{3,}),? and (\w{3,})\b")
EM_DASH = re.compile(r"—|\s–\s|\s--\s")
HEDGE_STACK = re.compile(r"\b(?:may|might|could|can) (?:potentially|possibly|perhaps|arguably)\b|"
                         r"\b(?:potentially|possibly|perhaps) (?:may|might|could)\b|"
                         r"\bit (?:could|may|might) be argued that\b[^.]*\b(?:may|might|could)\b|"
                         r"\b(?:seems|appears) to (?:potentially|possibly|suggest that .* may)\b", re.I)
SIGNPOST = re.compile(r"\b(?:this|the (?:following|next|present|current)) (?:chapter|section|subsection)\b"
                      r"(?:\s+\w+){0,2}\s+(?:will\s+)?(?:discuss|present|explore|examine|describe|outline|provide|"
                      r"introduce|highlight|focus|review|delve|aim)|\bas (?:mentioned|discussed|stated|noted) "
                      r"(?:above|earlier|previously|before)\b|\bit is (?:important|worth|essential) to "
                      r"(?:note|mention|highlight|emphasi[sz]e)\b", re.I)
CLOSER = re.compile(r"^\s*(?:overall|in summary|in short|in essence|ultimately|taken together|in conclusion|"
                    r"to sum up|all in all|thus|therefore|hence|consequently|as such|"
                    r"this (?:highlights|underscores|demonstrates|shows|illustrates|emphasi[sz]es|reinforces|"
                    r"suggests|indicates|means)|these (?:findings|results|studies) (?:highlight|underscore|"
                    r"demonstrate|show|suggest|indicate))\b", re.I)
STOP_START = {"the", "a", "an"}
REF = re.compile(r"@(?:fig|tbl|sec|app):[\w\-]+")


# ---------------------------------------------------------------- parsing
def paragraphs(body: str) -> list[str]:
    out = []
    for b in blocks(strip_code(body)):
        if classify(b) == "paragraph":
            out.append(re.sub(r"<!--.*?-->|\{[^}]*\}", " ", b, flags=re.S).strip())
    return [p for p in out if p]


def sentences(par: str) -> list[str]:
    clean = re.sub(r"\[[^\]]*@[^\]]*\]", "", par)
    clean = re.sub(r"\b(?:e\.g|i\.e|et al|etc|vs|cf|Fig|Eq|No|p|pp)\.", lambda m: m.group(0).replace(".", "§"), clean)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(@\"'“])", clean)
    return [s.replace("§", ".").strip() for s in parts if len(s.split()) >= 2]


def words(s: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'\-]*", REF.sub(" ", s))


def first_word(s: str) -> str:
    w = words(s)
    return w[0].lower() if w else ""


def opening_connective(s: str) -> str | None:
    low = s.lower().lstrip("(\"'“ ")
    for c in sorted(CONNECTIVES, key=len, reverse=True):
        if low.startswith(c) and (len(low) == len(c) or not low[len(c)].isalpha()):
            return c
    return None


def short(s: str, n: int = 12) -> str:
    w = s.split()
    return " ".join(w[:n]) + (" ..." if len(w) > n else "")


# ---------------------------------------------------------------- measuring
def analyse(body: str, profile: dict | None = None) -> dict:
    profile = profile or {}
    target = (profile.get("sentence_length") or {}).get("target", 20)
    paras = paragraphs(body)
    sents_by_par = [sentences(p) for p in paras]
    sents = [s for ss in sents_by_par for s in ss]
    lens = [len(words(s)) for s in sents]
    text = " ".join(paras)
    nwords = max(1, len(words(text)))
    per_k = 1000 / nwords
    m: dict = {"paragraphs": len(paras), "sentences": len(sents), "words": nwords}

    # rhythm
    if len(lens) >= 2:
        mean = statistics.mean(lens)
        sd = statistics.pstdev(lens)
        m["mean_len"], m["sd_len"], m["cv"] = round(mean, 1), round(sd, 1), round(sd / mean, 2) if mean else 0
    else:
        m["mean_len"], m["sd_len"], m["cv"] = (lens[0] if lens else 0), 0, 0
    short_t, long_t = max(6, round(target * 0.55)), round(target * 1.4)
    m["short_share"] = round(sum(ln <= short_t for ln in lens) / len(lens), 2) if lens else 0
    m["long_share"] = round(sum(ln >= long_t for ln in lens) / len(lens), 2) if lens else 0
    m["short_threshold"], m["long_threshold"] = short_t, long_t
    flat_runs = []
    for ss in sents_by_par:
        ls = [len(words(s)) for s in ss]
        i = 0
        while i < len(ls):
            j = i
            while j + 1 < len(ls) and abs(ls[j + 1] - ls[i]) <= 3:
                j += 1
            if j - i + 1 >= 4:
                flat_runs.append(ss[i])
            i = j + 1
    m["flat_runs"] = flat_runs
    plens = [len(ss) for ss in sents_by_par if ss]
    m["paragraph_sizes"] = plens
    m["paragraph_size_spread"] = round(statistics.pstdev(plens), 2) if len(plens) >= 2 else None

    # openings
    starts = Counter(first_word(s) for s in sents if first_word(s) and first_word(s) not in STOP_START)
    m["top_openers"] = starts.most_common(5)
    repeats = []
    for ss in sents_by_par:
        for a, b, c in zip(ss, ss[1:], ss[2:]):
            if first_word(a) and first_word(a) == first_word(b) == first_word(c):
                repeats.append(a)
    m["same_opening_runs"] = repeats
    conn_open = [(s, opening_connective(s)) for s in sents]
    m["connective_open_share"] = round(sum(1 for _, c in conn_open if c) / len(sents), 2) if sents else 0

    # connectives budget
    low = f" {text.lower()} "
    counts = {c: len(re.findall(rf"(?<![a-z]){re.escape(c)}(?![a-z])", low)) for c in CONNECTIVES
              if c not in ("also", "yet", "for example")}
    cap = max(3, round(2.5 * nwords / 1000))
    m["connective_cap"] = cap
    m["overused_connectives"] = sorted(((c, n) for c, n in counts.items() if n > cap), key=lambda x: -x[1])

    # shape
    closers = [ss[-1] for ss in sents_by_par if len(ss) >= 3 and CLOSER.search(ss[-1])]
    m["closer_share"] = round(len(closers) / max(1, sum(1 for ss in sents_by_par if len(ss) >= 3)), 2)
    m["closers"] = closers
    m["signposts"] = [s for s in sents if SIGNPOST.search(s)]
    frames = Counter()
    frame_examples: dict[str, str] = {}
    for b in blocks(strip_code(body)):
        if classify(b) not in ("paragraph", "list"):
            continue
        for s in sentences(re.sub(r"\{[^}]*\}", " ", b)):
            if REF.search(s):
                key = " ".join(REF.sub("REF", s).lower().split()[:3])
                frames[key] += 1
                frame_examples.setdefault(key, s)
    m["formulaic_frames"] = [(k, n, frame_examples[k]) for k, n in frames.most_common() if n >= 3]

    # tells
    def hits(rx):
        return [s for s in sents if rx.search(s)]
    m["negative_parallel"] = hits(NEG_PARALLEL)
    m["trailing_ing"] = hits(TRAILING_ING)
    m["inflated"] = hits(INFLATED)
    m["hedge_stacks"] = hits(HEDGE_STACK)
    m["em_dashes"] = len(EM_DASH.findall(text))
    triples = [s for s in sents if TRIPLE.search(s)]
    m["triples"] = triples
    m["triples_per_k"] = round(len(triples) * per_k, 1)
    vocab = Counter()
    for w in re.findall(r"[a-z][a-z\-]+", low):
        if w in EXCESS_VOCAB:
            vocab[w] += 1
    score = sum(EXCESS_VOCAB[w] * n for w, n in vocab.items())
    m["excess_vocab"] = vocab.most_common(10)
    m["excess_vocab_per_k"] = round(score * per_k, 1)
    m["bold_in_prose"] = sum(len(re.findall(r"\*\*[^*]+\*\*", p)) for p in paras)

    # specificity
    generic = []
    for p in paras:
        if len(p.split()) < 40:
            continue
        has_num = re.search(r"\d", REF.sub("", p))
        has_cite = find_citekeys(p) or REF.search(p)
        mid_caps = re.findall(r"(?<=[a-z,;] )[A-Z][\w\-]{2,}", p)
        has_term = re.search(r"\b[A-Z]{2,}\b|`[^`]+`", p)
        if not (has_num or has_cite or mid_caps or has_term):
            generic.append(p)
    m["generic_paragraphs"] = generic
    return m


# ---------------------------------------------------------------- warnings
def warnings_for(body: str, profile: dict | None = None) -> tuple[list[str], dict]:
    m = analyse(body, profile)
    w: list[str] = []
    if m["sentences"] < 12:
        return w, m
    min_cv = ((profile or {}).get("rhythm") or {}).get("min_cv", 0.35)
    if m["cv"] < min_cv:
        w.append(f"rhythm: sentence lengths are very even (variation {m['cv']}, aim for {min_cv}+; mean "
                 f"{m['mean_len']} ± {m['sd_len']} words). Mix a short, direct sentence after a long one, and let "
                 "a complex point run longer")
    if m["short_share"] < 0.08:
        w.append(f"rhythm: almost no short sentences (≤{m['short_threshold']} words: {int(m['short_share'] * 100)}%); "
                 "state some key points plainly in a few words")
    if m["long_share"] < 0.05 and m["sentences"] >= 25:
        w.append(f"rhythm: almost no longer sentences (≥{m['long_threshold']} words); connect related ideas "
                 "in one sentence where the reasoning needs it")
    for s in m["flat_runs"][:3]:
        w.append(f"rhythm: 4+ sentences of nearly the same length in a row, starting '{short(s)}'")
    if m["paragraph_size_spread"] is not None and len(m["paragraph_sizes"]) >= 6 and m["paragraph_size_spread"] < 0.8:
        w.append(f"rhythm: paragraphs are all about {round(statistics.mean(m['paragraph_sizes']))} sentences long; "
                 "let paragraph length follow the point (some short, some developed)")
    if m["top_openers"]:
        word, n = m["top_openers"][0]
        if n / m["sentences"] > 0.15 and n >= 5:
            w.append(f"openings: {n} of {m['sentences']} sentences start with '{word.capitalize()}'; vary how "
                     "sentences begin (start with the subject, the evidence, a number or a condition)")
    for s in m["same_opening_runs"][:2]:
        w.append(f"openings: three sentences in a row start with the same word: '{short(s)}'")
    if m["connective_open_share"] > 0.3:
        w.append(f"openings: {int(m['connective_open_share'] * 100)}% of sentences open with a connective "
                 "(However, Moreover, Therefore ...); most sentences need none, the logic should carry them")
    for c, n in m["overused_connectives"][:4]:
        w.append(f"connectives: '{c}' used {n} times (budget about {m['connective_cap']} for this length); "
                 "drop it where the link is obvious or vary the construction")
    if m["closer_share"] > 0.4 and len(m["closers"]) >= 3:
        w.append(f"shape: {int(m['closer_share'] * 100)}% of paragraphs end with a summing-up sentence "
                 f"('{short(m['closers'][0], 6)}'); end on the point itself, and cut closers that only restate it")
    if len(m["signposts"]) > 3:
        w.append(f"shape: {len(m['signposts'])} signposting sentences ('{short(m['signposts'][0], 8)}'); keep them for "
                 "the chapter introduction and summary")
    for k, n, ex in m["formulaic_frames"][:2]:
        w.append(f"shape: {n} figure/table references are introduced the same way ('{short(ex, 8)}'); vary them and "
                 "lead with what the reader should see")
    if m["negative_parallel"]:
        w.append(f"tells: {len(m['negative_parallel'])} 'not only ... but also' / 'not just ... but' construction(s) "
                 f"('{short(m['negative_parallel'][0])}'); state the point directly")
    if m["trailing_ing"]:
        w.append(f"tells: {len(m['trailing_ing'])} sentence(s) end with a ', highlighting / underscoring / "
                 f"ensuring ...' clause ('{short(m['trailing_ing'][0])}'); make the significance its own claim "
                 "with evidence, or cut it")
    if m["triples_per_k"] > 4 and len(m["triples"]) >= 4:
        w.append(f"tells: {len(m['triples'])} lists of three ('X, Y and Z') in running text; use two when two is "
                 "true, or a list or table when there really are several")
    if m["em_dashes"] > max(2, m["words"] // 1000):
        w.append(f"tells: {m['em_dashes']} dashes in the prose; use commas, brackets or a new sentence")
    if m["hedge_stacks"]:
        w.append(f"tells: stacked hedges ('{short(m['hedge_stacks'][0])}'); hedge once, where the evidence is "
                 "genuinely uncertain")
    if m["inflated"]:
        w.append(f"tells: {len(m['inflated'])} inflated-importance phrase(s) ('{short(m['inflated'][0])}'); say what "
                 "it does and show the evidence instead of calling it crucial")
    if m["excess_vocab_per_k"] > 6:
        w.append(f"tells: heavy use of words common in machine text ({', '.join(f'{x} x{n}' for x, n in m['excess_vocab'][:6])}); "
                 "use the plain word (use, show, important, many, detailed)")
    if m["bold_in_prose"] > 2:
        w.append(f"tells: {m['bold_in_prose']} bold phrases inside paragraphs; academic prose uses emphasis rarely")
    if m["generic_paragraphs"]:
        g = m["generic_paragraphs"]
        w.append(f"specificity: {len(g)} paragraph(s) with no number, name, citation or concrete term "
                 f"('{short(g[0], 8)}'); anchor each claim in a figure, a named system, a source or the "
                 "author's own example")
    return [f"voice: {x}" for x in w], m


def report(n: int, profile: dict | None) -> dict:
    _, body = read_front_matter(chapter_file(n))
    w, m = warnings_for(body, profile)
    return {"chapter": n, "warnings": w, "metrics": {k: v for k, v in m.items()}}


def print_report(r: dict) -> None:
    m = r["metrics"]
    print(f"== Chapter {r['chapter']} naturalness ==")
    if not m["sentences"]:
        print("  no prose yet")
        return
    print(f"  {m['sentences']} sentences | length {m['mean_len']} ± {m['sd_len']} (variation {m['cv']}) | short "
          f"{int(m['short_share'] * 100)}% long {int(m['long_share'] * 100)}% | connective openings "
          f"{int(m['connective_open_share'] * 100)}% | summing-up closers {int(m['closer_share'] * 100)}% | excess "
          f"vocabulary {m['excess_vocab_per_k']}/1000 words")
    for x in r["warnings"]:
        print(f"  warning {x}")
    details = [("flat rhythm", m["flat_runs"]), ("summing-up closer", m["closers"]), ("signposting", m["signposts"]),
               ("not only / not just", m["negative_parallel"]), ("trailing -ing clause", m["trailing_ing"]),
               ("inflated importance", m["inflated"]), ("stacked hedge", m["hedge_stacks"]),
               ("list of three", m["triples"])]
    shown = [(label, s) for label, ss in details for s in ss]
    if shown:
        print("  sentences to revise:")
        for label, s in shown[:40]:
            print(f"    [{label}] {short(s, 22)}")
    if not r["warnings"]:
        print("  voice: OK")


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chapter")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    load_config()
    import style
    profile = style.load()
    nums = existing_chapters() if a.chapter == "all" else [int(a.chapter)]
    results = [report(n, profile) for n in nums]
    if a.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        for r in results:
            print_report(r)


if __name__ == "__main__":
    main()
