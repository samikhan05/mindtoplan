"""Live benchmark: runs message packs + updates through plan.py (real model calls, settings from .env)
in throwaway copies of a code directory, and checks each step against hand-computed expected figures.

    python benchmark.py                      # current code, every scenario once
    python benchmark.py --runs 3             # repeat (model output varies run to run)
    python benchmark.py --code ../baseline   # benchmark another checkout (e.g. a git worktree) the same way

Each step is put in one category: clean (correct), wrong (clean response, wrong figures), temporary (provider
overload/timeout/key error), quota (used up: the benchmark stops), after_provider_failure, crashed.

Expected figures below are TEST FIXTURES worked out by hand from the message files; production code never
imports this file. Packs live in samples/ (sample pack, unseen test) and samples/bench/ (synthetic packs)."""
import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).parent
S, B = "samples", "samples/bench"
PAUSE = 6   # seconds between steps

# each step: (message file, expected). Keys: status, teams, headcount, judges, venue, total, rejected (min count),
# messages (new messages detected). Only figures a correct plan must have; schedule details are left to the validator.
SCENARIOS = {
    "judging": [       # the official judging pack (regression) + three updates written for it
        (f"{S}/judging_pack.txt", dict(status="VALID", messages=10, teams=30, headcount=136, judges=8, venue="Hall 2",
                                       total=344160)),
        (f"{B}/j_u1_banners.txt", dict(status="VALID", total=347160)),
        (f"{B}/j_u2_wrong_boxes.txt", dict(status="VALID", total=347160, rejected=1)),
        (f"{B}/j_u3_more_students.txt", dict(status="VALID", teams=35, headcount=157, judges=9, total=370795)),
    ],
    "sample": [
        (f"{S}/messages.txt", dict(status="VALID", teams=50, headcount=177, judges=17, venue="Hall A", total=547400)),
        (f"{S}/practice_printing.txt", dict(status="VALID", total=552400)),
        (f"{S}/practice_wrong.txt", dict(status="VALID", total=552400, rejected=1)),
    ],
    "unseen": [
        (f"{S}/unseen_test.txt", dict(status="VALID", teams=30, headcount=136, judges=8, venue="Crystal Hall",
                                      total=389600)),
    ],
    "synthetic_a": [   # Roman Urdu, no-stairs need vs 2nd-floor hall, veg split, duplicate, optional + irrelevant
        (f"{B}/pack_a.txt", dict(status="VALID", messages=10, teams=30, headcount=102, judges=6, venue="Auditorium",
                                 total=237600)),
        (f"{B}/a_u1_more_students.txt", dict(status="VALID", teams=35, headcount=118, judges=7, total=251800)),
        (f"{B}/a_u2_wrong_boxes.txt", dict(status="VALID", total=251800, rejected=1)),
        (f"{B}/a_u3_free_delivery.txt", dict(status="VALID", total=246800)),
    ],
    "synthetic_b": [   # Dec->Jan dates, tentative then final count, booked hall, 10% reserve, 5% food charge,
        (f"{B}/pack_b.txt", dict(status="VALID", messages=8, teams=50, headcount=225, judges=13, venue="Hall B",
                                 total=680625, rejected=1)),           # student's budget claim rejected
        (f"{B}/b_u1_swag.txt", dict(status="VALID", total=695625)),
        (f"{B}/b_u2_wrong_students.txt", dict(status="VALID", total=695625, rejected=1)),
        (f"{B}/b_u3_judge_load.txt", dict(status="VALID", teams=50, headcount=229, judges=17, total=723405)),
    ],
}


def actual(state, rep):
    p = state.get("plan") or {}
    d, b, v = p.get("derived", {}), p.get("budget", {}), (p.get("venue") or {}).get("chosen")
    return {"status": (p.get("validation") or {}).get("status"), "teams": d.get("teams"),
            "headcount": d.get("headcount"), "judges": d.get("judges_used"), "venue": v and v["name"],
            "total": b.get("total") and round(float(b["total"])), "rejected": len(rep["rejected"]),
            "messages": len(rep["new_messages"])}


def check(exp, got):
    bad = []
    for k, want in exp.items():
        have = got.get(k)
        ok = (have or 0) >= want if k == "rejected" else (
            str(have).lower() == str(want).lower() if isinstance(want, str) else have == want)
        if not ok:
            bad.append(f"{k}={have} (want {want})")
    return bad


# provider-side failures (not the model's answer): used-up quota, overload/rate limit/server error, timeouts, bad
# key or no credit. Bad JSON or a wrong reply shape is the MODEL's failure and stays in the accuracy numbers.
_QUOTA = re.compile(r"exceeded your current quota", re.I)
_PROVIDER = re.compile(r"Error code: (4(?:01|02|03|08|29)|5\d\d)|Timeout|APIConnectionError|ConnectionError", re.I)


def provider_kind(errors):
    """'quota', 'temporary' or None for one step's error list."""
    if any(_QUOTA.search(e) for e in errors):
        return "quota"
    return "temporary" if any(_PROVIDER.search(e) for e in errors) else None


def run_scenario(code, name, steps, py, keep=False, env=()):
    work = Path(tempfile.mkdtemp(prefix=f"bench_{name}_"))
    for f in code.glob("*.py"):
        shutil.copy(f, work)
    shutil.copy(ROOT / ".env", work)
    if env:   # overrides for an experiment (e.g. MODEL_NAME=...); later lines win in .env
        with open(work / ".env", "a", encoding="utf-8") as fh:
            fh.write("\n" + "\n".join(env) + "\n")
    rows, hit = [], False
    for msg_file, exp in steps:
        time.sleep(PAUSE)   # free-tier keys rate-limit bursts (429); a pause keeps retries out of the numbers
        t0 = time.monotonic()
        subprocess.run([py, "plan.py", str(ROOT / msg_file)], cwd=work, capture_output=True, timeout=240)
        wall = time.monotonic() - t0
        sp = work / ".state" / "state.json"
        if not sp.exists():
            rows.append({"step": Path(msg_file).name, "fail": ["no state (run crashed)"], "category": "crashed"})
            continue
        state = json.loads(sp.read_text(encoding="utf-8"))
        rep = state["updates"][-1]
        recs = [r for r in state["trace"] if r["update_id"] == rep["update_id"]]
        got = actual(state, rep)
        errors = [r["error"] for r in recs if r.get("error")]
        kind = provider_kind(errors)
        fail = check(exp, got)
        # an update after a provider-hit step starts from a different state: not a fair accuracy sample
        category = kind or ("after_provider_failure" if hit else ("wrong" if fail else "clean"))
        hit = hit or bool(kind)
        rows.append({"category": category, "step": Path(msg_file).name, "mode": rep["mode"], "calls": rep["calls"],
                     "retries": sum(1 for r in recs if r.get("attempt", 1) > 1),
                     "in": rep["tokens"]["input"], "out": rep["tokens"]["output"], "total": rep["tokens"]["total"],
                     "unavailable": rep["tokens"]["unavailable"], "s": rep["seconds"], "wall": round(wall, 1),
                     "errors": errors, "got": got, "fail": fail})
        if kind == "quota":
            break      # the rest of this scenario cannot be read either
    if keep:
        print(f"   (kept {work})")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default=str(ROOT), help="directory with the .py files to benchmark")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", nargs="*", help="scenario names")
    ap.add_argument("--json", help="write raw results here")
    ap.add_argument("--keep", action="store_true", help="keep each scenario's work folder (state + trace)")
    ap.add_argument("--env", nargs="*", default=[], help="KEY=VALUE overrides for this benchmark only")
    ap.add_argument("--full-only", action="store_true", help="only the first (full-run) step of each scenario")
    a = ap.parse_args()
    code, py = Path(a.code).resolve(), sys.executable
    results, quota = [], False
    for run in range(1, a.runs + 1):
        for name, steps in SCENARIOS.items():
            if a.only and name not in a.only:
                continue
            if quota:
                break
            for row in run_scenario(code, name, steps[:1] if a.full_only else steps, py, a.keep, a.env):
                row.update(scenario=name, run=run)
                results.append(row)
                mark = "OK  " if not row["fail"] else "FAIL"
                print(f"{mark} run{run} {name:12} {row['step']:26} " + (
                    f"calls={row['calls']} retries={row['retries']} in={row['in']} out={row['out']} "
                    f"total={row['total']} s={row['s']} " if "calls" in row else "") +
                    (f"-> {'; '.join(row['fail'])}" if row["fail"] else "") +
                    (f" [{row['category']}] errors={[e[:80] for e in row['errors']]}" if row.get("errors") else
                     (f" [{row['category']}]" if row["category"] != "clean" else "")), flush=True)
                quota = quota or row["category"] == "quota"
        if quota:
            print("\nSTOPPED: the provider says the quota is used up; no more requests are sent. "
                  "Results so far are kept; rerun after the quota resets.", flush=True)
            break
    done = [r for r in results if "calls" in r]
    for mode in ("full", "update"):    # accuracy and cost: clean model responses only
        rs = [r for r in done if r["mode"] == mode and r["category"] in ("clean", "wrong")]
        if rs:
            print(f"\n{mode:6}: steps={len(rs)} correct={sum(not r['fail'] for r in rs)}/{len(rs)} "
                  f"avg in={statistics.mean(r['in'] for r in rs):.0f} out={statistics.mean(r['out'] for r in rs):.0f} "
                  f"total={statistics.mean(r['total'] for r in rs):.0f} calls={statistics.mean(r['calls'] for r in rs):.2f} "
                  f"time={statistics.mean(r['s'] for r in rs):.1f}s")
    cats = {c: [r for r in results if r["category"] == c]
            for c in ("clean", "wrong", "temporary", "quota", "after_provider_failure", "crashed")}
    fair = cats["clean"] + cats["wrong"]
    print(f"\nclean model responses: correct {len(cats['clean'])}/{len(fair)}  <- accuracy (extraction + planning)")
    print(f"temporary provider failures (429/5xx/timeout/key): {len(cats['temporary'])} steps, "
          f"still correct {sum(not r['fail'] for r in cats['temporary'])}  <- reliability, not accuracy")
    print(f"quota used up: {len(cats['quota'])} steps;  after a provider-hit step: "
          f"{len(cats['after_provider_failure'])};  crashed: {len(cats['crashed'])}")
    print(f"correct overall: {sum(not r['fail'] for r in results)}/{len(results)}")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
