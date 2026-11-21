"""Clear requirements are converted in Python (no model call); unclear ones still go to the model."""
import copy

import pytest

import pipeline
from rulefit import python_rule
from test_pipeline import BASE, fake_reader


def rule(q):
    return {"k": "rule", "t": "rule", "h": True, "q": q, "c": None, "a": "venue", "e": ""}


def fact(k, v, e=""):
    return {"k": k, "v": v, "e": e, "a": "schedule", "t": "fact"}


@pytest.mark.parametrize("q, want", [
    ("The venue must have step-free access throughout.", {"m": "venue_features", "op": "requires", "v": "step free"}),
    ("Hall must have a backup generator", {"m": "venue_features", "op": "requires", "v": "generator"}),
    ("No more than 180 people are allowed in the hall.", {"m": "headcount", "op": "lte", "v": 180}),
    ("We need at least 50 participants.", {"m": "headcount", "op": "gte", "v": 50}),
    ("The event must finish by 17:30.", {"m": "end_min", "op": "lte", "v": 17 * 60 + 30}),
    ("Venue mein lift zaroori hai", {"m": "venue_features", "op": "requires", "v": "lift"}),   # Roman Urdu
])
def test_clear_requirements_become_constraints(q, want):
    kind, c, why = python_rule(rule(q), [])
    assert kind == "c" and c == want and "Python" in why


def test_required_break_not_yet_a_fact_becomes_a_break():
    kind, payload, _ = python_rule(rule("Please keep a 20-minute prayer break in the schedule."), [])
    assert kind == "break" and payload == (20, "prayer break")
    kind, payload, _ = python_rule(rule("A tea break of 15 minutes is mandatory"), [])
    assert kind == "break" and payload == (15, "tea break")


def test_requirement_already_extracted_is_covered_not_duplicated():
    sib = [fact("break_min", 20, "prayer break"), fact("students", 120), fact("budget_total", 400000)]
    kind, _, why = python_rule(rule("Approved: a 4-hour hackathon for 120 students. Please keep a "
                                    "20-minute prayer break in the schedule."), sib)
    assert kind == "covered" and "break_min" in why


def test_restated_facts_without_requirement_wording_are_covered():
    sib = [fact("students", 120), fact("team_size", 4), fact("budget_total", 400000)]
    kind, _, why = python_rule(rule("Approved: a 4-hour hackathon for 120 students in teams of 4."), sib)
    assert kind == "covered" and "no requirement wording" in why


@pytest.mark.parametrize("q", [
    "The hall must feel spacious for every team.",               # vague: no clear pattern
    "Judges should be from at least three universities.",        # unknown kind of constraint
    "Must have a ramp and no more than 100 people.",             # two new constraints in one item
    "Everyone gets a souvenir.",                                 # no requirement wording, no sibling facts
])
def test_unclear_requirements_still_go_to_the_model(q):
    assert python_rule(rule(q), []) is None


# end-to-end: the pipeline uses the Python conversion and makes no model call -------------------------------------
@pytest.fixture
def script(monkeypatch):
    s = {"PACK": ("Registrar", "institution", copy.deepcopy(BASE), False)}
    monkeypatch.setattr(pipeline, "read_messages", fake_reader(s))
    return s


def test_clear_rule_in_update_needs_no_model_call_and_is_enforced(script, monkeypatch):
    pipeline.process("PACK all facts")
    calls = []
    monkeypatch.setattr(pipeline, "call_model", lambda *a, **kw: calls.append(a) or None)
    script["no more than"] = ("Registrar", "institution",
                              [{"a": "venue", "e": "", "k": "rule", "t": "rule", "h": True,
                                "q": "No more than 50 people may attend."}], False)
    state, rep = pipeline.process("no more than 50 people may attend")
    assert calls == []                                              # no rule-conversion call
    item = [i for i in state["items"] if i["k"] == "rule"][0]
    assert item["c"] == {"m": "headcount", "op": "lte", "v": 50} and item["c_source"] == "python"
    # 90 students cannot fit under 50 people: the update is rejected with a reason and the valid plan kept
    assert item["status"] == "rejected" and state["plan"]["validation"]["status"] == "VALID"
    assert any("no model call" in n for n in rep["notes"])


def test_duplicate_fact_from_one_message_is_kept_once(script):
    script["PACK"] = ("Registrar", "institution", copy.deepcopy(BASE) + [copy.deepcopy(BASE[0])], False)
    state, rep = pipeline.process("PACK all facts")
    assert sum(i["k"] == BASE[0]["k"] for i in state["items"]) == 1
    assert any("duplicate fact" in n for n in rep["notes"])
