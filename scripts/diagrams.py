"""Render a chapter's diagram sources to high-resolution PNG and check they are readable.

Sources live in output/chapters/chapter_<n>/diagrams/ and produce a PNG with the same name:
  *.mmd     Mermaid (flowcharts, UML sequence/class/state, ER, user journey, Gantt, mind map ...) -> mermaid-cli
  *.drawio  draw.io (use case, DFD, object/communication, network, detailed architecture)       -> draw.io CLI
  *.py      matplotlib / seaborn charts using scripts/figlib.py (bar, line, box, scatter, heatmap ...)
  _*.py     helper scripts (e.g. generators for .drawio files) - skipped

Checks (see .claude/skills/dissertation/diagram-standard.md):
  * charts: overlapping text, legend over data, clipped text, missing legend   (figlib.save)
  * draw.io: shapes whose labels sit on top of other shapes
  * all: text size as printed at the width used in chapter.md (minimum 8 pt), figure not taller than a page

Usage:
  diagrams.py <chapter-number> [--force] [--only name]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from PIL import Image

from common import PYTHON, ROOT, TEMPLATES, chapter_dir, chapter_file, require_tool, setup_stdout

TEXT_WIDTH_PT = (21.0 - 2 * 2.54) / 2.54 * 72      # 451 pt
MAX_HEIGHT_PT = 600                                  # leaves room for caption on an A4 page
MIN_FONT_PT = 8.0
SCALE = 3


def stale(src, out, force):
    return force or not out.exists() or out.stat().st_mtime < src.stat().st_mtime


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    msg = (r.stdout + r.stderr).strip()
    if r.returncode != 0 and msg:
        print("   " + msg[-2500:].replace("\n", "\n   "))
    return r.returncode == 0


# ---------------------------------------------------------------- draw.io geometry check

def drawio_problems(path) -> tuple[list[str], float]:
    """Return (overlap problems, smallest font size in px)."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        return [f"invalid draw.io XML: {e}"], 12.0
    cells = {c.get("id"): c for c in root.iter("mxCell")}
    rects, fonts = {}, []

    def absolute(cid):
        c = cells.get(cid)
        g = c.find("mxGeometry") if c is not None else None
        if g is None or c.get("vertex") != "1":
            return 0.0, 0.0
        px, py = absolute(c.get("parent"))
        return px + float(g.get("x", 0)), py + float(g.get("y", 0))

    for cid, c in cells.items():
        style = c.get("style") or ""
        if m := re.search(r"fontSize=(\d+(?:\.\d+)?)", style):
            fonts.append(float(m.group(1)))
        elif (c.get("value") or "").strip():
            fonts.append(12.0)
        if c.get("vertex") != "1":
            continue
        g = c.find("mxGeometry")
        if g is None:
            continue
        x, y = absolute(cid)
        w, h = float(g.get("width", 0)), float(g.get("height", 0))
        container = any(k in style for k in ("container=1", "swimlane", "group", "verticalAlign=top", "shape=umlFrame"))
        rects[cid] = (x, y, x + w, y + h, bool((c.get("value") or "").strip()), container, c.get("parent"))

    def ancestors(cid):
        out, p = set(), cells.get(cid).get("parent") if cells.get(cid) is not None else None
        while p in cells:
            out.add(p)
            p = cells[p].get("parent")
        return out

    problems = []
    ids = list(rects)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ax0, ay0, ax1, ay1, alab, acont, _ = rects[a]
            bx0, by0, bx1, by1, blab, bcont, _ = rects[b]
            if not (alab or blab):
                continue
            ix, iy = min(ax1, bx1) - max(ax0, bx0), min(ay1, by1) - max(ay0, by0)
            if ix <= 1 or iy <= 1:
                continue
            if a in ancestors(b) or b in ancestors(a):
                continue
            a_in_b = ax0 >= bx0 and ay0 >= by0 and ax1 <= bx1 and ay1 <= by1
            b_in_a = bx0 >= ax0 and by0 >= ay0 and bx1 <= ax1 and by1 <= ay1
            if (a_in_b and bcont) or (b_in_a and acont):
                continue
            la = (cells[a].get("value") or a)[:30]
            lb = (cells[b].get("value") or b)[:30]
            problems.append(f"shape '{re.sub('<[^>]+>', '', la)}' overlaps '{re.sub('<[^>]+>', '', lb)}' "
                            "(move apart, or make the outer one a container with container=1)")
    return problems, (min(fonts) if fonts else 12.0)


# ---------------------------------------------------------------- printed size check

def placed_width_pt(n: int, png_name: str) -> float:
    text = chapter_file(n).read_text(encoding="utf-8") if chapter_file(n).exists() else ""
    m = re.search(rf"\]\(diagrams/{re.escape(png_name)}\)\{{[^}}]*width=(\d+)%", text)
    return TEXT_WIDTH_PT * (int(m.group(1)) / 100 if m else 1.0)


def size_problems(n: int, out, font_px_at_scale: float) -> list[str]:
    with Image.open(out) as im:
        w, h = im.size
    placed = placed_width_pt(n, out.name)
    eff = font_px_at_scale * placed / w
    problems = []
    if eff < MIN_FONT_PT:
        problems.append(f"text prints at about {eff:.1f} pt (minimum {MIN_FONT_PT:g} pt): the diagram is too wide/dense. "
                        "Use top-to-bottom layout, shorten labels, split into two figures, or increase width=..%")
    if placed * h / w > MAX_HEIGHT_PT:
        problems.append(f"figure would be {placed * h / w / 72 * 2.54:.0f} cm tall - more than a page; reduce width=..% or split it")
    return problems


# ---------------------------------------------------------------- render

def render(n, src, force):
    out = src.with_suffix(".png")
    if not stale(src, out, force):
        return None
    problems: list[str] = []
    if src.suffix == ".mmd":
        ok = run([require_tool("mmdc"), "-i", str(src), "-o", str(out), "-s", str(SCALE), "-b", "white",
                  "-c", str(TEMPLATES / "mermaid.json"), "-p", str(TEMPLATES / "puppeteer.json")])
        font_px = float(json.loads((TEMPLATES / "mermaid.json").read_text())["themeVariables"]["fontSize"].rstrip("px"))
        font_scaled = font_px * SCALE
    elif src.suffix == ".drawio":
        problems, min_font = drawio_problems(src)
        ok = run([require_tool("drawio"), "--export", "--format", "png", "--scale", str(SCALE), "--border", "10",
                  "--output", str(out), str(src)])
        font_scaled = min_font * SCALE
    elif src.suffix == ".py":
        env = {**os.environ, "MPLSTYLE": str(TEMPLATES / "thesis.mplstyle"), "MPLBACKEND": "Agg",
               "WORKFLOW_SCRIPTS": str(ROOT / "scripts")}
        ok = run([str(PYTHON), src.name], cwd=src.parent, env=env)
        font_scaled = 10 / 72 * 300          # smallest chart text (ticks) 10 pt at 300 dpi
    else:
        return None
    ok = ok and out.exists()
    if ok:
        problems += size_problems(n, out, font_scaled)
    status = "ok    " if ok and not problems else "FAILED"
    print(f"{status} {src.name} -> {out.name}")
    for p in problems:
        print(f"   - {p}")
    return ok and not problems


def main():
    setup_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("chapter", type=int)
    p.add_argument("--force", action="store_true")
    p.add_argument("--only")
    args = p.parse_args()
    d = chapter_dir(args.chapter) / "diagrams"
    srcs = sorted(x for ext in ("*.mmd", "*.drawio", "*.py") for x in d.glob(ext) if not x.name.startswith("_"))
    if args.only:
        srcs = [s for s in srcs if s.stem == args.only or s.name == args.only]
    results = [render(args.chapter, s, args.force) for s in srcs]
    done = [r for r in results if r is not None]
    if not done:
        print("all diagrams up to date (use --force to re-render and re-check)")
    if any(r is False for r in done):
        print("\nFix the problems above, re-render, then LOOK at each PNG before continuing.")
        sys.exit(2)


if __name__ == "__main__":
    main()
