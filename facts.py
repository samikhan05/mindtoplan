"""Fact store. Items are kept in arrival order; status is recomputed by replay so any item can be
rejected later (transactional updates) and the facts it superseded come back automatically."""
import re

import config

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# keys where several values can be true at once (no superseding)
MULTI_KEYS = {"feature", "lacks_feature", "requires_feature", "rule", "other", "late_min", "judges_leaving_early"}
NOT_FACT_KINDS = {"suggestion", "question", "irrelevant"}
MAGNITUDE_LIMIT = 20     # a correction that changes a number 20x or more is treated as a unit/typing error
VENDOR_KEYS = {"capacity", "price", "feature", "unavailable", "price_per_head", "delivery_fee", "tier", "order_qty"}


def parse_date(s):
    """(month, day) from text like '9 Nov', 'Nov 9', '09/11'. No year is invented."""
    if not s:
        return None
    s = s.lower()
    mon = next((MONTHS[k] for k in MONTHS if k in s), None)
    nums = [int(n) for n in re.findall(r"\d+", s) if int(n) <= 31]
    if mon and nums:
        return (mon, nums[0])
    if len(nums) >= 2 and nums[1] <= 12:
        return (nums[1], nums[0])          # dd/mm
    return None


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v or ""))
    return float(m.group().replace(",", "")) if m else None


# one value per event, whatever area/entity label the model attached
GLOBAL_KEYS = {"students", "team_size", "staff", "duration_min", "budget_total", "start_time", "location",
               "judges_available", "honorarium", "minutes_per_team", "max_teams_per_judge", "reserve_pct"}


def key_of(f):
    if f["k"] in GLOBAL_KEYS:
        return ("*", "", f["k"])
    return (f["a"], norm(f["e"]), f["k"])


def resolve(items):
    """Compute status for every item. items carry 'order' (chronology) and may carry status='rejected'
    (set by validation). Returns the same list with status/reason filled in."""
    active = {}
    for f in sorted(items, key=lambda x: x["order"]):
        if f.get("locked"):               # rejected by validation or flagged; stays rejected
            continue
        f["status"], f["reason"] = "accepted", ""
        if f["t"] in ("suggestion", "question") and f["k"] in GLOBAL_KEYS | VENDOR_KEYS | {"expense"}:
            f["status"] = "rejected"
            f["reason"] = (f"'{f['sender']}' only requests/claims a change to {f['k']} ({f['v']}); "
                           "not a confirmed fact, so the plan keeps the current value")
            continue
        if f["t"] in NOT_FACT_KINDS:
            f["status"] = "optional" if f["k"] == "optional_cost" else "noted"
            f["reason"] = {"suggestion": "a request/quote, not approved: never counted as spending",
                           "question": "a question, not a fact",
                           "irrelevant": "not relevant to the plan"}[f["t"]]
            continue
        if f["k"] in MULTI_KEYS:
            continue
        k = key_of(f)
        old = active.get(k)
        if old is not None:
            a, b = num(old["v"]), num(f["v"])
            if a and b and max(a, b) / min(a, b) >= MAGNITUDE_LIMIT:
                f["status"] = "rejected"
                f["reason"] = (f"magnitude check: {f['k']} {b:,.0f} vs previous {a:,.0f} from {old['msg']} "
                               f"(x{max(a, b) / min(a, b):,.0f}); likely a unit or typing error")
                continue
            same_sender = norm(old["sender"]) == norm(f["sender"])
            vendor_offer = f["role"] == "vendor" and f["k"] in VENDOR_KEYS   # a vendor owns its own offer terms
            if same_sender or vendor_offer or \
                    config.AUTHORITY.get(f["role"], 0) >= config.AUTHORITY.get(old["role"], 0):
                old["status"] = "superseded"
                old["reason"] = f"replaced by {f['msg']} ({f['sender']}, {f['date'] or 'later'}): {f['q']}"
            else:
                f["status"] = "rejected"
                f["reason"] = (f"sender '{f['sender']}' ({f['role']}) lacks authority to change "
                               f"{f['k']} set by '{old['sender']}' ({old['role']})")
                continue
        active[k] = f
    return items


def active(items):
    return [f for f in items if f.get("status") == "accepted"]


class View:
    """Read helpers over accepted facts."""

    def __init__(self, items):
        self.facts = active(items)

    def get(self, k, a=None):
        hits = [f for f in self.facts if f["k"] == k and (a is None or k in GLOBAL_KEYS or f["a"] == a)]
        return hits[-1] if hits else None

    def val(self, k, a=None):
        f = self.get(k, a)
        return num(f["v"]) if f else None

    def all(self, k):
        return [f for f in self.facts if f["k"] == k]

    def options(self, area, keys):
        """Group facts of an area by entity -> {key: fact}."""
        out = {}
        for f in self.facts:
            if f["a"] == area and f["k"] in keys:
                out.setdefault(norm(f["e"]), {}).setdefault("_name", f["e"])
                if f["k"] in ("feature", "lacks_feature"):
                    out[norm(f["e"])].setdefault(f["k"], []).append(f)
                else:
                    out[norm(f["e"])][f["k"]] = f
        return out


# generic facility vocabulary: different words for the same facility (no pack facts)
FACILITY_GROUPS = [
    {"step free", "stepfree", "step-free", "ramp", "wheelchair", "ground floor", "accessible", "accessibility",
     "lift", "elevator", "barrier free", "disabled access", "no stairs", "without stairs", "stair free",
     "stairless", "level access", "no steps"},
    {"generator", "backup power", "power backup", "standby power", "ups"},
    {"projector", "screen", "multimedia", "display"},
    {"air conditioning", "air conditioned", "ac", "a c", "cooling"},
    {"wifi", "wi fi", "internet", "wireless"},
    {"parking", "car park"},
    {"prayer room", "prayer area", "musalla"},
]


def same_facility(need, feat):
    if need in feat or feat in need:
        return True
    has = lambda text, w: f" {w} " in f" {text.replace('-', ' ')} "      # whole words only
    return any(any(has(need, w) for w in g) and any(has(feat, w) for w in g) for g in FACILITY_GROUPS)
