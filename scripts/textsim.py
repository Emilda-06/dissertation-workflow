"""Text similarity engine: verbatim overlap, close paraphrase (patchwriting) and the sources to compare.

Patchwriting keeps a source's sentence structure while swapping words for synonyms. To catch it,
sentences are reduced to canonical content words (light stemming + academic synonym groups), then
compared by order-aware similarity and by containment. Phrases shared by many sources (standard
terminology, stock academic phrases) are discounted so they do not count as matches.

Sources compared with a chapter:
  * full texts downloaded for any chapter of the project   (research/fulltext/*.txt)
  * abstracts of the search candidates                      (research/candidates.json)
  * the author's own earlier work                           (docs/past_work/*, self-plagiarism)
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from common import load_library, normalize_title, project

STOP = set("""a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each either few for from further had has have having
he her here hers him his how i if in into is it its itself just more most much must my no nor not of off on once
only or other our ours out over own same shall she should so some such than that the their theirs them then there
these they this those through thus to too under until up upon very was we were what when where whether which while
who whom why will with within without would yet you your however therefore moreover furthermore although though
whereas hence et al""".split())

# groups of interchangeable academic words; every member maps to the first (after stemming)
SYNONYMS = [
    "show demonstrate indicate reveal illustrate display evidence",
    "use utilise utilize employ apply adopt leverage",
    "large big huge substantial considerable vast",
    "important crucial critical vital essential key significant central",
    "method approach technique strategy mechanism procedure",
    "result finding outcome",
    "improve enhance boost strengthen",
    "increase grow rise expand escalate raise",
    "reduce decrease lower diminish minimise minimize lessen",
    "problem issue challenge difficulty",
    "many numerous several various multiple",
    "propose present introduce suggest develop design",
    "examine investigate analyse analyze explore assess evaluate",
    "aim goal objective purpose",
    "fast rapid quick swift",
    "obtain get acquire achieve attain gain",
    "need require necessitate",
    "help aid assist support facilitate",
    "main primary principal chief major",
    "often frequently commonly regularly",
    "accurate precise exact",
    "effect impact influence consequence",
    "detect identify recognise recognize discover spot",
    "protect secure safeguard defend shield",
    "attack assault",
    "threat risk danger hazard",
    "model framework system architecture",
    "data information",
    "find observe note notice",
    "new novel recent modern",
    "prior previous earlier existing",
    "limit restrict constrain",
    "begin start commence initiate",
    "end finish conclude complete",
    "build construct create make",
    "change alter modify adjust",
    "describe explain outline discuss",
    "confidentiality privacy secrecy",
    "integrity correctness",
    "train teach",
    "client participant node device",
    "server aggregator coordinator",
    "malicious adversarial hostile",
    "robust resilient resistant",
    "performance efficiency effectiveness",
    "suitable appropriate fitting",
    "ensure guarantee assure",
    "allow permit let enable",
    "particular specific certain",
    "combination mixture blend mix",
    "global worldwide international universal",
    "advance progress advancement breakthrough",
    "pave open",
    "possible feasible viable",
    "image picture photograph photo",
    "difficult hard challenging tough",
    "lack absence shortage scarcity",
    "accuracy precision",
    "farmer grower producer",
    "affect influence alter",
    "rely depend",
    "large-scale widespread extensive",
    "approach way",
    "therefore consequently hence",
    "first initial",
    "concern worry",
    "highlight emphasise emphasize stress underline",
    "argue claim contend assert maintain",
    "high elevated",
    "low reduced",
]
SUFFIXES = ("izations", "isations", "ization", "isation", "ational", "fulness", "iveness", "ations", "ation",
            "ments", "ment", "ings", "ing", "edly", "ies", "ied", "ed", "es", "ly", "s")


def stem(w: str) -> str:
    """Light stemmer: 'utilised', 'utilise', 'utilises' -> 'utilis'; 'used', 'uses' -> 'use'."""
    for suf in SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            base = w[:-len(suf)]
            if suf in ("ies", "ied"):
                return base + "y"
            return base[:-1] if base.endswith("e") and len(base) > 4 else base
    if w.endswith(("ed", "es")) and len(w) <= 5:
        return w[:-1]                                   # used -> use, uses -> use
    return w[:-1] if w.endswith("e") and len(w) > 4 else w


_CANON: dict[str, str] = {}
for _group in SYNONYMS:
    _words = _group.split()
    for _w in _words:
        _CANON.setdefault(stem(_w), stem(_words[0]))


def canon(word: str) -> str:
    s = stem(word.lower())
    return _CANON.get(s, s)


WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")


def content_tokens(text: str) -> list[str]:
    return [canon(w) for w in WORD_RE.findall(normalize_title(text)) if w not in STOP and len(w) > 2]


def words(text: str) -> list[str]:
    return normalize_title(text).split()


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"-\n(?=[a-z])", "", text)                    # hyphenated line breaks in PDFs
    text = re.sub(r"\s*\n\s*", " ", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"“])", text)
    return [p.strip() for p in parts if len(p.split()) >= 6]


# ---------------------------------------------------------------- corpus

@dataclass
class SourceSentence:
    doc: str          # label shown to the user
    kind: str         # fulltext | abstract | own
    page: int | None
    text: str
    tokens: list[str]


@dataclass
class Corpus:
    sentences: list[SourceSentence] = field(default_factory=list)
    index: dict[str, list[int]] = field(default_factory=dict)       # token -> sentence ids
    token_docs: dict[str, set] = field(default_factory=dict)        # token -> docs containing it
    shingles: dict[int, set] = field(default_factory=dict)          # 8-word shingle hash -> docs
    docs: set = field(default_factory=set)

    def add(self, doc: str, kind: str, text: str) -> None:
        self.docs.add(doc)
        text = unicodedata.normalize("NFKC", text)        # PDF ligatures: "ﬁ" -> "fi"
        pages = re.split(r"\[page (\d+)\]\n", text)
        chunks = [(None, pages[0])] + [(int(pages[i]), pages[i + 1]) for i in range(1, len(pages) - 1, 2)]
        for page, chunk in chunks:
            ws = words(chunk)
            for i in range(len(ws) - 7):
                self.shingles.setdefault(hash(" ".join(ws[i:i + 8])), set()).add(doc)
            for s in split_sentences(chunk):
                toks = content_tokens(s)
                if len(toks) < 5:
                    continue
                sid = len(self.sentences)
                self.sentences.append(SourceSentence(doc, kind, page, s, toks))
                for t in set(toks):
                    self.index.setdefault(t, []).append(sid)
                    self.token_docs.setdefault(t, set()).add(doc)

    def common_token(self, t: str) -> bool:
        """Token found in many sources: standard terminology rather than evidence of copying."""
        return len(self.docs) >= 4 and len(self.token_docs.get(t, ())) / len(self.docs) >= 0.5

    def common_shingle(self, h: int) -> bool:
        return len(self.shingles.get(h, ())) >= 3


def doi_labels() -> dict[str, str]:
    """safe file name of a DOI -> '@key' label, for readable reports."""
    out = {}
    for k, e in load_library().items():
        if e.get("DOI"):
            out[re.sub(r"[^a-z0-9]+", "_", e["DOI"].lower())] = f"@{k}"
    return out


def read_existing(path: Path) -> str:
    import guidelines
    reader = {".docx": guidelines.read_docx, ".pdf": guidelines.read_pdf}.get(path.suffix.lower(),
                                                                             guidelines.read_text)
    entries, _ = reader(path)
    return guidelines.render(entries)


def imported_drafts() -> set[str]:
    """Past-work files the chapters were imported from (front matter 'imported_from')."""
    from common import read_front_matter
    names = set()
    for ch in project().chapters.glob("chapter_*/chapter.md") if project().chapters.exists() else []:
        src = str((read_front_matter(ch)[0] or {}).get("imported_from") or "")
        if src:
            names.add(Path(re.sub(r"\s*\(.*\)\s*$", "", src)).name)
    return names


def build_corpus(include_own: bool = True, include_abstracts: bool = True) -> Corpus:
    p = project()
    c = Corpus()
    labels = doi_labels()
    seen_abstracts = set()
    if p.chapters.exists():
        for f in sorted(p.chapters.glob("chapter_*/research/fulltext/*.txt")):
            c.add(labels.get(f.stem, f.stem), "fulltext", f.read_text(encoding="utf-8", errors="replace"))
        if include_abstracts:
            for cand in sorted(p.chapters.glob("chapter_*/research/candidates.json")):
                try:
                    items = json.loads(cand.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                for it in items:
                    ab, doi = it.get("abstract") or "", (it.get("doi") or "").lower()
                    safe = re.sub(r"[^a-z0-9]+", "_", doi)
                    if len(ab.split()) < 30 or doi in seen_abstracts:
                        continue
                    seen_abstracts.add(doi)
                    label = labels.get(safe) or (f"doi:{doi}" if doi else it.get("title", "")[:40])
                    c.add(f"{label} (abstract)", "abstract", ab)
    if include_own and p.existing.exists():
        drafts = imported_drafts()
        for f in sorted(p.existing.iterdir()):
            if f.name in drafts:
                continue          # an earlier draft of this dissertation, not a separate submission
            if f.is_file() and f.name != "NOTES.md" and f.suffix.lower() in (".docx", ".pdf", ".md", ".txt"):
                try:
                    c.add(f"your earlier work: {f.name}", "own", read_existing(f))
                except Exception:
                    continue
    return c


# ---------------------------------------------------------------- matching

@dataclass
class Match:
    sentence: str
    kind: str          # verbatim | paraphrase | own
    score: float
    source: str
    source_text: str
    page: int | None


def verbatim_share(sentence: str, corpus: Corpus) -> tuple[float, str | None]:
    ws = words(sentence)
    sh = [hash(" ".join(ws[i:i + 8])) for i in range(len(ws) - 7)]
    if not sh:
        return 0.0, None
    per: dict[str, int] = {}
    for h in sh:
        if corpus.common_shingle(h):
            continue
        for d in corpus.shingles.get(h, ()):
            per[d] = per.get(d, 0) + 1
    if not per:
        return 0.0, None
    doc, hits = max(per.items(), key=lambda kv: kv[1])
    return hits / len(sh), doc


def paraphrase_score(a: list[str], b: list[str], corpus: Corpus) -> float:
    """Order-aware similarity of canonical content words. Sharing only standard terminology (words found
    in most sources) is not enough: at least 3 shared words must be distinctive."""
    if len(a) < 5 or len(b) < 5:
        return 0.0
    shared = set(a) & set(b)
    if len([t for t in shared if not corpus.common_token(t)]) < 3 or len(shared) < 4:
        return 0.0
    seq = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    contain = len(shared) / len(set(a))
    return max(seq, 0.5 * seq + 0.5 * contain if contain >= 0.8 else 0.0)


def best_match(sentence: str, corpus: Corpus, threshold: float = 0.7) -> Match | None:
    vshare, vdoc = verbatim_share(sentence, corpus)
    toks = content_tokens(sentence)
    if vshare >= 0.5:
        src = next((s for s in corpus.sentences if s.doc == vdoc and
                    paraphrase_score(toks, s.tokens, corpus) > 0.5), None)
        kind = "own" if vdoc and vdoc.startswith("your earlier work") else "verbatim"
        return Match(sentence, kind, vshare, vdoc, src.text if src else "", src.page if src else None)
    if len(toks) < 6:
        return None
    rare = sorted(set(toks), key=lambda t: len(corpus.index.get(t, ())))[:6]
    counts: dict[int, int] = {}
    for t in rare:
        ids = corpus.index.get(t, ())
        if len(ids) > 5000:
            continue
        for sid in ids:
            counts[sid] = counts.get(sid, 0) + 1
    best: Match | None = None
    for sid, n in counts.items():
        if n < 2:
            continue
        s = corpus.sentences[sid]
        sc = paraphrase_score(toks, s.tokens, corpus)
        if sc >= threshold and (best is None or sc > best.score):
            kind = "own" if s.kind == "own" else "paraphrase"
            best = Match(sentence, kind, sc, s.doc, s.text, s.page)
    return best


QUOTED = re.compile(r"[\"“][^\"”]{0,600}[\"”]")


def prose_sentences(body: str) -> list[str]:
    """The chapter's own sentences: paragraphs and lists, without code, quotations, citations or markup."""
    from chapterdoc import blocks, classify
    from common import strip_code
    out = []
    for b in blocks(strip_code(body)):
        if classify(b) not in ("paragraph", "list"):
            continue
        b = QUOTED.sub(" ", b)
        b = re.sub(r"\[[^\]]*@[^\]]*\]|@[\w:.\-]+|<!--.*?-->|\{[^}]*\}", " ", b, flags=re.S)
        b = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", b, flags=re.M)
        out += [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(])|\n", b) if len(s.split()) >= 8]
    return out


def scan_text(body: str, corpus: Corpus | None = None, threshold: float = 0.7) -> tuple[list[Match], int]:
    """All flagged sentences of a chapter, and the chapter's prose word count."""
    corpus = corpus if corpus is not None else build_corpus()
    sents = prose_sentences(body)
    total = sum(len(s.split()) for s in sents)
    if not corpus.sentences and not corpus.shingles:
        return [], total
    matches = [m for s in sents if (m := best_match(s, corpus, threshold))]
    return matches, total
