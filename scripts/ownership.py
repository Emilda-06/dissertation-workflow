"""Your turn: the author rewrites the paragraphs that carry the chapter's argument, in their own words.

The paragraphs that state the gap, the author's position, the key evaluation or the conclusions are the
ones an examiner will ask about. Writing them yourself makes the chapter genuinely yours and makes the
viva easier. This picks 3-5 of them, writes them to your_turn.md with space for your version, and puts
your versions back into chapter.md (citations must be kept; nothing else in the chapter is touched).

Usage:
  ownership.py pick <n> [--count 4] [--force]   choose the key paragraphs -> your_turn.md
  ownership.py apply <n>                        put your rewritten versions into chapter.md
  ownership.py status <n>                       which have been rewritten, and how different they are
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from datetime import datetime

import critique
from chapterdoc import blocks, classify, parse_headings
from common import (chapter_dir, chapter_file, die, find_citekeys, init_cli, load_config, load_library, project,
                    read_front_matter, save_json, write_front_matter)

PLACEHOLDER = "(write your version here)"
KEY_SECTIONS = re.compile(r"gap|discussion|conclusion|contribution|summary|justification|significance|problem|"
                          r"critical|evaluation|limitation|implication|recommendation|position|synthesis|findings",
                          re.I)
POSITION = re.compile(r"\b(?:this (?:study|project|research|dissertation|work)|the present study|gap|argues?|"
                      r"contribution|therefore|in contrast|whereas|unlike|remains unclear|few studies|"
                      r"little is known|limitation)\b", re.I)


def jpath(n: int):
    return chapter_dir(n) / "ownership.json"


def tpath(n: int):
    return chapter_dir(n) / "your_turn.md"


def load(n: int) -> dict:
    return json.loads(jpath(n).read_text(encoding="utf-8")) if jpath(n).exists() else {"picked": []}


def candidates(body: str, n: int) -> list[dict]:
    heads = parse_headings(body, n)
    out = []
    pos = 0
    for b in blocks(body):
        if classify(b) != "paragraph":
            continue
        words = len(b.split())
        if not 40 <= words <= 260:
            continue
        idx = body.find(b, pos)
        pos = max(pos, idx)
        line = body[:idx].count("\n") if idx >= 0 else 0
        sec = None
        for h in heads:
            if h.line <= line:
                sec = h
        score = 2 * critique.evaluative_hits(b) + min(3, len(set(find_citekeys(b))))
        score += 2 * min(3, len(POSITION.findall(b)))
        if sec and KEY_SECTIONS.search(sec.title):
            score += 4
        out.append({"text": b, "score": score, "section": f"{sec.number or ''} {sec.title}".strip() if sec else "",
                    "order": len(out)})
    return out


def cmd_pick(n: int, count: int, force: bool) -> None:
    if tpath(n).exists() and not force:
        die(f"{project().rel(tpath(n))} exists (apply it first, or --force to pick again)")
    _, body = read_front_matter(chapter_file(n))
    cands = sorted(candidates(body, n), key=lambda c: -c["score"])
    chosen, per_sec = [], {}
    for c in cands:
        if per_sec.get(c["section"], 0) >= 2:
            continue
        chosen.append(c)
        per_sec[c["section"]] = per_sec.get(c["section"], 0) + 1
        if len(chosen) >= count:
            break
    if not chosen:
        die("no suitable paragraphs (40-260 words) in the chapter yet")
    chosen.sort(key=lambda c: c["order"])
    picked = [{"id": f"p{i}", "section": c["section"], "original": c["text"],
               "keys": sorted(set(find_citekeys(c["text"]))), "rewritten": False} for i, c in enumerate(chosen, 1)]
    save_json(jpath(n), {"picked": picked, "created": datetime.now().isoformat(timespec="seconds")})
    lines = [f"# Your turn - chapter {n}", "",
             "These paragraphs carry the chapter's argument. Rewrite each one in your own words, the way you would "
             "explain it to your examiner. Change the structure, the examples and the emphasis as you see fit, "
             "and add your own judgement. Keep every citation (the [@key] parts) that still supports what you say, "
             "and the project's style (person, spelling). You do not have to keep any of the draft's wording.",
             "", "Write under 'Your version'. Leave the placeholder for any you want to skip. Then ask for "
             f"'ownership.py apply {n}' (or run it).", ""]
    for pk in picked:
        lines += [f"## [{pk['id']}] {pk['section'] or 'Paragraph'}", "", "### Draft", ""]
        lines += ["> " + ln for ln in pk["original"].splitlines()]
        lines += ["", "### Your version", "", PLACEHOLDER, ""]
    tpath(n).write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {project().rel(tpath(n))} ({len(picked)} paragraph(s): "
          + ", ".join(f"[{p['id']}] {p['section']}" for p in picked) + ")")


def versions(n: int) -> dict[str, str]:
    if not tpath(n).exists():
        die(f"no {project().rel(tpath(n))} yet: ownership.py pick {n}")
    text = tpath(n).read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^## \[(p\d+)\].*?^### Your version\s*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M):
        v = m.group(2).strip()
        if v and v != PLACEHOLDER:
            out[m.group(1)] = " ".join(ln.strip() for ln in v.splitlines() if ln.strip())
    return out


def changed_share(a: str, b: str) -> float:
    return round(1 - difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio(), 2)


def cmd_apply(n: int) -> None:
    data = load(n)
    if not data["picked"]:
        die(f"nothing picked yet: ownership.py pick {n}")
    vs = versions(n)
    meta, body = read_front_matter(chapter_file(n))
    lib = load_library()
    applied, problems = [], []
    for pk in data["picked"]:
        v = vs.get(pk["id"])
        if not v or pk.get("rewritten"):
            continue
        keys = set(find_citekeys(v))
        unknown = sorted(k for k in keys if k not in lib)
        if unknown:
            problems.append(f"[{pk['id']}] cites {', '.join('@' + k for k in unknown)}, which is not in the reference "
                            "library; add it with refs.py first (sources are never typed in by hand)")
            continue
        dropped = sorted(set(pk["keys"]) - keys)
        if dropped and not keys:
            problems.append(f"[{pk['id']}] has no citations left (the draft cited {', '.join('@' + k for k in dropped)}); "
                            "keep the citations for claims that come from sources")
            continue
        if pk["original"] not in body:
            problems.append(f"[{pk['id']}] the draft paragraph has changed in chapter.md since it was picked; "
                            "edit chapter.md directly")
            continue
        body = body.replace(pk["original"], v, 1)
        pk.update({"rewritten": True, "applied": datetime.now().isoformat(timespec="seconds"),
                   "changed": changed_share(pk["original"], v), "dropped_keys": dropped})
        applied.append(pk)
    if applied:
        write_front_matter(chapter_file(n), meta, body)
        save_json(jpath(n), data)
        import provenance
        log = provenance.load(n)
        for pk in applied:
            log["events"].append({"type": "your-turn", "date": pk["applied"], "id": pk["id"],
                                  "changed": pk["changed"]})
        provenance.save(n, log)
    for pk in applied:
        note = f"; citations no longer used: {', '.join(pk['dropped_keys'])}" if pk["dropped_keys"] else ""
        print(f"applied [{pk['id']}] {pk['section']} ({int(pk['changed'] * 100)}% different from the draft{note})")
    for p in problems:
        print(f"NOT applied {p}")
    if not applied and not problems:
        print("no new versions found under 'Your version'")
    if applied:
        print(f"next: check.py {n} (integrity and style), then pipeline.py finish {n} for a new build")
    sys.exit(2 if problems else 0)


def cmd_status(n: int) -> None:
    data = load(n)
    if not data["picked"]:
        print(f"chapter {n}: no key paragraphs picked yet (ownership.py pick {n})")
        sys.exit(2)
    done = [p for p in data["picked"] if p.get("rewritten")]
    print(f"chapter {n}: {len(done)}/{len(data['picked'])} key paragraph(s) rewritten by the author")
    for p in data["picked"]:
        st = f"rewritten, {int(p['changed'] * 100)}% different" if p.get("rewritten") else "waiting"
        print(f"  [{p['id']}] {p['section'] or '-'}: {st}")
    sys.exit(0)


def main():
    init_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["pick", "apply", "status"])
    ap.add_argument("n", type=int)
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    load_config()
    if not chapter_file(a.n).exists():
        die(f"{project().rel(chapter_file(a.n))} does not exist")
    if a.cmd == "pick":
        cmd_pick(a.n, max(1, min(8, a.count)), a.force)
    elif a.cmd == "apply":
        cmd_apply(a.n)
    else:
        cmd_status(a.n)


if __name__ == "__main__":
    main()
