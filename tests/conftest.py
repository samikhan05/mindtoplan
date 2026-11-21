"""Helpers: build reader-style items directly so the planner/validator/transaction run without a model.
All facts here are invented for tests and differ from the sample pack."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

_n = [0]


def item(a, k, v, e="", t="fact", h=False, sender="Registrar", role="institution", msg="T1", q=None,
         order=None, c=None):
    _n[0] += 1
    return {"id": f"{msg}.{_n[0]}", "msg": msg, "sender": sender, "role": role, "date": "", "a": a, "e": e,
            "k": k, "v": v, "u": "", "t": t, "h": h, "q": q or f"{e} {k} {v}", "c": c, "status": "",
            "reason": "", "locked": False, "order": order if order is not None else _n[0]}


def base_pack():
    """A different event: 90 students in teams of 4, budget 900k, 6 staff, 3-hour event."""
    return [
        item("event", "students", 90), item("event", "team_size", 4), item("event", "staff", 6),
        item("event", "duration_min", 180), item("event", "budget_total", 900000),
        item("schedule", "break_min", 20, e="tea break", h=True),
        item("venue", "capacity", 100, e="Lab 1", sender="Campus Venues", role="vendor"),
        item("venue", "price", 50000, e="Lab 1", sender="Campus Venues", role="vendor"),
        item("venue", "capacity", 250, e="Auditorium", sender="Campus Venues", role="vendor"),
        item("venue", "price", 200000, e="Auditorium", sender="Campus Venues", role="vendor"),
        item("food", "price_per_head", 900, e="regular meal", sender="Biryani Point", role="vendor"),
        item("food", "tier", "standard", e="regular meal", sender="Biryani Point", role="vendor"),
        item("food", "price_per_head", 500, e="snack pack", sender="Biryani Point", role="vendor"),
        item("food", "delivery_fee", 3000, e="regular meal", sender="Biryani Point", role="vendor"),
        item("judging", "judges_available", 12, sender="Panel lead", role="organizer"),
        item("judging", "max_teams_per_judge", 4, sender="Panel lead", role="organizer"),
        item("judging", "minutes_per_team", 10, sender="Panel lead", role="organizer"),
        item("judging", "honorarium", 4000, sender="Panel lead", role="organizer"),
        item("budget", "expense", 60000, e="trophies", sender="Accounts", role="finance"),
    ]


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / ".state")
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    for k in ("FALLBACK_BASE_URL", "FALLBACK_MODEL_NAME", "FALLBACK_API_KEY"):
        monkeypatch.setattr(config, k, "")   # tests never depend on the developer's .env fallback
    import llm
    llm._BROKEN_ROUTES.clear()               # route memory is per process: never shared between tests
    yield tmp_path
