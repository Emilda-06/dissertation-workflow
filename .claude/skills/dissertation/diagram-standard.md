# Diagram standard

Every figure in the dissertation must meet this standard. It has three parts:
**A. picking the right diagram, B. drawing it so it is clear, C. connecting it to the text.**
`scripts/diagrams.py` and `scripts/check.py` enforce the measurable rules and block the build on
failure. The rest you check by **looking at every rendered PNG** with the Read tool.

Files: sources and PNGs go in `output/chapters/chapter_<word>/diagrams/`, named after the label
(`use-case.drawio` -> `use-case.png` -> `{#fig:use-case}`). Render with
`.venv/Scripts/python.exe scripts/diagrams.py <n>`.

---

## A. Catalogue: which diagram, which tool

### Process and analysis diagrams
| Diagram | Use it to show | Tool | Notation essentials |
|---|---|---|---|
| Flowchart | an algorithm or decision procedure | Mermaid `flowchart TB` | oval start/end `([Start])`, rectangle process, diamond decision `{Valid?}` with labelled Yes/No exits |
| Data Flow Diagram (DFD), level 0 context | the system as one process and its external entities | draw.io | Gane–Sarson: rounded rectangle process "0 System name", rectangle entity, labelled data-flow arrows |
| DFD level 1 / 2 | the main processes inside the system | draw.io | numbered processes 1.0, 2.0...; data stores as open-ended rectangles "D1 Readings"; every flow labelled with a noun (data, not actions); flows balanced with the parent level |
| Entity Relationship Diagram (ERD) | the database design | Mermaid `erDiagram` | entities with attributes and PK/FK, crow's-foot cardinalities `||--o{` |
| User stories | requirements from the user's view | **Table** (not a picture) | `As a <role>, I want <goal>, so that <benefit>` plus acceptance criteria, ID US-01... and priority (MoSCoW) |
| User journey / story map | the steps a user goes through and how satisfied they are | Mermaid `journey` | sections = stages, tasks scored 1–5, actors named |
| Requirements diagram | how requirements trace to components and tests | Mermaid `requirementDiagram` | |
| Mind map | a concept breakdown or literature themes | Mermaid `mindmap` | |
| Gantt chart | the project plan | **figlib chart (`.py`)** with `barh` bars and diamond milestones (Mermaid's Gantt text is too small in print) | phases on the y-axis, weeks on the x-axis, milestones labelled |
| Timeline | the history of a field | Mermaid `timeline` | |

### UML (department guidelines: chapters 2 and 3)
| Diagram | Tool | Notation essentials |
|---|---|---|
| Use case (**mandatory**, chapter 2) | draw.io | stick-figure actors outside a system boundary rectangle labelled with the system name; use cases as ellipses with verb phrases; `«include»` / `«extend»` as dashed open arrows |
| Activity | Mermaid `flowchart TB` | filled start node, rounded actions, diamond decisions with guards `[valid]`, fork/join bars, swimlanes as `subgraph` per actor |
| Class | Mermaid `classDiagram` | `+public -private` attributes with types, operations with parameters, associations with multiplicities `"1" --> "0..*"`, inheritance, composition |
| Object | draw.io | boxes titled `name : Class` **underlined** (`fontStyle=4`), attribute values `id = 42`, plain links |
| Sequence | Mermaid `sequenceDiagram` | participants `p as p1: Class`, activation bars (`activate`), self-calls, `alt`/`opt`/`loop` frames with guards, return messages dashed |
| Communication | draw.io | objects joined by links; messages numbered `1: request()`, `1.1: verify()` with small arrows along the link |
| State machine | Mermaid `stateDiagram-v2` | `[*]` start and end, states named as conditions ("Quarantined"), transitions `event [guard] / action` |
| Component / package | Mermaid `flowchart` with subgraphs | provided/required interfaces named on links |
| Deployment | draw.io | nodes as 3D boxes (`shape=cube`) for devices (ESP32, Raspberry Pi, cloud VM), artefacts inside, links labelled with protocol (MQTT/TLS, HTTPS) |
| Process design (pre/postconditions) | **Text block or table** | `Context`, `Pre:`, `Post:` as in the chapter 3 guideline |

### Architecture and network
| Diagram | Tool | Notation essentials |
|---|---|---|
| System / conceptual architecture | draw.io (complex) or Mermaid (simple) | tiers or layers as labelled containers; hardware, software, protocols and transmission media (wired / Wi-Fi) labelled on links (guideline 2.5.2) |
| Network topology (logical / physical) | draw.io | hierarchical core / distribution / access layers, VLAN IDs and subnets (VLSM) on segments, device names and models |
| Threat model / attack tree / attack flow | draw.io or Mermaid | the attacker as an external entity, trust boundaries as dashed red containers, numbered attack steps |
| ML pipeline / data pipeline | Mermaid `flowchart LR` | stages as processes, datasets as stores `[(Dataset)]`, model artefacts labelled |

### Charts (non-technical / results)
| Chart | Use it for | Tool |
|---|---|---|
| Bar / grouped bar | comparing categories (protected vs unprotected model) | matplotlib/seaborn via figlib |
| Stacked bar | composition across categories | figlib |
| Line | change over time or across a parameter (accuracy vs poisoning rate) | figlib |
| Box / violin | distributions across repeated runs (latency per scenario) | figlib |
| Histogram / KDE | the distribution of one variable | figlib |
| Scatter | the relationship between two variables | figlib |
| Heatmap / confusion matrix | classification results, correlations | figlib (`sns.heatmap`, annotated cells) |
| ROC / precision–recall curve | detector performance | figlib |
| Pie | **avoid**; use a bar chart. Allowed only for at most 4 parts of one whole | figlib |

If a diagram type isn't listed here, use draw.io and follow the same rules.

---

## B. Drawing rules: clear and readable

### B1. One message per figure
- Each figure answers one question. If you need two sentences to say what it shows, split it.
- At most about 15 nodes or shapes per diagram, and at most 6 series per chart.

### B2. Text must be readable when printed
- **Minimum printed text size: 8 pt.** `diagrams.py` measures this at the width given in
  chapter.md and fails the figure if it is smaller. When it fails: use a top-to-bottom layout
  instead of left-to-right, shorten labels, split the diagram, or use a larger `width=` (90–100%).
- Short labels: 2–5 words in boxes, 1–3 words on arrows. Explanations go in the text, never in
  the boxes.
- All diagram text in Times New Roman (set by the templates). No text smaller than the axis ticks.

### B3. Nothing on top of anything
- **No text or shape may overlap another shape, label or line.** This is checked automatically:
  - charts: `figlib.save()` rejects overlapping labels, legends covering data, and clipped text;
  - draw.io: `diagrams.py` rejects shapes overlapping other shapes. Zones, layers and boundaries
    must be real containers (`container=1;` plus children with `parent="<container id>"`) or have
    `verticalAlign=top;` so their label sits above the children;
  - Mermaid: no automatic check, so look at the PNG. Edge labels crossing nodes or other labels
    must be fixed: change the direction (`LR` / `TB`), reorder node declarations, put long
    labels on nodes instead of edges, or split the diagram.
- Arrows must not pass through boxes. Reduce crossings by grouping related nodes.

### B4. Titles and legends
- **The numbered Word caption is the figure's title** ("Figure 3.2: ..."). Do not repeat a title
  inside the image. Exception: multi-panel charts may label panels "(a)", "(b)" and use those in
  the caption.
- **Legends are required whenever colour, line style, shape or icon carries meaning**:
  - charts: `ax.legend(title=...)`, placed where it covers no data (`loc="best"`, or outside the
    plot with `bbox_to_anchor`). figlib fails a chart with several series and no legend;
  - draw.io / Mermaid: if you use more than one fill colour, border style or arrow style with a
    meaning (e.g. red dashed = attack path, grey = external system), add a small "Legend" box
    (draw.io) or `subgraph Legend` (Mermaid) in a corner that doesn't overlap anything.
- Axes: every axis has a label **with units** ("Latency (ms)", "Detection rate (%)"). Ticks are
  readable and not crowded; rotate long category names 30–45° or use a horizontal bar chart.

### B5. Consistent visual language (house style)
| Element | Style |
|---|---|
| Lines and borders | navy `#1f3b57`, 1–1.5 px |
| Fill: normal components | white `#ffffff` |
| Fill: groups, zones, layers | very light grey-blue `#f4f7fa` with grey border `#7a8a99` |
| Fill: external systems / actors | light grey `#eeeeee` |
| Highlight: attack, threat, failure | red `#c0504d` (use sparingly, always explained in a legend) |
| Highlight: the proposed or new component | blue `#4f81bd` border or light-blue fill `#dce6f1` |
| Chart series | figlib `PALETTE` in order; same colour = same thing in every chart of the dissertation |
| Font | Times New Roman |

- The same component has **exactly the same name** in every diagram and in the text.
- Never use colour alone to carry meaning. Also use labels, line style or position, so the figure
  works in greyscale print.

### B6. Data integrity (charts)
- Results charts read **only real data** from `output/chapters/chapter_<n>/data/`. Never invent values.
- Bar charts start at zero. Show error bars (SD) or distributions for repeated runs, and say what
  the bars mean in the caption.
- Put exact values in a table next to the chart when the numbers matter to the argument.

### B7. Tool recipes

**Mermaid** (`.mmd`). The style comes from `config/templates/mermaid.json`.
```
flowchart TB
  subgraph Edge["Edge tier (Raspberry Pi 4)"]
    L1["Layer 1: spoof detection"] --> L2["Layer 2: gatekeeper"]
  end
  S["ESP32 light sensors"] -->|MQTT readings| L1
  L2 -->|clean data| C[("Cloud training store")]
  L2 -.->|rejected| Q["Quarantine"]
```

**draw.io** (`.drawio`). Write uncompressed XML: `<mxfile><diagram name="..."><mxGraphModel><root>`
with `<mxCell id="0"/><mxCell id="1" parent="0"/>`, then shapes. Lay shapes out on a 10 px grid
with at least 30 px gaps. Style snippets:
- actor: `shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;fontFamily=Times New Roman;fontSize=12;`
- use case: `ellipse;whiteSpace=wrap;html=1;fontFamily=Times New Roman;fontSize=12;strokeColor=#1f3b57;`
- system boundary or zone (container): `rounded=0;whiteSpace=wrap;html=1;container=1;verticalAlign=top;fontStyle=1;fillColor=#f4f7fa;strokeColor=#7a8a99;fontFamily=Times New Roman;fontSize=12;`
- DFD process: `rounded=1;whiteSpace=wrap;html=1;fontFamily=Times New Roman;fontSize=12;strokeColor=#1f3b57;`
- DFD data store: `shape=partialRectangle;right=0;html=1;whiteSpace=wrap;fontFamily=Times New Roman;fontSize=12;`
- external entity: `rounded=0;whiteSpace=wrap;html=1;fillColor=#eeeeee;fontFamily=Times New Roman;fontSize=12;`
- device or node (deployment): `shape=cube;whiteSpace=wrap;html=1;boundedLbl=1;fontFamily=Times New Roman;fontSize=12;`
- include / extend: `endArrow=open;dashed=1;html=1;fontFamily=Times New Roman;fontSize=11;` with value `«include»` / `«extend»`
  (always use guillemets « » for stereotypes; `<<...>>` is read as HTML and disappears)
- edge label: put it in the edge's `value`. Never place a free text box on top of a line.
For complex layouts, generate the `.drawio` XML from a helper script named `_make_<name>.py` (files starting with `_`
are skipped by the renderer) so coordinates are exact. The user may open `.drawio` files in draw.io desktop to adjust them. If a file looks hand-edited, keep its layout.

**Charts** (`.py`). Always use figlib:
```python
import os, sys
sys.path.insert(0, os.environ["WORKFLOW_SCRIPTS"])
from pathlib import Path
import pandas as pd
import seaborn as sns
from figlib import new_figure, save, PALETTE

here = Path(__file__).parent
df = pd.read_csv(here.parent / "data" / "detection_results.csv")    # real data only
fig, ax = new_figure()
sns.barplot(data=df, x="attack", y="detection_rate", hue="model", palette=PALETTE[:2],
            errorbar="sd", ax=ax)
ax.set_xlabel("Attack type"); ax.set_ylabel("Detection rate (%)"); ax.set_ylim(0, 100)
ax.legend(title="Model", loc="upper left", bbox_to_anchor=(1.01, 1))
save(fig, __file__)
```

---

## C. Connecting figures to the text (no disconnect)

`check.py` blocks the build unless every figure has all of these:

1. **Introduction before the figure.** A sentence in the paragraph just before it refers to it by
   label and says why the reader is looking at it: "The data flow between the three layers is
   shown in @fig:dfd-level1."
2. **The figure itself**, placed straight after that paragraph, never two figures in a row and
   never directly before a heading.
3. **An explanation after the figure** (at least 40 words in paragraphs citing `@fig:id`) that:
   - walks the reader through it in reading order ("Readings enter at the ESP32 nodes on the left...");
   - names the key elements exactly as labelled in the figure;
   - explains every legend item, colour or line style, and any notation (e.g. `<<include>>`, multiplicities);
   - states the takeaway and links it to the argument, requirement or research objective it supports;
   - for charts, quotes the important values and compares them ("Layer 2 kept detection at 94%
     while the unprotected model fell to 41%").
4. **A descriptive caption**: one sentence saying what the figure shows and, where useful, the
   key takeaway, at least 6 words. Add `Source: Adapted from @key.` when it is based on someone
   else's figure. "Figure 2.1: Use case diagram" is not acceptable; write "Figure 2.1: Use case
   diagram showing how the operator, attacker and edge gateway interact with the framework".
5. **Consistency.** The names in the figure, its caption and the text are identical. The figure
   agrees with the requirements, tables and other diagrams (a use case in the diagram must exist
   as a functional requirement, and so on).

### Final visual review (mandatory, after every render)
Open each PNG with the Read tool and confirm:
- [ ] All text is readable, with nothing overlapping, clipped or crossing a line.
- [ ] The notation is correct for the diagram type (section A).
- [ ] A legend is present if colours or styles carry meaning, and it covers nothing.
- [ ] Names match the text and other figures.
- [ ] The figure answers one clear question, and the caption says what that is.
Fix and re-render until every box is ticked. Mention in the report any figure you could not
make fully clear.
