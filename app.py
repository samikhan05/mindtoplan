"""Web viewer: streamlit run app.py. Uses the same process() function as plan.py."""
from pathlib import Path

import streamlit as st

import config
from llm import ConfigError, Trace
from pipeline import load_state, process, reset
from report import plan_text, rs, submission_text, trace_text
from ui import STATUS_KIND, STATUS_LABEL, css, dot, e, stats, table, tag

st.set_page_config(page_title="MindToPlan", layout="wide")

PLAIN = {  # one-line plain explanation per check
    "correct figures": "Teams hold every student; food covers everyone on site.",
    "within budget": "Planned costs (plus any reserve) stay inside the budget.",
    "venue fits": "The venue seats everyone and has every required facility.",
    "schedule valid": "Blocks fill the event exactly, with every required break and fixed time.",
    "enough judges": "Every team is judged without exceeding any judge's limit.",
    "all areas covered": "Venue, schedule, food, judging and budget all have a plan.",
}
BLOCK_COLOR = {"hack": "#475569", "judg": "#1d4ed8", "break": "#b45309", "prayer": "#b45309", "meal": "#15803d",
               "lunch": "#15803d", "open": "#6b7280", "clos": "#6b7280"}


def html(s):
    st.markdown(s, unsafe_allow_html=True)


def run(text, source):
    """Returns True when the run finished cleanly (caller reruns); on failure the error stays on screen."""
    try:
        with st.status("Processing…", expanded=False) as s:
            st_, rep = process(text, source)
            s.update(label=f"Done · {rep['calls']} model call(s) · {rep['tokens']['total']:,} tokens · {rep['seconds']} s",
                     state="complete")
        st.session_state["last"] = rep
    except ConfigError as err:
        st.error(f"Config error: {err}")
        return False
    errors = [r["error"] for r in st_["trace"][len(st_["trace"]) - rep["calls"]:] if r.get("error")]
    if rep["incomplete"] or errors:
        st.error("Run incomplete; previous plan kept.\n\n" + "\n\n".join(dict.fromkeys(errors + rep["notes"])))
        return False
    return True


def src(ev):
    return ev["msg"] if isinstance(ev, dict) else "computed"


def sources(rows, title="Sources"):
    """One table of evidence per section instead of many expanders."""
    rows = [(label, ev) for label, ev in rows if isinstance(ev, dict)]
    if rows:
        with st.expander(f"{title} ({len(rows)})"):
            html(table([{"decision": l, "message": ev["msg"], "sender": ev["sender"], "date": ev["date"] or "-",
                         "quote": f"“{ev['quote']}”" if ev["quote"] else "(no quote returned)"} for l, ev in rows],
                       ["decision", "message", "sender", "date", "quote"]))


def key_numbers(p):
    if not p:
        return {}
    d, b = p["derived"], p["budget"]
    v, f = p["venue"]["chosen"], p["food"]
    return {"Total planned spend": rs(b["total"]), "Remaining budget": rs(b["remaining"]), "Budget": rs(b["budget"]),
            "Venue": f"{v['name']} ({rs(v['price'])})" if v else "-",
            "Food": f"{f['qty']} × {f['name']} = {rs(f['cost'])}" if f else "-",
            "Headcount": d["headcount"], "Teams": d["teams"], "Judges used": d["judges_used"],
            "Judging window": f"{p['schedule']['judging_min']} min", "Hacking time": f"{p['schedule']['hacking_min']} min",
            "Status": p["validation"]["status"]}


# ---------------- sidebar ----------------
if "dark" not in st.session_state:
    st.session_state["dark"] = False
state = load_state()
with st.sidebar:
    html('<div class="brand"><div class="ic">&#9636;</div><div><div class="t1">MindToPlan AI</div>'
         '<div class="t2">Event ops engine</div></div></div>'
         f'<div class="modelpill"><span><span class="d"></span>{e(config.MODEL_NAME or "not set")}</span>'
         f'<span>{"ALLOWED" if config.ALLOWED_MODELS else "TEAM CHOICE"}</span></div>')
    st.toggle("Dark mode", key="dark")
    html('<div class="slabel">Active step / controls</div>')
    up = st.file_uploader("Load message pack or new messages (.txt)", type=["txt"])
    if up and st.button("Process file", type="primary", width="stretch"):
        if run(up.getvalue().decode("utf-8-sig"), up.name):
            st.rerun()
    if state and state.get("plan"):
        st.download_button("Download submission.txt", submission_text(state), "submission.txt", type="primary",
                           width="stretch", help="Final plan + full trace, for the upload form")
    if st.button("Reset (start over)", width="stretch"):
        reset()
        st.session_state.pop("last", None)
        st.rerun()
    html('<div class="slabel" style="margin-top:28px">Execution CLI helper</div>'
         '<div class="modelpill"><span>python plan.py &lt;messages.txt&gt;</span></div>')

html(css("dark" if st.session_state["dark"] else "light"))

has_plan = bool(state and state.get("plan"))
if not has_plan:
    html('<div class="panel"><b>No plan yet.</b><div class="muted small">Upload the message pack in the sidebar, or run '
         '<code>python plan.py pack.txt</code>. The model reads the messages once; Python plans venue, schedule, '
         'food, judging and budget and checks every rule.</div></div>')
    st.stop()

plan = state["plan"]
v = plan["validation"]
d, b = plan["derived"], plan["budget"]
checks = v["checks"]
fails = [c for c in checks if c["result"] == "FAIL"]
unres = [c for c in checks if c["result"] == "UNRESOLVED"]
last = st.session_state.get("last") or state["updates"][-1]
n_upd = len([u for u in state["updates"] if u["mode"] == "update"])

step = 3 if n_upd else 2
html('<div class="steps">' + "".join(
    f'<span class="step {"done" if i < step else "now" if i == step else ""}">{"&#10003;" if i < step else "&#9675;"} {i}. {t}</span>'
    for i, t in ((1, "Load message pack"), (2, "Review the plan"), (3, "Add new messages"))) + "</div>")
if v["status"] == "VALID":
    sentence = f"All {len(checks)} checks pass."
elif v["status"] == "INVALID":
    sentence = "Failing: " + "; ".join(f"{c['name']} — {c['detail']}" for c in fails)
else:
    sentence = "Needs clarification: " + "; ".join(f"{c['name']} — {c['detail']}" for c in unres)
html(f'<div class="panel status {v["status"].split()[0]}"><span class="s">&#10003; {e(v["status"])}</span>'
     f'<span class="sent">{e(sentence)}</span><span class="st">{len(state["messages"])} messages · '
     f'{n_upd} update(s) · {len(state["trace"])} model call(s)</span></div>')

tabs = st.tabs(["Overview", "Event Plan", "Messages & Facts", "Execution Trace", "Incremental Update"])

# ---------------- overview ----------------
with tabs[0]:
    html(stats([("Students", d["students"] or "-", f"teams of {int(d['team_size'] or 0)}"),
                ("Teams", d["teams"] or "-", ""),
                ("Headcount", d["headcount"], f"{int(d['students'] or 0)} + {int(d['staff'])} staff + {d['judges_used'] or 0} judges"),
                ("Budget", rs(b["budget"]), ""),
                ("Planned", rs(b["total"]), f"committed {rs(b['committed'])}"),
                ("Remaining", rs(b["remaining"]),
                 (f"+{100 * b['remaining'] / b['budget']:.1f}% slack" if b["budget"] and b["remaining"] is not None
                  and b["remaining"] >= 0 else "over budget"), bool(b["remaining"] is not None and b["remaining"] >= 0))]))
    npass = sum(c["result"] == "PASS" for c in checks)
    html(f'<div class="sechead"><span class="t">Checks</span>{tag(f"{npass}/{len(checks)} pass", "acc")}'
         '<span class="r">&#9679; deterministic Python validator</span></div>')
    rk = {"PASS": "ok", "FAIL": "bad", "UNRESOLVED": "warn"}
    html('<div class="chkgrid">' + "".join(
        f'<div class="chk"><div class="h">{"&#9745;" if c["result"] == "PASS" else "&#9746;" if c["result"] == "FAIL" else "&#9888;"} '
        f'{e(c["name"])}<span class="r">{tag(c["result"], rk.get(c["result"], "info"))}</span></div>'
        f'<div class="m">{e(PLAIN.get(c["name"], "Requirement stated in the messages."))}</div>'
        f'<div><span class="mono">{e(c["detail"])}</span></div></div>' for c in checks) + "</div>")
    rejected = [i for i in state["items"] if i["status"] == "rejected"]
    if rejected:
        html(f'<div class="sechead"><span class="t">&#8856; Rejected messages</span>'
             f'{tag(f"{len(rejected)} blocked", "bad")}</div>')
        for i in rejected:
            html(f'<div class="panel rej">{tag(i["msg"], "bad")}<b style="font-size:1.15rem">{e(i["sender"])}</b>'
                 f'<div class="q">“{e(i["q"])}”</div><div class="reason">&#9432; Reason: {e(i["reason"])}</div></div>')
    html('<div class="sechead"><span class="t">Last run</span></div>')
    imp = last["impact"]
    full_tokens = next((u["tokens"]["total"] for u in state["updates"] if u["mode"] == "full"), None)
    pred = ""
    if "prediction_ok" in last:
        pred = (f' · prediction {", ".join(last["predicted_areas"]) or "none"} '
                + (tag("matched", "ok") if last["prediction_ok"] else tag("differed", "warn")))
    saving = (f'<div class="muted small">{last["tokens"]["total"]:,} tokens vs {full_tokens:,} for the full run</div>'
              if last["mode"] == "update" and full_tokens else "")
    html(f'<div class="panel"><b>{e(last["update_id"])}</b> <span class="muted">({e(last["mode"])})</span> · '
         f'{last["calls"]} of {5 if last["mode"] == "update" else 8} model calls · areas called: '
         f'{", ".join(last["call_areas"]) or "none"}{pred} · {last["tokens"]["total"]:,} tokens · {last["seconds"]} s'
         f'<div class="small" style="margin-top:6px">Recalculated: '
         f'{"".join(tag(a, "warn") for a in imp.get("changed") or []) or tag("none")} &nbsp; Untouched: '
         f'{"".join(tag(a) for a in imp.get("untouched") or []) or tag("none")}</div>{saving}'
         + ('<div style="color:var(--warn)">Run incomplete (limit or model failure): last valid plan kept.</div>'
            if last["incomplete"] else "") + "</div>")
    if d["assumptions"]:
        st.markdown("### Assumptions")
        html('<div class="panel small">' + "".join(f"<div>· {e(a)}</div>" for a in d["assumptions"])
             + '<div class="muted">The pack does not state these; they are planning defaults.</div></div>')

# ---------------- plan ----------------
with tabs[1]:
    ven = plan["venue"]["chosen"]
    st.markdown("### Venue")
    rows = ([{"option": ven["name"], "seats": int(ven["capacity"]), "cost": rs(ven["price"]),
              "status": f'<span>{tag("chosen", "ok")}</span>', "note": ", ".join(ven["features"]) or ""}] if ven else []) \
        + [{"option": a["name"], "seats": int(a["capacity"]), "cost": rs(a["price"]), "status": "alternative",
            "note": "fits, costs more"} for a in plan["venue"]["alternatives"]] \
        + [{"option": r["name"], "seats": int(r["capacity"]) if r["capacity"] else "-", "cost": rs(r["price"]),
            "status": f'<span>{tag("rejected", "bad")}</span>', "note": r["reason"]} for r in plan["venue"]["rejected"]]
    req = plan["venue"]["required_features"]
    html('<div class="panel">' + table(rows, ["option", "seats", "cost", "status", "note"], num=("seats", "cost"))
         + (f'<div class="muted small" style="margin-top:6px">Required: {", ".join(req)}</div>' if req else "") + "</div>")
    sources([(f"Venue {ven['name']}", ven["evidence"])] if ven else [])

    st.markdown("### Schedule")
    s = plan["schedule"]
    segs = []
    for blk in s["blocks"]:
        col = next((c for k, c in BLOCK_COLOR.items() if k in blk["name"].lower()), "#64748b")
        segs.append(f'<div style="flex:{blk["min"]};background:{col}" title="{e(blk["time"])} {e(blk["name"])}">'
                    f'{e(blk["name"])}</div>')
    html('<div class="panel"><div class="tl">' + "".join(segs) + "</div>"
         + table([{"time": x["time"], "block": x["name"], "min": x["min"], "source": src(x["evidence"])}
                  for x in s["blocks"]], ["time", "block", "min", "source"], num=("min",)) + "</div>")
    sources([(x["name"], x["evidence"]) for x in s["blocks"]])

    st.markdown("### Food")
    f = plan["food"]
    if f:
        frows = [{"meal": f["name"], "qty": f.get("main_qty", f["qty"]), "per head": rs(f["pph"]),
                  "cost": rs(f.get("main_qty", f["qty"]) * f["pph"]), "for": "everyone else" if f.get("splits") else "everyone"}]
        frows += [{"meal": x["name"], "qty": x["qty"], "per head": rs(x["pph"]), "cost": rs(x["qty"] * x["pph"]),
                   "for": x["diet"]} for x in f.get("splits", [])]
        frows += [{"meal": "delivery", "qty": "", "per head": "", "cost": rs(f["delivery"]), "for": ""}]
        html('<div class="panel">' + table(frows, ["meal", "qty", "per head", "cost", "for"], num=("qty", "per head", "cost"))
             + f'<div class="small" style="margin-top:6px"><b>{rs(f["cost"])}</b> for {f["qty"]} meals · people to feed '
             f'{f["people_to_feed"]} = {int(d["students"] or 0)} students + {int(d["staff"])} staff + {d["judges_used"]} judges'
             + (f' · alternatives: {", ".join(a["name"] + " " + rs(a["pph"]) for a in f["alternatives"])}' if f["alternatives"] else "")
             + "</div></div>")
        sources([("Meal price", f["evidence"])] + ([("Quantity", f["qty_source"])] if isinstance(f.get("qty_source"), dict) else [])
                + [(f"{x['diet']} meals", x["evidence"]) for x in f.get("splits", [])])

    st.markdown("### Judging")
    j = plan["judging"]
    html(f'<div class="panel"><div class="small" style="margin-bottom:8px">{j["judges_used"]} of {j["judges_available"]} '
         f'available judges used (need {j["judges_needed"]}) · max {j["max_teams_per_judge"]} teams each · '
         f'{j["minutes_per_team"]} min per team · {j["rounds"]} rounds · late offset {j["late_offset_min"]} min · '
         f'window {j["window_min"]} min</div><div class="roster">'
         + "".join(f"<div><b>{e(k)}</b>{e(', '.join(t.replace('Team ', 'T') for t in teams))}</div>"
                   for k, teams in j["allocation"].items()) + "</div></div>")
    sources([(i["k"].replace("_", " "), {"msg": i["msg"], "sender": i["sender"], "date": i["date"], "quote": i["q"]})
             for i in state["items"] if i["status"] == "accepted" and i["k"] in
             ("judges_available", "max_teams_per_judge", "minutes_per_team", "honorarium", "late_min", "judges_leaving_early")])

    st.markdown("### Budget")
    cap = float(b["budget"] or 0)
    com, res = float(b["committed"]), float(b.get("reserve") or 0)
    est = float(b["total"]) - com
    rem = max(cap - float(b["total"]) - res, 0)
    tot = max(cap, float(b["total"]) + res) or 1
    over = float(b["total"]) + res > cap
    # waterfall: start from the budget, each cost steps down from what is left, end at the remaining amount
    steps, run_ = [("Budget", cap, 0.0, cap, "#64748b")], cap
    for x in b["lines"] + ([{"item": "Reserve held back", "amount": res, "type": "reserve"}] if res else []):
        amt = float(x["amount"])
        col = {"committed": "#64748b", "reserve": "var(--warn)", "percent": "#7c3aed"}.get(x["type"], "var(--accent)")
        steps.append((x["item"], -amt, run_ - amt, run_, col))
        run_ -= amt
    steps.append(("Remaining", run_, min(run_, 0.0), max(run_, 0.0), "var(--bad)" if run_ < 0 else "var(--ok)"))
    lo_, hi_ = min(0.0, run_), max(cap, 1.0)
    span = hi_ - lo_
    wf = "".join(
        f'<div class="wf"><div class="wl">{e(label)}</div><div class="wt"><div style="left:{100 * (a - lo_) / span:.2f}%;'
        f'width:{max(100 * (z - a) / span, 0.3):.2f}%;background:{col}"></div></div>'
        f'<div class="wv">{rs(abs(val)) if label in ("Budget", "Remaining") else "−" + rs(abs(val))}</div></div>'
        for label, val, a, z, col in steps)
    html('<div class="panel"><div class="small muted" style="margin-bottom:6px">Budget waterfall</div>' + wf + "</div>")
    html('<div class="panel"><div class="bar">'
         f'<div style="width:{100 * com / tot:.1f}%;background:#64748b"></div>'
         f'<div style="width:{100 * est / tot:.1f}%;background:{"var(--bad)" if over else "var(--accent)"}"></div>'
         f'<div style="width:{100 * res / tot:.1f}%;background:var(--warn)"></div>'
         f'<div style="width:{100 * rem / tot:.1f}%;background:var(--ok);opacity:.45"></div></div>'
         f'<div class="legend"><span><i style="background:#64748b"></i>committed {rs(com)}</span>'
         f'<span><i style="background:var(--accent)"></i>planned {rs(est)}</span>'
         + (f'<span><i style="background:var(--warn)"></i>reserve {rs(res)}</span>' if res else "")
         + f'<span><i style="background:var(--ok);opacity:.45"></i>remaining {rs(b["remaining"])}</span></div>'
         + table([{"item": x["item"], "type": x["type"], "amount": rs(x["amount"]), "source": src(x["evidence"])}
                  for x in b["lines"]]
                 + [{"item": "<span><b>Total planned</b></span>", "type": "", "amount": rs(b["total"]), "source": ""}]
                 + ([{"item": "Reserve held back", "type": "reserve", "amount": rs(res), "source": src(b.get("reserve_evidence"))}] if res else [])
                 + [{"item": "Remaining", "type": "", "amount": rs(b["remaining"]), "source": ""}],
                 ["item", "type", "amount", "source"], num=("amount",))
         + "".join(f'<div class="small muted" style="margin-top:6px">{tag("not included", "info")}{e(o["item"])} '
                   f'{rs(o["amount"])} from {e(o["sender"])} ({e(o["msg"])}) — '
                   f'{"affordable" if o["affordable"] else "not affordable"}; pending approval</div>' for o in b["optional"])
         + "".join(f'<div class="small" style="color:var(--warn);margin-top:6px">{e(x)}</div>' for x in b.get("issues", []))
         + "</div>")
    sources([(x["item"], x["evidence"]) for x in b["lines"]])
    st.download_button("Download plan.txt", plan_text(state), "plan.txt")

# ---------------- messages ----------------
with tabs[2]:
    c1, c2 = st.columns([2, 1])
    q = c1.text_input("Search")
    sf = c2.multiselect("Status", sorted({m["status"] for m in state["messages"]}))
    counts = " ".join(tag(f"{STATUS_LABEL.get(s_, s_)} {sum(m['status'] == s_ for m in state['messages'])}",
                          STATUS_KIND.get(s_, "")) for s_ in sorted({m["status"] for m in state["messages"]}))
    html(f'<div style="margin-bottom:8px">{counts}</div>')
    rows = []
    for m in state["messages"]:
        if (q and q.lower() not in m["text"].lower()) or (sf and m["status"] not in sf):
            continue
        body = " ".join(l for l in m["text"].split("\n") if not l.lower().startswith(("message ", "from:", "date:")))
        rows.append({"id": m["id"], "status": f'<span>{tag(STATUS_LABEL.get(m["status"], m["status"]), STATUS_KIND.get(m["status"], ""))}</span>',
                     "from": m["sender"] or "?", "date": m["date"] or "-", "message": body.strip()[:220],
                     "reason": m["reason"] or ""})
    html('<div class="panel" style="padding:4px 10px">' + table(rows, ["id", "status", "from", "date", "message", "reason"]) + "</div>")
    with st.expander("Facts read from each message"):
        html(table([{"msg": i["msg"], "area": i["a"], "entity": i["e"], "key": i["k"], "value": i["v"], "kind": i["t"],
                     "status": f'<span>{tag(i["status"], STATUS_KIND.get(i["status"], ""))}</span>', "quote": i["q"]}
                    for i in state["items"]], ["msg", "area", "entity", "key", "value", "kind", "status", "quote"]))

# ---------------- trace ----------------
with tabs[3]:
    t = Trace(state["trace"]).totals()
    html(stats([("Model calls", t["calls"], "all runs"), ("Input tokens", f"{t['input']:,}", ""),
                ("Output tokens", f"{t['output']:,}", ""), ("Total tokens", f"{t['total']:,}", "as reported by the provider"),
                ("Planning calls", 0, "venue, schedule, food, judging, budget run in Python")]))
    if t["unavailable"]:
        st.warning(f"{t['unavailable']} call(s) with provider usage unavailable (never estimated)")
    biggest = max([r["total_tokens"] or 0 for r in state["trace"]] + [1])
    html('<div class="panel" style="padding:4px 10px">' + table(
        [{"#": r["n"], "run": r["update_id"], "area": r["area"], "model": r["model"],
          "in": f"{r['input_tokens']:,}" if r["input_tokens"] is not None else "unavailable",
          "out": f"{r['output_tokens']:,}" if r["output_tokens"] is not None else "unavailable",
          "total": f"{r['total_tokens']:,}" if r["total_tokens"] is not None else "unavailable",
          "meter": f'<span style="display:inline-block;height:8px;border-radius:4px;background:var(--accent);'
                   f'width:{int(120 * (r["total_tokens"] or 0) / biggest)}px"></span>',
          "s": r["duration_s"], "result": f'<span>{tag("ok", "ok") if r["ok"] else tag("failed", "bad")}</span>'}
         for r in state["trace"]],
        ["#", "run", "area", "model", "in", "out", "total", "meter", "s", "result"], num=("in", "out", "total", "s")) + "</div>")
    for r in reversed(state["trace"]):
        with st.expander(f"Call #{r['n']} · {r['area']} · {r['update_id']} · full input and output"):
            if r["error"]:
                st.error(r["error"])
            st.text("SYSTEM:\n" + r["input"]["system"])
            st.text("USER:\n" + r["input"]["user"])
            st.text("OUTPUT:\n" + (r["output"] or "(none)"))
    st.markdown("### Run history")
    html('<div class="panel" style="padding:4px 10px">' + table(
        [{"run": u["update_id"], "mode": u["mode"], "new": ", ".join(u["new_messages"]), "calls": u["calls"],
          "areas called": ", ".join(u["call_areas"]),
          "prediction": ("matched" if u.get("prediction_ok") else "differed") if "prediction_ok" in u else "-",
          "tokens": f"{u['tokens']['total']:,}", "s": u["seconds"],
          "changed": ", ".join(u["impact"].get("changed") or []), "rejected": len(u["rejected"])} for u in state["updates"]],
        ["run", "mode", "new", "calls", "areas called", "prediction", "tokens", "s", "changed", "rejected"],
        num=("calls", "tokens", "s", "rejected")) + "</div>")
    cols = st.columns(5)
    cols[0].download_button("plan.txt", plan_text(state), "plan.txt", width="stretch")
    cols[1].download_button("trace.txt", trace_text(state), "trace.txt", width="stretch")
    cols[2].download_button("submission.txt", submission_text(state), "submission.txt", width="stretch")
    for col, name in zip(cols[3:], ("plan.json", "trace.json")):
        p = Path(config.OUT_DIR) / name
        if p.exists():
            col.download_button(name, p.read_bytes(), name, width="stretch")

# ---------------- update ----------------
with tabs[4]:
    st.caption("Paste one or more new messages (blank line between messages). They go through the same pipeline as "
               "the pack. Prediction: only the reading step calls the model; Python re-plans the affected areas.")
    new = st.text_area("New message(s)", height=120, placeholder="Paste the message text exactly as received")
    if st.button("Process update", type="primary", disabled=not new.strip()):
        if run(new, "ui"):
            st.rerun()
    if last["mode"] == "update":
        before, after = key_numbers(state.get("previous_plan")), key_numbers(plan)
        rows = [(k, before.get(k), after[k]) for k in after if before.get(k) != after[k]]
        html(f'<div class="panel"><b>{e(last["update_id"])}</b> <span class="muted small">new: '
             f'{e(", ".join(last["new_messages"]) or "none")} · {last["calls"]} of 5 calls</span>'
             + ('<div class="diff" style="margin-top:10px">' + "".join(
                 f"<div>{e(k)}</div><div class='muted' style='text-decoration:line-through'>{e(a)}</div><div>→</div>"
                 f"<div class='new'>{e(bv)}</div>" for k, a, bv in rows) + "</div>"
                if rows else '<div class="small" style="margin-top:8px">No plan figures changed'
                + (" — the message was rejected and the previous valid plan was kept." if last["rejected"] else ".") + "</div>")
             + f'<div class="small" style="margin-top:8px">Recalculated: '
             f'{"".join(tag(a, "warn") for a in last["impact"].get("changed") or []) or tag("none")} &nbsp; Untouched: '
             f'{"".join(tag(a) for a in last["impact"].get("untouched") or [])}</div>'
             + "".join(f'<div class="panel rej" style="margin-top:10px">{tag("rejected", "bad")}“{e(x["quote"])}”'
                       f'<div class="muted small">{e(x["reason"])}</div></div>' for x in last["rejected"]) + "</div>")
