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
        """Sums of PROVIDER-REPORTED usage only; nothing is estimated. A call with no usage at all is counted
        in 'unavailable' (never as zero tokens); partial usage (e.g. no total) keeps the parts it has."""
        recs = self.records if records is None else records
        t = {"calls": len(recs), "input": 0, "output": 0, "total": 0, "unavailable": 0, "failed": 0,
             "retries": 0, "cached_input": 0, "by_area": {}}
        for r in recs:
            t["failed"] += not r.get("ok")
            t["retries"] += r.get("attempt", 1) > 1
            t["cached_input"] += r.get("cached_input_tokens") or 0
            parts = [r.get("input_tokens"), r.get("output_tokens"), r.get("total_tokens")]
            if all(v is None for v in parts):
                t["unavailable"] += 1
                continue
            total = r["total_tokens"] if r.get("total_tokens") is not None else                 (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
            t["input"] += r.get("input_tokens") or 0
            t["output"] += r.get("output_tokens") or 0
            t["total"] += total
            t["by_area"][r["area"]] = t["by_area"].get(r["area"], 0) + total
        return t


def parse_json(text):
    """First complete JSON value in the reply; ignores code fences and trailing text (e.g. a stray '.')."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=0)
    try:
        value, end = json.JSONDecoder().raw_decode(t[start:])
        # a stray closer can end the value early ('...}]}],"id":"M4",...'): if more message records follow,
        # stopping here would silently lose them, so repair record by record instead
        if not re.search(r'"id"\s*:\s*"', t[start + end:]):
            return value
    except json.JSONDecodeError:
        pass
    # small models sometimes drop or misplace a bracket: repair each {"id": ...} record on its own.
    # A record starts at '{"id":' or, when its '{' was dropped, at '],"id":' / '},"id":' after a closed record.
    starts = []
    for m in re.finditer(r'"id"\s*:', t):
        i = m.start() - 1
        while i >= 0 and t[i].isspace():
            i -= 1
        if i >= 0 and t[i] == "{":
            starts.append((i, ""))
        elif i >= 0 and t[i] == ",":
            j = i - 1
            while j >= 0 and t[j].isspace():
                j -= 1
            if j >= 0 and t[j] in "]}":
                starts.append((i + 1, "{"))      # opening brace missing: supply it
    if not starts:
        value, _ = json.JSONDecoder().raw_decode(_balance(t[start:]))
        return value
    records = []
    for (a, pre), (z, _) in zip(starts, starts[1:] + [(len(t), "")]):
        chunk = (pre + t[a:z]).rstrip().rstrip(",").rstrip()
        try:
            rec, _ = json.JSONDecoder().raw_decode(_balance(chunk))
            records.append(rec)
        except json.JSONDecodeError:
            continue          # an unrepairable record is skipped; its message is re-read (see pipeline)
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


_BROKEN_ROUTES = set()   # routes that answered with an error a retry cannot fix (e.g. 402 no credit): skipped


def _routes():
    """Primary route from .env, plus an optional FALLBACK_* route used only when the primary is overloaded.
    A fallback that already failed with an unfixable error in this process is skipped (saves a wasted attempt)."""
    r = [(config.BASE_URL, config.MODEL_NAME, config.API_KEY)]
    if config.FALLBACK_BASE_URL and config.FALLBACK_MODEL_NAME and config.FALLBACK_API_KEY:
        fb = (config.FALLBACK_BASE_URL, config.FALLBACK_MODEL_NAME, config.FALLBACK_API_KEY)
        if fb[:2] not in _BROKEN_ROUTES:
            r.append(fb)
    return r


def _client(timeout, route=None):
    base, model, key = route or _routes()[0]
    if not (key and base and model):
        raise ConfigError("Missing model settings: set BASE_URL, MODEL_NAME and API_KEY in .env "
                          "(see .env.example).")
    if config.ALLOWED_MODELS and model.split("/")[-1] not in config.ALLOWED_MODELS and model not in config.ALLOWED_MODELS:
        raise ConfigError(f"MODEL_NAME {model!r} is not in ALLOWED_MODELS.")
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=base, timeout=timeout, max_retries=0)


RETRYABLE = (429, 500, 502, 503, 504)   # overloaded / rate limited / server error: worth another attempt
MAX_ATTEMPTS = 3          # any error
OVERLOAD_ATTEMPTS = 4     # overload/rate-limit errors only (they return no tokens); still bounded by the Budgeter


class ResponseSchemaError(Exception):
    """The reply parsed as JSON but its top-level type is not what the caller expects (e.g. a list where an
    object is required). Deterministic for the same request, so it is recorded and never retried."""


def call_model(budgeter, trace, area, system, user, message_ids, update_id, max_tokens=2000, attempts=MAX_ATTEMPTS,
               expect=dict):
    """One logical call: up to `attempts` tries (each counted as a call). Overload errors retry with a pause,
    on the FALLBACK route if one is set; errors a retry cannot fix (bad key, bad request, wrong reply shape) stop
    at once. `expect`: the JSON top-level type(s) the caller accepts (default: an object).
    Returns the parsed JSON value or None. Never raises for API or reply errors."""
    assert area in AREAS
    routes, route = _routes(), _routes()[0]
    limit = attempts                     # raised to OVERLOAD_ATTEMPTS only while the provider reports overload
    attempt = 0
    while attempt < limit:
        attempt += 1
        if not budgeter.can_call():
            budgeter.incomplete = True
            return None
        budgeter.calls += 1
        rec = {"n": len(trace.records) + 1, "timestamp": datetime.now().isoformat(timespec="seconds"),
               "model": route[1], "area": area, "update_id": update_id,
               "message_ids": message_ids, "attempt": attempt,
               "input": {"system": system, "user": user}, "output": "",
               "input_tokens": None, "output_tokens": None, "total_tokens": None,
               "duration_s": 0.0, "ok": False, "error": None}
        t0 = time.monotonic()
        try:
            client = _client(timeout=max(budgeter.remaining(), 1), route=route)
            extra = {"reasoning_effort": config.REASONING_EFFORT} if config.REASONING_EFFORT else {}
            resp = client.chat.completions.create(**extra,
                model=route[1], temperature=0, max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            rec["model"] = resp.model or route[1]
            rec["output"] = resp.choices[0].message.content or ""
            u = resp.usage
            if u:   # provider-reported only; a missing field stays None (never estimated)
                rec["input_tokens"] = getattr(u, "prompt_tokens", None)
                rec["output_tokens"] = getattr(u, "completion_tokens", None)
                rec["total_tokens"] = getattr(u, "total_tokens", None)
                if rec["total_tokens"] is None and None not in (rec["input_tokens"], rec["output_tokens"]):
                    rec["total_tokens"] = rec["input_tokens"] + rec["output_tokens"]
                    rec["usage_note"] = "total = input + output (provider sent no total)"
                details = getattr(u, "prompt_tokens_details", None)
                if details is not None and getattr(details, "cached_tokens", None):
                    rec["cached_input_tokens"] = details.cached_tokens   # still part of input_tokens
            parsed = parse_json(rec["output"])
            if not isinstance(parsed, expect):
                want = " or ".join(t.__name__ for t in (expect if isinstance(expect, tuple) else (expect,)))
                raise ResponseSchemaError(f"reply top level is JSON {type(parsed).__name__}, expected {want}")
            rec["ok"] = True
            return parsed
        except ConfigError:
            budgeter.calls -= 1   # no request was sent, so no call happened
            raise
        except ResponseSchemaError as e:
            rec["error"] = f"ResponseSchemaError: {e} | not retried (same request gives the same shape)"
            return None   # finally still records it (tokens were used and are reported)
        except Exception as e:  # API error, timeout or invalid JSON: record honestly
            rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            resp = getattr(e, "response", None)
            if resp is not None:   # providers sometimes put the real reason only in the body: keep it
                body = (getattr(resp, "text", "") or "").strip()
                rec["error"] += (f" | body: {body[:400]}" if body else " | empty body") + \
                    f" | endpoint {route[0]} model {route[1]}"
            status = getattr(e, "status_code", None)
            if status == 429 and "exceeded your current quota" in rec["error"].lower():
                # a used-up quota (e.g. a daily free-tier limit) is not a short overload: waiting will not fix it,
                # but another provider can still answer the same request
                if len(routes) > 1 and route == routes[0]:
                    route = routes[1]
                    rec["error"] += f" | quota used up: trying fallback {route[1]}"
                    continue
                status = 403
                rec["error"] += " | quota used up: treated as not retryable"
            if status is not None and status not in RETRYABLE:
                if len(routes) > 1 and route == routes[1]:
                    _BROKEN_ROUTES.add(route[:2])   # skip it for the rest of this process, not just this call
                    route = routes[0]          # the backup itself is broken (e.g. bad key): back to primary
                    routes = routes[:1]
                    rec["error"] += " | fallback unusable, retrying primary"
                    if budgeter.remaining() > 15:
                        time.sleep(3 * attempt)
                    continue
                rec["error"] += " | not retried (a retry cannot fix this)"
                return None   # finally still records it
            if status in RETRYABLE:
                if attempts == MAX_ATTEMPTS:
                    limit = max(limit, OVERLOAD_ATTEMPTS)   # short provider outages: one more patient attempt
                if len(routes) > 1 and route == routes[0]:
                    route = routes[1]          # same task, backup route; no pause needed
                    rec["error"] += f" | retrying via fallback {route[1]}"
                else:                          # overloaded / rate limited: back off 4, 8, 16 s within the budget
                    pause = min(4 * 2 ** (attempt - 1), budgeter.remaining() - 15)
                    if pause > 0 and attempt < limit:
                        time.sleep(pause)
            elif attempt >= MAX_ATTEMPTS:
                limit = attempt                # non-overload errors (e.g. invalid JSON) keep the old limit
        finally:
            rec["duration_s"] = round(time.monotonic() - t0, 2)
            if rec["ok"] or rec["error"]:
                trace.records.append(rec)
    return None
