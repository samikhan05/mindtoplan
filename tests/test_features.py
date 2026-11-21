"""New constraint kinds: clock-time anchors, percentage charges, per-team/person costs, reserve,
dietary splits, judges leaving early. Invented facts (base_pack: 90 students, teams of 4, 3 hours)."""
from decimal import Decimal

from conftest import base_pack, item
from facts import resolve
from planner import build_plan

BASE_TOTAL = 60000 + 200000 + 102 * 900 + 3000 + 6 * 4000      # 378,800


def plan_of(extra):
    items = base_pack() + extra
    resolve(items)
    return build_plan(items)


def check(p, name):
    return next(c for c in p["validation"]["checks"] if c["name"] == name)


def test_cost_per_team_and_person():
    p = plan_of([item("budget", "cost_per_team", 1000, e="starter kit", sender="Accounts", role="finance"),
                 item("budget", "cost_per_person", 100, e="badge", sender="Accounts", role="finance")])
    assert p["budget"]["total"] == BASE_TOTAL + 23 * 1000 + 102 * 100


def test_percent_tax_on_venue_and_on_all():
    p = plan_of([item("budget", "percent_charge", 16, e="venue", sender="Campus Venues", role="vendor")])
    assert p["budget"]["total"] == BASE_TOTAL + 32000
    p = plan_of([item("budget", "percent_charge", 10, e="total", sender="Accounts", role="finance")])
    assert p["budget"]["total"] == BASE_TOTAL + Decimal(BASE_TOTAL) / 10      # every non-percentage line


def test_reserve_forces_cheaper_food_or_invalid():
    p = plan_of([item("budget", "reserve_pct", 60, sender="Accounts", role="finance")])
    assert p["food"]["name"] == "snack pack" and p["validation"]["status"] == "VALID"
    p = plan_of([item("budget", "reserve_pct", 70, sender="Accounts", role="finance")])
    assert p["validation"]["status"] == "INVALID"


def test_dietary_split_uses_matching_option():
    p = plan_of([item("food", "price_per_head", 1100, e="vegetarian thali", sender="Biryani Point", role="vendor"),
                 item("food", "diet_count", 10, e="vegetarian")])
    f = p["food"]
    assert f["name"] == "regular meal" and f["splits"][0]["qty"] == 10 and f["main_qty"] == 92
    assert f["cost"] == 92 * 900 + 10 * 1100 + 3000 and p["validation"]["status"] == "VALID"


def test_dietary_need_without_option_needs_clarification():
    p = plan_of([item("food", "diet_count", 8, e="gluten free")])
    assert check(p, "correct figures")["result"] == "UNRESOLVED"
    assert p["validation"]["status"] == "NEEDS CLARIFICATION"


def test_clock_anchor_places_break_at_time():
    p = plan_of([item("event", "start_time", "10:00"),
                 item("schedule", "at_time", "11:30", e="tea break")])
    blocks = p["schedule"]["blocks"]
    tea = next(b for b in blocks if b["name"].lower() == "tea break")
    assert tea["start"] == 11 * 60 + 30 and tea["time"].startswith("11:30")
    assert p["schedule"]["total_min"] == 180 and blocks[0]["name"] == "Opening"
    assert [b["name"] for b in blocks][-2:] == ["Judging", "Closing"]
    assert all(a["end"] <= b["start"] for a, b in zip(blocks, blocks[1:]))
    assert p["validation"]["status"] == "VALID"


def test_clock_anchor_outside_event_fails():
    p = plan_of([item("event", "start_time", "10:00"), item("schedule", "at_time", "15:00", e="tea break")])
    assert check(p, "schedule valid")["result"] == "FAIL"


def test_time_without_any_digits_is_ignored_not_unresolved():
    # a model can echo the format placeholder ("+N minutes after event start") when no time was stated
    p = plan_of([item("event", "start_time", "10:00"),
                 item("schedule", "at_time", "+N minutes after event start", e="tea break")])
    assert check(p, "schedule valid")["result"] == "PASS"
    assert p["validation"]["status"] == "VALID"


def test_clock_anchor_without_start_time_needs_clarification():
    p = plan_of([item("schedule", "at_time", "13:30", e="tea break")])
    assert check(p, "schedule valid")["result"] == "UNRESOLVED"


def test_judges_leaving_early_reduce_available():
    p = plan_of([item("judging", "judges_leaving_early", 2, sender="Panel lead", role="organizer")])
    assert p["derived"]["judges_available"] == 10 and p["validation"]["status"] == "VALID"
    p = plan_of([item("judging", "judges_leaving_early", 7, sender="Panel lead", role="organizer")])
    assert check(p, "enough judges")["result"] == "FAIL"


def test_fixed_time_near_end_moves_judging_earlier():
    # break pinned late in the day must not collide with judging: judging moves to the latest free slot
    p = plan_of([item("event", "start_time", "10:00"), item("schedule", "at_time", "12:25", e="tea break")])
    blocks = p["schedule"]["blocks"]
    assert all(a["end"] <= b["start"] for a, b in zip(blocks, blocks[1:]))
    judging = next(b for b in blocks if b["name"] == "Judging")
    assert judging["end"] <= 12 * 60 + 25 and p["validation"]["status"] == "VALID"


def test_veg_option_matches_vegetarian_need():
    p = plan_of([item("food", "price_per_head", 700, e="veg thali", sender="Biryani Point", role="vendor"),
                 item("food", "diet_count", 5, e="vegetarian")])
    assert p["food"]["splits"][0]["name"] == "veg thali" and p["food"]["name"] == "regular meal"


def test_percent_on_named_base_and_specific_line_no_double_count():
    p = plan_of([item("budget", "percent_charge", 10, e="food", sender="Accounts", role="finance"),
                 item("budget", "percent_charge", 50, e="trophies", sender="Accounts", role="finance"),
                 item("budget", "percent_charge", 5, e="committed", sender="Accounts", role="finance")])
    food = 102 * 900 + 3000
    assert p["budget"]["total"] == BASE_TOTAL + Decimal(food) / 10 + 30000 + 3000   # no % on a % line


def test_percent_on_judging_base():
    p = plan_of([item("budget", "percent_charge", 25, e="judging", sender="Accounts", role="finance")])
    assert p["budget"]["total"] == BASE_TOTAL + 6 * 4000 // 4


def test_reserve_shown_separately_and_counted_in_check():
    p = plan_of([item("budget", "reserve_pct", 10, sender="Accounts", role="finance")])
    b = p["budget"]
    assert b["total"] == BASE_TOTAL and b["reserve"] == 90000 and b["remaining"] == 900000 - BASE_TOTAL - 90000


def test_cost_per_judge():
    p = plan_of([item("budget", "cost_per_judge", 1500, e="judge travel", sender="Accounts", role="finance")])
    assert p["budget"]["total"] == BASE_TOTAL + 6 * 1500


def test_missing_quantity_needs_clarification():
    items = [i for i in base_pack() if i["k"] != "team_size"] +         [item("budget", "cost_per_team", 500, e="kit", sender="Accounts", role="finance")]
    from facts import resolve
    resolve(items)
    p = build_plan(items)
    chk = check(p, "within budget")
    assert chk["result"] == "UNRESOLVED" and "number of teams is unknown" in chk["detail"]
    assert p["validation"]["status"] != "VALID"


def test_percent_with_unknown_base_needs_clarification():
    p = plan_of([item("budget", "percent_charge", 5, e="spaceship", sender="Accounts", role="finance")])
    assert check(p, "within budget")["result"] == "UNRESOLVED"


def sched(extra, start="10:00"):
    pre = [item("event", "start_time", start)] if start else []
    p = plan_of(pre + extra)
    return p, {b["name"].lower(): b for b in p["schedule"]["blocks"]}


def test_anchor_exact_end_time():
    p, b = sched([item("schedule", "at_time", "end 11:40", e="tea break")])
    assert b["tea break"]["end"] == 11 * 60 + 40 and p["validation"]["status"] == "VALID"


def test_anchor_minute_offset_without_clock_start():
    p, b = sched([item("schedule", "at_time", "+75", e="tea break")], start=None)
    assert b["tea break"]["start"] == 75 and p["validation"]["status"] == "VALID"


def test_anchor_window():
    p, b = sched([item("schedule", "at_time", "10:20-11:00", e="tea break")])
    t = b["tea break"]
    assert 10 * 60 + 20 <= t["start"] and t["end"] <= 11 * 60 and p["validation"]["status"] == "VALID"


def test_conflicting_anchors_fail():
    p, _ = sched([item("schedule", "at_time", "11:00", e="tea break"),
                  item("schedule", "at_time", "11:10", e="meal break")])
    assert check(p, "schedule valid")["result"] == "FAIL"


def test_window_too_small_fails():
    p, _ = sched([item("schedule", "at_time", "10:20-10:30", e="tea break")])
    assert check(p, "schedule valid")["result"] == "FAIL"


def test_not_enough_time_left_fails():
    p, _ = sched([item("schedule", "activity_min", 150, e="workshop")])
    assert check(p, "schedule valid")["result"] == "FAIL"


def test_judge_search_adds_judges_when_minimum_does_not_fit():
    # 6 judges -> 4 rounds x 10 = 40 min judging leaves too little hacking; 8 judges -> 3 rounds fits
    p = plan_of([item("schedule", "activity_min", 40, e="workshop")])
    assert p["validation"]["status"] == "VALID"
    assert p["derived"]["judges_used"] == 8 and p["schedule"]["judging_min"] == 30
    assert p["search"]["tried"] > 1


def test_judge_search_keeps_minimum_when_it_fits():
    p = plan_of([])
    assert p["derived"]["judges_used"] == 6


def test_facility_synonyms_ramp_satisfies_step_free():
    p = plan_of([item("venue", "feature", "ramp access", e="Auditorium", sender="Campus Venues", role="vendor"),
                 item("venue", "requires_feature", "step-free access", e="need", h=True)])
    assert p["venue"]["chosen"]["name"] == "Auditorium" and p["validation"]["status"] == "VALID"
    p = plan_of([item("venue", "feature", "ramp access", e="Auditorium", sender="Campus Venues", role="vendor"),
                 item("venue", "requires_feature", "air conditioning", e="need", h=True)])
    assert p["venue"]["chosen"] is None or "air" not in " ".join(p["venue"]["chosen"]["features"])


def test_vendor_service_charge_on_total_applies_to_own_bill():
    p = plan_of([item("budget", "percent_charge", 10, e="total", sender="Biryani Point", role="vendor")])
    food = 102 * 900 + 3000
    assert p["budget"]["total"] == BASE_TOTAL + Decimal(food) / 10


def test_reader_unwraps_extra_nesting():
    from reader import ReadOut
    import reader
    for shape in ([{"m": [{"id": "M1", "it": []}]}], {"m": [{"m": [{"id": "M1", "it": []}]}]}):
        out = shape
        if isinstance(out, list):
            out = out[0] if len(out) == 1 and isinstance(out[0], dict) and "m" in out[0] else {"m": out}
        if isinstance(out, dict) and len(out.get("m") or []) == 1 and "m" in out["m"][0] and "id" not in out["m"][0]:
            out = out["m"][0]
        assert ReadOut.model_validate(out).m[0].id == "M1"


def test_rule_requires_uses_facility_synonyms():
    p = plan_of([item("venue", "feature", "ramp access", e="Auditorium", sender="Campus Venues", role="vendor"),
                 item("venue", "rule", None, t="rule", h=True, q="must be step-free",
                      c={"m": "venue_features", "op": "requires", "v": "step-free access"})])
    assert p["venue"]["chosen"]["name"] == "Auditorium" and p["validation"]["status"] == "VALID"
