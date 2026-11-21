"""Reply-shape validation, provider failure handling and transactional rollback (no network)."""
import copy
from types import SimpleNamespace as NS

import pytest

import config
import llm
import pipeline
from llm import Budgeter, Trace
from test_pipeline import BASE, fake_reader


def _route(monkeypatch, fallback=False):
    monkeypatch.setattr(config, "API_KEY", "k")
    monkeypatch.setattr(config, "BASE_URL", "http://a")
    monkeypatch.setattr(config, "MODEL_NAME", "primary")
    if fallback:
        monkeypatch.setattr(config, "FALLBACK_BASE_URL", "http://b")
        monkeypatch.setattr(config, "FALLBACK_API_KEY", "k2")
        monkeypatch.setattr(config, "FALLBACK_MODEL_NAME", "backup")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


class _Status(Exception):
    def __init__(self, code):
        super().__init__(f"Error code: {code}")
        self.status_code = code


def _clients(monkeypatch, replies):
    """replies: model name -> list of status codes (raised) or reply texts; consumed in order, the last repeats."""
    seen = []

    def make(timeout, route=None):
        model = (route or llm._routes()[0])[1]

        def create(**kw):
            seen.append(model)
            queue = replies[model]
            r = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(r, int):
                raise _Status(r)
            return NS(model=model, usage=NS(prompt_tokens=7, completion_tokens=3, total_tokens=10),
                      choices=[NS(message=NS(content=r))])
        return NS(chat=NS(completions=NS(create=create)))
    monkeypatch.setattr(llm, "_client", make)
    return seen


# 1-3: reply shapes ----------------------------------------------------------------------------------------------
def test_valid_object_reply_is_returned(monkeypatch):
    _route(monkeypatch)
    _clients(monkeypatch, {"primary": ['{"m": "headcount", "op": "lte", "v": 150}']})
    t = Trace()
    out = llm.call_model(Budgeter("update"), t, "venue", "s", "u", ["M1"], "U1")
    assert out == {"m": "headcount", "op": "lte", "v": 150}
    assert t.records[0]["ok"] and t.records[0]["total_tokens"] == 10


def test_top_level_list_where_object_expected_is_a_schema_error_not_retried(monkeypatch):
    _route(monkeypatch)
    seen = _clients(monkeypatch, {"primary": ['[{"m": "students", "op": "gte", "v": 100}]']})
    t, b = Trace(), Budgeter("update")
    assert llm.call_model(b, t, "venue", "s", "u", ["M1"], "U1") is None
    assert seen == ["primary"] and b.calls == 1                       # one attempt only
    rec = t.records[0]
    assert not rec["ok"] and rec["error"].startswith("ResponseSchemaError") and "not retried" in rec["error"]
    assert rec["total_tokens"] == 10                                  # tokens the call used are still reported
    # the reading call explicitly accepts a list (its documented wrapper slips are unwrapped by the reader)
    out = llm.call_model(Budgeter("update"), Trace(), "reading", "s", "u", [], "U1", expect=(dict, list))
    assert out == [{"m": "students", "op": "gte", "v": 100}]


def test_malformed_json_is_recorded_and_retried_then_gives_up(monkeypatch):
    _route(monkeypatch)
    seen = _clients(monkeypatch, {"primary": ['{"m": "students", "op": ']})
    t = Trace()
    assert llm.call_model(Budgeter("update"), t, "venue", "s", "u", ["M1"], "U1", attempts=2) is None
    assert seen == ["primary", "primary"]
    assert all(not r["ok"] and "JSONDecodeError" in r["error"] for r in t.records)


# 5-6: provider failures ---------------------------------------------------------------------------------------
def test_primary_503_then_fallback_succeeds(monkeypatch):
    _route(monkeypatch, fallback=True)
    seen = _clients(monkeypatch, {"primary": [503], "backup": ['{"ok": true}']})
    t = Trace()
    assert llm.call_model(Budgeter("update"), t, "reading", "s", "u", ["M1"], "U1") == {"ok": True}
    assert seen == ["primary", "backup"] and [r["ok"] for r in t.records] == [False, True]
    assert "fallback" in t.records[0]["error"]


def test_both_providers_overloaded_returns_none_with_every_attempt_traced(monkeypatch):
    _route(monkeypatch, fallback=True)
    seen = _clients(monkeypatch, {"primary": [503], "backup": [503]})
    t, b = Trace(), Budgeter("update")
    assert llm.call_model(b, t, "reading", "s", "u", ["M1"], "U1") is None
    assert seen == ["primary", "backup", "backup"] and b.calls == 3 == len(t.records)
    assert all(not r["ok"] and "503" in r["error"] for r in t.records)


# 4, 7-9: rule conversion and rollback -------------------------------------------------------------------------
@pytest.fixture
def script(monkeypatch):
    s = {"PACK": ("Registrar", "institution", copy.deepcopy(BASE), False)}
    monkeypatch.setattr(pipeline, "read_messages", fake_reader(s))
    return s


RULE = ("Registrar", "institution", [{"a": "venue", "e": "", "k": "rule", "t": "rule", "h": True,
                                      "q": "hall must hold no more than 150 people"}], False)


def test_rule_conversion_returning_a_list_keeps_the_requirement(script, monkeypatch):
    pipeline.process("PACK all facts")
    _route(monkeypatch)
    _clients(monkeypatch, {"primary": ['[{"m": "headcount", "op": "lte", "v": 150}]']})
    script["no more than"] = RULE
    state, rep = pipeline.process("no more than 150 people in the hall")   # previously: AttributeError
    assert not any("AttributeError" in n for n in rep["notes"]) and not rep.get("rolled_back")
    rule = [i for i in state["items"] if i["k"] == "rule"][0]
    assert rule["c"] is None and rule["status"] == "rejected"          # kept and visible, with its reason
    assert "NEEDS CLARIFICATION" in rule["reason"] and "no machine-checkable form" in rule["reason"]
    assert state["messages"][-1]["status"] == "rejected"
    assert state["plan"]["validation"]["status"] == "VALID"            # the last valid plan is kept
    assert any(r["area"] == "venue" and "ResponseSchemaError" in (r["error"] or "") for r in state["trace"])


def test_failure_during_rule_conversion_rolls_back_and_same_input_is_retried(script, monkeypatch):
    state, _ = pipeline.process("PACK all facts")
    before = copy.deepcopy({k: state[k] for k in ("messages", "items", "plan", "next_order")})
    script["no more than"] = RULE

    def boom(*a, **kw):
        raise RuntimeError("provider client crashed")
    monkeypatch.setattr(pipeline, "call_model", boom)
    state, rep = pipeline.process("no more than 150 people in the hall")
    # 7 + 9: the message is not stored as processed; plan, facts and counters are exactly as before
    assert rep["rolled_back"] and rep["incomplete"]
    assert {k: state[k] for k in ("messages", "items", "plan", "next_order")} == before
    saved = pipeline.load_state()
    assert saved["plan"] == before["plan"] and saved["items"] == before["items"]
    assert rep["new_messages"] == ["M2"] and any("rolled back" in n for n in rep["notes"])
    assert saved["updates"][-1]["rolled_back"]                          # the failed run is still in the history
    # 8: the same input again is read again (not skipped as a duplicate), now succeeding
    monkeypatch.setattr(pipeline, "call_model", lambda *a, **kw: {"m": "headcount", "op": "lte", "v": 150})
    state, rep = pipeline.process("no more than 150 people in the hall")
    assert rep["new_messages"] == ["M2"] and not rep.get("rolled_back")
    assert state["plan"]["validation"]["status"] == "VALID"
    assert [m["id"] for m in state["messages"]] == ["M1", "M2"]


def test_successful_update_still_commits_normally(script):
    pipeline.process("PACK all facts")
    script["meal now"] = ("Biryani Point", "vendor",
                          [{"a": "food", "e": "regular meal", "k": "price_per_head", "v": 1000, "t": "update",
                            "q": "meal now 1000"}], False)
    state, rep = pipeline.process("regular meal now 1000 per head")
    assert not rep.get("rolled_back") and rep["accepted"]
    assert state["plan"]["food"]["pph"] == 1000
