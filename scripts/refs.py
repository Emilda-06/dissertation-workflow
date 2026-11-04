"""Reference library of the active project: add sources by DOI, verify them, sync with Zotero.

Usage:
  refs.py add --doi 10.1109/xxx [10.1145/yyy ...]
  refs.py add-manual '<CSL JSON object>'        (standards, reports, websites without DOI)
  refs.py verify [--keys k1 k2 | --chapter 2 | --all] [--force]
  refs.py list [--chapter 2]
  refs.py show <key>
  refs.py find <surname> [<year>]
  refs.py mark-foundational <key> "<reason>"
  refs.py remove <key>
  refs.py sync-zotero                            (push new verified sources into this project's Zotero collection)
  refs.py pull-zotero                            (copy this project's Zotero collection to references/zotero.json)

Verification statuses: verified | mismatch | failed | retracted | missing. Only 'verified' may be cited.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import sys
import time
from datetime import date, datetime
from urllib.parse import quote

import requests
from rapidfuzz import fuzz

from common import (ascii_fold, chapter_file, die, ensure_zotero, entry_title, entry_year, find_citekeys,
                    first_author_family, http_get, init_cli, load_config, load_json_list, load_library,
                    load_verification, normalize_title, project, save_json, zotero_base)

KEEP_FIELDS = {
    "id", "type", "title", "author", "editor", "issued", "container-title", "collection-title",
    "volume", "issue", "page", "article-number", "DOI", "URL", "publisher", "publisher-place",
    "edition", "ISBN", "ISSN", "number", "genre", "event", "event-title", "accessed", "note",
    "abstract",
}
STOPWORDS = {"a", "an", "the", "on", "of", "in", "for", "to", "and", "towards", "toward", "with",
             "from", "using", "via", "is", "are", "at", "by"}
RETRACTION_TYPES = {"retraction", "withdrawal", "removal", "partial_retraction"}
TITLE_THRESHOLD = 90


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
    sub = data.get("subtitle")
    if isinstance(sub, list):
        sub = sub[0] if sub else ""
    entry.pop("abstract", None)
    reg = clean_doi(entry.get("DOI") or doi)
    entry["DOI"] = doi if reg.lower() == doi.lower() else reg   # keep the canonical capitalisation given
    entry["title"] = re.sub(r"<[^>]+>", "", entry.get("title", "")).strip()
    if sub and normalize_title(sub) not in normalize_title(entry["title"]):
        entry["title"] = f"{entry['title']}: {re.sub(r'<[^>]+>', '', sub).strip()}"
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
    save_json(project().library, entries)


def save_verification(ver: dict) -> None:
    save_json(project().verification, ver)


def cmd_add(args, cfg):
    p = project()
    entries = load_json_list(p.library)
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
    if not isinstance(entry, dict) or not entry.get("title"):
        die("manual entry needs at least a title")
    entries = load_json_list(project().library)
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

def fingerprint(e: dict) -> str:
    """Changes whenever a field that verification depends on changes."""
    basis = [normalize_title(entry_title(e)), normalize_title(first_author_family(e)), entry_year(e),
             (e.get("DOI") or "").lower(), e.get("URL") or ""]
    return hashlib.sha1(json.dumps(basis).encode()).hexdigest()[:16]


def title_similarity(library_title: str, registry_titles: list[str]) -> float:
    """Strict comparison: the whole title must match (a short title that is merely a subset does not).

    Registries sometimes keep the subtitle separately, so 'Main: Sub' is also compared with 'Main'
    when the main part alone is specific (4+ words)."""
    lib = normalize_title(library_title)
    if not lib:
        return 0.0
    lib_variants = {lib}
    main = normalize_title(re.split(r"[:?.]\s", library_title, maxsplit=1)[0])
    if len(main.split()) >= 4:
        lib_variants.add(main)
    best = 0.0
    for reg in registry_titles:
        r = normalize_title(reg)
        if not r:
            continue
        for v in lib_variants:
            best = max(best, fuzz.token_sort_ratio(v, r), fuzz.ratio(v, r))
    return best


def crossref_retracted(msg: dict) -> list[str]:
    out = []
    for u in msg.get("updated-by") or []:
        if (u.get("type") or "").lower() in RETRACTION_TYPES:
            out.append(f"{u.get('type')} notice {u.get('DOI', '')}".strip())
    return out


def openalex_retracted(doi: str, cfg: dict) -> bool:
    r = http_get(f"https://api.openalex.org/works/doi:{doi}", cfg, retries=2)
    if r is None or r.status_code != 200:
        return False
    try:
        return bool(r.json().get("is_retracted"))
    except ValueError:
        return False


def check_doi(entry: dict, cfg: dict) -> tuple[str, list[str]]:
    doi = clean_doi(entry["DOI"])
    issues: list[str] = []
    r = http_get(f"https://api.crossref.org/works/{quote(doi, safe='/:;()')}", cfg)
    meta = None
    retracted: list[str] = []
    if r is not None and r.status_code == 200:
        msg = r.json().get("message", {})
        titles = [t for t in (msg.get("title") or []) if t]
        subs = [s for s in (msg.get("subtitle") or []) if s]
        variants = titles + [f"{t}: {s}" for t in titles for s in subs]
        meta = {
            "titles": variants or [""],
            "year": ((msg.get("issued") or {}).get("date-parts") or [[None]])[0][0],
            "family": ((msg.get("author") or [{}])[0]).get("family", ""),
        }
        retracted = crossref_retracted(msg)
    else:
        csl = fetch_csl(doi, cfg)          # DataCite DOIs (arXiv, Zenodo) are not in Crossref
        if csl:
            meta = {"titles": [entry_title(csl)], "year": entry_year(csl), "family": first_author_family(csl)}
    if not meta:
        return "failed", ["DOI does not resolve in Crossref or DataCite"]
    if retracted or openalex_retracted(doi, cfg):
        return "retracted", retracted or ["OpenAlex marks this work as retracted - do not cite it"]
    sim = title_similarity(entry_title(entry), meta["titles"])
    if sim < TITLE_THRESHOLD:
        issues.append(f"title mismatch ({sim:.0f}%): registry says '{meta['titles'][0][:90]}'")
    y = entry_year(entry)
    if meta["year"] and y and abs(int(meta["year"]) - y) > 1:
        issues.append(f"year mismatch: registry {meta['year']} vs library {y}")
    fam = first_author_family(entry)
    if meta["family"] and fam and normalize_title(meta["family"]) != normalize_title(fam):
        issues.append(f"first author mismatch: registry '{meta['family']}' vs library '{fam}'")
    return ("verified" if not issues else "mismatch"), issues


def page_text(resp: requests.Response) -> str:
    """Visible text (and <title>) of an HTML page, or the first pages of a PDF."""
    ctype = resp.headers.get("content-type", "")
    if resp.content[:4] == b"%PDF" or "pdf" in ctype:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(resp.content))
            return "\n".join((p.extract_text() or "") for p in reader.pages[:5])
        except Exception:
            return ""
    text = resp.text[:2_000_000]
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def title_on_page(title: str, text: str) -> float:
    t, body = normalize_title(title), normalize_title(text)[:300_000]
    if len(t.split()) < 3 or not body:
        return 100.0 if t and t in body else 0.0
    if t in body:
        return 100.0
    return fuzz.partial_ratio(t, body)


def check_no_doi(entry: dict, cfg: dict) -> tuple[str, list[str]]:
    """A source without a DOI is verified when its own page shows the title, or a catalogue has it."""
    issues: list[str] = []
    title = entry_title(entry)
    page_ok = False
    if entry.get("URL"):
        try:
            r = requests.get(entry["URL"], timeout=30, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (dissertation-workflow link check)"})
            if r.status_code >= 400:
                issues.append(f"URL returned HTTP {r.status_code}")
            else:
                score = title_on_page(title, page_text(r))
                page_ok = score >= TITLE_THRESHOLD
                if not page_ok:
                    issues.append(f"the page at the URL does not show this title (best match {score:.0f}%)")
        except requests.RequestException as e:
            issues.append(f"URL unreachable: {e.__class__.__name__}")
    r = http_get("https://api.openalex.org/works", cfg, params={"search": title[:200], "per-page": 5})
    found = False
    if r is not None and r.status_code == 200:
        for w in r.json().get("results", []):
            if title_similarity(title, [w.get("title") or ""]) >= 92:
                found = True
                if w.get("is_retracted"):
                    return "retracted", ["OpenAlex marks this work as retracted - do not cite it"]
                if w.get("doi"):
                    issues.append(f"has a DOI you should use: {w['doi']}")
                break
    if page_ok or found:
        return "verified", issues
    if not entry.get("URL"):
        issues.append("no DOI, no URL, and not found in OpenAlex")
        return "failed", issues
    reachable = not any("HTTP" in i or "unreachable" in i for i in issues)
    # reachable page that does not show the title: the metadata does not describe what is at the URL
    return ("mismatch" if reachable else "failed"), issues


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
        fp = fingerprint(e)
        if prev.get("status") == "verified" and prev.get("fingerprint") == fp and not force:
            status, issues, checked = prev["status"], prev.get("issues", []), prev.get("checked", _now())
        else:
            status, issues = check_doi(e, cfg) if e.get("DOI") else check_no_doi(e, cfg)
            checked = _now()
        y = entry_year(e)
        rec = {"status": status, "issues": issues, "checked": checked, "fingerprint": fp,
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
    save_verification(ver)
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
        if st == "verified" and ver[k].get("fingerprint") not in (None, fingerprint(e)):
            st = "changed"     # edited since it was verified: run verify again
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
    if args.key not in load_library():
        die(f"{args.key} not in library")
    ver = load_verification()
    ver.setdefault(args.key, {})["foundational"] = args.reason
    save_verification(ver)
    print(f"{args.key} marked foundational: {args.reason}")


def cmd_remove(args, cfg):
    entries = [e for e in load_json_list(project().library) if e["id"] != args.key]
    save_library(entries)
    ver = load_verification()
    ver.pop(args.key, None)
    save_verification(ver)
    print(f"removed {args.key}")


# ---------------------------------------------------------------- zotero (per-project collection)

def zotero_settings(cfg: dict) -> dict:
    z = cfg.get("zotero") or {}
    return {"collection": (z.get("collection") or "").strip(), "library_id": int(z.get("library_id", 1))}


def selected_collection(cfg: dict) -> str | None:
    """Name of the collection currently selected in the Zotero window (None if unknown)."""
    try:
        r = requests.post(f"{zotero_base(cfg)}/connector/getSelectedCollection", json={}, timeout=10)
        if r.status_code == 200:
            j = r.json()
            return j.get("name") if j.get("id") else ""          # "" = library root selected
    except (requests.RequestException, ValueError):
        pass
    return None


def cmd_sync_zotero(args, cfg):
    p = project()
    synced = set(json.loads(p.zotero_sync.read_text(encoding="utf-8"))) if p.zotero_sync.exists() else set()
    pending = [e for e in load_json_list(p.library) if e["id"] not in synced]
    if not pending:
        print("Zotero already up to date.")
        return
    base = zotero_base(cfg)
    try:
        running = requests.get(f"{base}/connector/ping", timeout=5).status_code == 200
    except requests.RequestException:
        running = False
    want = zotero_settings(cfg)["collection"]
    blocked = ""
    if running and want:
        sel = selected_collection(cfg)
        if sel is not None and sel.lower() != want.lower():
            blocked = (f"Zotero has '{sel or 'My Library (no collection)'}' selected, but this project uses the "
                       f"collection '{want}'. Select '{want}' in the Zotero window and run sync-zotero again.")
    failed = []
    for e in pending:
        item = {k: v for k, v in e.items() if k != "_source"}
        # Better BibTeX reads 'Citation Key: x' from Extra (CSL 'note'), so Zotero keeps the pipeline's key.
        item["note"] = (f"Citation Key: {e['id']}\n" + (e.get("note") or "")).strip()
        if not running or blocked:
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
    save_json(p.zotero_sync, sorted(synced))
    if failed:
        out = p.refs_dir / "zotero_import.json"
        out.write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
        why = blocked or ("Zotero is not running" if not running else f"{len(failed)} item(s) were rejected")
        print(f"{why}\nWrote {len(failed)} item(s) to {p.rel(out)}; import with Zotero File > Import... "
              "(CSL JSON) into the right collection, or fix the above and run sync-zotero again.")
    else:
        print(f"Zotero up to date ({len(pending)} item(s) added to '{want or 'the selected collection'}').")


def zotero_rpc(cfg: dict, method: str, params: list, timeout: int = 60):
    r = requests.post(f"{zotero_base(cfg)}/better-bibtex/json-rpc",
                      json={"jsonrpc": "2.0", "method": method, "params": params}, timeout=timeout)
    r.raise_for_status()
    return r.json().get("result")


def fetch_zotero_items(cfg: dict) -> list[dict] | None:
    """This project's Zotero items as CSL JSON. With a collection configured, only that collection."""
    zs = zotero_settings(cfg)
    if zs["collection"]:
        url = (f"{zotero_base(cfg)}/better-bibtex/export/collection?/{zs['library_id']}/"
               f"{quote(zs['collection'])}.csljson")
        try:
            r = requests.get(url, timeout=60)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            print(f"  ! Zotero collection '{zs['collection']}' could not be exported (HTTP {r.status_code}). "
                  "Create it in Zotero (or fix zotero.collection in project.yaml). Zotero items not included.",
                  file=sys.stderr)
            return []
        try:
            return r.json()
        except ValueError:
            return []
    print("  ! no zotero.collection set in project.yaml: using the WHOLE Zotero library (not isolated per "
          "project)", file=sys.stderr)
    try:
        found = zotero_rpc(cfg, "item.search", [""], timeout=20) or []
    except requests.RequestException:
        return None
    keys = sorted({it.get("citekey") for it in found if it.get("citekey")})
    return json.loads(zotero_rpc(cfg, "item.export", [keys, "Better CSL JSON"]) or "[]") if keys else []


def pull_zotero(cfg: dict, quiet: bool = False) -> int | None:
    """Copy this project's Zotero items to references/zotero.json. None if Zotero is closed."""
    p = project()
    items = fetch_zotero_items(cfg)
    if items is None:
        if not quiet:
            print("Zotero (with Better BibTeX) is not running; start Zotero and try again.")
        return None
    items = [normalise({k: v for k, v in it.items() if k != "citation-key"}) for it in items if it.get("id")]
    for it in items:
        parts = (it.get("issued") or {}).get("date-parts") or []
        if parts and parts[0]:
            it["issued"] = {"date-parts": [[int(x) for x in parts[0] if str(x).isdigit()]]}
    save_json(p.zotero_export, items)
    if not quiet:
        own = {e["id"] for e in load_json_list(p.library)}
        extra = [i["id"] for i in items if i["id"] not in own]
        print(f"Pulled {len(items)} item(s) from Zotero -> {p.rel(p.zotero_export)} "
              f"({len(extra)} not yet in the pipeline library: {', '.join(extra) or 'none'})")
        if extra:
            print("Run 'refs.py verify --keys ...' on any of these before citing them.")
    return len(items)


def cmd_pull_zotero(args, cfg):
    if pull_zotero(cfg) is None:
        sys.exit(1)


NEEDS_ZOTERO = {"sync-zotero", "pull-zotero"}


def main():
    init_cli()
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
    cfg = load_config()
    if args.cmd in NEEDS_ZOTERO:
        ensure_zotero(cfg)
    {"add": cmd_add, "add-manual": cmd_add_manual, "verify": cmd_verify, "list": cmd_list,
     "show": cmd_show, "find": cmd_find, "mark-foundational": cmd_mark_foundational,
     "remove": cmd_remove, "sync-zotero": cmd_sync_zotero, "pull-zotero": cmd_pull_zotero}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
