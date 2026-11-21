"""Deterministic conversion of CLEAR requirements into checkable rules, so they need no extra model call.
Conservative by design: anything not matched exactly here still goes to the model (pipeline._rule_fallback),
and nothing is ever dropped. Generic vocabulary only; no facts from any message pack."""
import re

from facts import FACILITY_GROUPS, norm, num

# words that make a sentence a requirement (English + common Roman Urdu)
MARKERS = re.compile(r"\b(must|need|needs|needed|required?|requires|mandatory|should|have to|has to|keep|ensure|"
                     r"only|at least|at most|no more than|not more than|maximum|minimum|cannot|can't|never|"
                     r"lazmi|zaroori|zaruri|chahiye)\b", re.I)
_BREAK = [re.compile(r"(\d+)\s*-?\s*(?:minutes?|mins?)\s+(?:long\s+)?([a-z][a-z ]{0,24}?)\s*break", re.I),
          re.compile(r"([a-z][a-z ]{0,24}?)\s*break\s+(?:of|for)\s+(\d+)\s*(?:minutes?|mins?)", re.I)]
_PEOPLE = r"(?:people|persons|participants|attendees|guests|heads)"
_MAX = re.compile(r"\b(?:no more than|not more than|at most|maximum(?: of)?|max\.?|up to)\s+(\d[\d,]*)\s+" + _PEOPLE, re.I)
_MIN = re.compile(r"\b(?:at least|minimum(?: of)?|min\.?)\s+(\d[\d,]*)\s+" + _PEOPLE, re.I)
_END = re.compile(r"\b(?:finish|end|wrap up|close|over)\w*\s+(?:by|before|no later than)\s+"
                  r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", re.I)
_FACILITY_WORDS = sorted({w for g in FACILITY_GROUPS for w in g}, key=len, reverse=True)


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text or "") if s.strip()]


def _break(sentence):
    for i, rx in enumerate(_BREAK):
        m = rx.search(sentence)
        if m:
            mins, name = (m.group(1), m.group(2)) if i == 0 else (m.group(2), m.group(1))
            name = re.sub(r"^(a|an|the)\s+", "", name.strip().lower())
            return int(mins), (name + " break").strip()
    return None


def _facility(sentence):
    s = f" {norm(sentence)} "
    return next((norm(w) for w in _FACILITY_WORDS if f" {norm(w)} " in s), None)


def _covered_by(sentence, siblings):
    """A fact already extracted from the same message that states this requirement."""
    br = _break(sentence)
    if br:
        hit = next((f for f in siblings if f["k"] == "break_min" and num(f["v"]) == br[0]), None)
        if hit:
            return f"{hit['k']} {hit['e'] or ''} {hit['v']}".strip()
    fac = _facility(sentence)
    if fac:
        hit = next((f for f in siblings if f["k"] == "requires_feature" and f["v"] and
                    (norm(fac) in norm(f["v"]) or norm(f["v"]) in norm(fac) or _facility(str(f["v"])))), None)
        if hit:
            return f"requires_feature {hit['v']}"
    return None


def _convert(sentence):
    """Exactly one clear pattern -> ('c', constraint) or ('break', minutes, name). None if no pattern or if
    several match (e.g. "a ramp and no more than 100 people"): taking one would silently lose the other."""
    from planner import clock
    found = []
    br = _break(sentence)
    if br:
        found.append(("break",) + br)
    m = _MAX.search(sentence) or _MIN.search(sentence)
    if m:
        found.append(("c", {"m": "headcount", "op": "lte" if m.re is _MAX else "gte", "v": num(m.group(1))}))
    m = _END.search(sentence)
    if m and clock(m.group(1)) is not None:
        found.append(("c", {"m": "end_min", "op": "lte", "v": clock(m.group(1))}))
    fac = _facility(sentence)
    if fac:
        found.append(("c", {"m": "venue_features", "op": "requires", "v": fac}))
    return found[0] if len(found) == 1 else None


def python_rule(item, siblings):
    """item: a hard rule with no checkable form. siblings: other facts read from the same message.
    Returns (kind, payload, note) or None when the model is still needed:
      ('covered', None, why)         every requirement in the text is already a fact (or there is none)
      ('c', constraint, why)         exactly one clear constraint
      ('break', (minutes, name), why) a required break that was not extracted as a fact"""
    sents = _sentences(item.get("q"))
    reqs = [s for s in sents if MARKERS.search(s)]
    if not reqs:
        # no requirement wording at all: the model restated facts it also extracted (e.g. a whole approval)
        if len(siblings) >= 2:
            return ("covered", None, "no requirement wording; restates facts already read from this message")
        return None
    new = []
    covers = []
    for s in reqs:
        cov = _covered_by(s, siblings)
        if cov:
            covers.append(cov)
            continue
        conv = _convert(s)
        if conv is None:
            return None                          # one unclear requirement: let the model handle the whole item
        new.append(conv)
    if not new:
        return ("covered", None, "already stated by " + "; ".join(covers))
    if len(new) > 1:
        return None                              # several new constraints in one item: keep the model path
    kind = new[0]
    if kind[0] == "break":
        return ("break", kind[1:], f"required {kind[2]} of {kind[1]} min read in Python")
    return ("c", kind[1], f"converted in Python: {kind[1]['m']} {kind[1]['op']} {kind[1]['v']}")
