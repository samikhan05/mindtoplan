"""Missing values: recover in Python when the fact's own quote states exactly one unambiguous number (phase 3A),
and list what is still missing so only those facts are asked about again (phase 3B). Generic: no pack facts."""
import re

from facts import num

TIME_KEYS = {"start_time", "at_time"}
DURATION_KEYS = {"duration_min", "break_min", "activity_min", "minutes_per_team", "late_min"}
PERCENT_KEYS = {"percent_charge", "reserve_pct"}
NUMBER_KEYS = {"students", "team_size", "staff", "budget_total", "capacity", "price", "price_per_head",
               "delivery_fee", "order_qty", "diet_count", "judges_available", "honorarium", "max_teams_per_judge",
               "judges_leaving_early", "expense", "optional_cost", "cost_per_team", "cost_per_student",
               "cost_per_person", "cost_per_judge"} | PERCENT_KEYS
VALUE_KEYS = NUMBER_KEYS | DURATION_KEYS | TIME_KEYS

_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b|\b(\d{1,2})\s*(am|pm)\b", re.I)
# 1,234,567 (international) | 1,80,000 / 12,50,000 (South Asian lakh grouping) | 1234
# a comma after a number ends it ("Rs 50,000, generator included" is 50000, not 50)
_NUM = re.compile(r"(?<![\w.:,])(\d{1,3}(?:,\d{3})+(?!,?\d)|\d{1,2}(?:,\d{2})+,\d{3}(?!,?\d)|\d+)(\.\d+)?(?![\d:])")
_SCALE = re.compile(r"^\s*(k\b|lakh|lac|crore|million|thousand|m\b|bn|billion)", re.I)
_DUR = re.compile(r"^\s*-?\s*(minutes?|mins?|hours?|hrs?|h\b)", re.I)


def missing(item):
    """True when a value-carrying fact has no usable value (what the planner would have to skip)."""
    k, v = item["k"], item["v"]
    if k not in VALUE_KEYS or item["t"] in ("suggestion", "question", "irrelevant"):
        return False
    if k in TIME_KEYS:
        from planner import clock
        return v is None or clock(str(v)) is None
    return num(v) is None


def _clock(m):
    if m.group(1):
        h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    else:
        h, mi, ap = int(m.group(4)), 0, m.group(5).lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


# Explicit "no charge" wording = 0 for a charge the model read without a value. Deliberately narrow: a bare "free"
# never counts ("Hall A is free on Monday" means available); delivery phrases only for the delivery fee.
CHARGE_KEYS = {"delivery_fee", "price", "price_per_head", "honorarium", "cost_per_team", "cost_per_student",
               "cost_per_person", "cost_per_judge"}
# "no charge"/"no fee" only when nothing qualifies it ("no extra charge", "no service charge" and "no fee discussion"
# say nothing about this price being zero)
_NO_CHARGE = re.compile(r"\b(waived?|free of (?:charge|cost)|without (?:any )?charges?|muft)\b|"
                        r"\bno (?:charges?|fees?)(?=\s*(?:[.,;:!?)]|$|\b(?:now|ab|hai|at all)\b))", re.I)
_FREE_DELIVERY = re.compile(r"\b(free delivery|delivery (?:is |will be |hai |bhi )?free|"
                            r"no delivery (?:charges?|fees?))\b", re.I)
# an English negation turns "waived" into its opposite ("will not be waived", "cannot waive")
_NEGATION = re.compile(r"\b(not|cannot|can't|can not|won't|wont|isn't|aren't|never|no longer)\b", re.I)


def _zero_charge(k, text):
    if k not in CHARGE_KEYS or _NEGATION.search(text):
        return False
    return bool(_NO_CHARGE.search(text)) or (k == "delivery_fee" and bool(_FREE_DELIVERY.search(text)))


def recover(item):
    """(value, note) when the quote holds exactly one unambiguous number of the right kind, else None."""
    q, k = item.get("q") or "", item["k"]
    if _zero_charge(k, q) and not _NUM.findall(q):
        return 0, f"{k} 0 recovered from its quote (no-charge wording)"
    times = list(_TIME.finditer(q))
    if k in TIME_KEYS:
        # one clock time and no other number in the quote
        if len(times) == 1 and not _NUM.findall(_TIME.sub(" ", q)):
            t = _clock(times[0])
            return (t, f"time {t} recovered from its quote") if t else None
        return None
    if times:
        return None                                     # a clock time next to a count/price: ambiguous
    nums = list(_NUM.finditer(q))
    if len(nums) != 1:
        return None                                     # none, or several numbers: never guess
    m = nums[0]
    after = q[m.end():]
    if _SCALE.match(after):
        return None                                     # "1.2 lakh", "50k": scale words are not plain values
    value = float((m.group(1) + (m.group(2) or "")).replace(",", ""))
    if k in DURATION_KEYS:
        unit = _DUR.match(after)
        if not unit:
            return None                                 # a duration needs its unit
        if unit.group(1).lower().startswith("h"):
            value *= 60
    elif after.lstrip().startswith("%") and k not in PERCENT_KEYS:
        return None                                     # a percentage where an amount is expected
    value = int(value) if value == int(value) else value
    return value, f"{k} {value} recovered from its quote"


def accepts(item, value, text):
    """A value returned by the targeted re-check, kept only if it is actually written in the message text.
    Returns the value to store, or None."""
    k = item["k"]
    if k in TIME_KEYS:
        from planner import clock
        if value is None or clock(str(value)) is None:
            return None
        want = clock(str(value))
        written = {clock(t) for t in (_clock(m) for m in _TIME.finditer(text)) if t}
        return str(value) if want in written else None
    v = num(value)
    if v is None:
        return None
    if v == 0 and _zero_charge(k, item.get("q") or ""):
        return 0          # the fact's OWN quote says no charge (another charge waived in the message does not count)
    written = {float((m.group(1) + (m.group(2) or "")).replace(",", "")) for m in _NUM.finditer(text)}
    if v in written:
        return int(v) if v == int(v) else v
    if k in DURATION_KEYS and re.search(r"\bhours?\b|\bhrs?\b", text, re.I) and v / 60 in written:
        return int(v)                                   # "4-hour" written, 240 minutes returned
    return None
