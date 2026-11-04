"""Shared helpers for the dissertation workflow scripts.

Every dissertation is a *project* in projects/<slug>/ with its own configuration, chapters,
reference library and git history. Scripts work on the *active* project, chosen by (first match):
  1. --project <slug> on the command line (any script)
  2. the DISSERTATION_PROJECT environment variable
  3. projects/.active (set with: project.py use <slug>)
  4. the only project, if exactly one exists
"""
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
SHARED_CONFIG = ROOT / "config"
SHARED_TEMPLATES = SHARED_CONFIG / "templates"        # default templates shared by all projects
# projects live in ./projects unless DISSERTATION_PROJECTS_DIR points elsewhere (e.g. a synced folder)
PROJECTS = Path(os.environ.get("DISSERTATION_PROJECTS_DIR") or ROOT / "projects").resolve()
ACTIVE_FILE = PROJECTS / ".active"
TOOLS = ROOT / "tools"
PYTHON = Path(sys.executable)                          # the interpreter running the workflow (venv)
IS_WINDOWS = os.name == "nt"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")

# ---------------------------------------------------------------- number words (chapters 1-99)

_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_word(n: int) -> str:
    """1 -> 'one', 21 -> 'twenty-one' (1..99)."""
    if not 1 <= n <= 99:
        raise ValueError(f"chapter number must be between 1 and 99 (got {n})")
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    return _TENS[t] + (f"-{_ONES[o]}" if o else "")


NUMBER_WORDS = {n: number_word(n) for n in range(1, 100)}
WORD_NUMBERS = {v.replace("-", "_"): k for k, v in NUMBER_WORDS.items()}


def setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- projects

class Project:
    """All paths that belong to one dissertation."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.slug = self.root.name
        self.config_file = self.root / "project.yaml"
        self.guidelines = self.root / "guidelines"
        self.existing = self.root / "existing"
        self.feedback = self.root / "feedback"
        self.templates = self.root / "templates"
        self.output = self.root / "output"
        self.chapters = self.output / "chapters"
        self.appendices = self.output / "appendices"
        self.dissertation = self.output / "dissertation"
        self.refs_dir = self.root / "references"
        self.library = self.refs_dir / "references.json"          # verified sources (CSL JSON)
        self.zotero_export = self.refs_dir / "zotero.json"        # copy of this project's Zotero collection
        self.verification = self.refs_dir / "verification.json"
        self.zotero_sync = self.refs_dir / "zotero_sync.json"
        self.build = self.root / ".build"
        self.requirements = self.root / "requirements"            # generated from guidelines/
        self.manifest = self.requirements / "manifest.json"       # which guideline part belongs to which chapter
        self.mapping = self.requirements / "mapping.yaml"         # your manual corrections (kept across scans)
        self.spec = self.requirements / "spec.yaml"               # structured, sourced requirements

    def __repr__(self) -> str:
        return f"Project({self.slug!r})"

    def template(self, name: str) -> Path:
        """A per-project template overrides the shared default of the same name."""
        own = self.templates / name
        return own if own.exists() else SHARED_TEMPLATES / name

    def rel(self, p: Path) -> str:
        try:
            return Path(p).resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return str(p)


_selected: str | None = None


def list_projects() -> list[str]:
    if not PROJECTS.exists():
        return []
    return sorted(d.name for d in PROJECTS.iterdir()
                  if d.is_dir() and not d.name.startswith(".") and (d / "project.yaml").exists())


def select_project(slug: str | None) -> None:
    global _selected
    _selected = slug


def active_source() -> tuple[str | None, str]:
    """(slug, how it was chosen) for the active project."""
    if _selected:
        return _selected, "--project"
    if os.environ.get("DISSERTATION_PROJECT"):
        return os.environ["DISSERTATION_PROJECT"], "DISSERTATION_PROJECT"
    if ACTIVE_FILE.exists():
        s = ACTIVE_FILE.read_text(encoding="utf-8").strip()
        if s:
            return s, "active project"
    found = list_projects()
    return (found[0], "the only project") if len(found) == 1 else (None, "")


def active_slug() -> str | None:
    """The active project's slug, or None if none can be determined."""
    return active_source()[0]


_announced: str | None = None


def project_title(slug: str) -> str:
    try:
        cfg = yaml.safe_load((PROJECTS / slug / "project.yaml").read_text(encoding="utf-8")) or {}
        return str((cfg.get("project") or {}).get("title", ""))
    except (OSError, yaml.YAMLError):
        return ""


def announce(slug: str) -> None:
    """Say once per command which project it works on (stderr, so --json output stays clean)."""
    global _announced
    if _announced == slug or os.environ.get("DISSERTATION_QUIET") == "1":
        return
    _announced = slug
    _, how = active_source()
    title = project_title(slug)
    line = f"== Project: {slug}" + (f" - {title}" if title else "") + f"  [{how}] =="
    try:
        default = ACTIVE_FILE.read_text(encoding="utf-8").strip() if ACTIVE_FILE.exists() else ""
    except OSError:
        default = ""
    if default and default != slug:
        line += f"  (the active project is '{default}'; this command uses '{slug}')"
    print(line, file=sys.stderr, flush=True)


def legacy_layout() -> bool:
    """True when the old single-project layout (config/project.yaml at the root) is still in use."""
    return (SHARED_CONFIG / "project.yaml").exists()


def project(required: bool = True) -> Project | None:
    slug = active_slug()
    if not slug:
        if not required:
            return None
        if legacy_layout():
            die("this workflow now keeps each dissertation in projects/<name>/. Move your current one with:\n"
                "  python scripts/project.py migrate <name>")
        found = list_projects()
        if not found:
            die("no project yet. Create one with:  python scripts/project.py new <name> --title \"...\"")
        die(f"several projects exist ({', '.join(found)}); choose one with: python scripts/project.py use <name>"
            " (or pass --project <name>)")
    p = Project(PROJECTS / slug)
    if not p.config_file.exists():
        if not required:
            return None
        die(f"project '{slug}' not found (expected {p.config_file}). Known projects: "
            f"{', '.join(list_projects()) or 'none'}")
    announce(slug)
    return p


def init_cli(argv: list[str] | None = None) -> None:
    """Call first in every script: UTF-8 output and the --project option (removed from sys.argv)."""
    setup_stdout()
    argv = sys.argv if argv is None else argv
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--project" and i + 1 < len(argv):
            select_project(argv[i + 1])
            del argv[i:i + 2]
            continue
        if a.startswith("--project="):
            select_project(a.split("=", 1)[1])
            del argv[i]
            continue
        i += 1


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
    for k in ("CONTACT_EMAIL", "OPENALEX_API_KEY", "S2_API_KEY", "ZOTERO_PORT"):
        if os.environ.get(k):
            values[k] = os.environ[k]
    return values


def _int_keys(d):
    """YAML may give chapter numbers as ints or strings; normalise to int."""
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            out[k] = v
    return out


def load_config(require_project: bool = True) -> dict:
    """require_project=False lets setup tools (doctor, ensure_zotero) run before any project exists."""
    p = project(required=require_project)
    cfg = {}
    if p is not None:
        cfg = yaml.safe_load(p.config_file.read_text(encoding="utf-8")) or {}
    cfg["chapters"] = _int_keys(cfg.get("chapters"))
    env = load_env()
    cfg["local"] = {
        "contact_email": env.get("CONTACT_EMAIL", ""),
        "openalex_api_key": env.get("OPENALEX_API_KEY", ""),
        "s2_api_key": env.get("S2_API_KEY", ""),
        "zotero_port": env.get("ZOTERO_PORT", "23119"),
    }
    cfg["_project"] = p.slug if p else None
    return cfg


def contact_email(cfg: dict) -> str:
    return (cfg.get("local", {}).get("contact_email") or "").strip()


def user_agent(cfg: dict) -> str:
    email = contact_email(cfg)
    return f"dissertation-workflow/2.0 (mailto:{email})" if email else "dissertation-workflow/2.0"


# ---------------------------------------------------------------- chapters and appendices

def chapter_slug(n: int) -> str:
    return f"chapter_{number_word(n).replace('-', '_')}"


def chapter_dir(n: int) -> Path:
    return project().chapters / chapter_slug(n)


def chapter_file(n: int) -> Path:
    return chapter_dir(n) / "chapter.md"


def chapter_title(cfg: dict, n: int) -> str:
    return (cfg.get("chapters", {}).get(n) or {}).get("title", f"Chapter {n}")


def existing_chapters() -> list[int]:
    found = []
    for d in project().chapters.glob("chapter_*"):
        word = d.name.removeprefix("chapter_")
        if word in WORD_NUMBERS and (d / "chapter.md").exists():
            found.append(WORD_NUMBERS[word])
    return sorted(found)


def ensure_chapter_dirs(n: int) -> Path:
    d = chapter_dir(n)
    for sub in ("docs", "diagrams", "research", "research/fulltext", "data"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def appendix_letter(x: str) -> str:
    x = str(x).strip().upper()
    if not re.fullmatch(r"[A-Z]", x):
        raise ValueError(f"appendix id must be a single letter A-Z (got {x!r})")
    return x


def appendix_dir(letter: str) -> Path:
    return project().appendices / f"appendix_{appendix_letter(letter).lower()}"


def appendix_file(letter: str) -> Path:
    return appendix_dir(letter) / "appendix.md"


def existing_appendices() -> list[str]:
    root = project().appendices
    if not root.exists():
        return []
    return sorted(d.name.removeprefix("appendix_").upper() for d in root.glob("appendix_?")
                  if (d / "appendix.md").exists())


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


def _versions(docs_dir: Path, stem: str, ext: str) -> list[tuple[int, Path]]:
    if not docs_dir.exists():
        return []
    return [(int(m.group(1)), p) for p in docs_dir.glob(f"{stem}_v*{ext}")
            if (m := re.fullmatch(rf"{re.escape(stem)}_v(\d+){re.escape(ext)}", p.name))]


def next_version(docs_dir: Path, stem: str, ext: str = ".docx") -> Path:
    docs_dir.mkdir(parents=True, exist_ok=True)
    nums = [n for n, _ in _versions(docs_dir, stem, ext)]
    return docs_dir / f"{stem}_v{max(nums, default=0) + 1}{ext}"


def latest_version(docs_dir: Path, stem: str, ext: str = ".docx") -> Path | None:
    v = _versions(docs_dir, stem, ext)
    return max(v)[1] if v else None


def all_versions(docs_dir: Path, stem: str, ext: str = ".docx") -> list[Path]:
    return [p for _, p in sorted(_versions(docs_dir, stem, ext))]


# ---------------------------------------------------------------- tools

KNOWN_PATHS = {
    "drawio": [r"C:\Program Files\draw.io\draw.io.exe",
               os.path.expandvars(r"%LOCALAPPDATA%\Programs\draw.io\draw.io.exe"),
               "/Applications/draw.io.app/Contents/MacOS/draw.io"],
    "zotero": [r"C:\Program Files\Zotero\zotero.exe",
               os.path.expandvars(r"%LOCALAPPDATA%\Zotero\zotero.exe"),
               "/Applications/Zotero.app/Contents/MacOS/zotero", "/usr/bin/zotero", "/opt/zotero/zotero"],
    "soffice": [r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\LibreOffice\program\soffice.exe"),
                "/Applications/LibreOffice.app/Contents/MacOS/soffice"],
}


def find_tool(name: str) -> str | None:
    for cand in (TOOLS / f"{name}.exe", TOOLS / name,
                 ROOT / "node_modules" / ".bin" / f"{name}.cmd", ROOT / "node_modules" / ".bin" / name):
        if cand.exists() and (cand.suffix in (".exe", ".cmd") or os.access(cand, os.X_OK) or IS_WINDOWS):
            return str(cand)
    for p in KNOWN_PATHS.get(name, []):
        if Path(p).exists():
            return p
    return shutil.which(name)


def require_tool(name: str) -> str:
    path = find_tool(name)
    if not path:
        die(f"'{name}' not found. Run: python scripts/doctor.py")
    return path


# ---------------------------------------------------------------- zotero

def zotero_base(cfg: dict) -> str:
    return f"http://127.0.0.1:{cfg['local']['zotero_port']}"


def zotero_ready(cfg: dict) -> bool:
    base = zotero_base(cfg)
    try:
        if requests.get(f"{base}/connector/ping", timeout=3).status_code != 200:
            return False
        r = requests.post(f"{base}/better-bibtex/json-rpc", timeout=5,
                          json={"jsonrpc": "2.0", "method": "api.ready", "params": []})
        return r.status_code == 200 and "result" in r.json()
    except (requests.RequestException, ValueError):
        return False


def ensure_zotero(cfg: dict, wait: int = 120, quiet: bool = False) -> None:
    """Zotero (with Better BibTeX) must be open for commands that use it. Start it if needed, or stop."""
    if os.environ.get("DISSERTATION_SKIP_ZOTERO") == "1":     # tests / CI only
        return
    if zotero_ready(cfg):
        return
    exe = find_tool("zotero")
    if not exe:
        die("Zotero is not installed (https://www.zotero.org/download/). This command needs it running.")
    if not quiet:
        print("Zotero is not running - starting it ...", flush=True)
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
            if attempt == retries - 1:
                print(f"  ! {url}: HTTP {r.status_code} after {retries} attempts", file=sys.stderr)
                return r
            ra = r.headers.get("Retry-After", "")
            time.sleep(min(float(ra), 60) if ra.isdigit() else delay)
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
    """Write JSON atomically (a crash never leaves a half-written library)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_library(include_zotero: bool = True) -> dict[str, dict]:
    """All known references of the active project keyed by citekey. Pipeline entries win over Zotero ones."""
    p = project()
    lib: dict[str, dict] = {}
    if include_zotero:
        for e in load_json_list(p.zotero_export):
            if e.get("id"):
                lib[e["id"]] = {**e, "_source": "zotero"}
    for e in load_json_list(p.library):
        lib[e["id"]] = {**e, "_source": "pipeline"}
    return lib


def load_verification() -> dict:
    v = project().verification
    if not v.exists():
        return {}
    return json.loads(v.read_text(encoding="utf-8") or "{}")


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


def slugify(s: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", ascii_fold(s).lower()).strip("-")
    return (s[:maxlen].rstrip("-")) or "dissertation"


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
CROSSREF_PREFIXES = ("fig:", "tbl:", "sec:", "eq:", "lst:", "app:")
CODE_RE = re.compile(r"```.*?```|`[^`\n]+`", re.S)


def strip_code(text: str) -> str:
    return CODE_RE.sub(" ", text)


def find_citekeys(text: str) -> list[str]:
    keys = []
    for k in CITE_RE.findall(strip_code(text)):
        if not k.startswith(CROSSREF_PREFIXES):
            keys.append(k)
    return keys
