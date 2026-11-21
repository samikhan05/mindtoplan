"""3B: facts still missing a value get ONE targeted re-check with only their own message; answers are used only
when the value is written in that message."""
import copy

import pytest

import pipeline
from test_pipeline import BASE, fake_reader
from valuefix import accepts


@pytest.fixture
def script(monkeypatch):
    s = {"PACK": ("Registrar", "institution", copy.deepcopy(BASE), False)}
    monkeypatch.setattr(pipeline, "read_messages", fake_reader(s))
    return s


def _price_update(script, v=None):
    script["ab Rs"] = ("Biryani Point", "vendor",
                       [{"a": "food", "e": "regular meal", "k": "price_per_head", "v": v, "t": "fact",
                         "q": ""}], False)    # plain facts carry no quote, so 3A cannot help: 3B must


def _spy(monkeypatch, reply):
    calls = []

    def fake(budgeter, trace, area, system, user, ids, uid, **kw):
        calls.append({"area": area, "user": user, "ids": ids, "kw": kw})
        return reply
    monkeypatch.setattr(pipeline, "call_model", fake)
    return calls


def test_missing_value_is_rechecked_with_only_its_own_message(script, monkeypatch):
    pipeline.process("PACK all facts")
    _price_update(script)
    calls = _spy(monkeypatch, {"v": {"M2.1": 1000}})
    state, rep = pipeline.process("Salam! regular meal ab Rs 1000 per head")
    assert len(calls) == 1 and calls[0]["area"] == "reading" and calls[0]["ids"] == ["M2"]
    assert "PACK all facts" not in calls[0]["user"]                 # earlier messages are not resent
    assert "M2.1: price_per_head of \"regular meal\"" in calls[0]["user"]
    item = [i for i in state["items"] if i["id"] == "M2.1"][0]
    assert item["v"] == 1000 and item["v_source"].startswith("targeted re-check")
    assert state["plan"]["food"]["pph"] == 1000


def test_value_not_written_in_the_message_is_ignored(script, monkeypatch):
    pipeline.process("PACK all facts")
    _price_update(script)
    _spy(monkeypatch, {"v": {"M2.1": 1500}})                        # 1500 appears nowhere in the message
    state, rep = pipeline.process("Salam! regular meal ab Rs 1000 per head")
    item = [i for i in state["items"] if i["id"] == "M2.1"][0]
    assert item["v"] is None and item["status"] == "needs review" and "not written in M2" in item["reason"]
    assert state["plan"]["food"]["pph"] == 900                      # unchanged: nothing invented


def test_no_recheck_when_nothing_is_missing(script, monkeypatch):
    pipeline.process("PACK all facts")
    _price_update(script, v=1000)
    calls = _spy(monkeypatch, None)
    pipeline.process("Salam! regular meal ab Rs 1000 per head")
    assert calls == []


def test_failed_recheck_leaves_fact_unplanned_without_crash(script, monkeypatch):
    pipeline.process("PACK all facts")
    _price_update(script)
    _spy(monkeypatch, None)                                          # provider down / schema error
    state, rep = pipeline.process("Salam! regular meal ab Rs 1000 per head")
    assert not rep.get("rolled_back") and any("no value even after" in n for n in rep["notes"])
    assert state["plan"]["validation"]["status"] == "VALID" and state["plan"]["food"]["pph"] == 900


def test_value_in_quote_is_recovered_in_python_before_any_recheck(script, monkeypatch):
    pipeline.process("PACK all facts")
    script["ab Rs"] = ("Biryani Point", "vendor",
                       [{"a": "food", "e": "regular meal", "k": "price_per_head", "v": None, "t": "update",
                         "q": "regular meal ab Rs 1000 per head"}], False)
    calls = _spy(monkeypatch, None)
    state, rep = pipeline.process("Salam! regular meal ab Rs 1000 per head")
    assert calls == []                                               # 3A fixed it: no model call at all
    item = [i for i in state["items"] if i["id"] == "M2.1"][0]
    assert item["v"] == 1000 and item["v_source"] == "quote (Python)" and item["q"]


@pytest.mark.parametrize("k, value, text, want", [
    ("price_per_head", 700, "karahi box ab Rs 700 per head", 700),
    ("price_per_head", "Rs 700", "karahi box ab Rs 700 per head", 700),
    ("price_per_head", 750, "karahi box ab Rs 700 per head", None),
    ("break_min", 240, "a 4-hour hackathon", 240),                   # hours written, minutes returned
    ("at_time", "13:00", "lunch must start at 1 pm", "13:00"),
    ("at_time", "14:00", "lunch must start at 1 pm", None),
    ("students", 1250000, "budget Rs 12,50,000", 1250000),
])
def test_accepts_only_values_written_in_text(k, value, text, want):
    assert accepts({"k": k}, value, text) == want


def test_recheck_zero_accepted_only_with_no_charge_wording():
    waived = "delivery charge waived, no delivery fee now"
    assert accepts({"k": "delivery_fee", "q": waived}, 0, waived) == 0
    assert accepts({"k": "delivery_fee", "q": "delivery is Rs 5,000"}, 0, "delivery is Rs 5,000") is None
    assert accepts({"k": "price", "q": "Hall A is free on Monday"}, 0, "Hall A is free on Monday") is None


def test_recheck_zero_needs_the_facts_own_quote_not_another_charge_in_the_message():
    # review finding: the hall rent was accepted as 0 because the DELIVERY charge in the same message was waived
    msg = "Hall C rent to be confirmed. Delivery charge waived."
    assert accepts({"k": "price", "q": "Hall C rent to be confirmed"}, 0, msg) is None
    assert accepts({"k": "delivery_fee", "q": "Delivery charge waived"}, 0, msg) == 0
