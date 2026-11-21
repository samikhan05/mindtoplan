"""Live benchmark: runs message packs + updates through plan.py (real model calls, settings from .env)
in throwaway copies of a code directory, and checks each step against hand-computed expected figures.

    python benchmark.py                      # current code, every scenario once
    python benchmark.py --runs 3             # repeat (model output varies run to run)
    python benchmark.py --code ../baseline   # benchmark another checkout (e.g. a git worktree) the same way

Expected figures below are TEST FIXTURES worked out by hand from the message files; production code never
imports this file. Packs live in samples/ (sample pack, unseen test) and samples/bench/ (synthetic packs)."""
import argparse
import json
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


def run_scenario(code, name, steps, py, keep=False):
    work = Path(tempfile.mkdtemp(prefix=f"bench_{name}_"))
    for f in code.glob("*.py"):
        shutil.copy(f, work)
    shutil.copy(ROOT / ".env", work)
    rows = []
    for msg_file, exp in steps:
        time.sleep(PAUSE)   # free-tier keys rate-limit bursts (429); a pause keeps retries out of the numbers
        t0 = time.monotonic()
        subprocess.run([py, "plan.py", str(ROOT / msg_file)], cwd=work, capture_output=True, timeout=240)
        wall = time.monotonic() - t0
        sp = work / ".state" / "state.json"
        if not sp.exists():
            rows.append({"step": Path(msg_file).name, "fail": ["no state (run crashed)"]})
            continue
        state = json.loads(sp.read_text(encoding="utf-8"))
        rep = state["updates"][-1]
        recs = [r for r in state["trace"] if r["update_id"] == rep["update_id"]]
        got = actual(state, rep)
        rows.append({"step": Path(msg_file).name, "mode": rep["mode"], "calls": rep["calls"],
                     "retries": sum(1 for r in recs if r.get("attempt", 1) > 1),
                     "in": rep["tokens"]["input"], "out": rep["tokens"]["output"], "total": rep["tokens"]["total"],
                     "unavailable": rep["tokens"]["unavailable"], "s": rep["seconds"], "wall": round(wall, 1),
                     "errors": [r["error"][:80] for r in recs if r.get("error")],
                     "got": got, "fail": check(exp, got)})
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
    a = ap.parse_args()
    code, py = Path(a.code).resolve(), sys.executable
    results = []
    for run in range(1, a.runs + 1):
        for name, steps in SCENARIOS.items():
            if a.only and name not in a.only:
                continue
            for row in run_scenario(code, name, steps, py, a.keep):
                row.update(scenario=name, run=run)
                results.append(row)
                mark = "OK  " if not row["fail"] else "FAIL"
                print(f"{mark} run{run} {name:12} {row['step']:26} " + (
                    f"calls={row['calls']} retries={row['retries']} in={row['in']} out={row['out']} "
                    f"total={row['total']} s={row['s']} " if "calls" in row else "") +
                    (f"-> {'; '.join(row['fail'])}" if row["fail"] else "") +
                    (f" errors={row['errors']}" if row.get("errors") else ""), flush=True)
    done = [r for r in results if "calls" in r]
    for mode in ("full", "update"):
        rs = [r for r in done if r["mode"] == mode and not r["errors"]]
        if rs:
            print(f"\n{mode:6}: steps={len(rs)} correct={sum(not r['fail'] for r in rs)}/{len(rs)} "
                  f"avg in={statistics.mean(r['in'] for r in rs):.0f} out={statistics.mean(r['out'] for r in rs):.0f} "
                  f"total={statistics.mean(r['total'] for r in rs):.0f} calls={statistics.mean(r['calls'] for r in rs):.2f} "
                  f"time={statistics.mean(r['s'] for r in rs):.1f}s")
    errs = [r for r in done if r["errors"]]
    print(f"steps hit by provider errors (excluded from averages): {len(errs)}; "
          f"correct overall: {sum(not r['fail'] for r in results)}/{len(results)}")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
