"""Shared helpers for the dissertation workflow scripts."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
TEMPLATES = CONFIG / "templates"
REFS_DIR = ROOT / "references"
LIBRARY = REFS_DIR / "references.json"          # pipeline-managed, verified sources (CSL JSON)
ZOTERO_EXPORT = REFS_DIR / "zotero.json"        # Better BibTeX auto-export (optional)
VERIFICATION = REFS_DIR / "verification.json"
TOOLS = ROOT / "tools"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
OUTPUT = ROOT / "output"
CHAPTERS = OUTPUT / "chapters"                  # output/chapters/chapter_one/ ...
DISSERTATION = OUTPUT / "dissertation"          # combined document, front matter

NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
}
WORD_NUMBERS = {v: k for k, v in NUMBER_WORDS.items()}


def setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- config

ENV_FILE = ROOT / ".env"


def load_env() -> dict[str, str]:
    """Read KEY=value lines from .env (API keys and private settings). Real environment variables win."""
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.split(" #", 1)[0].strip().strip('"').strip("'")
    for k in list(values):
        if os.environ.get(k):
            values[k] = os.environ[k]
    return values


def load_config() -> dict:
    project = CONFIG / "project.yaml"
    if not project.exists():
        die("config/project.yaml not found - copy config/project.example.yaml to config/project.yaml and fill it in")
    cfg = yaml.safe_load(project.read_text(encoding="utf-8")) or {}
    env = load_env()
    cfg["local"] = {
        "contact_email": env.get("CONTACT_EMAIL", ""),
        "openalex_api_key": env.get("OPENALEX_API_KEY", ""),
        "zotero_port": env.get("ZOTERO_PORT", "23119"),
    }
    return cfg


def contact_email(cfg: dict) -> str:
    return (cfg.get("local", {}).get("contact_email") or "").strip()


def user_agent(cfg: dict) -> str:
    email = contact_email(cfg)
    return f"dissertation-workflow/1.0 (mailto:{email})" if email else "dissertation-workflow/1.0"


# ---------------------------------------------------------------- chapters

def chapter_slug(n: int) -> str:
    return f"chapter_{NUMBER_WORDS[n]}"


def chapter_dir(n: int) -> Path:
    return CHAPTERS / chapter_slug(n)


def chapter_file(n: int) -> Path:
    return chapter_dir(n) / "chapter.md"


def chapter_title(cfg: dict, n: int) -> str:
    return (cfg.get("chapters", {}).get(n) or {}).get("title", f"Chapter {n}")


def existing_chapters() -> list[int]:
    found = []
    for d in CHAPTERS.glob("chapter_*"):
        word = d.name.removeprefix("chapter_")
        if word in WORD_NUMBERS and (d / "chapter.md").exists():
            found.append(WORD_NUMBERS[word])
    return sorted(found)


def ensure_chapter_dirs(n: int) -> Path:
    d = chapter_dir(n)
    for sub in ("docs", "diagrams", "research", "research/fulltext", "data"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def read_front_matter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = FRONT_RE.match(text)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, text[m.end():]


def write_front_matter(path: Path, meta: dict, body: str) -> None:
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{head}\n---\n\n{body.lstrip()}", encoding="utf-8")


def next_version(docs_dir: Path, stem: str, ext: str = ".docx") -> Path:
    docs_dir.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for p in docs_dir.glob(f"{stem}_v*{ext}")
            if (m := re.fullmatch(rf"{re.escape(stem)}_v(\d+){re.escape(ext)}", p.name))]
    return docs_dir / f"{stem}_v{max(nums, default=0) + 1}{ext}"


def latest_version(docs_dir: Path, stem: str, ext: str = ".docx") -> Path | None:
    nums = [(int(m.group(1)), p) for p in docs_dir.glob(f"{stem}_v*{ext}")
            if (m := re.fullmatch(rf"{re.escape(stem)}_v(\d+){re.escape(ext)}", p.name))]
    return max(nums)[1] if nums else None


# ---------------------------------------------------------------- tools

KNOWN_PATHS = {
    "drawio": [r"C:\Program Files\draw.io\draw.io.exe",
               os.path.expandvars(r"%LOCALAPPDATA%\Programs\draw.io\draw.io.exe")],
    "zotero": [r"C:\Program Files\Zotero\zotero.exe",
               os.path.expandvars(r"%LOCALAPPDATA%\Zotero\zotero.exe")],
}


def find_tool(name: str) -> str | None:
    for cand in (TOOLS / f"{name}.exe", TOOLS / name,
                 ROOT / "node_modules" / ".bin" / f"{name}.cmd"):
        if cand.exists():
            return str(cand)
    for p in KNOWN_PATHS.get(name, []):
        if Path(p).exists():
            return p
    return shutil.which(name)


def require_tool(name: str) -> str:
    path = find_tool(name)
    if not path:
        die(f"'{name}' not found. Run: .venv/Scripts/python.exe scripts/doctor.py")
    return path


# ---------------------------------------------------------------- zotero (must be running)

def zotero_ready(cfg: dict) -> bool:
    base = f"http://127.0.0.1:{cfg['local']['zotero_port']}"
    try:
        if requests.get(f"{base}/connector/ping", timeout=3).status_code != 200:
            return False
        r = requests.post(f"{base}/better-bibtex/json-rpc", timeout=5,
                          json={"jsonrpc": "2.0", "method": "api.ready", "params": []})
        return r.status_code == 200 and "result" in r.json()
    except (requests.RequestException, ValueError):
        return False


def ensure_zotero(cfg: dict, wait: int = 120, quiet: bool = False) -> None:
    """Workflow rule: Zotero (with Better BibTeX) must be open. Start it if needed, or stop with an error."""
    if zotero_ready(cfg):
        return
    exe = find_tool("zotero")
    if not exe:
        die("Zotero is not installed (winget install DigitalScholar.Zotero). The workflow needs it running.")
    if not quiet:
        print("Zotero is not running - starting it (the workflow requires Zotero to be open) ...", flush=True)
    import subprocess
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([exe], creationflags=flags, close_fds=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(3)
        if zotero_ready(cfg):
            if not quiet:
                print("Zotero is ready.", flush=True)
            return
    die("Zotero did not become ready within 2 minutes. Open Zotero manually (and check Better BibTeX "
        "is enabled under Tools > Plugins), then run the command again.")


# ---------------------------------------------------------------- http

def http_get(url: str, cfg: dict, params: dict | None = None, headers: dict | None = None,
             retries: int = 4, timeout: int = 30, accept_404: bool = True) -> requests.Response | None:
    h = {"User-Agent": user_agent(cfg)}
    h.update(headers or {})
    delay = 2.0
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout, allow_redirects=True)
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f"  ! request failed: {url}: {e}", file=sys.stderr)
                return None
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 404 and accept_404:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            wait = float(r.headers.get("Retry-After", delay)) if r.headers.get("Retry-After", "").isdigit() else delay
            time.sleep(wait)
            delay *= 2
            continue
        return r
    return None


# ---------------------------------------------------------------- references

def load_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8") or "[]")
    return data if isinstance(data, list) else []


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_library(include_zotero: bool = True) -> dict[str, dict]:
    """All known references keyed by citekey. Pipeline entries win over Zotero ones."""
    lib: dict[str, dict] = {}
    if include_zotero:
        for e in load_json_list(ZOTERO_EXPORT):
            if e.get("id"):
                lib[e["id"]] = {**e, "_source": "zotero"}
    for e in load_json_list(LIBRARY):
        lib[e["id"]] = {**e, "_source": "pipeline"}
    return lib


def load_verification() -> dict:
    if not VERIFICATION.exists():
        return {}
    return json.loads(VERIFICATION.read_text(encoding="utf-8") or "{}")


def entry_year(e: dict) -> int | None:
    for field in ("issued", "published-print", "published-online", "created"):
        parts = (e.get(field) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                pass
    return None


def entry_title(e: dict) -> str:
    t = e.get("title") or ""
    return t[0] if isinstance(t, list) else t


def first_author_family(e: dict) -> str:
    authors = e.get("author") or e.get("editor") or []
    if not authors:
        return ""
    a = authors[0]
    return a.get("family") or a.get("literal") or ""


def ascii_fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def normalize_title(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", ascii_fold(s).lower())).strip()


def _realign_grid(block: list[str]) -> list[str]:
    border = block[0].strip()
    ncols = border.count("+") - 1
    rows = []
    for line in block:
        s = line.strip()
        if s.startswith("+"):
            rows.append(("border", "=" if "=" in s else "-"))
        elif s.startswith("|") and s.endswith("|"):
            cells = s[1:-1].split("|")
            if len(cells) != ncols:
                return block                      # merged cells or a '|' inside text: leave untouched
            rows.append(("cells", [(c[1:] if c.startswith(" ") else c).rstrip() for c in cells]))
        else:
            return block
    widths = [3] * ncols
    for kind, val in rows:
        if kind == "cells":
            widths = [max(w, len(c) + 2) for w, c in zip(widths, val)]
    out = []
    for kind, val in rows:
        if kind == "border":
            out.append("+" + "+".join(val * w for w in widths) + "+")
        else:
            out.append("|" + "|".join(" " + c.ljust(w - 2) + " " for c, w in zip(val, widths)) + "|")
    return out


def realign_grid_tables(text: str) -> str:
    """Re-pad grid tables so edited cells (e.g. converted citations) never break the table."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if re.match(r"^\s*\+[-=:+]+\+\s*$", lines[i]):
            j = i
            while j < len(lines) and lines[j].strip().startswith(("+", "|")):
                j += 1
            out += _realign_grid(lines[i:j])
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


CITE_RE = re.compile(r"(?<![\w@.])@([A-Za-z0-9_][\w:.#$%&\-+?<>~/]*[A-Za-z0-9_])")
CROSSREF_PREFIXES = ("fig:", "tbl:", "sec:", "eq:", "lst:")


def find_citekeys(text: str) -> list[str]:
    keys = []
    for k in CITE_RE.findall(text):
        if not k.startswith(CROSSREF_PREFIXES):
            keys.append(k)
    return keys
