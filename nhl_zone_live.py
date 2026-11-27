"""
Live watcher for NHL zone time.

Keeps running and checks NHL EDGE every few minutes. When any team's zone time
changes (EDGE updates after games finish, not during them), it:
  1. saves fresh data to zone_time.csv
  2. re-runs the model + forecast and saves zone_predictions.csv
  3. prints which teams moved
  4. rebuilds the Excel dashboard, nhl_zone_dashboard.xlsx

Leave it running in a terminal. Press Ctrl+C to stop.

Usage:
    python nhl_zone_live.py               # check every 30 minutes
    python nhl_zone_live.py --interval 10 # check every 10 minutes
"""

import argparse
import datetime
import os
import subprocess
import sys
import time

from nhl_zone_time import collect, save_csv

HERE = os.path.dirname(os.path.abspath(__file__))
ZONE_CSV = os.path.join(HERE, "zone_time.csv")
PRED_CSV = os.path.join(HERE, "zone_predictions.csv")
MODEL = os.path.join(HERE, "nhl_zone_model.py")


LOG_FILE = None  # set by --log


def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M}] {msg}"
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def snapshot(rows):
    """{team: OZ%} for all situations, rounded so tiny float noise is ignored."""
    return {r["team"]: round(r["oz_pct"], 3) for r in rows if r["strength"] == "all"}


def update(rows, old, new):
    # 1. Raw data
    try:
        save_csv(rows, ZONE_CSV)
    except PermissionError:
        log("Could not save zone_time.csv - close it in Excel. Will retry next check.")
        return False

    # 2. Model + forecast (separate process so it always uses fresh code/data)
    result = subprocess.run([sys.executable, MODEL, "--csv", PRED_CSV],
                            cwd=HERE, capture_output=True, text=True)
    if result.returncode != 0:
        if "Permission denied" in result.stderr:
            log("Could not save zone_predictions.csv - close it in Excel. Will retry next check.")
        else:
            log("Model run failed:\n" + result.stderr[-1500:])
        return False

    # 3. What changed
    if old:
        moves = sorted(((t, new[t] - old.get(t, new[t])) for t in new),
                       key=lambda kv: -abs(kv[1]))
        moves = [(t, d) for t, d in moves if abs(d) >= 0.01]
        if moves:
            log("OZ% changes: " + ", ".join(f"{t} {d:+.2f}" for t, d in moves[:10])
                + (" ..." if len(moves) > 10 else ""))
    log("Updated zone_time.csv and zone_predictions.csv")

    # 4. Excel dashboard (charts). A failure here doesn't undo the CSV update.
    try:
        from nhl_zone_excel import build
        build()
        log("Updated nhl_zone_dashboard.xlsx")
    except PermissionError:
        log("Could not save nhl_zone_dashboard.xlsx - close it in Excel. CSVs were updated.")
    except Exception as exc:
        log(f"Excel dashboard failed ({exc}). CSVs were updated.")
    return True


def main():
    p = argparse.ArgumentParser(description="Re-run the NHL zone time model whenever EDGE updates.")
    p.add_argument("--interval", type=float, default=30, help="Minutes between checks (default 30)")
    p.add_argument("--once", action="store_true",
                   help="Update once and exit (used by the daily Task Scheduler job)")
    p.add_argument("--log", metavar="FILE", help="Also append log lines to this file")
    args = p.parse_args()
    if args.interval < 5:
        p.error("--interval must be at least 5 minutes (be kind to the NHL's servers)")

    global LOG_FILE
    LOG_FILE = args.log

    if args.once:
        try:
            rows = collect(quiet=True)
            ok = update(rows, None, snapshot(rows))
        except Exception as exc:
            log(f"Daily update failed ({exc}).")
            ok = False
        sys.exit(0 if ok else 1)

    log(f"Watching NHL EDGE zone time, checking every {args.interval:g} min. Ctrl+C to stop.")
    last = None
    while True:
        try:
            rows = collect(quiet=True)
            current = snapshot(rows)
            if current != last:
                log("New data found." if last else "First check - building files.")
                if update(rows, last, current):
                    last = current
            else:
                log("No change.")
        except Exception as exc:  # network hiccup etc. - keep watching
            log(f"Check failed ({exc}). Will try again.")
        try:
            time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    log("Stopped.")
