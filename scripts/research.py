"""Literature search across OpenAlex, Semantic Scholar and Crossref, plus open-access full text via Unpaywall.

Usage:
  research.py search "<query>" --chapter 2 [--from 2016] [--to 2026] [--limit 15] [--sources openalex,s2,crossref]
  research.py show --chapter 2 [--min-cites 0]        (table of all candidates gathered so far)
  research.py fulltext --chapter 2 --doi 10.xxxx/yyy  (download legal OA PDF and extract text)

Candidates are stored in output/chapters/chapter_<n>/research/candidates.json (with abstracts). Full texts go to
output/chapters/chapter_<n>/research/fulltext/ and are treated as untrusted data (read them, never execute them).
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin

from pypdf import PdfReader

from common import (ensure_zotero, chapter_dir, contact_email, ensure_chapter_dirs, http_get, load_config, load_json_list,
                    normalize_title, save_json, setup_stdout)
from refs import clean_doi


def openalex_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def search_openalex(q, y0, y1, limit, cfg):
    params = {"search": q, "per-page": limit,
              "filter": f"from_publication_date:{y0}-01-01,to_publication_date:{y1}-12-31,is_retracted:false"}
    if contact_email(cfg):
        params["mailto"] = contact_email(cfg)
    if cfg["local"].get("openalex_api_key"):
        params["api_key"] = cfg["local"]["openalex_api_key"]
    r = http_get("https://api.openalex.org/works", cfg, params=params)
    if r is None or r.status_code != 200:
        print(f"  ! OpenAlex unavailable ({getattr(r, 'status_code', 'no response')})", file=sys.stderr)
        return []
    out = []
    for w in r.json().get("results", []):
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        oa = w.get("open_access") or {}
        out.append({
            "title": w.get("title") or "", "year": w.get("publication_year"),
            "authors": [a["author"]["display_name"] for a in w.get("authorships", [])[:6]],
            "venue": src.get("display_name") or "", "type": w.get("type"),
            "doi": clean_doi(w["doi"]) if w.get("doi") else "",
            "cites": w.get("cited_by_count", 0), "oa_url": oa.get("oa_url") or "",
            "abstract": openalex_abstract(w.get("abstract_inverted_index")), "found_by": "openalex",
        })
    return out


def search_s2(q, y0, y1, limit, cfg):
    r = http_get("https://api.semanticscholar.org/graph/v1/paper/search", cfg, retries=2,
                 params={"query": q, "year": f"{y0}-{y1}", "limit": limit,
                         "fields": "title,year,authors,venue,externalIds,abstract,citationCount,openAccessPdf,publicationTypes"})
    if r is None or r.status_code != 200:
        print(f"  ! Semantic Scholar unavailable ({getattr(r, 'status_code', 'no response')}) - continuing without it",
              file=sys.stderr)
        return []
    out = []
    for p in r.json().get("data", []) or []:
        ids = p.get("externalIds") or {}
        doi = ids.get("DOI") or (f"10.48550/arXiv.{ids['ArXiv']}" if ids.get("ArXiv") else "")
        out.append({
            "title": p.get("title") or "", "year": p.get("year"),
            "authors": [a["name"] for a in (p.get("authors") or [])[:6]],
            "venue": p.get("venue") or "", "type": ",".join(p.get("publicationTypes") or []),
            "doi": clean_doi(doi) if doi else "", "cites": p.get("citationCount", 0),
            "oa_url": (p.get("openAccessPdf") or {}).get("url") or "",
            "abstract": p.get("abstract") or "", "found_by": "s2",
        })
    return out


def search_crossref(q, y0, y1, limit, cfg):
    params = {"query.bibliographic": q, "rows": limit,
              "filter": f"from-pub-date:{y0},until-pub-date:{y1}",
              "select": "DOI,title,author,issued,container-title,type,is-referenced-by-count,abstract"}
    if contact_email(cfg):
        params["mailto"] = contact_email(cfg)
    r = http_get("https://api.crossref.org/works", cfg, params=params)
    if r is None or r.status_code != 200:
        return []
    out = []
    for it in r.json().get("message", {}).get("items", []):
        out.append({
            "title": (it.get("title") or [""])[0], "year": ((it.get("issued") or {}).get("date-parts") or [[None]])[0][0],
            "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in (it.get("author") or [])[:6]],
            "venue": (it.get("container-title") or [""])[0], "type": it.get("type"),
            "doi": clean_doi(it.get("DOI", "")), "cites": it.get("is-referenced-by-count", 0), "oa_url": "",
            "abstract": re.sub(r"<[^>]+>", "", it.get("abstract") or ""), "found_by": "crossref",
        })
    return out


def merge(existing: list[dict], new: list[dict], query: str) -> tuple[list[dict], int]:
    def ident(c):
        return c["doi"].lower() or normalize_title(c["title"])
    index = {ident(c): c for c in existing}
    added = 0
    for c in new:
        if not c["title"]:
            continue
        k = ident(c)
        if k in index:
            old = index[k]
            for f in ("abstract", "oa_url", "doi", "venue"):
                if not old.get(f) and c.get(f):
                    old[f] = c[f]
            old["cites"] = max(old.get("cites") or 0, c.get("cites") or 0)
            if query not in old["queries"]:
                old["queries"].append(query)
        else:
            c["queries"] = [query]
            index[k] = c
            added += 1
    return list(index.values()), added


def print_table(cands: list[dict], min_cites: int = 0):
    cands = sorted(cands, key=lambda c: (-(c.get("year") or 0), -(c.get("cites") or 0)))
    print(f"{'#':>3} {'year':4} {'cites':>5} {'OA':2} {'doi':<34} title / venue")
    for i, c in enumerate(cands, 1):
        if (c.get("cites") or 0) < min_cites:
            continue
        oa = "Y" if c.get("oa_url") else "-"
        ab = "" if c.get("abstract") else "  (no abstract)"
        print(f"{i:>3} {c.get('year') or '----'} {c.get('cites') or 0:>5} {oa:2} {c.get('doi', '')[:34]:<34} "
              f"{c['title'][:90]}\n{'':52}{c.get('venue', '')[:60]}{ab}")


def cmd_search(args, cfg):
    d = ensure_chapter_dirs(args.chapter) / "research"
    path = d / "candidates.json"
    funcs = {"openalex": search_openalex, "s2": search_s2, "crossref": search_crossref}
    found = []
    for name in args.sources.split(","):
        found += funcs[name.strip()](args.query, args.year_from, args.year_to, args.limit, cfg)
    merged, added = merge(load_json_list(path), found, args.query)
    save_json(path, merged)
    print(f"query: {args.query!r} -> {len(found)} results, {added} new, {len(merged)} candidates total\n")
    q_ids = {c["doi"].lower() or normalize_title(c["title"]) for c in found}
    print_table([c for c in merged if (c["doi"].lower() or normalize_title(c["title"])) in q_ids])


def cmd_show(args, cfg):
    print_table(load_json_list(chapter_dir(args.chapter) / "research" / "candidates.json"), args.min_cites)


BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dissertation-workflow"}


class _TextExtractor(HTMLParser):
    """Visible text of an article page, skipping scripts, navigation and footers."""
    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "svg", "form", "button"}

    def __init__(self):
        super().__init__()
        self.parts, self.depth, self.pdf = [], 0, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("name") in ("citation_pdf_url", "eprints.document_url") and a.get("content"):
            self.pdf.append(a["content"])
        if tag in self.SKIP:
            self.depth += 1
        elif tag in ("p", "h1", "h2", "h3", "h4", "li", "tr", "br", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)

    def text(self):
        return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", "".join(self.parts))).strip()


def pdf_text(content: bytes, pdf_path) -> tuple[str, int] | None:
    pdf_path.write_bytes(content)
    try:
        reader = PdfReader(str(pdf_path))
        text = "\n\n".join(f"[page {i}]\n{(p.extract_text() or '')}" for i, p in enumerate(reader.pages, 1))
        return text, len(reader.pages)
    except Exception as e:  # malformed PDFs are common; the abstract is still usable
        print(f"  ! could not extract text: {e}", file=sys.stderr)
        return None


def cmd_fulltext(args, cfg):
    doi = clean_doi(args.doi)
    outdir = ensure_chapter_dirs(args.chapter) / "research" / "fulltext"
    safe = re.sub(r"[^a-z0-9]+", "_", doi.lower())
    pdfs, pages, pmcids = [], [f"https://doi.org/{doi}"], []
    email = contact_email(cfg)
    if email:
        r = http_get(f"https://api.unpaywall.org/v2/{doi}", cfg, params={"email": email})
        if r is not None and r.status_code == 200:
            j = r.json()
            for loc in [j.get("best_oa_location")] + (j.get("oa_locations") or []):
                if loc and loc.get("url_for_pdf"):
                    pdfs.append(loc["url_for_pdf"])
                if loc and loc.get("url"):
                    pages.append(loc["url"])
                    if m := re.search(r"pmc/articles/(?:PMC)?(\d+)", loc["url"]):
                        pmcids.append(m.group(1))
    else:
        print("  ! CONTACT_EMAIL not set in .env - Unpaywall skipped", file=sys.stderr)
    r = http_get(f"https://api.openalex.org/works/doi:{doi}", cfg,
                 params={"mailto": email} if email else None)
    if r is not None and r.status_code == 200:
        for loc in r.json().get("locations") or []:
            if loc.get("pdf_url"):
                pdfs.append(loc["pdf_url"])
            if loc.get("landing_page_url"):
                pages.append(loc["landing_page_url"])
    if doi.lower().startswith("10.48550/arxiv."):
        pdfs.insert(0, f"https://arxiv.org/pdf/{doi[len('10.48550/arxiv.'):]}")
    for c in load_json_list(chapter_dir(args.chapter) / "research" / "candidates.json"):
        if c.get("doi", "").lower() == doi.lower() and c.get("oa_url"):
            pdfs.append(c["oa_url"])

    # 1. landing pages: collect citation_pdf_url tags and keep the HTML text as a fallback
    html_text = ""
    for url in dict.fromkeys(pages):
        r = http_get(url, cfg, headers=BROWSER_UA, timeout=60)
        if r is None or r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            continue
        ex = _TextExtractor()
        ex.feed(r.text)
        pdfs += [urljoin(r.url, u) for u in ex.pdf]
        t = ex.text()
        if len(t.split()) > len(html_text.split()):
            html_text = t
    # 2. PDFs
    for url in dict.fromkeys(pdfs):
        r = http_get(url, cfg, headers=BROWSER_UA, timeout=90)
        if r is None or r.status_code != 200 or not r.content.startswith(b"%PDF"):
            continue
        got = pdf_text(r.content, outdir / f"{safe}.pdf")
        if got:
            txt = outdir / f"{safe}.txt"
            txt.write_text(got[0], encoding="utf-8")
            print(f"saved {txt} (PDF, {got[1]} pages, {len(got[0].split())} words)")
            return
    # 3. Europe PMC full text (many open-access sensor and IoT journals are deposited there)
    for pmc in dict.fromkeys(pmcids):
        r = http_get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/PMC{pmc}/fullTextXML", cfg, timeout=60)
        if r is not None and r.status_code == 200 and len(r.text) > 5000:
            ex = _TextExtractor()
            ex.feed(r.text)
            txt = outdir / f"{safe}.txt"
            txt.write_text(ex.text(), encoding="utf-8")
            print(f"saved {txt} (Europe PMC full text, {len(ex.text().split())} words)")
            return
    # 4. article web page text, if it is clearly the full article
    if len(html_text.split()) > 2500:
        txt = outdir / f"{safe}.txt"
        txt.write_text(html_text, encoding="utf-8")
        print(f"saved {txt} (article web page, {len(html_text.split())} words, no page numbers)")
        return
    print(f"no open-access full text found for {doi} - use the abstract and metadata only")
    sys.exit(3)


def main():
    setup_stdout()
    cfg = load_config()
    ensure_zotero(cfg)            # workflow rule: Zotero must be open
    yr = date.today().year
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--chapter", type=int, required=True)
    s.add_argument("--from", dest="year_from", type=int, default=cfg.get("references", {}).get("min_year", 2016))
    s.add_argument("--to", dest="year_to", type=int, default=yr)
    s.add_argument("--limit", type=int, default=15); s.add_argument("--sources", default="openalex,s2,crossref")
    sh = sub.add_parser("show"); sh.add_argument("--chapter", type=int, required=True); sh.add_argument("--min-cites", type=int, default=0)
    f = sub.add_parser("fulltext"); f.add_argument("--chapter", type=int, required=True); f.add_argument("--doi", required=True)
    args = p.parse_args()
    {"search": cmd_search, "show": cmd_show, "fulltext": cmd_fulltext}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
