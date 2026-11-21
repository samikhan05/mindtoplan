"""The only place that talks to a model. Every call goes through the Budgeter and lands in the trace."""
import json
import re
import time
from datetime import datetime

import config

AREAS = ("reading", "venue", "schedule", "food", "judging", "budget")


class ConfigError(Exception):
    pass


class BudgetExhausted(Exception):
    pass


class Budgeter:
    """Wall-clock deadline and call cap for one run (full or update). Retries count as calls."""

    def __init__(self, mode):
        self.mode = mode
        self.start = time.monotonic()
        self.limit = config.FULL_RUN_SECONDS if mode == "full" else config.UPDATE_SECONDS
        self.max_calls = config.FULL_RUN_MAX_CALLS if mode == "full" else config.UPDATE_MAX_CALLS
        self.calls = 0
        self.incomplete = False

    def elapsed(self):
        return time.monotonic() - self.start

    def remaining(self):
        return self.limit - config.SAFETY_SECONDS - self.elapsed()

    def can_call(self):
        return self.calls < self.max_calls and self.remaining() > 2


class Trace:
    def __init__(self, records=None):
        self.records = records or []

    def totals(self, records=None):
        recs = self.records if records is None else records
        t = {"calls": len(recs), "input": 0, "output": 0, "total": 0, "unavailable": 0}
        for r in recs:
            if r["total_tokens"] is None:
                t["unavailable"] += 1
                continue
            t["input"] += r["input_tokens"] or 0
            t["output"] += r["output_tokens"] or 0
            t["total"] += r["total_tokens"]
        return t


def parse_json(text):
    """First complete JSON value in the reply; ignores code fences and trailing text (e.g. a stray '.')."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=0)
    try:
        value, _ = json.JSONDecoder().raw_decode(t[start:])
        return value
    except json.JSONDecodeError:
        pass
    # small models sometimes drop or misplace a bracket: repair each {"id": ...} record on its own
    starts = [m.start() for m in re.finditer(r'\{\s*"id"\s*:', t)]
    if not starts:
        value, _ = json.JSONDecoder().raw_decode(_balance(t[start:]))
        return value
    records = []
    for a, z in zip(starts, starts[1:] + [len(t)]):
        chunk = t[a:z].rstrip().rstrip(",").rstrip()
        try:
            rec, _ = json.JSONDecoder().raw_decode(_balance(chunk))
            records.append(rec)
        except json.JSONDecodeError:
            continue          # an unrepairable record is skipped; its message is re-read on the next run
    if not records:
        raise json.JSONDecodeError("no readable message records", t, 0)
    return {"m": records}


def _balance(s):
    """Repair bracket structure only: insert missing closers, add closers left open at the end."""
    out, stack, in_str, esc = [], [], False, False
    pair = {"{": "}", "[": "]"}
    for ch in s:
        if in_str:
            out.append(ch)
            esc = (ch == "\\" and not esc)
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in pair:
            stack.append(pair[ch])
        elif ch in "}]":
            while stack and stack[-1] != ch:
                out.append(stack.pop())
            if not stack:
                break                       # extra closer: the JSON value is complete
            stack.pop()
        out.append(ch)
        if not stack and ch in "}]":
            break
    return "".join(out) + "".join(reversed(stack))


def _client(timeout):
    if not (config.API_KEY and config.BASE_URL and config.MODEL_NAME):
        raise ConfigError("Missing model settings: set BASE_URL, MODEL_NAME and API_KEY in .env "
                          "(see .env.example).")
    if config.ALLOWED_MODELS and config.MODEL_NAME not in config.ALLOWED_MODELS:
        raise ConfigError(f"MODEL_NAME {config.MODEL_NAME!r} is not in ALLOWED_MODELS.")
    from openai import OpenAI
    return OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL, timeout=timeout, max_retries=0)


def call_model(budgeter, trace, area, system, user, message_ids, update_id, max_tokens=2000):
    """One logical call, at most one retry. Returns parsed JSON dict or None. Never raises for API errors."""
    assert area in AREAS
    for attempt in (1, 2):
        if not budgeter.can_call():
            budgeter.incomplete = True
            return None
        budgeter.calls += 1
        rec = {"n": len(trace.records) + 1, "timestamp": datetime.now().isoformat(timespec="seconds"),
               "model": config.MODEL_NAME, "area": area, "update_id": update_id,
               "message_ids": message_ids, "attempt": attempt,
               "input": {"system": system, "user": user}, "output": "",
               "input_tokens": None, "output_tokens": None, "total_tokens": None,
               "duration_s": 0.0, "ok": False, "error": None}
        t0 = time.monotonic()
        try:
            client = _client(timeout=max(budgeter.remaining(), 1))
            extra = {"reasoning_effort": config.REASONING_EFFORT} if config.REASONING_EFFORT else {}
            resp = client.chat.completions.create(**extra,
                model=config.MODEL_NAME, temperature=0, max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            rec["model"] = resp.model or config.MODEL_NAME
            rec["output"] = resp.choices[0].message.content or ""
            if resp.usage:
                rec["input_tokens"] = resp.usage.prompt_tokens
                rec["output_tokens"] = resp.usage.completion_tokens
                rec["total_tokens"] = resp.usage.total_tokens
            parsed = parse_json(rec["output"])
            rec["ok"] = True
            return parsed
        except ConfigError:
            budgeter.calls -= 1   # no request was sent, so no call happened
            raise
        except Exception as e:  # API error, timeout or invalid JSON: record honestly
            rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            resp = getattr(e, "response", None)
            if resp is not None:   # providers sometimes put the real reason only in the body: keep it
                body = (getattr(resp, "text", "") or "").strip()
                rec["error"] += (f" | body: {body[:400]}" if body else " | empty body") + \
                    f" | endpoint {config.BASE_URL} model {config.MODEL_NAME}"
            if getattr(e, "status_code", None) in (429, 500, 503) and budgeter.remaining() > 15:
                time.sleep(3)   # overloaded / rate limited: brief pause before the single retry
        finally:
            rec["duration_s"] = round(time.monotonic() - t0, 2)
            if rec["ok"] or rec["error"]:
                trace.records.append(rec)
    return None
