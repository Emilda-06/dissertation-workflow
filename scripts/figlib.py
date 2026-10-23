"""Chart helper for dissertation figures: house style plus automatic readability checks.

Every chart script in output/chapters/chapter_<n>/diagrams/*.py should use it:

    import sys, os; sys.path.insert(0, os.environ["WORKFLOW_SCRIPTS"])
    from figlib import new_figure, save, PALETTE

    fig, ax = new_figure()
    ax.bar(...); ax.set_xlabel("Scenario"); ax.set_ylabel("Latency (ms)")
    ax.legend(title="Model")
    save(fig, __file__)        # writes <name>.png; exits with an error if anything overlaps

Checks performed by save():
  * text overlapping other text (tick labels, axis labels, annotations, legend entries, titles)
  * a legend covering plotted data (lines, points, bars)
  * text cut off at the figure edge
  * more than one series/colour without a legend
"""
from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import PathCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.text import Text  # noqa: E402
from matplotlib.transforms import Bbox  # noqa: E402

STYLE = Path(__file__).resolve().parent.parent / "config" / "templates" / "thesis.mplstyle"
PALETTE = ["#1f3b57", "#c0504d", "#4f81bd", "#9bbb59", "#8064a2", "#f79646", "#4bacc6"]
TEXT_WIDTH_IN = 6.27          # A4 text width with 2.54 cm margins


def new_figure(nrows: int = 1, ncols: int = 1, width: float = TEXT_WIDTH_IN, height: float | None = None, **kw):
    plt.style.use(os.environ.get("MPLSTYLE", str(STYLE)))
    height = height or (3.9 if nrows == 1 else 2.9 * nrows)
    return plt.subplots(nrows, ncols, figsize=(width, height), layout="constrained", **kw)


def _visible_texts(fig) -> list[Text]:
    # matplotlib keeps tick labels just outside the view limits; they are never drawn
    hidden = set()
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            lo, hi = sorted(axis.get_view_interval())
            eps = (hi - lo) * 1e-6
            for tick in axis.get_major_ticks() + axis.get_minor_ticks():
                if not (lo - eps <= tick.get_loc() <= hi + eps):
                    hidden.update({id(tick.label1), id(tick.label2)})
    out = []
    for t in fig.findobj(Text):
        if id(t) in hidden:
            continue
        if t.get_visible() and t.get_text().strip() and t.get_alpha() != 0:
            out.append(t)
    return out


def _area(b: Bbox) -> float:
    return max(0.0, b.width) * max(0.0, b.height)


def check(fig) -> list[str]:
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    problems: list[str] = []
    fb = fig.bbox
    texts = [(t, t.get_window_extent(r)) for t in _visible_texts(fig)]

    for (a, ba), (b, bb) in itertools.combinations(texts, 2):
        inter = Bbox.intersection(ba, bb)
        if inter is not None and _area(inter) > 6:
            problems.append(f"text '{a.get_text()[:40]}' overlaps text '{b.get_text()[:40]}'")
    for t, bt in texts:
        if bt.x0 < fb.x0 - 1 or bt.y0 < fb.y0 - 1 or bt.x1 > fb.x1 + 1 or bt.y1 > fb.y1 + 1:
            problems.append(f"text '{t.get_text()[:40]}' is cut off at the figure edge")

    for ax in fig.axes:
        leg = ax.get_legend()
        series = [l for l in ax.get_lines() if not l.get_label().startswith("_")]
        series += [c for c in ax.collections if not str(c.get_label()).startswith("_")]
        if leg is None and len(series) > 1:
            problems.append("several series/colours but no legend: add ax.legend() so every colour is explained")
        if leg is None:
            continue
        lb = leg.get_window_extent(r)
        for line in ax.get_lines():
            if not line.get_visible():
                continue
            pts = line.get_transform().transform(line.get_xydata())
            if any(lb.contains(x, y) for x, y in pts):
                problems.append(f"legend covers data line '{line.get_label()}': move it (loc='best', or outside with bbox_to_anchor)")
                break
        for coll in ax.collections:
            if isinstance(coll, PathCollection):
                pts = coll.get_offset_transform().transform(coll.get_offsets())
                if any(lb.contains(x, y) for x, y in pts):
                    problems.append("legend covers scatter points: move it")
                    break
        for p in ax.patches:
            if isinstance(p, Rectangle) and p.get_height() != 0:
                inter = Bbox.intersection(lb, p.get_window_extent(r))
                if inter is not None and _area(inter) > 6:
                    problems.append("legend covers bars: move it above/outside the plot or raise the y-limit")
                    break
    return sorted(set(problems))


def save(fig, script_file: str, strict: bool = True) -> Path:
    out = Path(script_file).with_suffix(".png")
    problems = check(fig)
    fig.savefig(out, dpi=300)
    for p in problems:
        print(f"OVERLAP/READABILITY: {p}")
    if problems and strict:
        sys.exit(3)
    return out
