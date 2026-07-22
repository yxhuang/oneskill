#!/usr/bin/env python3
"""Generate a self-contained terminal-card SVG demo for oneskill's README.

Grid-based, monospace, fixed pixel coordinates -> deterministic layout.
No external assets, no fonts embedded (uses a system monospace stack).
"""
from html import escape

# ---- design tokens ---------------------------------------------------------
FONT = "ui-monospace, 'SF Mono', 'Cascadia Code', 'JetBrains Mono', Menlo, Consolas, monospace"
BG        = "#14171e"   # card
BORDER    = "#2a2f3a"
BARLINE   = "#232833"   # hairlines / rules
TITLEBAR  = "#191d25"
IRIS      = "#8b95f2"   # brand accent (prompt, title)
PRIMARY   = "#dfe4ec"   # skill names, command
DIM       = "#6a7280"   # source/scope, header
FAINT     = "#464c57"   # the em-dash (not applicable)
LABEL     = "#9aa4b2"   # section labels, status text
JADE      = "#5ec98a"   # linked / healthy
AMBER     = "#e6b450"   # needs attention
DOT       = "#39404c"   # traffic dots

# ---- geometry --------------------------------------------------------------
W = 792
PAD_X = 28
BAR_H = 46
TOP = BAR_H + 30          # first body baseline area
LH = 23                  # line height
FS = 14                  # body font size

# column x anchors (pixels) -- independent of font advance width
COL = {"skill": PAD_X, "source": 214, "scope": 306, "claude": 436, "codex": 566, "kimi": 676}

# ---- content (a plausible real setup; matches README's example spirit) -----
SHARED = [
    ("doc-writer", "self"),
    ("pdf-editing", "self"),
    ("refine-prompt", "self"),
    ("stock-data", "vendor"),
    ("web-search", "self"),
]
CLIENT = [
    ("superpowers", "plugin", "claude-only", ("plugin", None, None)),
    ("mail-organizer", "self", "codex-only", (None, "linked", None)),
    ("kimi-helper", "self", "kimi-only", (None, None, "linked")),
]
ATTENTION = [
    ("officecli", "external", "shared", ("realdir", "linked", "linked")),
]

out = []
def el(s): out.append(s)

def text(x, y, s, fill, size=FS, weight=400, ls=None, anchor="start", opacity=None):
    extra = ""
    if ls is not None: extra += f' letter-spacing="{ls}"'
    if opacity is not None: extra += f' opacity="{opacity}"'
    el(f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" '
       f'font-weight="{weight}" text-anchor="{anchor}"{extra}>{escape(s)}</text>')

def rule(y, x1=PAD_X, x2=W-PAD_X, color=BARLINE, w=1):
    el(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="{w}"/>')

# status cell renderer: glyph colored, label in LABEL/FAINT
def status(col, y, kind):
    x = COL[col]
    if kind is None:
        text(x, y, "—", FAINT)                       # em dash
    elif kind == "linked":
        text(x, y, "✓", JADE, weight=600)
        text(x + 16, y, "linked", LABEL)
    elif kind == "plugin":
        text(x, y, "✓", JADE, weight=600)
        text(x + 16, y, "plugin", LABEL)
    elif kind == "realdir":
        text(x, y, "!", AMBER, weight=700)
        text(x + 16, y, "real dir", AMBER, opacity=0.85)

# ---- build body ------------------------------------------------------------
y = TOP
# prompt line
text(PAD_X, y, "$", IRIS, weight=700)
text(PAD_X + 16, y, "osk list", PRIMARY, weight=600)
y += LH + 8

# column header
text(COL["skill"], y, "skill", DIM, size=12.5, ls="0.3")
text(COL["source"], y, "source", DIM, size=12.5, ls="0.3")
text(COL["scope"], y, "scope", DIM, size=12.5, ls="0.3")
text(COL["claude"], y, "claude", DIM, size=12.5, ls="0.3")
text(COL["codex"], y, "codex", DIM, size=12.5, ls="0.3")
text(COL["kimi"], y, "kimi", DIM, size=12.5, ls="0.3")
y += 10
rule(y)
y += LH + 4

def section(label, rows, rail=None):
    global y
    text(PAD_X, y, label, LABEL, size=11.5, weight=600, ls="1.4")
    y += 9
    rule(y)
    rail_top = y + 8
    y += LH
    for row in rows:
        if len(row) == 2:               # shared: name, source -> all linked
            name, source = row
            text(COL["skill"], y, name, PRIMARY)
            text(COL["source"], y, source, DIM)
            text(COL["scope"], y, "shared", DIM)
            for c in ("claude", "codex", "kimi"):
                status(c, y, "linked")
        else:
            name, source, scope, states = row
            text(COL["skill"], y, name, PRIMARY)
            text(COL["source"], y, source, DIM)
            text(COL["scope"], y, scope, DIM)
            for c, st in zip(("claude", "codex", "kimi"), states):
                status(c, y, st)
        y += LH
    if rail:
        el(f'<rect x="{PAD_X-14}" y="{rail_top}" width="2.5" height="{y-rail_top-6}" '
           f'rx="1.25" fill="{rail}" opacity="0.9"/>')
    y += 14

section("SHARED  ·  ALL THREE CLIENTS", SHARED)
section("CLIENT-SPECIFIC", CLIENT)
section("NEEDS ATTENTION", ATTENTION, rail=AMBER)

# summary
y += 2
rule(y - LH + 6)
sy = y + 4
text(PAD_X, sy, "9 skills", PRIMARY, weight=600)
text(PAD_X + 78, sy, "·", DIM)
text(PAD_X + 96, sy, "5", JADE, weight=700)
text(PAD_X + 110, sy, "shared across all clients", LABEL)
text(PAD_X + 314, sy, "·", DIM)
text(PAD_X + 332, sy, "1 issue", AMBER, weight=700)
y = sy + 20

H = y + 8

# ---- assemble --------------------------------------------------------------
body = "\n".join(out)
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">
  <defs>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="10" stdDeviation="24" flood-color="#000000" flood-opacity="0.45"/>
    </filter>
  </defs>
  <rect x="6" y="4" width="{W-12}" height="{H-12}" rx="13" fill="{BG}" stroke="{BORDER}" stroke-width="1" filter="url(#shadow)"/>
  <path d="M6 17 a13 13 0 0 1 13 -13 h{W-38} a13 13 0 0 1 13 13 v{BAR_H-17} h-{W-12} z" fill="{TITLEBAR}"/>
  <line x1="6" y1="{BAR_H+4}" x2="{W-6}" y2="{BAR_H+4}" stroke="{BARLINE}" stroke-width="1"/>
  <circle cx="30" cy="{BAR_H//2+2}" r="5.5" fill="{DOT}"/>
  <circle cx="50" cy="{BAR_H//2+2}" r="5.5" fill="{DOT}"/>
  <circle cx="70" cy="{BAR_H//2+2}" r="5.5" fill="{DOT}"/>
  <text x="96" y="{BAR_H//2+7}" fill="{IRIS}" font-size="12.5" font-weight="600">oneskill</text>
  <text x="170" y="{BAR_H//2+7}" fill="{DIM}" font-size="12.5">— coverage matrix</text>
{body}
</svg>'''

import os
_here = os.path.dirname(os.path.abspath(__file__))
_out = os.path.join(_here, "demo.svg")
with open(_out, "w") as f:
    f.write(svg)

# ---- geometry self-check ---------------------------------------------------
print(f"canvas: {W} x {H}")
print(f"rightmost kimi col x={COL['kimi']}, +'linked'(~56px) -> {COL['kimi']+16+56} (must be < {W-PAD_X})")
print(f"cols: {COL}")
print("XML well-formed:", end=" ")
import xml.dom.minidom as m
try:
    m.parseString(svg); print("yes")
except Exception as e:
    print("NO", e)
