"""Look and feel for app.py: theme CSS (light/dark via CSS variables), restrained motion, small HTML helpers.
Pure presentation: no planning logic here."""
from html import escape

THEMES = {
    "light": {"bg": "#eef3ef", "side": "#e7eee9", "card": "#ffffff", "card2": "#f1f5f2", "text": "#17241d",
              "muted": "#5f6f66", "border": "#dbe5de", "accent": "#1f4d3a", "accent2": "#d6ecdc", "ok": "#1e7a4a",
              "okbg": "#d6ecdc", "bad": "#b5452c", "badbg": "#fbe4dc", "warn": "#b7791f", "warnbg": "#fbefd9",
              "info": "#1f4d3a"},
    "dark": {"bg": "#0f1714", "side": "#121c18", "card": "#16211c", "card2": "#1c2a23", "text": "#e3ece6",
             "muted": "#93a59b", "border": "#26362e", "accent": "#6fcf97", "accent2": "#1f3b2d", "ok": "#6fcf97",
             "okbg": "#1f3b2d", "bad": "#f08a6c", "badbg": "#3a2019", "warn": "#f2c14e", "warnbg": "#3a2f15",
             "info": "#6fcf97"},
}

FONTS = ("@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
         "&family=JetBrains+Mono:wght@400;500;600&display=swap');")

CSS = """
:root{VARS;--mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Consolas,monospace;--sans:'Inter',system-ui,sans-serif}
html,body,[data-testid="stAppViewContainer"],[data-testid="stHeader"],[data-testid="stMain"]{background:var(--bg)!important;color:var(--text)!important;font-family:var(--sans)}
[data-testid="stSidebar"]{background:var(--side)!important;border-right:1px solid var(--border)}
[data-testid="stSidebar"] *,[data-testid="stMarkdownContainer"],[data-testid="stMarkdownContainer"] *,label,p,h1,h2,h3,h4,span,li{color:var(--text);font-family:var(--sans)}
[data-testid="stCaptionContainer"] *{color:var(--muted)!important}
.block-container,[data-testid="stMainBlockContainer"]{padding-top:4.5rem!important;max-width:1240px}
[data-testid="stHeader"]{background:transparent!important}
[data-testid="stIconMaterial"],[data-testid="stIconMaterial"] *,span[class*="material"]{font-family:"Material Symbols Rounded"!important}
h3{font-size:1.45rem!important;font-weight:500!important;margin:1.4rem 0 .6rem!important}
[data-testid="stExpander"] details{background:var(--card);border:1px solid var(--border)!important;border-radius:8px}
[data-testid="stExpander"] summary p{font-family:var(--mono);font-size:.76rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
textarea,input,[data-baseweb="select"]>div,[data-testid="stFileUploaderDropzone"]{background:var(--card)!important;color:var(--text)!important;border-color:var(--border)!important;border-radius:8px!important}
textarea{font-family:var(--mono)!important;font-size:.85rem!important}
[data-testid="stFileUploaderDropzone"] *{color:var(--muted)!important}
[data-testid="stFileChip"]{background:var(--card2)!important;border:1px solid var(--border)!important;border-radius:6px}
[data-testid="stFileChip"] *,[data-testid="stFileChipName"]{color:var(--text)!important}
[data-testid="stAlertContainer"]{background:var(--warnbg)!important;border-left:4px solid var(--warn);border-radius:8px}
[data-testid="stAlertContainer"] *{color:var(--text)!important}
[data-testid="stCheckbox"] label>div:first-child{background:var(--border)!important}
[data-testid="stCheckbox"] label:has(input:checked)>div:first-child{background:var(--accent)!important}
[data-testid="stCheckbox"] label>div:first-child>div{background:#fff!important}
.stButton button,.stDownloadButton button{border-radius:6px;border:1px solid var(--border);background:var(--card2);color:var(--text);font-weight:600;letter-spacing:.04em;text-transform:uppercase;font-size:.78rem;transition:filter .15s,border-color .15s}
.stButton button:hover,.stDownloadButton button:hover{border-color:var(--accent);color:var(--accent)}
.stButton button[kind="primary"],.stDownloadButton button[kind="primary"]{background:var(--accent);color:#fff;border-color:var(--accent)}
.stButton button[kind="primary"] *,.stDownloadButton button[kind="primary"] *{color:#fff}
.stButton button[kind="primary"]:hover,.stDownloadButton button[kind="primary"]:hover{filter:brightness(1.12);color:#fff}
[data-baseweb="tab-list"]{gap:6px;background:transparent}
button[role="tab"]{border-radius:8px!important;padding:6px 16px!important}
button[role="tab"] p{color:var(--text)!important;font-size:.95rem}
button[role="tab"][aria-selected="true"]{background:var(--card)!important}
button[role="tab"][aria-selected="true"] p{color:var(--accent)!important;font-weight:600}
[data-baseweb="tab-highlight"],[data-baseweb="tab-border"]{display:none}
code,pre{background:var(--card2)!important;color:var(--text)!important;font-family:var(--mono)!important}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.brand{display:flex;gap:12px;align-items:center;margin:4px 0 16px}
.brand .ic{width:44px;height:44px;border-radius:8px;background:var(--accent);display:flex;align-items:center;justify-content:center;color:#fff!important;font-size:1.2rem}
.brand .t1{font-size:1.25rem;font-weight:500} .brand .t2{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase}
.modelpill{display:flex;justify-content:space-between;align-items:center;background:var(--card2);border-radius:6px;padding:7px 10px;font-family:var(--mono)!important;font-size:.78rem;margin-bottom:14px}
.modelpill *{font-family:var(--mono)!important}
.modelpill .d{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--ok);margin-right:6px}
.slabel{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;font-weight:600;margin:12px 0 4px}
.steps{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 14px}
.step{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:999px;font-size:.76rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;background:var(--card2);color:var(--text)}
.step.done{background:var(--okbg);color:var(--ok)} .step.now{background:var(--accent2);color:var(--accent);box-shadow:inset 0 0 0 1.5px var(--accent)}
.panel{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 20px;margin:8px 0 14px;animation:fade .25s ease-out both}
.status{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.status .s{display:inline-flex;align-items:center;gap:6px;padding:5px 16px;border-radius:999px;font-weight:600;font-size:.8rem;letter-spacing:.06em;color:#fff!important;background:var(--muted)}
.status.VALID .s{background:var(--accent)} .status.INVALID .s{background:var(--bad)} .status.NEEDS .s{background:var(--warn)}
.status .sent{font-size:1.02rem;flex:1;min-width:240px}
.status .st{font-family:var(--mono)!important;font-size:.74rem;background:var(--card2);padding:4px 10px;border-radius:4px;color:var(--muted)!important;white-space:nowrap}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:8px 0 14px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;animation:fade .3s both}
.stat .l{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;font-weight:500}
.stat .v{font-family:var(--mono)!important;font-size:1.35rem;font-weight:600;margin:8px 0 4px}
.stat .x{font-family:var(--mono)!important;font-size:.72rem;color:var(--muted)!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat .x.good{display:inline-block;background:var(--okbg);color:var(--ok)!important;padding:2px 8px;border-radius:4px}
.sechead{display:flex;align-items:center;gap:12px;margin:22px 0 10px}
.sechead .t{font-size:1.45rem;font-weight:500}
.sechead .r{margin-left:auto;font-family:var(--mono)!important;font-size:.76rem;color:var(--muted)!important}
.chkgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}
.chk{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px 20px;animation:fade .3s both;display:flex;flex-direction:column;gap:8px}
.chk .h{display:flex;align-items:center;gap:10px;font-size:1.2rem;font-weight:500}
.chk .h .r{margin-left:auto}
.chk .m{font-size:.92rem;flex:1}
.mono{font-family:var(--mono)!important;font-size:.78rem;background:var(--card2);padding:6px 10px;border-radius:4px;display:inline-block}
.tbl{width:100%;border-collapse:collapse;font-size:.86rem}
.tbl th{text-align:left;font-weight:600;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--border);padding:8px;background:var(--card2)}
.tbl td{border-bottom:1px solid var(--border);padding:9px 8px;vertical-align:top}
.tbl td.num{text-align:right;white-space:nowrap;font-family:var(--mono)!important;font-size:.8rem}
.tbl tr:last-child td{border-bottom:none}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:var(--muted)}
.dot.PASS,.dot.ok{background:var(--ok)} .dot.FAIL,.dot.bad{background:var(--bad)} .dot.UNRESOLVED,.dot.warn{background:var(--warn)} .dot.info{background:var(--info)}
.tag{display:inline-block;padding:2px 9px;border-radius:4px;font-family:var(--mono)!important;font-size:.72rem;font-weight:600;letter-spacing:.04em;background:var(--card2);color:var(--muted)!important;margin-right:4px;text-transform:uppercase}
.tag.ok{background:var(--okbg);color:var(--ok)!important} .tag.bad{background:var(--badbg);color:var(--bad)!important}
.tag.warn{background:var(--warnbg);color:var(--warn)!important} .tag.info,.tag.acc{background:var(--accent2);color:var(--accent)!important}
.rej{border-left:4px solid var(--bad)} .q{font-style:italic;background:var(--card2);padding:8px 12px;border-radius:4px;margin:8px 0;font-size:1.05rem}
.reason{font-family:var(--mono)!important;font-size:.8rem;color:var(--bad)!important}
.muted{color:var(--muted)!important} .small{font-size:.84rem}
.tl{display:flex;height:34px;border-radius:6px;overflow:hidden;margin:4px 0 10px;transform-origin:left;animation:grow .35s ease-out both}
.tl div{display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:.7rem;color:#fff!important;overflow:hidden;white-space:nowrap;border-right:1px solid rgba(255,255,255,.35);padding:0 4px}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--card2);transform-origin:left;animation:grow .35s ease-out both}
.legend{margin:8px 0 12px} .legend span{display:inline-flex;align-items:center;gap:6px;margin-right:18px;font-family:var(--mono)!important;font-size:.75rem;color:var(--muted)!important}
.legend i{width:10px;height:10px;border-radius:50%;display:inline-block}
.wf{display:grid;grid-template-columns:minmax(140px,30%) 1fr 120px;gap:10px;align-items:center;font-size:.82rem;padding:4px 0;border-bottom:1px dashed var(--border)}
.wf:last-child{border-bottom:none;font-weight:650}
.wl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap} .wv{text-align:right;font-family:var(--mono)!important;font-size:.78rem}
.wt{position:relative;height:14px;background:var(--card2);border-radius:3px}
.wt div{position:absolute;top:0;bottom:0;border-radius:3px;transform-origin:left;animation:grow .35s ease-out both}
.roster{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px}
.roster div{border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-family:var(--mono)!important;font-size:.74rem;background:var(--card2)}
.roster b{display:block;font-family:var(--sans)!important;font-size:.75rem;color:var(--muted)!important;font-weight:600}
.diff{display:grid;grid-template-columns:1.2fr 1fr 24px 1fr;gap:4px 10px;font-family:var(--mono);font-size:.82rem}
.diff .new{font-weight:650;color:var(--accent)!important;animation:fade .4s both}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
"""


def css(theme):
    vars_ = ";".join(f"--{k}:{v}" for k, v in THEMES[theme].items())
    return "<style>" + FONTS + CSS.replace("VARS", vars_) + "</style>"


def e(x):
    return escape(str(x))


def tag(text, kind=""):
    return f'<span class="tag {kind}">{e(text)}</span>'


chip = tag   # same look; kept for callers


def dot(kind):
    return f'<span class="dot {kind}"></span>'


def stats(items):
    """items: (label, value, sub) or (label, value, sub, good)"""
    return '<div class="stats">' + "".join(
        f'<div class="stat"><div class="l">{e(it[0])}</div><div class="v">{e(it[1])}</div>'
        f'<div class="x{" good" if len(it) > 3 and it[3] else ""}">{e(it[2])}</div></div>'
        for it in items) + "</div>"


def table(rows, cols, num=()):
    head = "".join(f"<th>{e(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(
        f'<td class="{"num" if c in num else ""}">'
        f'{r.get(c, "") if str(r.get(c, "")).startswith("<span") else e(r.get(c, ""))}</td>' for c in cols) + "</tr>"
        for r in rows)
    return f'<table class="tbl"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


STATUS_KIND = {"accepted": "ok", "partly accepted": "warn", "rejected": "bad", "superseded": "", "noted": "info",
               "optional": "info", "irrelevant": "", "needs review": "warn", "pending": "warn"}
STATUS_LABEL = {"accepted": "used", "noted": "pending approval"}
