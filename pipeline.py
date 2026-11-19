"""One function for every run: process(path_or_text). Full run if no state, else an update with only
messages not seen before. Transactional: a new item that breaks a passing check is rejected and the
previous valid plan is kept."""
import copy
import re
import json
from datetime import datetime
from pathlib import Path

import config
from facts import NOT_FACT_KINDS, num, parse_date, resolve
from llm import Budgeter, Trace, call_model
from planner import build_plan
from reader import METRICS, header, read_messages, split_messages, text_hash
from validate import checkable

AREAS = ("venue", "schedule", "food", "judging", "budget")
# Dependency router: which plan areas an attribute can change. Deterministic and listed in the README.
ROUTES = {
    "students": AREAS, "team_size": AREAS, "staff": ("venue", "food", "budget"),
    "duration_min": ("schedule",), "start_time": ("schedule",), "location": ("venue",),
    "budget_total": ("budget",), "capacity": ("venue", "budget"), "price": ("venue", "budget"),
    "feature": ("venue", "budget"), "lacks_feature": ("venue", "budget"), "unavailable": ("venue", "budget"),
    "requires_feature": ("venue", "budget"), "rule": AREAS,
    "break_min": ("schedule",), "activity_min": ("schedule",),
    "price_per_head": ("food", "budget"), "delivery_fee": ("food", "budget"), "tier": ("food", "budget"),
    "order_qty": ("food", "budget"), "judges_available": ("judging", "venue", "food", "budget", "schedule"),
    "honorarium": ("judging", "budget"), "minutes_per_team": ("judging", "schedule"),
    "max_teams_per_judge": ("judging", "venue", "food", "budget", "schedule"),
    "late_min": ("judging", "schedule"), "expense": ("budget",), "optional_cost": ("budget",),
    "at_time": ("schedule",), "diet_count": ("food", "budget"), "judges_leaving_early": AREAS,
    "cost_per_team": ("budget",), "cost_per_student": ("budget",), "cost_per_person": ("budget",), "cost_per_judge": ("budget",),
    "percent_charge": ("budget",), "reserve_pct": ("budget",),
}


PREDICTED = ["reading"]   # stated before every run; a new kind of rule adds its own area (shown as a mismatch)


def _jsonable(o):
    from decimal import Decimal
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral() else float(o)
    raise TypeError(type(o))


def load_state():
    p = config.STATE_DIR / "state.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(state):
    config.STATE_DIR.mkdir(exist_ok=True)
    (config.STATE_DIR / "state.json").write_text(json.dumps(state, default=_jsonable, indent=1), encoding="utf-8")


def new_state():
    return {"messages": [], "items": [], "plan": None, "trace": [], "updates": [], "next_order": 0}


def _order_key(date_str, seq):
    d = parse_date(date_str)
    return (d[0] * 100 + d[1]) if d else 10_000 + seq


def _rule_fallback(item, budgeter, trace, update_id):
    """Escape hatch: a hard rule with no checkable form gets ONE call tagged with its area."""
    area = item["a"] if item["a"] in AREAS else "budget"
    system = ('Turn the requirement into JSON {"m":metric,"op":"eq|ne|lt|lte|gt|gte|requires|excludes|within",'
              '"v":value} using ONLY a metric from: ' + METRICS + '. Minutes for times. If impossible return {"m":null}.')
    out = call_model(budgeter, trace, area, system, item["q"], [item["msg"]], update_id, max_tokens=80)
    return out if out and out.get("m") else None


def _failing(plan):
    return {c["name"] for c in plan["validation"]["checks"] if c["result"] == "FAIL"}


def _unresolved(plan):
    return sum(c["result"] == "UNRESOLVED" for c in plan["validation"]["checks"])


def process(text, source="input"):
    """The single entry point used by plan.py and the Streamlit app."""
    state = load_state()
    mode = "full" if state is None or state["plan"] is None else "update"
    state = state or new_state()
    budgeter = Budgeter(mode)
    trace = Trace(state["trace"])
    calls_before = len(trace.records)
    update_id = f"U{len(state['updates'])}" if mode == "update" else "FULL"
    report = {"update_id": update_id, "mode": mode, "time": datetime.now().isoformat(timespec="seconds"),
              "source": source, "new_messages": [], "accepted": [], "rejected": [], "impact": {},
              "incomplete": False, "notes": []}
    try:
        seen = {m["hash"] for m in state["messages"]}
        blocks = [b for b in split_messages(text) if text_hash(b) not in seen]
        new = []
        for b in blocks:
            mid = f"M{len(state['messages']) + 1}"
            msg = {"id": mid, "text": b, "hash": text_hash(b), "update_id": update_id, "status": "pending",
                   "reason": "", "sender": "", "role": "", "date": ""}
            state["messages"].append(msg)
            new.append(msg)
            seen.add(msg["hash"])
        report["new_messages"] = [m["id"] for m in new]
        if not new:
            report["notes"].append("no new messages (all already processed)")
            return _finish(state, report, trace, budgeter, calls_before)

        known = sorted({f"{i['a']}:{i['e']}" for i in state["items"] if i["e"] and i["t"] not in NOT_FACT_KINDS})
        parsed = read_messages([{"id": m["id"], "text": m["text"]} for m in new],
                               known if mode == "update" else [], budgeter, trace, update_id)
        if parsed is None:
            for m in new:   # unread messages are not marked seen, so the next run retries them
                state["messages"].remove(m)
            report["incomplete"] = True
            report["notes"].append("reading call failed or ran out of time; previous plan kept")
            return _finish(state, report, trace, budgeter, calls_before)

        new_items = []
        for m in new:
            pm = parsed.get(m["id"])
            if pm is None:
                # not read (e.g. a malformed record was skipped): not marked as seen, so the next run reads it
                state["messages"].remove(m)
                report["notes"].append(f"{m['id']} could not be read this run; run the command again to read it")
                continue
            hdr = header(m["text"])
            pm.frm, pm.date = pm.frm or hdr["from"], pm.date or hdr["date"]
            m.update(sender=pm.frm, role=pm.role, date=pm.date)
            if pm.inj:
                report["notes"].append(f"{m['id']}: contains instructions to the system; ignored as instructions")
            if not pm.rel or not pm.it:
                m["status"], m["reason"] = "irrelevant", "no planning facts"
                continue
            for it in pm.it:
                state["next_order"] += 1
                item = {"id": f"{m['id']}.{len(new_items) + 1}", "msg": m["id"], "sender": pm.frm,
                        "role": pm.role if pm.role in config.AUTHORITY else "unknown", "date": pm.date,
                        "a": it.a, "e": it.e, "k": it.k, "v": it.v, "u": it.u, "t": it.t, "h": it.h,
                        "q": it.q, "c": it.c, "status": "", "reason": "", "locked": False,
                        # full run: chronological by stated date; update: arrives after everything known
                        "order": _order_key(pm.date, state["next_order"]) if mode == "full"
                        else 20_000 + state["next_order"]}
                _normalize(item)
                if item["k"] == "rule" or item["t"] == "rule":
                    if pm.inj:      # an instruction aimed at the system is never a planning rule
                        item["t"], item["k"] = "irrelevant", "other"
                    elif config.AUTHORITY.get(item["role"], 0) < config.AUTHORITY["vendor"]:
                        item["t"] = "suggestion"     # a request from someone without authority is not binding
                new_items.append(item)
            _venue_prices(new_items, m["id"])

        # escape hatch for rules the reader could not express (limited by the Budgeter)
        for it in new_items:
            if it["k"] == "rule" and it["h"] and not checkable(it["c"]):
                c = _rule_fallback(it, budgeter, trace, update_id)
                if c:
                    it["c"] = c

        _transaction(state, new_items, mode, report)
        for m in new:
            if m["status"] == "pending":
                mine = [i for i in state["items"] if i["msg"] == m["id"]]
                rej = [i for i in mine if i["status"] == "rejected"]
                if rej and len(rej) == len(mine):
                    m["status"], m["reason"] = "rejected", "; ".join(i["reason"] for i in rej)
                elif rej:
                    m["status"], m["reason"] = "partly accepted", "; ".join(i["reason"] for i in rej)
                elif mine and all(i["status"] == "superseded" for i in mine):
                    m["status"], m["reason"] = "superseded", mine[0]["reason"]
                elif mine and all(i["status"] in ("noted", "optional") for i in mine):
                    m["status"], m["reason"] = "noted", mine[0]["reason"]
                else:
                    m["status"] = "accepted"
        for m in state["messages"]:   # older messages can become superseded by new ones
            mine = [i for i in state["items"] if i["msg"] == m["id"]]
            if m["status"] == "accepted" and mine and all(i["status"] == "superseded" for i in mine):
                m["status"], m["reason"] = "superseded", mine[0]["reason"]
        return _finish(state, report, trace, budgeter, calls_before)
    except Exception as e:
        report["incomplete"] = True
        report["notes"].append(f"error: {type(e).__name__}: {e}; previous plan kept")
        if type(e).__name__ == "ConfigError":
            raise
        return _finish(state, report, trace, budgeter, calls_before)


def _venue_prices(items, msg_id):
    """An 'expense' for an entity the same message gives a seating capacity is that venue's price."""
    venues = {i["e"].strip().lower() for i in items if i["msg"] == msg_id and i["k"] == "capacity"}
    for i in items:
        if i["msg"] == msg_id and i["k"] == "expense" and i["e"].strip().lower() in venues:
            i["a"], i["k"] = "venue", "price"
        # "Hall B has a generator": a facility of a listed venue, not a requirement of the event
        if i["msg"] == msg_id and i["k"] == "requires_feature" and i["e"].strip().lower() in venues:
            i["k"], i["t"] = "feature", "fact"


def _normalize(item):
    """Fix common key misuse by a small model (generic, not pack-specific)."""
    if item["k"] == "at_time" and set(item["e"].lower().split()) & {"end", "event", "finish", "close", "closing",
                                                                       "building", "start", "begin"}:
        # a time for the whole event, not for one block: start time or an "end by" rule
        from planner import clock
        t = clock(re.sub(r"^(end|by|until)\s*", "", str(item["v"]).lower()))
        if t is not None and ("start" in item["e"].lower() or "begin" in item["e"].lower()):
            item["a"], item["k"], item["e"] = "event", "start_time", ""
        elif t is not None:
            item["a"], item["k"], item["t"], item["h"] = "schedule", "rule", "rule", True
            item["c"] = {"m": "end_min", "op": "lte", "v": t}
    if item["t"] == "irrelevant":
        item["k"] = "other"
    elif item["k"] == "expense" and "deliver" in item["e"].lower():
        item["a"], item["k"], item["e"] = "food", "delivery_fee", "delivery"   # a caterer's delivery charge
    elif item["t"] == "rule" and item["c"] and item["k"] not in ("requires_feature", "break_min", "activity_min"):
        item["k"] = "rule"                       # a checkable requirement is a rule, whatever key was used
    elif item["k"] == "feature" and (item["t"] == "rule" or
                                     item["e"].strip().lower() in ("need", "required", "requirement", "")):
        item["k"] = "requires_feature"           # a demanded facility, not a property of one venue


def _transaction(state, new_items, mode, report):
    old_plan = state["plan"]
    old_valid = old_plan is not None and old_plan["validation"]["status"] == "VALID"
    items = copy.deepcopy(state["items"]) + copy.deepcopy(new_items)
    resolve(items)
    plan = build_plan(items)
    new_ids = {i["id"] for i in new_items}
    baseline_fail = _failing(old_plan) if old_plan else set()
    # Try to make the plan valid by rejecting new items that break checks (latest first).
    if plan["validation"]["status"] == "INVALID":
        for it in sorted([i for i in items if i["id"] in new_ids and i["t"] not in NOT_FACT_KINDS
                          and i["status"] == "accepted"], key=lambda x: -x["order"]):
            before = _failing(plan) - baseline_fail if mode == "update" else _failing(plan)
            it["locked"], it["status"] = True, "rejected"
            resolve(items)
            trial = build_plan(items)
            after = _failing(trial) - baseline_fail if mode == "update" else _failing(trial)
            # a rejection must fix a failure without making the plan lose a fact it needs
            if len(after) < len(before) and _unresolved(trial) <= _unresolved(plan):
                broke = [c for c in plan["validation"]["checks"] if c["result"] == "FAIL" and c["name"] not in after]
                it["reason"] = "would break: " + "; ".join(f"{c['name']} ({c['detail']})" for c in broke)
                plan = trial
                if plan["validation"]["status"] != "INVALID":
                    break
            else:
                it["locked"], it["status"] = False, ""
                resolve(items)
    if mode == "update" and old_valid and plan["validation"]["status"] != "VALID":
        # keep the last valid plan: reject everything this update tried to change
        for it in items:
            if it["id"] in new_ids and it["status"] == "accepted":
                it["locked"], it["status"] = True, "rejected"
                it["reason"] = "update would leave the plan " + plan["validation"]["status"] + ": " + \
                    "; ".join(f"{c['name']}: {c['detail']}" for c in plan["validation"]["checks"]
                              if c["result"] in ("FAIL", "UNRESOLVED"))
        resolve(items)
        plan = build_plan(items)
    state["items"] = items
    report["impact"] = _impact(old_plan, plan, [i for i in items if i["id"] in new_ids])
    state["previous_plan"] = old_plan
    state["plan"] = plan
    report["accepted"] = [i["id"] for i in items if i["id"] in new_ids and i["status"] == "accepted"]
    report["rejected"] = [{"id": i["id"], "msg": i["msg"], "quote": i["q"], "reason": i["reason"]}
                          for i in items if i["id"] in new_ids and i["status"] == "rejected"]


def _impact(old, new, new_items):
    routed = sorted({a for i in new_items if i["status"] in ("accepted", "optional")
                     for a in ((i["a"],) if i["k"] == "rule" and i["a"] in AREAS else ROUTES.get(i["k"], ()))})
    if old is None:
        return {"routed": list(AREAS), "changed": list(AREAS), "untouched": []}
    dump = lambda p, a: json.dumps(p.get(a), default=_jsonable, sort_keys=True)
    changed = [a for a in AREAS if dump(old, a) != dump(new, a)]
    return {"routed": routed, "changed": changed, "untouched": [a for a in AREAS if a not in changed]}


def _finish(state, report, trace, budgeter, calls_before):
    report["incomplete"] = report["incomplete"] or budgeter.incomplete
    run_recs = trace.records[calls_before:]
    report["calls"] = len(run_recs)
    report["call_areas"] = sorted({r["area"] for r in run_recs})
    # predict-then-verify: the routing rule says only 'reading' calls the model (if anything is new)
    report["predicted_areas"] = PREDICTED if report["new_messages"] else []
    report["prediction_ok"] = report["call_areas"] == report["predicted_areas"]
    report["tokens"] = trace.totals(run_recs)
    report["seconds"] = round(budgeter.elapsed(), 2)
    state["trace"] = trace.records
    state["updates"].append(report)
    save_state(state)
    from report import write_outputs
    write_outputs(state)
    return state, report


def reset():
    p = config.STATE_DIR / "state.json"
    if p.exists():
        p.unlink()
