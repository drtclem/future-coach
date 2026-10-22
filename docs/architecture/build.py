"""Build the architecture docs: `python3 docs/architecture/build.py`.

1. Draws the diagrams as SVG files (brand colors baked in as CSS-variable
   fallbacks, so they read on GitLab and pick up theme tokens when inlined).
2. Renders ARCHITECTURE.md into architecture.html (branded, diagrams inlined).
ARCHITECTURE.md is the source of truth; never edit the HTML by hand.
Needs the `markdown` package (pip install markdown).
"""

from __future__ import annotations

import re
from pathlib import Path

import markdown

HERE = Path(__file__).parent
FONT = "'Bricolage Grotesque',system-ui,sans-serif"
STYLE = f"""<style>
.bg{{fill:var(--d-bg,#F3EFE7)}}.n{{fill:var(--d-node,#FFFFFF)}}.p{{fill:var(--d-pnode,#F3EFE7)}}
.l{{fill:var(--d-llm,#BFD0FF)}}.i{{fill:var(--d-inv,#0A0A0A)}}.g{{fill:#2741E8}}
.t{{font:600 15px {FONT};fill:var(--d-ink,#0A0A0A)}}.s{{font:400 13px {FONT};fill:var(--d-muted,#4A4A4A)}}
.lb{{font:400 12px {FONT};fill:var(--d-muted,#4A4A4A)}}.hd{{font:700 13px {FONT};fill:var(--d-muted,#4A4A4A)}}
.ti{{fill:var(--d-on-inv,#F3EFE7)}}.si{{fill:var(--d-on-inv-muted,#CFCFCF)}}.tg{{fill:#FFFFFF}}
.e{{stroke:var(--d-muted,#4A4A4A);stroke-width:2;fill:none}}.ah{{fill:var(--d-muted,#4A4A4A)}}
.d{{stroke:var(--d-muted,#4A4A4A);stroke-width:1.5;fill:none;stroke-dasharray:6 6}}
</style>"""
TEXT = {
    "n": ("t", "s"),
    "p": ("t", "s"),
    "l": ("t", "s"),
    "i": ("t ti", "s si"),
    "g": ("t tg", "s tg"),
}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Diagram:
    def __init__(self, name: str, title: str, h: int):
        self.name, self.title, self.h, self.parts = name, title, h, []

    def node(self, x, y, w, h, cls, *lines, r=16):
        self.parts.append(
            f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"/>'
        )
        t, s = TEXT[cls]
        block = 20 + 17 * (len(lines) - 1)
        ty = y + h / 2 - block / 2 + 15
        for k, line in enumerate(lines):
            c, dy = (t, 0) if k == 0 else (s, 20 + 17 * (k - 1))
            self.parts.append(
                f'<text class="{c}" x="{x + w / 2}" y="{ty + dy:.0f}" text-anchor="middle">{esc(line)}</text>'
            )

    def panel(self, x, y, w, h, label):
        self.parts.append(
            f'<rect class="n" x="{x}" y="{y}" width="{w}" height="{h}" rx="24"/>'
        )
        self.parts.append(
            f'<text class="hd" x="{x + 24}" y="{y + 32}">{esc(label)}</text>'
        )

    def box(self, x, y, w, h, label):  # dashed boundary (a host, not a component)
        self.parts.append(
            f'<rect class="d" x="{x}" y="{y}" width="{w}" height="{h}" rx="24"/>'
        )
        self.parts.append(
            f'<text class="hd" x="{x + 20}" y="{y + 28}">{esc(label)}</text>'
        )

    def edge(self, d, arrow=True):
        self.parts.append(
            f'<path class="e" d="{d}"'
            + (f' marker-end="url(#a-{self.name})"' if arrow else "")
            + "/>"
        )

    def label(self, x, y, s, anchor="start"):
        self.parts.append(
            f'<text class="lb" x="{x}" y="{y}" text-anchor="{anchor}">{esc(s)}</text>'
        )

    def svg(self) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 {self.h}" role="img" aria-labelledby="t-{self.name}">'
            f'<title id="t-{self.name}">{esc(self.title)}</title>{STYLE}'
            f'<defs><marker id="a-{self.name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path class="ah" d="M0 0L10 5L0 10z"/></marker></defs>'
            f'<rect class="bg" width="960" height="{self.h}"/>'
            + "".join(self.parts)
            + "</svg>\n"
        )


def system() -> Diagram:
    d = Diagram(
        "system",
        "System and deployment: coach browser, Caddy, the FastAPI app, graph store, event log, model providers",
        460,
    )
    d.node(16, 180, 150, 72, "n", "Coach", "browser")
    d.box(196, 16, 520, 428, "DigitalOcean droplet, Ubuntu 24.04")
    d.node(216, 180, 140, 72, "n", "Caddy", "HTTPS, coach login")
    d.parts.append('<rect class="n" x="386" y="64" width="310" height="260" rx="24"/>')
    d.parts.append(
        '<text class="t" x="410" y="96">FastAPI app</text><text class="s" x="410" y="116">one process, served by uvicorn</text>'
    )
    rows = [
        "Router, resolver, safety filter",
        "Scorer, composer, validator",
        "Copilot tools, grounding check",
        "Member intake and signals",
        "Dashboard (built React files)",
    ]
    for k, row in enumerate(rows):
        y = 132 + 34 * k
        d.parts.append(
            f'<rect class="p" x="406" y="{y}" width="270" height="28" rx="14"/>'
        )
        d.parts.append(
            f'<text class="s" x="541" y="{y + 19}" text-anchor="middle">{esc(row)}</text>'
        )
    d.node(386, 348, 148, 76, "n", "Oxigraph", "KG1 + KG2, in-process")
    d.node(548, 348, 148, 76, "n", "Event log", "append-only JSONL")
    d.node(760, 64, 184, 64, "l", "Anthropic", "primary, via LiteLLM")
    d.node(760, 152, 184, 64, "l", "OpenAI", "fallback, via LiteLLM")
    d.node(760, 264, 184, 64, "n", "Langfuse", "traces and scores")
    d.edge("M166 216H214")
    d.edge("M356 216H384")
    d.edge("M460 324V346")
    d.edge("M622 324V346")
    d.edge("M696 96H758")
    d.edge("M696 184H758")
    d.edge("M696 296H758")
    return d


def pipeline() -> Diagram:
    d = Diagram(
        "pipeline",
        "Workout request pipeline from coach request to plan with provenance",
        832,
    )
    note = lambda y, *lines: [d.label(728, y + 17 * k, s) for k, s in enumerate(lines)]
    d.node(
        260, 16, 440, 56, "n", "Coach request", "“Lower body, avoid her knee, 30 min”"
    )
    d.node(
        260, 104, 440, 56, "n", "Router", "rules, plus intent from the extraction call"
    )
    note(126, "compose, lookup, analyze,", "or analyze then compose")
    d.node(260, 192, 210, 72, "n", "Rules extractor", "SKOS labels, fuzzy match")
    d.node(490, 192, 210, 72, "l", "LLM extractor", "in parallel, 2 s timeout")
    note(214, "Union: the model can add", "caution, never remove it")
    d.node(16, 192, 190, 72, "g", "Ask the coach", "a concern it can't place")
    d.edge("M258 228H208")
    d.label(232, 220, "blocks", "middle")
    d.node(
        260,
        296,
        440,
        56,
        "n",
        "Constraints",
        "injuries, care-team rules, request, readiness",
    )
    note(318, "from KG2 and today's", "check-in or messages")
    d.node(
        260, 384, 440, 64, "i", "Safety filter", "graph traversal, no model involved"
    )
    note(406, "every exclusion keeps its", "rule, source and graph path")
    d.node(
        260, 480, 440, 56, "n", "Scorer", "goals, history, journey stage, preferences"
    )
    note(502, "ranks only what is", "already safe")
    d.node(
        260, 568, 210, 72, "n", "Deterministic builder", "offline floor, under 50 ms"
    )
    d.node(490, 568, 210, 72, "l", "LLM composer", "picks from safe IDs only")
    note(590, "falls back to the builder", "on timeout or bad output")
    d.node(260, 672, 440, 56, "n", "Validator", "always runs, whichever builder won")
    note(
        694,
        "drops unknown IDs and unsafe text,",
        "swaps picks, clamps doses, fits time",
    )
    d.node(
        260,
        760,
        440,
        56,
        "n",
        "Plan + provenance",
        "sets, reps, rest, RPE, and why for each",
    )
    for y in (72, 352, 448, 728):
        d.edge(f"M480 {y}V{y + 30}")
    for top, bot in ((160, 192), (536, 568)):  # split into the two halves
        d.edge(f"M480 {top}V{top + 16}H365V{bot - 2}")
        d.edge(f"M480 {top + 16}H595V{bot - 2}")
    for top, bot in ((264, 296), (640, 672)):  # merge back
        d.edge(f"M365 {top}V{top + 16}H595V{top}", arrow=False)
        d.edge(f"M480 {top + 16}V{bot - 2}")
    return d


def graph() -> Diagram:
    d = Diagram(
        "graph",
        "Knowledge graph model, worked example: why the goblet squat is excluded for Jordan's knee",
        640,
    )
    d.panel(16, 16, 640, 528, "KG1: domain graph")
    d.panel(672, 16, 272, 528, "KG2: member graph")
    d.node(40, 80, 200, 56, "p", "Kettlebell Goblet Squat", "exercise")
    d.node(40, 200, 200, 56, "p", "lower push: squat", "movement pattern")
    d.node(40, 320, 200, 56, "p", "kettlebell, 1 needed", "equipment requirement")
    d.node(300, 80, 160, 56, "p", "Stress", "derived from the pattern")
    d.node(300, 200, 160, 56, "p", "knee", "structure")
    d.node(300, 320, 160, 56, "p", "patellofemoral joint", "structure")
    d.node(300, 440, 160, 56, "p", "PFP", "condition (SNOMED)")
    d.node(490, 200, 150, 56, "p", "loaded deep flexion", "load type")
    d.node(
        490, 320, 150, 72, "p", "PFP rule", "recovering: downrank", "source: Willy 2019"
    )
    d.node(
        692,
        80,
        232,
        72,
        "p",
        "Care-team note",
        "“avoid deep knee flexion",
        "under load”",
    )
    d.node(692, 200, 232, 56, "p", "Member rule", "deep flexion: exclude")
    d.node(692, 440, 232, 56, "p", "Left knee injury", "Jordan, recovering")
    d.edge("M240 108H298")
    d.label(269, 100, "stresses", "middle")
    d.edge("M140 136V198")
    d.label(148, 172, "pattern")
    d.edge("M140 256V318")
    d.label(148, 292, "requires")
    d.edge("M380 136V198")
    d.label(388, 172, "structure")
    d.edge("M440 136L540 198")
    d.label(500, 158, "load type")
    d.edge("M380 320V258")
    d.label(388, 292, "part of")
    d.edge("M380 440V378")
    d.label(388, 412, "affects")
    d.edge("M565 320V258")
    d.label(573, 292, "load type")
    d.edge("M565 392V455H462")
    d.label(573, 428, "condition")
    d.edge("M692 480H462")
    d.label(577, 498, "instance of", "middle")
    d.edge("M808 152V198")
    d.label(816, 180, "parsed into")
    d.edge("M692 228H642")
    d.edge("M808 256V438")
    d.label(816, 350, "applies to")
    d.node(
        16,
        568,
        928,
        56,
        "i",
        "Strictest tier wins",
        "The member rule (exclude) beats the condition rule (downrank), so the goblet squat is excluded, with this path as its reason.",
    )
    return d


def replan() -> Diagram:
    d = Diagram(
        "replan",
        "Member data flow: a message is stored, changes readiness, and re-plans today's session in the background",
        340,
    )
    d.node(
        16, 16, 208, 96, "n", "Member message", "“slept 4 hours,", "only 20 min today”"
    )
    d.node(
        256, 16, 208, 96, "n", "Intake", "sleep 4 h, one-off cause,", "20 min available"
    )
    d.node(
        496,
        16,
        208,
        96,
        "n",
        "Event log and KG2",
        "stored as observations,",
        "nothing overwritten",
    )
    d.node(736, 16, 208, 96, "n", "Signals", "readiness low:", "RPE cap 6, volume 0.6")
    d.node(
        16,
        208,
        208,
        96,
        "g",
        "Reply at once",
        "“Got it, today's session",
        "will fit in 20 min.”",
    )
    d.node(
        496,
        208,
        208,
        96,
        "l",
        "Background re-plan",
        "same pipeline,",
        "same safety gate",
    )
    d.node(
        736,
        208,
        208,
        96,
        "n",
        "Plan v2 + diff",
        "the coach sees what",
        "changed and why",
    )
    d.edge("M224 64H254")
    d.edge("M464 64H494")
    d.edge("M704 64H734")
    d.edge("M360 112V156H120V206")
    d.label(240, 148, "immediately", "middle")
    d.edge("M840 112V176H600V206")
    d.label(720, 168, "if a plan exists today", "middle")
    d.edge("M704 256H734")
    return d


def delivery() -> Diagram:
    d = Diagram("delivery", "Delivery pipeline from commit to the live site", 300)
    d.node(16, 16, 212, 88, "n", "Commit", "ruff, gitleaks,", "conventional message")
    d.node(252, 16, 212, 88, "n", "Push", "LLM-free tests", "(pre-push hook)")
    d.node(
        488,
        16,
        212,
        88,
        "l",
        "MR pipeline",
        "lint, tests, build,",
        "golden set, real models",
    )
    d.node(
        724,
        16,
        220,
        88,
        "i",
        "Eval gate",
        "all cases pass, floors met,",
        "no drop vs baseline",
    )
    d.node(
        16,
        196,
        212,
        88,
        "n",
        "Merge to main",
        "protected branch,",
        "pipeline must pass",
    )
    d.node(
        252,
        196,
        212,
        88,
        "n",
        "Deploy job",
        "rsync, write keys,",
        "restart, health check",
    )
    d.node(488, 196, 212, 88, "n", "Live site", "198-199-77-33", ".sslip.io")
    d.edge("M228 60H250")
    d.edge("M464 60H486")
    d.edge("M700 60H722")
    d.edge("M834 104V150H122V194")
    d.edge("M228 240H250")
    d.edge("M464 240H486")
    d.label(478, 142, "all jobs run on the self-hosted Mac runner", "middle")
    return d


PAGE_CSS = """
:root{--surface:#F3EFE7;--surface-raised:#FFFFFF;--ink:#0A0A0A;--ink-muted:#4A4A4A;--signal:#2741E8;--on-signal:#FFFFFF;
--signal-text:#2741E8;--sky:#BFD0FF;--contrast-surface:#0A0A0A;--on-contrast:#F3EFE7;--on-contrast-muted:#CFCFCF;--hairline:#D9D3C7;
--d-bg:var(--surface);--d-node:var(--surface-raised);--d-pnode:var(--surface);--d-llm:var(--sky);--d-inv:var(--contrast-surface);
--d-ink:var(--ink);--d-muted:var(--ink-muted);--d-on-inv:var(--on-contrast);--d-on-inv-muted:var(--on-contrast-muted);
--font:'Bricolage Grotesque',system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface:#16140F;--surface-raised:#221F19;--ink:#F3EFE7;
--ink-muted:#B9B3A8;--signal-text:#8C9CFF;--sky:#26306B;--contrast-surface:#F3EFE7;--on-contrast:#0A0A0A;--on-contrast-muted:#4A4A4A;
--hairline:#3A362E;color-scheme:dark}}
:root[data-theme="dark"]{--surface:#16140F;--surface-raised:#221F19;--ink:#F3EFE7;--ink-muted:#B9B3A8;--signal-text:#8C9CFF;
--sky:#26306B;--contrast-surface:#F3EFE7;--on-contrast:#0A0A0A;--on-contrast-muted:#4A4A4A;--hairline:#3A362E;color-scheme:dark}
body{background:var(--surface);color:var(--ink);font:400 16px/24px var(--font);margin:0}
.wrap{max-width:1040px;margin:0 auto;padding-block:48px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:20px}
main{display:grid;gap:20px;min-width:0}
header.cover{display:grid;gap:12px;padding-block:24px 8px}
.byline{color:var(--ink-muted);font-weight:600;font-size:14px;line-height:20px;margin:0}
h1{font-weight:800;font-size:clamp(36px,6vw,56px);line-height:1.04;letter-spacing:-0.03em;margin:0;text-wrap:balance}
.hl{background:var(--signal);color:var(--on-signal);border-radius:16px;padding:0 .18em}
.lede{font-size:20px;line-height:30px;max-width:65ch;margin:0;color:var(--ink)}
nav.toc{display:flex;flex-wrap:wrap;gap:8px}
nav.toc a{display:inline-flex;align-items:center;min-height:40px;padding:0 16px;border-radius:999px;background:var(--surface-raised);
color:var(--ink);text-decoration:none;font-weight:600;font-size:14px}
nav.toc a:focus-visible,a:focus-visible{outline:2px solid var(--signal-text);outline-offset:2px}
section{background:var(--surface-raised);border-radius:24px;padding:28px;display:grid;gap:16px;min-width:0}
section.feature{background:var(--contrast-surface);color:var(--on-contrast)}
section.feature p,section.feature li{color:var(--on-contrast)}
section > *{margin:0}
h2{font-weight:700;font-size:32px;line-height:36px;letter-spacing:-0.02em;text-wrap:balance}
h3{font-weight:800;font-size:22px;line-height:28px;letter-spacing:-0.01em}
p,li{max-width:70ch}
ul,ol{padding-left:22px;display:grid;gap:6px}
a{color:var(--signal-text)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:var(--surface);border-radius:6px;padding:1px 5px}
section.feature code{background:transparent;border:1px solid var(--on-contrast-muted)}
.fig{overflow-x:auto;border-radius:16px;background:var(--surface)}
.fig svg{display:block;min-width:760px;width:100%;height:auto}
.legend{display:flex;flex-wrap:wrap;gap:8px;list-style:none;padding:0}
.legend li{display:inline-flex;align-items:center;gap:8px;font-size:14px;line-height:20px;font-weight:600}
.sw{width:18px;height:18px;border-radius:6px;display:inline-block}
.tbl{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:15px;line-height:22px}
th,td{text-align:left;vertical-align:top;padding:10px 12px 10px 0;border-bottom:1px solid var(--hairline)}
th{font-weight:600;color:var(--ink-muted);font-size:14px}
td{font-variant-numeric:tabular-nums}
footer{color:var(--ink-muted);font-size:13px;line-height:18px;padding-top:8px}
@media (max-width:600px){section{padding:20px}h2{font-size:26px;line-height:30px}}
"""


def page(md_text: str, svgs: dict[str, str]) -> str:
    title, _, rest = md_text.partition("\n")
    lede, _, body = rest.strip().partition("\n\n")
    html = markdown.markdown(body, extensions=["tables", "fenced_code", "toc"])
    for (
        name,
        svg,
    ) in (
        svgs.items()
    ):  # ![alt](name.svg) -> the inline SVG, so it follows the page theme
        html = re.sub(
            rf'<p><img alt="[^"]*" src="{name}\.svg" ?/?></p>',
            f'<div class="fig">{svg}</div>',
            html,
        )
    parts = re.split(r"(?=<h2)", html)
    sections, toc = [], []
    for p in parts[1:]:
        m = re.match(r'<h2 id="([^"]+)">(.*?)</h2>', p)
        toc.append(f'<a href="#{m.group(1)}">{m.group(2)}</a>')
        cls = ' class="feature"' if m.group(1) == "the-core-rule" else ""
        sections.append(f"<section{cls}>{p}</section>")
    plain = title.lstrip("# ")
    head, _, word = plain.rpartition(" ")
    h1 = f'{esc(head)} <span class="hl">{esc(word)}</span>'  # the brand's one highlighted word: the headline's last
    return f"""<title>Future Coach Architecture</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@400;600;700;800&display=swap">
<style>{PAGE_CSS}</style>
<div class="wrap">
<header class="cover"><p class="byline">Future Coach, by Taylor Clements, PhD</p><h1 aria-label="{esc(plain)}">{h1}</h1>
<p class="lede">{markdown.markdown(lede)[3:-4]}</p></header>
<nav class="toc" aria-label="Sections">{"".join(toc)}</nav>
<main>{"".join(sections)}</main>
<footer>Generated from docs/architecture/ARCHITECTURE.md by docs/architecture/build.py.</footer>
</div>
"""


def main() -> None:
    svgs = {}
    for make in (system, pipeline, graph, replan, delivery):
        dg = make()
        svgs[dg.name] = dg.svg()
        (HERE / f"{dg.name}.svg").write_text(svgs[dg.name])
    md = (HERE / "ARCHITECTURE.md").read_text()
    (HERE / "architecture.html").write_text(page(md, svgs))


if __name__ == "__main__":
    main()
