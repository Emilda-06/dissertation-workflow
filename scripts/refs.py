"""Reference library: add sources by DOI, verify them against Crossref/OpenAlex, sync to Zotero.

Usage:
  refs.py add --doi 10.1109/xxx [10.1145/yyy ...] [--chapter 2]
  refs.py add-manual '<CSL JSON object>'        (standards, reports, websites without DOI)
  refs.py verify [--keys k1 k2 | --chapter 2 | --all] [--force]
  refs.py list [--chapter 2]
  refs.py show <key>
  refs.py find <surname> <year>
  refs.py mark-foundational <key> "<reason>"
  refs.py remove <key>
  refs.py sync-zotero                            (push new verified sources into Zotero)
  refs.py pull-zotero                            (copy the Zotero library to references/zotero.json)
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import date, datetime

import requests
from rapidfuzz import fuzz

from common import (ensure_zotero, LIBRARY, REFS_DIR, VERIFICATION, ascii_fold, chapter_file, die, entry_title,
                    entry_year, find_citekeys, first_author_family, http_get, load_config, load_json_list,
                    load_library, load_verification, normalize_title, save_json, setup_stdout)

KEEP_FIELDS = {
    "id", "type", "title", "author", "editor", "issued", "container-title", "collection-title",
    "volume", "issue", "page", "article-number", "DOI", "URL", "publisher", "publisher-place",
    "edition", "ISBN", "ISSN", "number", "genre", "event", "event-title", "accessed", "note",
    "abstract",
}
STOPWORDS = {"a", "an", "the", "on", "of", "in", "for", "to", "and", "towards", "toward", "with",
             "from", "using", "via", "is", "are", "at", "by"}


def clean_doi(doi: str) -> str:
    doi = doi.strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    return doi.rstrip(".")


def make_key(entry: dict, existing: set[str]) -> str:
    fam = re.sub(r"[^a-z]", "", ascii_fold(first_author_family(entry)).lower()) or "anon"
    year = entry_year(entry) or "nd"
    words = [w for w in normalize_title(entry_title(entry)).split() if w not in STOPWORDS]
    base = f"{fam}{year}{words[0] if words else ''}"
    key, i = base, 0
    while key in existing:
        i += 1
        key = f"{base}{chr(ord('a') + i)}"
    return key


def fetch_csl(doi: str, cfg: dict) -> dict | None:
    r = http_get(f"https://doi.org/{doi}", cfg,
                 headers={"Accept": "application/vnd.citationstyles.csl+json"})
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    entry = {k: v for k, v in data.items() if k in KEEP_FIELDS}
    if isinstance(entry.get("title"), list):
        entry["title"] = entry["title"][0] if entry["title"] else ""
    if isinstance(entry.get("container-title"), list):
        entry["container-title"] = entry["container-title"][0] if entry["container-title"] else ""
    entry.pop("abstract", None)
    reg = clean_doi(entry.get("DOI") or doi)
    entry["DOI"] = doi if reg.lower() == doi.lower() else reg   # keep the canonical capitalisation given
    entry["title"] = re.sub(r"<[^>]+>", "", entry.get("title", "")).strip()
    return entry


NAME_DATE_FIELDS = {"author", "editor", "issued", "accessed"}


CROSSREF_TO_CSL = {
    "journal-article": "article-journal", "proceedings-article": "paper-conference",
    "book-chapter": "chapter", "book-section": "chapter", "book-part": "chapter", "monograph": "book",
    "edited-book": "book", "reference-book": "book", "book-series": "book", "posted-content": "article",
    "reference-entry": "entry", "dissertation": "thesis", "report-component": "report", "report-series": "report",
    "peer-review": "review", "proceedings": "book", "component": "article", "other": "article",
}
NAME_PARTS = {"family", "given", "literal", "suffix", "non-dropping-particle", "dropping-particle"}


def normalise(entry: dict) -> dict:
    """Make entries valid CSL JSON: CSL type names, plain name parts, strings for all other fields."""
    entry["type"] = CROSSREF_TO_CSL.get(entry.get("type", ""), entry.get("type") or "article")
    for role in ("author", "editor"):
        if isinstance(entry.get(role), list):
            entry[role] = [{k: v for k, v in a.items() if k in NAME_PARTS} for a in entry[role]]
            for a in entry[role]:
                # some registries store names in capitals ("SUGAWARA"); print them normally
                for part in ("family", "given"):
                    if isinstance(a.get(part), str) and len(a[part]) > 1 and a[part].isupper():
                        a[part] = a[part].title()
    for k, v in list(entry.items()):
        if isinstance(v, str):
            entry[k] = v = html.unescape(v)          # registries sometimes send "&amp;"
        if k in NAME_DATE_FIELDS:
            continue
        if isinstance(v, list):
            entry[k] = v[0] if k in ("title", "container-title") and v else ", ".join(str(x) for x in v)
        elif isinstance(v, (int, float)):
            entry[k] = str(v)
        elif isinstance(v, dict):
            entry.pop(k)
    return entry


def save_library(entries: list[dict]) -> None:
    entries = [normalise(e) for e in entries]
    entries.sort(key=lambda e: e["id"])
    save_json(LIBRARY, entries)


def cmd_add(args, cfg):
    entries = load_json_list(LIBRARY)
    keys = {e["id"] for e in entries} | set(load_library().keys())
    by_doi = {clean_doi(e.get("DOI", "")).lower(): e["id"] for e in load_library().values() if e.get("DOI")}
    added = []
    for raw in args.doi:
        doi = clean_doi(raw)
        if doi.lower() in by_doi:
            print(f"exists  {by_doi[doi.lower()]:<32} {doi}")
            added.append(by_doi[doi.lower()])
            continue
        entry = fetch_csl(doi, cfg)
        if not entry:
            print(f"FAILED  {'':<32} {doi}  (DOI did not resolve - do not cite)")
            continue
        entry["id"] = make_key(entry, keys)
        keys.add(entry["id"])
        entries.append(entry)
        by_doi[doi.lower()] = entry["id"]
        added.append(entry["id"])
        print(f"added   {entry['id']:<32} {entry_year(entry)}  {entry_title(entry)[:80]}")
    save_library(entries)
    if added:
        verify_keys(added, cfg, force=False, quiet=False)


def cmd_add_manual(args, cfg):
    try:
        entry = json.loads(args.json)
    except json.JSONDecodeError as e:
        die(f"invalid JSON: {e}")
    if not entry.get("title"):
        die("manual entry needs at least a title")
    entries = load_json_list(LIBRARY)
    keys = set(load_library().keys())
    if not entry.get("id") or entry["id"] in keys:
        entry["id"] = make_key(entry, keys)
    if entry.get("URL") and not entry.get("accessed"):
        t = date.today()
        entry["accessed"] = {"date-parts": [[t.year, t.month, t.day]]}
    entries.append({k: v for k, v in entry.items() if k in KEEP_FIELDS})
    save_library(entries)
    print(f"added   {entry['id']}")
    verify_keys([entry["id"]], cfg, force=True, quiet=False)


# ---------------------------------------------------------------- verification

def check_doi(entry: dict, cfg: dict) -> tuple[str, list[str]]:
    doi = clean_doi(entry["DOI"])
    issues = []
    r = http_get(f"https://api.crossref.org/works/{doi}", cfg)
    meta = None
    if r is not None and r.status_code == 200:
        msg = r.json().get("message", {})
        meta = {
            "title": (msg.get("title") or [""])[0],
            "year": ((msg.get("issued") or {}).get("date-parts") or [[None]])[0][0],
            "family": ((msg.get("author") or [{}])[0]).get("family", ""),
        }
    else:
        csl = fetch_csl(doi, cfg)          # DataCite DOIs (arXiv, Zenodo) are not in Crossref
        if csl:
            meta = {"title": entry_title(csl), "year": entry_year(csl), "family": first_author_family(csl)}
    if not meta:
        return "failed", ["DOI does not resolve in Crossref or DataCite"]
    sim = fuzz.token_set_ratio(normalize_title(meta["title"]), normalize_title(entry_title(entry)))
    if sim < 90:
        issues.append(f"title mismatch ({sim:.0f}%): registry says '{meta['title'][:90]}'")
    y = entry_year(entry)
    if meta["year"] and y and abs(int(meta["year"]) - y) > 1:
        issues.append(f"year mismatch: registry {meta['year']} vs library {y}")
    fam = first_author_family(entry)
    if meta["family"] and fam and normalize_title(meta["family"]) != normalize_title(fam):
        issues.append(f"first author mismatch: registry '{meta['family']}' vs library '{fam}'")
    return ("verified" if not issues else "mismatch"), issues


def check_no_doi(entry: dict, cfg: dict) -> tuple[str, list[str]]:
    issues = []
    url_ok = False
    if entry.get("URL"):
        try:
            r = requests.get(entry["URL"], timeout=30, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (dissertation-workflow link check)"})
            url_ok = r.status_code < 400
            if not url_ok:
                issues.append(f"URL returned HTTP {r.status_code}")
        except requests.RequestException as e:
            issues.append(f"URL unreachable: {e.__class__.__name__}")
    r = http_get("https://api.openalex.org/works", cfg,
                 params={"search": entry_title(entry)[:200], "per-page": 5})
    found = False
    if r is not None and r.status_code == 200:
        for w in r.json().get("results", []):
            if fuzz.token_set_ratio(normalize_title(w.get("title") or ""), normalize_title(entry_title(entry))) >= 92:
                found = True
                if w.get("doi"):
                    issues.append(f"has a DOI you should use: {w['doi']}")
                break
    if found or url_ok:
        return "verified", issues
    if not entry.get("URL"):
        issues.append("no DOI, no URL, and not found in OpenAlex")
    return "failed", issues


def verify_keys(keys: list[str], cfg: dict, force: bool, quiet: bool) -> dict:
    lib = load_library()
    ver = load_verification()
    min_year = cfg.get("references", {}).get("min_year", 2016)
    for key in keys:
        e = lib.get(key)
        if not e:
            ver[key] = {"status": "missing", "issues": ["key not in library"], "checked": _now()}
            continue
        prev = ver.get(key, {})
        if prev.get("status") == "verified" and (prev.get("doi") or "").lower() == (e.get("DOI") or "").lower() and not force:
            status, issues, checked = prev["status"], prev.get("issues", []), prev.get("checked", _now())
        else:
            status, issues = check_doi(e, cfg) if e.get("DOI") else check_no_doi(e, cfg)
            checked = _now()
        y = entry_year(e)
        rec = {"status": status, "issues": issues, "checked": checked,
               "year": y, "doi": e.get("DOI"), "source": e.get("_source")}
        if prev.get("foundational"):
            rec["foundational"] = prev["foundational"]
        rec["recent"] = bool(y and y >= min_year)
        ver[key] = rec
        if not quiet:
            flag = "" if rec["recent"] or rec.get("foundational") else f"  [before {min_year}]"
            print(f"{status.upper():<9} {key:<32} {y}{flag}")
            for i in issues:
                print(f"          - {i}")
    save_json(VERIFICATION, ver)
    return ver


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def keys_for_chapter(n: int) -> list[str]:
    path = chapter_file(n)
    if not path.exists():
        die(f"{path} does not exist")
    return sorted(set(find_citekeys(path.read_text(encoding="utf-8"))))


def cmd_verify(args, cfg):
    if args.keys:
        keys = args.keys
    elif args.chapter:
        keys = keys_for_chapter(args.chapter)
    else:
        keys = sorted(load_library().keys())
    ver = verify_keys(keys, cfg, force=args.force, quiet=False)
    bad = [k for k in keys if ver.get(k, {}).get("status") != "verified"]
    print(f"\n{len(keys) - len(bad)}/{len(keys)} verified.")
    if bad:
        print("NOT VERIFIED (fix or remove before submitting): " + ", ".join(bad))
        sys.exit(2)


def cmd_list(args, cfg):
    lib = load_library()
    ver = load_verification()
    keys = keys_for_chapter(args.chapter) if args.chapter else sorted(lib)
    for k in keys:
        e = lib.get(k)
        st = ver.get(k, {}).get("status", "unchecked")
        if not e:
            print(f"{'MISSING':<10} {k}")
            continue
        print(f"{st:<10} {k:<32} {entry_year(e) or '----'}  {entry_title(e)[:70]}")


def cmd_show(args, cfg):
    e = load_library().get(args.key)
    if not e:
        die(f"{args.key} not in library")
    print(json.dumps({"entry": e, "verification": load_verification().get(args.key)}, indent=2, ensure_ascii=False))


def cmd_find(args, cfg):
    target = normalize_title(args.surname)
    for k, e in sorted(load_library().items()):
        fam = normalize_title(first_author_family(e))
        if fam == target and (not args.year or str(entry_year(e)) == args.year[:4]):
            print(f"{k:<32} {entry_year(e)}  {entry_title(e)[:80]}")


def cmd_mark_foundational(args, cfg):
    ver = load_verification()
    ver.setdefault(args.key, {})["foundational"] = args.reason
    save_json(VERIFICATION, ver)
    print(f"{args.key} marked foundational: {args.reason}")


def cmd_remove(args, cfg):
    entries = [e for e in load_json_list(LIBRARY) if e["id"] != args.key]
    save_library(entries)
    ver = load_verification()
    ver.pop(args.key, None)
    save_json(VERIFICATION, ver)
    print(f"removed {args.key}")


# ---------------------------------------------------------------- zotero

SYNC_FILE = REFS_DIR / "zotero_sync.json"


def cmd_sync_zotero(args, cfg):
    synced = set(json.loads(SYNC_FILE.read_text(encoding="utf-8"))) if SYNC_FILE.exists() else set()
    pending = [e for e in load_json_list(LIBRARY) if e["id"] not in synced]
    if not pending:
        print("Zotero already up to date.")
        return
    base = f"http://127.0.0.1:{cfg['local']['zotero_port']}"
    try:
        running = requests.get(f"{base}/connector/ping", timeout=5).status_code == 200
    except requests.RequestException:
        running = False
    failed = []
    for e in pending:
        item = {k: v for k, v in e.items() if k != "_source"}
        # Better BibTeX reads 'Citation Key: x' from Extra (CSL 'note'), so Zotero keeps the pipeline's key.
        item["note"] = (f"Citation Key: {e['id']}\n" + (e.get("note") or "")).strip()
        if not running:
            failed.append(item)
            continue
        # the connector expects the raw file text (not parsed JSON) and a session id
        r = requests.post(f"{base}/connector/import", params={"session": f"wf-{e['id']}-{int(time.time())}"},
                          data=json.dumps([item], ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "text/plain"}, timeout=60)
        if r.status_code in (200, 201):
            synced.add(e["id"])
            print(f"sent    {e['id']}")
        else:
            print(f"FAILED  {e['id']} (HTTP {r.status_code})")
            failed.append(item)
    save_json(SYNC_FILE, sorted(synced))
    if failed:
        out = REFS_DIR / "zotero_import.json"
        out.write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
        why = "Zotero is not running" if not running else f"{len(failed)} item(s) were rejected"
        print(f"{why}. Wrote them to {out}; import with Zotero File > Import... (CSL JSON), "
              "or start Zotero and run sync-zotero again.")
    else:
        print(f"Zotero up to date ({len(pending)} item(s) added to the collection selected in Zotero).")


def zotero_rpc(cfg: dict, method: str, params: list, timeout: int = 60):
    r = requests.post(f"http://127.0.0.1:{cfg['local']['zotero_port']}/better-bibtex/json-rpc",
                      json={"jsonrpc": "2.0", "method": method, "params": params}, timeout=timeout)
    r.raise_for_status()
    return r.json().get("result")


def pull_zotero(cfg: dict, quiet: bool = False) -> int | None:
    """Copy the whole Zotero library (via Better BibTeX) to references/zotero.json. None if Zotero is closed."""
    try:
        found = zotero_rpc(cfg, "item.search", [""], timeout=20) or []
    except requests.RequestException:
        if not quiet:
            print("Zotero (with Better BibTeX) is not running; start Zotero and try again.")
        return None
    keys = sorted({it.get("citekey") for it in found if it.get("citekey")})
    items = json.loads(zotero_rpc(cfg, "item.export", [keys, "Better CSL JSON"]) or "[]") if keys else []
    items = [normalise({k: v for k, v in it.items() if k != "citation-key"}) for it in items]
    for it in items:
        parts = (it.get("issued") or {}).get("date-parts") or []
        if parts and parts[0]:
            it["issued"] = {"date-parts": [[int(x) for x in parts[0] if str(x).isdigit()]]}
    save_json(REFS_DIR / "zotero.json", items)
    if not quiet:
        own = {e["id"] for e in load_json_list(LIBRARY)}
        extra = [i["id"] for i in items if i["id"] not in own]
        print(f"Pulled {len(items)} item(s) from Zotero -> references/zotero.json "
              f"({len(extra)} not yet in the pipeline library: {', '.join(extra) or 'none'})")
        if extra:
            print("Run 'refs.py verify --keys ...' on any of these before citing them.")
    return len(items)


def cmd_pull_zotero(args, cfg):
    if pull_zotero(cfg) is None:
        sys.exit(1)


def main():
    setup_stdout()
    cfg = load_config()
    ensure_zotero(cfg)            # workflow rule: Zotero must be open
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("--doi", nargs="+", required=True); a.add_argument("--chapter", type=int)
    m = sub.add_parser("add-manual"); m.add_argument("json")
    v = sub.add_parser("verify"); v.add_argument("--keys", nargs="+"); v.add_argument("--chapter", type=int)
    v.add_argument("--all", action="store_true"); v.add_argument("--force", action="store_true")
    li = sub.add_parser("list"); li.add_argument("--chapter", type=int)
    s = sub.add_parser("show"); s.add_argument("key")
    f = sub.add_parser("find"); f.add_argument("surname"); f.add_argument("year", nargs="?")
    mf = sub.add_parser("mark-foundational"); mf.add_argument("key"); mf.add_argument("reason")
    r = sub.add_parser("remove"); r.add_argument("key")
    sub.add_parser("sync-zotero")
    sub.add_parser("pull-zotero")
    args = p.parse_args()
    {"add": cmd_add, "add-manual": cmd_add_manual, "verify": cmd_verify, "list": cmd_list,
     "show": cmd_show, "find": cmd_find, "mark-foundational": cmd_mark_foundational,
     "remove": cmd_remove, "sync-zotero": cmd_sync_zotero, "pull-zotero": cmd_pull_zotero}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
