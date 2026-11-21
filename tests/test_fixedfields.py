"""EXPERIMENT (EXTRACTION_MODE=fixed): fixed-field records convert to the same items the generic reader makes."""
import json

import config
import fixedfields
import llm
import pipeline
from fixedfields import to_items


def keyed(items):
    return {(i["a"], i["e"], i["k"]): i for i in items}


def test_event_venue_food_judging_budget_fields_convert():
    rec = {"id": "M1", "r": "institution",
           "ev": {"students": 120, "team_size": 4, "budget_total": 400000, "reserve_pct": 10},
           "ven": {"Hall 2": {"cap": 180, "price": 110000, "has": ["ramp access"], "lacks": ["lift"]},
                   "Hall 3": {"cap": 250, "na": 1}},
           "food": {"biryani box": {"pph": 850, "tier": "standard"}}, "deliv": {"delivery": 0},
           "ju": {"judges_available": 15, "honorarium": 4000}, "exp": {"trophies": 60000}, "pct": {"food": 10}}
    k = keyed(to_items(rec))
    assert k[("event", "", "students")]["v"] == 120 and k[("budget", "", "reserve_pct")]["v"] == 10
    assert k[("venue", "Hall 2", "capacity")]["v"] == 180 and k[("venue", "Hall 2", "feature")]["v"] == "ramp access"
    assert k[("venue", "Hall 2", "lacks_feature")]["v"] == "lift" and k[("venue", "Hall 3", "unavailable")]["v"] is True
    assert k[("food", "biryani box", "price_per_head")]["v"] == 850 and k[("food", "delivery", "delivery_fee")]["v"] == 0
    assert k[("judging", "", "honorarium")]["v"] == 4000 and k[("budget", "trophies", "expense")]["v"] == 60000
    assert k[("budget", "food", "percent_charge")]["v"] == 10
    assert all(i["t"] == "fact" for i in k.values())


def test_mandatory_vs_optional():
    k = keyed(to_items({"id": "M1", "need": ["step-free access"], "brk": {"prayer break": {"min": 20, "req": 1},
                                                                          "tea break": {"min": 10}},
                        "opt": {"photo booth": 30000}}))
    need = k[("venue", "need", "requires_feature")]
    assert need["h"] and need["t"] == "rule" and need["v"] == "step-free access"
    assert k[("schedule", "prayer break", "break_min")]["h"] and not k[("schedule", "tea break", "break_min")]["h"]
    assert k[("budget", "photo booth", "optional_cost")]["t"] == "suggestion"     # never counted as spending


def test_update_and_suggestion_kinds_carry_their_quote():
    upd = to_items({"id": "M5", "k": "u", "q": "biryani box ab Rs 850", "food": {"biryani box": {"pph": 850}}})
    assert upd[0]["t"] == "update" and upd[0]["q"] == "biryani box ab Rs 850"
    sug = to_items({"id": "M7", "k": "s", "q": "budget is now 1,200,000", "ev": {"budget_total": 1200000}})
    assert sug[0]["t"] == "suggestion" and sug[0]["k"] == "budget_total"


def test_unfamiliar_constraint_becomes_a_rule_with_or_without_machine_form():
    items = to_items({"id": "M4", "oc": [
        {"q": "Judges must come from at least three universities", "h": 1},
        {"q": "No more than 150 people inside", "h": 1, "c": {"m": "headcount", "op": "lte", "v": 150}}]})
    assert [i["k"] for i in items] == ["rule", "rule"] and all(i["h"] and i["t"] == "rule" for i in items)
    assert items[0]["c"] is None and items[0]["q"].startswith("Judges must")   # goes to the existing rule path
    assert items[1]["c"] == {"m": "headcount", "op": "lte", "v": 150}


def test_uncertain_reading_is_kept_visible_not_applied():
    items = to_items({"id": "M6", "unc": ["shayad 20 log aur aayen"]})
    assert items == [{"a": "event", "e": "", "k": "other", "v": "uncertain: shayad 20 log aur aayen",
                      "t": "question", "h": False, "q": "shayad 20 log aur aayen", "c": None}]


def test_empty_values_are_not_turned_into_facts():
    assert to_items({"id": "M1", "ven": {"Hall X": {"cap": None, "has": []}}, "ev": {"students": ""}}) == []


def test_pipeline_end_to_end_in_fixed_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "EXTRACTION_MODE", "fixed")
    reply = {"m": [
        {"id": "M1", "r": "institution", "ev": {"students": 90, "team_size": 3, "staff": 6, "duration_min": 180,
                                                "budget_total": 900000}, "brk": {"tea break": {"min": 20, "req": 1}}},
        {"id": "M2", "r": "vendor", "ven": {"Lab 1": {"cap": 80, "price": 50000},
                                            "Auditorium": {"cap": 250, "price": 200000}}},
        {"id": "M3", "r": "vendor", "food": {"regular meal": {"pph": 900, "tier": "standard"}}},
        {"id": "M4", "r": "organizer", "ju": {"judges_available": 12, "max_teams_per_judge": 4,
                                             "minutes_per_team": 10, "honorarium": 4000}},
        {"id": "M5", "k": "x"}]}
    seen = {}

    def fake(budgeter, trace, area, system, user, ids, uid, **kw):
        seen["system"] = system
        budgeter.calls += 1
        trace.records.append({"n": 1, "timestamp": "t", "model": "fake", "area": area, "update_id": uid,
                              "message_ids": ids, "attempt": 1, "input": {"system": system, "user": user},
                              "output": json.dumps(reply), "input_tokens": 10, "output_tokens": 5,
                              "total_tokens": 15, "duration_s": 0, "ok": True, "error": None})
        return reply
    monkeypatch.setattr(fixedfields, "call_model", fake)
    text = "\n\n".join(["approved 90 students", "Lab 1 and Auditorium", "regular meal 900", "12 judges", "cricket"])
    state, rep = pipeline.process(text)
    assert seen["system"] is fixedfields.SYSTEM_FIXED
    p = state["plan"]
    assert p["validation"]["status"] == "VALID" and p["venue"]["chosen"]["name"] == "Auditorium"
    assert p["derived"]["teams"] == 30 and p["derived"]["judges_used"] == 8
    assert [m["status"] for m in state["messages"]][-1] == "irrelevant"


def test_default_mode_is_unchanged():
    assert config.EXTRACTION_MODE == "generic"


def test_known_keys_count_in_either_group():
    k = keyed(to_items({"id": "M11", "k": "u", "q": "at most 3 teams", "ev": {"max_teams_per_judge": 3},
                        "ju": {"students": 140}}))
    assert k[("judging", "", "max_teams_per_judge")]["v"] == 3 and k[("event", "", "students")]["v"] == 140
