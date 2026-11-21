"""Phase 3D defects found in the audit: messages lost by an early-closed reply, messages omitted from a reply,
unrelated clock times blocking the schedule, and requirements silently disabled by a misread sender role."""
import copy

import pytest

import llm
import pipeline
import reader
from conftest import item
from facts import View, resolve
from planner import build_plan
from test_pipeline import BASE, fake_reader


# --- parser: a stray closer must not end the reply early ---------------------------------------------------------
def test_early_closed_reply_keeps_every_message_record():
    raw = ('{"m":[{"id":"M1","it":[{"k":"students","v":90}]},{"id":"M2","it":[{"k":"capacity","v":200}]}]}],'
           '"id":"M3","role":"organizer","it":[{"k":"judges_available","v":12}]},'
           '{"id":"M4","rel":false}]}')
    out = reader._repair(llm.parse_json(raw), [{"id": f"M{i}"} for i in range(1, 5)])
    assert [m["id"] for m in out["m"]] == ["M1", "M2", "M3", "M4"]
    assert out["m"][2]["it"][0]["v"] == 12


def test_clean_reply_with_trailing_text_is_unchanged():
    assert llm.parse_json('{"m":[{"id":"M1","it":[]}]} .') == {"m": [{"id": "M1", "it": []}]}


# --- a message with no record in the reply is re-read in the same run, alone ---------------------------------------
@pytest.fixture
def script(monkeypatch):
    s = {"PACK": ("Registrar", "institution", copy.deepcopy(BASE), False)}
    monkeypatch.setattr(pipeline, "read_messages", fake_reader(s))
    return s


def test_omitted_message_is_reread_once_in_the_same_run(monkeypatch):
    calls = []
    script = {"PACK": ("Registrar", "institution", copy.deepcopy(BASE), False),
              "judges": ("Panel lead", "organizer", [{"a": "judging", "e": "", "k": "honorarium", "v": 5000,
                                                       "t": "update", "q": "honorarium now 5000"}], False)}
    real = fake_reader(script)

    def first_drops_m2(msgs, known, budgeter, trace, uid):
        calls.append([m["id"] for m in msgs])
        out = real(msgs, known, budgeter, trace, uid)
        if len(calls) == 1:
            out.pop("M2", None)                   # the model returned no record for M2
        return out
    monkeypatch.setattr(pipeline, "read_messages", first_drops_m2)
    state, rep = pipeline.process("PACK all facts\n\njudges honorarium now 5000")
    assert calls == [["M1", "M2"], ["M2"]]        # second call: only the omitted message
    assert [m["id"] for m in state["messages"]] == ["M1", "M2"]
    assert any("re-read only those: got M2" in n for n in rep["notes"])
    assert any(i["msg"] == "M2" and i["k"] == "honorarium" for i in state["items"])


# --- an unrelated clock time does not block the schedule; a block's own time still does ---------------------------
def test_time_for_something_outside_the_schedule_is_a_note_not_a_blocker():
    items = [item(*a, **k) for a, k in [(("event", "students", 90), {}), (("event", "team_size", 3), {}),
                                         (("event", "duration_min", 240), {}), (("event", "staff", 4), {})]]
    lib = item("schedule", "at_time", "15:00", e="library", msg="M9")
    plan = build_plan(resolve(items + [lib]))
    s = plan["schedule"]
    assert not any("start time is unknown" in u for u in s["issues"]["unresolved"])
    assert any("library" in n and "not a block" in n for n in s["issues"]["notes"])


def test_time_for_a_real_block_without_start_time_still_needs_clarification():
    items = [item("event", "duration_min", 240), item("schedule", "break_min", 20, e="tea break", h=True),
             item("schedule", "at_time", "13:30", e="tea break")]
    plan = build_plan(resolve(items))
    assert any("start time is unknown" in u for u in plan["schedule"]["issues"]["unresolved"])


# --- sender roles and requirements from senders without authority --------------------------------------------------
@pytest.mark.parametrize("sender, model_role, want", [
    ("Student disability office, email", "student", "institution"),   # an office is not a student
    ("Registrar's office", "unknown", "institution"),
    ("Student society, WhatsApp", "student", "student"),               # a student group stays a student
    ("Ali (student, WhatsApp)", "student", "student"),
    ("Caterer, WhatsApp", "vendor", "vendor"),                         # never downgraded or changed otherwise
])
def test_sender_role_sanity(sender, model_role, want):
    rep = {"notes": []}
    assert pipeline._sender_role(model_role, sender, rep, "M3") == want


def test_requirement_from_office_misread_as_student_is_enforced(script):
    script["PACK"] = ("Registrar", "institution", copy.deepcopy(BASE), False)
    script["wheelchair"] = ("Student disability office", "student",
                            [{"a": "venue", "e": "need", "k": "requires_feature", "v": "step-free access",
                              "t": "rule", "h": True, "q": "The venue must have step-free access."}], False)
    state, rep = pipeline.process("PACK all facts\n\nwheelchair users: venue must be step free")
    req = [i for i in state["items"] if i["k"] == "requires_feature"][0]
    assert req["role"] == "institution" and req["status"] == "accepted" and req["t"] == "rule"


def test_requirement_from_a_student_is_visible_for_review_not_called_spending(script):
    pipeline.process("PACK all facts")
    script["please make"] = ("Ali", "student", [{"a": "venue", "e": "need", "k": "requires_feature",
                                                "v": "projector", "t": "rule", "h": True,
                                                "q": "venue must have a projector"}], False)
    state, rep = pipeline.process("please make sure the venue must have a projector")
    req = [i for i in state["items"] if i["k"] == "requires_feature"][0]
    assert req["status"] == "needs review" and "no authority" in req["reason"]
    assert "spending" not in req["reason"]
    assert state["plan"]["validation"]["status"] == "VALID"            # not applied, plan unchanged
