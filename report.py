"""Readable plan + trace text, file outputs (out/), and rich terminal printing."""
import json

import config


def _j(o):
    from decimal import Decimal
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral() else float(o)
    raise TypeError(type(o))


def rs(x):
    return "-" if x is None else f"Rs {int(x):,}"


def model_list_note():
    if config.ALLOWED_MODELS:
        return f"model on organizers' small-model list: yes (ALLOWED_MODELS={', '.join(config.ALLOWED_MODELS)})"
    return "small-model list: none published by the organizers; single model chosen by the team"


def plan_text(state):
    p = state["plan"]
    if not p:
        return "No plan yet.\n"
    v = p["validation"]
    d, s, b = p["derived"], p["schedule"], p["budget"]
    L = [f"EVENT PLAN — status: {v['status']}", "=" * 60,
         f"Students {d['students']} | team size {d['team_size']} | teams {d['teams']} | staff {d['staff']} | "
         f"judges used {d['judges_used']} | headcount {d['headcount']}", ""]
    ven = p["venue"]["chosen"]
    L.append("VENUE")
    L.append(f"  Chosen: {ven['name']} — seats {int(ven['capacity'])}, {rs(ven['price'])}"
             + (f", features: {', '.join(ven['features'])}" if ven["features"] else "") if ven else "  none")
    if p["venue"]["required_features"]:
        L.append(f"  Required: {', '.join(p['venue']['required_features'])}")
    for a in p["venue"]["alternatives"]:
        L.append(f"  Alternative: {a['name']} ({int(a['capacity'])} seats, {rs(a['price'])})")
    for r in p["venue"]["rejected"]:
        L.append(f"  Rejected: {r['name']} — {r['reason']}")
    L += ["", "SCHEDULE"]
    for blk in s["blocks"]:
        L.append(f"  {blk['time']:<16} {blk['name']} ({blk['min']} min)")
    for n in (s.get("issues") or {}).get("notes", []):
        L.append(f"  note: {n}")
    L += ["", "FOOD"]
    f = p["food"]
    if f:
        if f.get("splits"):
            L.append(f"  {f['main_qty']} x {f['name']} @ {rs(f['pph'])}")
            for sp in f["splits"]:
                L.append(f"  {sp['qty']} x {sp['name']} @ {rs(sp['pph'])} ({sp['diet']})")
            L.append(f"  + delivery {rs(f['delivery'])} = {rs(f['cost'])} for {f['qty']} people")
        else:
            L.append(f"  {f['qty']} x {f['name']} @ {rs(f['pph'])} + delivery {rs(f['delivery'])} = {rs(f['cost'])}")
        L.append(f"  People to feed: {f['people_to_feed']} ({d['students']} students + {d['staff']} staff + "
                 f"{d['judges_used']} judges)")
        for a in f["alternatives"]:
            L.append(f"  Alternative: {a['name']} @ {rs(a['pph'])}")
    j = p["judging"]
    L += ["", "JUDGING",
          f"  {j['judges_used']} of {j['judges_available']} judges used (need {j['judges_needed']}), "
          f"max {j['max_teams_per_judge']} teams each, {j['minutes_per_team']} min/team, "
          f"{j['rounds']} rounds, late offset {j['late_offset_min']} min, window {j['window_min']} min"]
    for name, teams in j["allocation"].items():
        L.append(f"  {name}: {', '.join(teams)}")
    L += ["", "BUDGET"]
    for l in b["lines"]:
        L.append(f"  {l['type']:<10} {l['item']:<45} {rs(l['amount']):>14}")
    L.append(f"  {'TOTAL':<56} {rs(b['total']):>14}")
    if b.get("reserve"):
        L.append(f"  {'Reserve held back (not spent)':<56} {rs(b['reserve']):>14}")
    L.append(f"  {'Budget':<56} {rs(b['budget']):>14}")
    L.append(f"  {'Remaining':<56} {rs(b['remaining']):>14}")
    if b["budget"] is not None:
        fits = b["total"] + (b.get("reserve") or 0) <= b["budget"]
        L.append(f"  Fits within budget: {'YES' if fits else 'NO'} (total {rs(b['total'])} against {rs(b['budget'])})")
    for o in b["optional"]:
        L.append(f"  optional (not in total): {o['item']} {rs(o['amount'])} from {o['sender']} — "
                 + ("affordable" if o["affordable"] else "NOT affordable"))
    if d["assumptions"]:
        L += ["", "ASSUMPTIONS (pack silent)"] + [f"  - {a}" for a in d["assumptions"]]
    L += ["", "CHECKS"] + [f"  [{c['result']}] {c['name']}: {c['detail']}" for c in v["checks"]]
    L += ["", "MESSAGES"]
    for m in state["messages"]:
        L.append(f"  {m['id']} [{m['status']}] {m['sender'] or '?'} {m['date']}"
                 + (f" — {m['reason']}" if m["reason"] else ""))
    rej = [i for i in state["items"] if i["status"] == "rejected"]
    if rej:
        L += ["", "REJECTED ITEMS"] + [f"  {i['id']} \"{i['q']}\" — {i['reason']}" for i in rej]
    sup = [i for i in state["items"] if i["status"] == "superseded"]
    if sup:
        L += ["", "SUPERSEDED"] + [f"  {i['id']} \"{i['q']}\" — {i['reason']}" for i in sup]
    L += ["", "UPDATES"]
    for u in state["updates"]:
        L.append(f"  {u['update_id']} ({u['mode']}) new={u['new_messages']} calls={u['calls']} "
                 f"areas={u['call_areas']} tokens={u['tokens']['total']} {u['seconds']}s "
                 f"changed={u['impact'].get('changed')} untouched={u['impact'].get('untouched')}"
                 + (" INCOMPLETE" if u["incomplete"] else ""))
        for n in u["notes"]:
            L.append(f"     note: {n}")
    return "\n".join(L) + "\n"


def _tok(r):
    """One call's provider-reported usage; partial usage is shown as reported, never estimated."""
    if all(r.get(k) is None for k in ("input_tokens", "output_tokens", "total_tokens")):
        return "tokens: unavailable (provider reported none)"
    show = lambda v: "n/a" if v is None else v
    extra = f" (cached input {r['cached_input_tokens']})" if r.get("cached_input_tokens") else ""
    note = f" [{r['usage_note']}]" if r.get("usage_note") else ""
    return (f"in={show(r.get('input_tokens'))} out={show(r.get('output_tokens'))} "
            f"total={show(r.get('total_tokens'))}{extra}{note}")


def _totals_line(t, label="model calls"):
    parts = [f"TOTAL: {t['calls']} {label} | input {t['input']} | output {t['output']} | total {t['total']} tokens"]
    if t["failed"]:
        parts.append(f"{t['failed']} failed")
    if t["retries"]:
        parts.append(f"{t['retries']} retries (counted above)")
    if t["unavailable"]:
        parts.append(f"{t['unavailable']} calls with usage unavailable (not counted as 0)")
    if t["cached_input"]:
        parts.append(f"{t['cached_input']} input tokens served from provider cache")
    if t["by_area"]:
        parts.append("by area: " + ", ".join(f"{a} {n}" for a, n in sorted(t["by_area"].items())))
    return " | ".join(parts)


def _per_update(state):
    from llm import Trace
    out = []
    for u in state["updates"]:
        t = Trace([r for r in state["trace"] if r["update_id"] == u["update_id"]]).totals()
        out.append(f"  {u['update_id']:5} ({u['mode']}): {t['calls']} calls, input {t['input']}, output {t['output']}, "
                   f"total {t['total']} tokens, {u['seconds']} s" + (f", {t['failed']} failed" if t["failed"] else ""))
    return out


def trace_text(state):
    from llm import Trace
    recs = state["trace"]
    L = [f"TRACE — {model_list_note()}", "=" * 60]
    for r in recs:
        tok = _tok(r)
        L += [f"#{r['n']} [{r['area']}] model={r['model']} {r['timestamp']} {r['duration_s']}s "
              f"{'OK' if r['ok'] else 'FAILED'} update={r['update_id']} msgs={','.join(r['message_ids'])} {tok}",
              "--- input (system) ---", r["input"]["system"], "--- input (user) ---", r["input"]["user"],
              "--- output ---", r["output"] or "(none)"]
        if r["error"]:
            L.append(f"--- error --- {r['error']}")
        L.append("-" * 60)
    for u in state["updates"]:
        rj = u["rejected"]
        for x in rj:
            L.append(f"REJECTED {x['id']} ({u['update_id']}): \"{x['quote']}\" — {x['reason']}")
    t = Trace(recs).totals()
    L.append(f"TOTAL: {t['calls']} model calls | input {t['input']} | output {t['output']} | total {t['total']} tokens"
             + (f" | {t['unavailable']} calls with usage unavailable" if t["unavailable"] else ""))
    return "\n".join(L) + "\n"


def write_outputs(state):
    config.OUT_DIR.mkdir(exist_ok=True)
    (config.OUT_DIR / "plan.json").write_text(json.dumps(
        {"plan": state["plan"], "messages": state["messages"], "items": state["items"],
         "updates": state["updates"]}, default=_j, indent=1), encoding="utf-8")
    (config.OUT_DIR / "trace.json").write_text(json.dumps(
        {"note": model_list_note(), "calls": state["trace"],
         "totals": __import__("llm").Trace(state["trace"]).totals()}, indent=1), encoding="utf-8")
    (config.OUT_DIR / "plan.txt").write_text(plan_text(state), encoding="utf-8")
    (config.OUT_DIR / "trace.txt").write_text(trace_text(state), encoding="utf-8")
    (config.OUT_DIR / "submission.txt").write_text(submission_text(state), encoding="utf-8")


def trace_summary(state):
    """One line per AI call (number, model, purpose, tokens) plus the total."""
    from llm import Trace
    purpose = {"reading": "reading messages"}
    L = ["TRACE SUMMARY (one line per AI call)", "=" * 60]
    for r in state["trace"]:
        tok = _tok(r)
        L.append(f"Call {r['n']:>2} | model {r['model']} | for: {purpose.get(r['area'], r['area'])} "
                 f"[{r['area']}] | {tok} | {'ok' if r['ok'] else 'FAILED: ' + (r['error'] or '')[:60]}")
    L.append(_totals_line(Trace(state["trace"]).totals(), "AI calls"))
    return "\n".join(L) + "\n"


def submission_text(state):
    """The file to upload: final plan + one-line-per-call trace + full trace with totals."""
    return ("MINDTOPLAN SUBMISSION\n" + "#" * 60 + "\n\n" + plan_text(state) + "\n" + "#" * 60 + "\n\n"
            + trace_summary(state) + "\n" + "#" * 60 + "\nFULL TRACE (inputs and outputs)\n\n" + trace_text(state))


def print_run(state, report):
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    con = Console()
    run_recs = [r for r in state["trace"] if r["update_id"] == report["update_id"]]
    t = Table(title=f"Model calls this run ({report['update_id']}, {report['mode']}) — {model_list_note()}")
    for c in ("#", "area", "model", "in", "out", "total", "s", "ok"):
        t.add_column(c)
    for r in run_recs:
        na = "unavailable"
        t.add_row(str(r["n"]), r["area"], r["model"], str(r["input_tokens"] if r["total_tokens"] is not None else na),
                  str(r["output_tokens"] if r["total_tokens"] is not None else na),
                  str(r["total_tokens"] if r["total_tokens"] is not None else na), str(r["duration_s"]),
                  "OK" if r["ok"] else f"FAIL {r['error'][:40]}")
    for r in run_recs:   # full input/output is required in the printed trace
        con.print(f"[bold]#{r['n']} [{r['area']}] {r['model']}[/bold]")
        con.print("[dim]input (system):[/dim]", r["input"]["system"], markup=False, highlight=False)
        con.print("[dim]input (user):[/dim]", r["input"]["user"], markup=False, highlight=False)
        con.print("[dim]output:[/dim]", r["output"] or "(none)", markup=False, highlight=False)
    from rich.text import Text
    con.print(Panel(Text(plan_text(state)), title="Plan"))
    con.print(t)
    for x in report["rejected"]:
        con.print(f"[red]REJECTED[/red] {x['id']} \"{x['quote']}\" — {x['reason']}", highlight=False)
    con.print(f"Messages detected in this input: {len(report['new_messages'])} new "
              f"({', '.join(report['new_messages']) or 'none'})", highlight=False)
    if "prediction_ok" in report:
        mark = "✓ matches" if report["prediction_ok"] else "✗ differs"
        con.print(f"Prediction check: predicted {report['predicted_areas']} → actual {report['call_areas']} {mark}",
                  highlight=False)
    imp = report["impact"]
    con.print(f"Impact: routed={imp.get('routed')} changed={imp.get('changed')} untouched={imp.get('untouched')}")
    status = state["plan"]["validation"]["status"] if state["plan"] else "NO PLAN"
    color = {"VALID": "green", "INVALID": "red"}.get(status, "yellow")
    con.print(f"[bold {color}]PLAN STATUS: {status}[/bold {color}]")
    if report["incomplete"]:
        con.print("[bold yellow]WARNING: run incomplete (time/call limit or model failure); last valid plan kept[/bold yellow]")
    rt, at = report["tokens"], __import__("llm").Trace(state["trace"]).totals()
    con.print(f"[bold]This run: {report['calls']} model calls | input {rt['input']} | output {rt['output']} | "
              f"total {rt['total']} tokens | {report['seconds']} s[/bold]")
    con.print(f"[bold]All runs: {at['calls']} model calls | input {at['input']} | output {at['output']} | "
              f"total {at['total']} tokens[/bold]"
              + (f" | usage unavailable on {at['unavailable']} calls" if at["unavailable"] else "")
              + (f" | {at['retries']} retries, {at['failed']} failed" if at["failed"] or at["retries"] else ""))
