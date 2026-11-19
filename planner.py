"""Derived numbers and the five area planners. Pure Python, no model calls, money in Decimal."""
import math
import re
from decimal import Decimal

import config
from facts import View, norm, num, same_facility
from validate import validate


def D(x):
    return Decimal(str(x if x is not None else 0)).quantize(Decimal("1"))


def ev(f):
    """Evidence for a decision: where it came from."""
    return {"msg": f["msg"], "sender": f["sender"], "date": f["date"], "quote": f["q"]} if f else None


def derive(v, judges=None):
    """judges: force a judge count (used by the plan search); None = the minimum needed."""
    d = {"assumptions": [], "missing": []}
    for k in ("students", "team_size", "staff", "duration_min", "budget_total"):
        d[k] = v.val(k)
    for k in ("judges_available", "max_teams_per_judge", "minutes_per_team", "honorarium"):
        d[k] = v.val(k, "judging")
    for k in ("students", "duration_min", "budget_total"):
        if d[k] is None:
            d["missing"].append(k)
    d["staff"] = d["staff"] or 0
    s, ts = d["students"], d["team_size"]
    d["teams"] = math.ceil(s / ts) if s and ts else None
    # judges who leave before judging ends cannot judge
    d["judges_leaving"] = int(sum(num(f["v"]) or 0 for f in v.all("judges_leaving_early")))
    d["judges_confirmed"] = d["judges_available"]
    if d["judges_available"] is not None and d["judges_leaving"]:
        d["judges_available"] = max(d["judges_available"] - d["judges_leaving"], 0)
    ja, mx = d["judges_available"], d["max_teams_per_judge"]
    if d["teams"] and mx:
        d["judges_needed"] = math.ceil(d["teams"] / mx)
    else:
        d["judges_needed"] = ja
    d["judges_used"] = min(x for x in (d["judges_needed"], ja) if x is not None) \
        if (d["judges_needed"] is not None or ja is not None) else None
    if judges is not None:
        d["judges_used"] = judges
    lates = [num(f["v"]) or 0 for f in v.all("late_min")]
    d["late_max"] = max(lates) if lates else 0
    if d["teams"] and d["judges_used"] and d["minutes_per_team"]:
        d["rounds"] = math.ceil(d["teams"] / d["judges_used"])
        d["judging_window"] = int(d["rounds"] * d["minutes_per_team"] + d["late_max"])
    else:
        d["rounds"], d["judging_window"] = None, None
    # everyone on site eats and needs a seat: students + staff + judges actually used
    d["headcount"] = int((s or 0) + d["staff"] + (d["judges_used"] or 0))
    return d


def venue_candidates(v, d):
    needs = [norm(f["v"]) for f in v.all("requires_feature")]
    opts = v.options("venue", {"capacity", "price", "feature", "lacks_feature", "unavailable"})
    ok, rejected = [], []
    for key, o in opts.items():
        if "capacity" not in o and "price" not in o:
            continue                                  # only a remark about a facility, not a venue offer
        cap = num(o["capacity"]["v"]) if "capacity" in o else None
        price = num(o["price"]["v"]) if "price" in o else None
        lacks = [norm(f["v"]) for f in o.get("lacks_feature", [])]
        feats = [norm(f["v"]) for f in o.get("feature", [])
                 if not any(norm(f["v"]) in x or x in norm(f["v"]) for x in lacks)]
        why = None
        if "unavailable" in o:
            why = "not available"
        elif cap is None or price is None:
            why = "capacity or price unknown"
        elif cap < d["headcount"]:
            why = f"seats {int(cap)} < headcount {d['headcount']}"
        else:
            lacking = [n for n in needs if not any(same_facility(n, f) for f in feats)]
            if lacking:
                why = f"lacks required: {', '.join(lacking)}"
        row = {"name": o["_name"], "capacity": cap, "price": price, "features": feats,
               "evidence": ev(o.get("capacity") or o.get("price"))}
        (rejected if why else ok).append({**row, "reason": why} if why else row)
    ok.sort(key=lambda r: r["price"])
    return ok, rejected, needs


def food_options(v):
    opts = v.options("food", {"price_per_head", "delivery_fee", "tier", "order_qty"})
    # a delivery fee not tied to a priced option applies to every option (caterer-wide charge)
    general = [num(o["delivery_fee"]["v"]) for o in opts.values()
               if "delivery_fee" in o and "price_per_head" not in o]
    general_fee = max(general) if general else 0
    out = []
    for key, o in opts.items():
        if "price_per_head" not in o:
            continue
        tier = norm(o["tier"]["v"]) if "tier" in o else ""
        out.append({"name": o["_name"], "pph": num(o["price_per_head"]["v"]),
                    "delivery": num(o["delivery_fee"]["v"]) if "delivery_fee" in o else general_fee,
                    "delivery_stated": "delivery_fee" in o or bool(general),
                    "tier": tier, "evidence": ev(o["price_per_head"])})
    # preference: the standard option first, then cheaper ones (fallback when budget fails)
    # untagged options: fuller (pricier) meal first; build_plan falls back to cheaper ones if the budget fails
    rank = lambda r: 0 if "standard" in r["tier"] or "standard" in norm(r["name"]) else \
        {"": 1, "premium": 2, "basic": 3}.get(r["tier"], 1)
    out.sort(key=lambda r: (rank(r), r["pph"] if rank(r) != 1 else -r["pph"]))
    return out


def schedule_plan(v, d):
    total = int(d["duration_min"] or 0)
    named = {norm(f["e"]): (f["e"], int(num(f["v"]) or 0), f) for f in v.all("activity_min")}

    def pick(word, label, default):
        for k, (name, m, f) in named.items():
            if word in k:
                named.pop(k)
                return name, m, f
        d["assumptions"].append(f"{label} {default} min (not stated in messages; planning default)")
        return label, default, None

    opening = pick("open", "opening", config.DEFAULT_MINUTES["opening"])
    meal = pick("lunch", "lunch", 0) if any("lunch" in k for k in named) \
        else pick("meal", "meal break", config.DEFAULT_MINUTES["meal"])
    closing = pick("clos", "closing", config.DEFAULT_MINUTES["closing"])
    judging_m = d["judging_window"] or 0
    for k in [k for k in named if "judg" in k]:
        judging_m = max(judging_m, named.pop(k)[1])
    breaks = [(f["e"], int(num(f["v"]) or 0), f) for f in v.all("break_min")]
    others = list(named.values())
    fixed = opening[1] + meal[1] + closing[1] + judging_m + sum(b[1] for b in breaks) + sum(o[1] for o in others)
    hacking = total - fixed
    h1 = hacking // 2 if hacking > 0 else 0
    h2 = hacking - h1 if hacking > 0 else 0
    seq = [("Opening", opening[1], opening[2]), ("Hacking (part 1)", h1, None)]
    seq += [(b[0].capitalize(), b[1], b[2]) for b in breaks]
    seq += [(meal[0].capitalize(), meal[1], meal[2])]
    seq += [(o[0].capitalize(), o[1], o[2]) for o in others]
    seq += [("Hacking (part 2)", h2, None), ("Judging", judging_m, None), ("Closing", closing[1], closing[2])]
    st = v.get("start_time")
    start = clock(st["v"]) if st else None
    if start is None:
        st, start = None, 0
    anchors = [(f, anchor_spec(f["v"])) for f in v.all("at_time")]
    issues = {"fail": [], "unresolved": []}
    needs_clock = any(sp is None or not sp["offset"] for _, sp in anchors)
    if anchors and (st or not needs_clock):
        blocks, hacking = _anchored(seq, anchors, start, total, issues)
    else:
        if anchors:
            issues["unresolved"].append("fixed clock times given but the event start time is unknown")
        blocks, t = [], start
        for name, m, f in seq:
            if m <= 0:
                continue
            blocks.append({"name": name, "start": t, "end": t + m, "min": m, "evidence": ev(f)})
            t += m
    fmt = (lambda x: f"{x // 60:02d}:{x % 60:02d}") if st else (lambda x: f"T+{x // 60}:{x % 60:02d}")
    for b in blocks:
        b["time"] = f"{fmt(b['start'])}-{fmt(b['end'])}"
    end = blocks[-1]["end"] if blocks else start
    return {"blocks": blocks, "total_min": end - start, "target_min": total, "hacking_min": max(hacking, 0),
            "meal_min": meal[1], "judging_min": judging_m, "start_min": start, "end_min": end, "issues": issues,
            "breaks": [{"name": b[0], "min": b[1], "hard": b[2]["h"], "evidence": ev(b[2])} for b in breaks]}


def clock(s):
    """'13:30', '1:30 pm', '1 pm' -> minutes after midnight, or None."""
    s = str(s or "").strip().lower()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3) == "pm" and h < 12:
        h += 12
    if m.group(3) == "am" and h == 12:
        h = 0
    return h * 60 + mi if h < 24 and mi < 60 else None


def anchor_spec(v):
    """'13:30' start | 'end 15:00' / 'by 15:00' | '+90' minutes after event start (also 'end +90')
    | '12:00-14:00' or 'between 12:00 and 14:00' window. Returns None if unreadable."""
    s = str(v or "").strip().lower()
    kind = "start"
    m = re.match(r"^(end|ends|by|until|till|finish(?:es)?)\b\s*(?:at\s*)?(.*)$", s)
    if m:
        kind, s = "end", m.group(2).strip()
    m = re.match(r"^\+\s*(\d+)\s*(m|min|mins|minutes)?$", s) or re.match(r"^(\d+)\s*(m|min|mins|minutes)\b", s)
    if m:
        return {"kind": kind, "a": int(m.group(1)), "offset": True}
    parts = re.split(r"\s*(?:-|–|to|and)\s*", s.replace("between", "").strip())
    if len(parts) == 2 and clock(parts[0]) is not None and clock(parts[1]) is not None:
        return {"kind": "window", "a": clock(parts[0]), "b": clock(parts[1]), "offset": False}
    t = clock(s)
    return {"kind": kind, "a": t, "offset": False} if t is not None else None


def _words(s):
    return {w for w in norm(s).split() if len(w) > 2 and w not in ("break", "time", "session", "the", "and", "for")} | \
        ({"meal", "lunch", "food"} if any(x in norm(s) for x in ("lunch", "meal", "food", "khana")) else set())


def _diet_words(s):
    generic = {"meal", "meals", "lunch", "food", "boxes", "option", "pack", "wala", "khana", "dinner", "people"}
    return {w for w in norm(s).split() if len(w) > 2 and w not in generic}


def _diet_match(need, option_words):
    """'veg' matches 'vegetarian': whole words or one a prefix of the other."""
    return any(a.startswith(b) or b.startswith(a) for a in _diet_words(need) for b in option_words)


def _anchored(seq, anchors, start, total, issues):
    """Pin blocks with a stated clock time; opening at the start, judging+closing at the end; other breaks
    float from the middle; hacking fills every gap. Overlaps or out-of-window times are reported."""
    end = start + total
    items = [{"name": n, "min": m, "f": f} for n, m, f in seq if m > 0 and not n.startswith("Hacking")]
    for f, sp in anchors:
        if sp is None and not any(ch.isdigit() for ch in str(f["v"])):
            continue   # no clock time at all (e.g. a format placeholder echoed by the model): nothing to pin
        hit = next((it for it in items if _words(it["name"]) & _words(f["e"])), None)
        if hit is None:
            issues["unresolved"].append(f"time for '{f['e']}' ({f['v']}) matches no schedule block")
        elif sp is None:
            issues["unresolved"].append(f"cannot read time '{f['v']}' for {f['e']}")
        elif "at" in hit or "window" in hit:
            issues["fail"].append(f"conflicting times for {hit['name']}: {f['v']}")
        else:
            hit["anchor"] = f
            t = start + sp["a"] if sp["offset"] else sp["a"]
            if sp["kind"] == "window":
                hit["window"] = (sp["a"], sp["b"])
            else:
                hit["at"] = t if sp["kind"] == "start" else t - hit["min"]
    pinned = []
    by = {it["name"].lower(): it for it in items}
    clos, judg, opn = by.get("closing"), by.get("judging"), by.get("opening")
    if opn and "at" not in opn:
        opn["at"] = start
    if clos and "at" not in clos:
        clos["at"] = end - clos["min"]
    pinned = [it for it in items if "at" in it]
    if judg and "at" not in judg:
        # judging goes in the latest free slot before closing that does not clash with a fixed-time block
        t = (clos["at"] if clos else end) - judg["min"]
        while t >= start and any(t < p["at"] + p["min"] and p["at"] < t + judg["min"] for p in pinned):
            t = min(p["at"] for p in pinned if t < p["at"] + p["min"] and p["at"] < t + judg["min"]) - judg["min"]
        judg["at"] = t
        pinned.append(judg)
    floating = [it for it in items if "at" not in it and it is not judg]
    mid = start + total // 2
    floating.sort(key=lambda it: "window" not in it)       # windowed blocks first: they have less freedom
    for it in floating:   # free gap closest to mid-event (inside its window, if any) that fits the block
        lo, hi = it.get("window", (start, end))
        taken = sorted((p["at"], p["at"] + p["min"]) for p in pinned)
        gaps, t0 = [], start
        for a, z in taken:
            if a > t0:
                gaps.append((t0, a))
            t0 = max(t0, z)
        gaps.append((t0, end))
        gaps = [(max(g0, lo), min(g1, hi)) for g0, g1 in gaps]
        fits = [max(g0, min(mid, g1 - it["min"])) for g0, g1 in gaps if g1 - g0 >= it["min"]]
        if fits:
            it["at"] = min(fits, key=lambda x: abs(x - mid))
        else:
            it["at"] = end
            if "window" in it:
                issues["fail"].append(f"{it['name']} ({it['min']} min) cannot fit in its window "
                                      f"{lo // 60:02d}:{lo % 60:02d}-{hi // 60:02d}:{hi % 60:02d}")
        pinned.append(it)
    pinned.sort(key=lambda it: it["at"])
    blocks, t, n = [], start, 0
    for it in pinned:
        if it["at"] < start or it["at"] + it["min"] > end:
            issues["fail"].append(f"{it['name']} at {it['at'] // 60:02d}:{it['at'] % 60:02d} is outside the event "
                                  f"window {start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}")
        if it["at"] < t:
            issues["fail"].append(f"{it['name']} overlaps the previous block")
        elif it["at"] > t:
            n += 1
            blocks.append({"name": f"Hacking (part {n})", "start": t, "end": it["at"], "min": it["at"] - t, "evidence": None})
        blocks.append({"name": it["name"], "start": it["at"], "end": it["at"] + it["min"], "min": it["min"],
                       "evidence": ev(it.get("anchor") or it["f"])})
        t = max(t, it["at"] + it["min"])
    if t < end:
        n += 1
        blocks.append({"name": f"Hacking (part {n})", "start": t, "end": end, "min": end - t, "evidence": None})
    hacking = sum(b["min"] for b in blocks if b["name"].startswith("Hacking"))
    return blocks, hacking


def judging_plan(d):
    teams, used, mx = d["teams"] or 0, d["judges_used"] or 0, d["max_teams_per_judge"]
    alloc = {}
    for i in range(teams):
        j = (i % used) + 1 if used else None
        if j:
            alloc.setdefault(f"Judge {j}", []).append(f"Team {i + 1}")
    return {"judges_available": d["judges_available"], "judges_needed": d["judges_needed"],
            "judges_used": used, "max_teams_per_judge": mx, "minutes_per_team": d["minutes_per_team"],
            "rounds": d["rounds"], "late_offset_min": d["late_max"], "window_min": d["judging_window"],
            "allocation": alloc}


def budget_plan(v, d, venue, food):
    lines = []
    for f in v.all("expense"):
        lines.append({"item": f["e"], "amount": D(num(f["v"])), "type": "committed", "group": "committed",
                      "evidence": ev(f)})
    if venue:
        lines.append({"item": f"Venue: {venue['name']}", "amount": D(venue["price"]), "type": "estimated",
                      "group": "venue", "evidence": venue["evidence"]})
    if food:
        lines.append({"item": f"Food: {food['qty']} x {food['name']}", "amount": D(food["cost"]),
                      "type": "estimated", "group": "food", "evidence": food["evidence"]})
    if d["honorarium"] and d["judges_used"]:
        lines.append({"item": f"Judge honorarium: {d['judges_used']} x Rs {int(d['honorarium']):,}",
                      "amount": D(d["honorarium"]) * d["judges_used"], "type": "estimated",
                      "group": "judging", "evidence": ev(v.get("honorarium", "judging"))})
    issues = []
    # costs that scale with teams / people / judges; a missing quantity is never invented
    for k, n, unit in (("cost_per_team", d["teams"], "teams"), ("cost_per_student", d["students"], "students"),
                       ("cost_per_person", d["headcount"], "people"), ("cost_per_judge", d["judges_used"], "judges")):
        for f in v.all(k):
            if not n:
                issues.append(f"{f['e'] or k}: Rs {int(num(f['v']) or 0):,} per {unit[:-1]} but the number of {unit} is unknown")
                continue
            lines.append({"item": f"{f['e'] or k.replace('_', ' ')}: {int(n)} {unit} x Rs {int(num(f['v']) or 0):,}",
                          "amount": D(num(f["v"])) * int(n), "type": "estimated", "group": "other", "evidence": ev(f)})
    # percentage charges: applied once to the NON-percentage lines they name (no recursion, no double count)
    base_lines = list(lines)
    groups = {"venue": ("venue", "hall", "rent", "room"), "food": ("food", "catering", "meal", "lunch", "caterer"),
              "judging": ("judging", "judge", "judges", "honorarium"), "committed": ("committed", "spent", "paid", "ordered")}
    for f in v.all("percent_charge"):
        pct, target = num(f["v"]) or 0, norm(f["e"])
        words = set(target.split())
        group = next((g for g, syn in groups.items() if words & set(syn)), None)
        generic = not words or words & {"all", "total", "event", "overall", "everything", "bill", "budget"}
        if generic and f["role"] == "vendor":
            # a vendor's "on the total" means the vendor's own bill (caterer -> food, venue -> venue)
            mine = {x["k"] for x in v.facts if norm(x["sender"]) == norm(f["sender"])}
            group = "food" if mine & {"price_per_head", "delivery_fee", "tier"} else \
                "venue" if mine & {"capacity", "price"} else None
            generic = group is None
        if generic:
            base, what = base_lines, "all costs"
        elif group:
            base, what = [l for l in base_lines if l["group"] == group], group
        else:
            base = [l for l in base_lines if {w for w in words if len(w) > 2} & set(norm(l["item"]).split())]
            what = ", ".join(l["item"] for l in base)
        if not base:
            issues.append(f"{pct:g}% charge on '{f['e']}' matches no budget line")
            continue
        amount = sum((l["amount"] for l in base), Decimal(0)) * Decimal(str(pct)) / 100
        lines.append({"item": f"{pct:g}% charge on {what}", "amount": amount.quantize(Decimal("1")),
                      "type": "percent", "group": "percent", "evidence": ev(f)})
    reserve_f, reserve = v.get("reserve_pct"), Decimal(0)
    if reserve_f and d["budget_total"]:
        reserve = (D(d["budget_total"]) * Decimal(str(num(reserve_f["v"]) or 0)) / 100).quantize(Decimal("1"))
    total = sum((l["amount"] for l in lines), Decimal(0))
    cap = D(d["budget_total"]) if d["budget_total"] is not None else None
    remaining = cap - total - reserve if cap is not None else None
    optional = []
    for f in v.optional:
        amt = D(num(f["v"]))
        optional.append({"item": f["e"], "amount": amt, "sender": f["sender"], "msg": f["msg"],
                         "affordable": remaining is not None and amt <= remaining,
                         "note": "optional quote, NOT included in total"})
    return {"lines": lines, "committed": sum((l["amount"] for l in lines if l["type"] == "committed"), Decimal(0)),
            "total": total, "budget": cap, "remaining": remaining, "optional": optional, "issues": issues,
            "reserve": reserve, "reserve_evidence": ev(reserve_f) if reserve_f else None}


def build_plan(items):
    """Search venue x food choices (preference order) and return the first plan that validates,
    or the best invalid one with its failing checks."""
    v = View(items)
    v.optional = [f for f in items if f.get("status") == "optional" and num(f["v"]) is not None]
    d = derive(v)
    diets = [f["e"] for f in v.all("diet_count")]
    # options that exist for a dietary need are not candidates for the main meal
    foods = [o for o in food_options(v) if not any(_diet_match(x, _diet_words(o["name"]) | _diet_words(o["tier"])) for x in diets)]         or food_options(v)
    qty_f = v.get("order_qty", "food")
    # judge counts to try: from the minimum needed up to all available (more judges = shorter judging)
    jn, ja = d["judges_used"], d["judges_available"]
    judge_opts = list(range(int(jn), int(min(ja, jn + 15)) + 1)) if jn and ja and ja > jn else [None]
    attempts, first, tried = [], None, 0
    for food in foods or [None]:                       # meal preference first (standard, then cheaper)
        valid = []
        for j in judge_opts:
            dj = derive(v, j) if j is not None else d
            venues_ok, venues_rej, needs = venue_candidates(v, dj)
            for venue in venues_ok or [None]:
                plan = assemble(v, dj, venue, venues_ok, venues_rej, needs, food, qty_f)
                plan["validation"] = validate(plan, v)
                tried += 1
                first = first or plan
                attempts.append(plan)
                if plan["validation"]["status"] == "VALID":
                    valid.append(plan)
        if valid:                                      # cheapest valid combination of venue x judges
            best = min(valid, key=lambda p: (p["budget"]["total"], p["derived"]["judges_used"]))
            best["search"] = {"tried": tried, "valid": len(valid)}
            return best
    # nothing valid: prefer a plan with fewest failures
    return min(attempts, key=lambda p: sum(c["result"] == "FAIL" for c in p["validation"]["checks"])) if attempts else first


def assemble(v, d, venue, venues_ok, venues_rej, needs, food, qty_f):
    dd = dict(d, assumptions=list(d["assumptions"]))
    food_sec = None
    if food:
        qty = int(num(qty_f["v"])) if qty_f else dd["headcount"]
        # dietary needs: N people get a matching option, the rest the main meal
        splits, diet_issues = [], []
        for f in v.all("diet_count"):
            n = int(num(f["v"]) or 0)
            opt = next((o for o in food_options(v) if _diet_match(f["e"], _diet_words(o["name"]) | _diet_words(o["tier"]))), None)
            if opt is None:
                diet_issues.append(f"{n} {f['e']} meals needed but no {f['e']} option was quoted")
            elif n:
                splits.append({"diet": f["e"], "qty": n, "name": opt["name"], "pph": opt["pph"], "evidence": ev(f)})
        if not food.get("delivery_stated", True):
            dd["assumptions"].append("food delivery Rs 0 (no delivery charge stated in messages; planning default)")
        main_qty = max(qty - sum(s["qty"] for s in splits), 0)
        cost = main_qty * food["pph"] + sum(s["qty"] * s["pph"] for s in splits) + (food["delivery"] or 0)
        food_sec = {**food, "qty": qty, "main_qty": main_qty, "splits": splits, "diet_issues": diet_issues,
                    "cost": D(cost), "people_to_feed": dd["headcount"],
                    "qty_source": ev(qty_f) if qty_f else "computed: headcount",
                    "alternatives": [{"name": f["name"], "pph": f["pph"]} for f in food_options(v) if f["name"] != food["name"]]}
    sched = schedule_plan(v, dd)
    return {
        "summary": {k: dd[k] for k in ("students", "team_size", "teams", "staff", "headcount", "duration_min",
                                        "budget_total", "judges_used")},
        "derived": dd,
        "venue": {"chosen": venue, "required_features": needs,
                  "alternatives": [x for x in venues_ok if venue and x["name"] != venue["name"]],
                  "rejected": venues_rej},
        "schedule": sched,
        "food": food_sec,
        "judging": judging_plan(dd),
        "budget": budget_plan(v, dd, venue, food_sec),
    }
