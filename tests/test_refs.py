"""Step 3: stricter verification (network calls are replaced by fakes)."""
from __future__ import annotations

import common
import refs
from common import load_config
from conftest import add_verified_source


class Resp:
    def __init__(self, status=200, data=None, text="", content=b"", headers=None):
        self.status_code = status
        self._data = data
        self.text = text
        self.content = content or text.encode()
        self.headers = headers or {"content-type": "text/html"}

    def json(self):
        if self._data is None:
            raise ValueError
        return self._data


def crossref(title, year=2021, family="Smith", subtitle=None, updated_by=None):
    msg = {"title": [title], "issued": {"date-parts": [[year]]}, "author": [{"family": family}]}
    if subtitle:
        msg["subtitle"] = [subtitle]
    if updated_by:
        msg["updated-by"] = updated_by
    return Resp(data={"message": msg})


def test_title_similarity_is_strict():
    assert refs.title_similarity("Edge intelligence security survey", ["Edge Intelligence: Security Survey"]) >= 90
    assert refs.title_similarity("Security", ["Security of edge intelligence systems in practice"]) < 90
    # registry keeps the subtitle separately; the library has it joined
    assert refs.title_similarity("Zero trust architecture: a survey of methods", ["Zero trust architecture"]) < 90
    assert refs.title_similarity("Federated learning for anomaly detection: a survey",
                                 ["Federated learning for anomaly detection", "Federated learning for anomaly "
                                  "detection: A survey"]) >= 90


def test_check_doi_verified_mismatch_and_retracted(proj, monkeypatch):
    cfg = load_config()
    entry = {"title": "Edge intelligence security survey", "author": [{"family": "Smith"}],
             "issued": {"date-parts": [[2021]]}, "DOI": "10.1/x"}
    monkeypatch.setattr(refs, "openalex_retracted", lambda doi, cfg: False)
    monkeypatch.setattr(refs, "http_get", lambda url, cfg, **kw: crossref("Edge intelligence security survey"))
    assert refs.check_doi(entry, cfg) == ("verified", [])
    monkeypatch.setattr(refs, "http_get", lambda url, cfg, **kw: crossref("Something else entirely", 2015, "Jones"))
    status, issues = refs.check_doi(entry, cfg)
    assert status == "mismatch" and len(issues) == 3
    monkeypatch.setattr(refs, "http_get", lambda url, cfg, **kw: crossref(
        "Edge intelligence security survey", updated_by=[{"type": "retraction", "DOI": "10.1/r"}]))
    assert refs.check_doi(entry, cfg)[0] == "retracted"
    monkeypatch.setattr(refs, "http_get", lambda url, cfg, **kw: crossref("Edge intelligence security survey"))
    monkeypatch.setattr(refs, "openalex_retracted", lambda doi, cfg: True)
    assert refs.check_doi(entry, cfg)[0] == "retracted"


def test_manual_source_needs_title_on_page(proj, monkeypatch):
    cfg = load_config()
    entry = {"title": "Zero Trust Architecture guidance for agencies", "URL": "https://example.org/zt"}
    monkeypatch.setattr(refs, "http_get", lambda url, cfg, **kw: Resp(data={"results": []}))
    monkeypatch.setattr(refs.requests, "get", lambda url, **kw: Resp(text="<html><title>Cooking blog</title>"
                                                                      "<p>pasta recipes</p></html>"))
    status, issues = refs.check_no_doi(entry, cfg)
    assert status == "mismatch" and "does not show this title" in issues[0]
    monkeypatch.setattr(refs.requests, "get", lambda url, **kw: Resp(
        text="<html><h1>Zero Trust Architecture Guidance for Agencies</h1></html>"))
    assert refs.check_no_doi(entry, cfg)[0] == "verified"
    monkeypatch.setattr(refs.requests, "get", lambda url, **kw: Resp(status=404))
    assert refs.check_no_doi(entry, cfg)[0] == "failed"


def test_reverify_when_metadata_edited(proj, monkeypatch):
    cfg = load_config()
    e = add_verified_source(proj)
    calls = []
    monkeypatch.setattr(refs, "check_doi", lambda entry, cfg: calls.append(entry["title"]) or ("verified", []))
    refs.verify_keys([e["id"]], cfg, force=False, quiet=True)
    assert calls == []                                            # unchanged: cached result used
    lib = common.load_json_list(proj.library)
    lib[0]["title"] = "A different title typed by hand"
    common.save_json(proj.library, lib)
    refs.verify_keys([e["id"]], cfg, force=False, quiet=True)
    assert calls == ["A different title typed by hand"]           # edited: verified again


def test_check_blocks_edited_and_retracted_citations(proj):
    import check
    e = add_verified_source(proj)
    errors, warnings = [], []
    lib = common.load_library()
    lib[e["id"]]["title"] = "edited by hand"
    check.citation_checks(f"Claim [@{e['id']}].", load_config(), 1, lib, common.load_verification(), errors, warnings)
    assert any("edited after it was verified" in x for x in errors)
    ver = common.load_verification()
    ver[e["id"]]["status"] = "retracted"
    errors = []
    check.citation_checks(f"Claim [@{e['id']}].", load_config(), 1, common.load_library(), ver, errors, warnings)
    assert any("RETRACTED" in x for x in errors)


def test_zotero_pull_uses_project_collection(proj, monkeypatch):
    cfg = load_config()
    cfg["zotero"] = {"collection": "My Thesis", "library_id": 1}
    seen = {}

    def fake_get(url, **kw):
        seen["url"] = url
        body = '[{"id": "doe2022x", "type": "article-journal", "title": "Café networks", "page": "10–20", ' \
               '"issued": {"date-parts": [["2022"]]}}]'
        # Zotero sends UTF-8 as text/plain without a charset (requests would guess Latin-1)
        return Resp(content=body.encode("utf-8"), headers={"content-type": "text/plain"})
    monkeypatch.setattr(refs.requests, "get", fake_get)
    assert refs.pull_zotero(cfg, quiet=True) == 1
    assert "/export/collection?/1/My%20Thesis.json" in seen["url"]
    item = common.load_json_list(proj.zotero_export)[0]
    assert item["issued"] == {"date-parts": [[2022]]}
    assert item["page"] == "10–20" and item["title"] == "Café networks"


def test_zotero_push_files_items_into_project_collection(proj, monkeypatch):
    cfg = load_config()
    cfg["zotero"] = {"collection": "alpha"}
    add_verified_source(proj)
    posts = []

    def fake_post(url, **kw):
        posts.append((url.rsplit("/", 1)[-1], kw))
        if url.endswith("getSelectedCollection"):
            return Resp(data={"id": None, "name": "My Library", "targets": [
                {"id": "L1", "name": "My Library"}, {"id": "C7", "name": "Alpha"}, {"id": "C8", "name": "beta"}]})
        return Resp(status=201 if "import" in url else 200)
    monkeypatch.setattr(refs.requests, "get", lambda url, **kw: Resp(status=200))
    monkeypatch.setattr(refs.requests, "post", fake_post)
    refs.cmd_sync_zotero(None, cfg)
    update = [kw for name, kw in posts if name == "updateSession"]
    assert update and update[0]["json"]["target"] == "C7"
    imported = [kw for name, kw in posts if name.startswith("import")]
    assert update[0]["json"]["sessionID"] == imported[0]["params"]["session"]
    assert "Citation Key: smith2021edge" in imported[0]["data"].decode()
    assert common.load_json_list(proj.zotero_sync) == ["smith2021edge"]


def test_zotero_push_refuses_missing_collection(proj, monkeypatch):
    cfg = load_config()
    cfg["zotero"] = {"collection": "alpha"}
    add_verified_source(proj)
    monkeypatch.setattr(refs.requests, "get", lambda url, **kw: Resp(status=200))
    monkeypatch.setattr(refs.requests, "post", lambda url, **kw: Resp(data={"targets": [{"id": "C1", "name": "Other"}]}))
    refs.cmd_sync_zotero(None, cfg)
    assert (proj.refs_dir / "zotero_import.json").exists()
    assert not proj.zotero_sync.exists() or common.load_json_list(proj.zotero_sync) == []
