"""
NHL team zone time collector.

Pulls offensive / neutral / defensive zone time percentages for every NHL team
from the NHL EDGE puck-tracking API (api-web.nhle.com), for all strengths:
  all = all situations, es = even strength, pp = power play, pk = penalty kill

Uses only the Python standard library, no installs needed.

Usage:
    python nhl_zone_time.py                      # current season, all strengths
    python nhl_zone_time.py --strength es        # even strength only in the table
    python nhl_zone_time.py --season 20242025    # a past season
    python nhl_zone_time.py --playoffs           # playoff data
    python nhl_zone_time.py --sort dz            # sort by defensive zone time
    python nhl_zone_time.py --csv zone_time.csv  # also save everything to CSV
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request

WEB_API = "https://api-web.nhle.com/v1"
STATS_API = "https://api.nhle.com/stats/rest/en"
HEADERS = {"User-Agent": "nhl-zone-time-script/1.0"}
STRENGTHS = ("all", "es", "pp", "pk")


def get_json(url, retries=3):
    """GET a URL and parse JSON, retrying on transient errors."""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries:
                raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc
            time.sleep(1.5 * attempt)


def get_current_teams():
    """Return {abbrev: {"id": int, "name": str}} for the teams in the current standings."""
    standings = get_json(f"{WEB_API}/standings/now")["standings"]
    active = {t["teamAbbrev"]["default"]: t["teamName"]["default"] for t in standings}

    # The stats API maps abbreviations to the numeric team IDs that EDGE needs.
    all_teams = get_json(f"{STATS_API}/team")["data"]
    teams = {}
    for t in all_teams:
        abbrev = t.get("triCode")
        if abbrev in active:
            teams[abbrev] = {"id": t["id"], "name": active[abbrev]}
    return teams


def get_zone_time(team_id, season=None, game_type=2):
    """Fetch EDGE zone time details for one team."""
    if season:
        url = f"{WEB_API}/edge/team-zone-time-details/{team_id}/{season}/{game_type}"
    else:
        url = f"{WEB_API}/edge/team-zone-time-details/{team_id}/now"
    return get_json(url)


def collect(season=None, game_type=2, quiet=False):
    """Collect zone time rows for every team and strength."""
    teams = get_current_teams()
    rows = []
    for i, (abbrev, info) in enumerate(sorted(teams.items()), 1):
        if not quiet:
            print(f"[{i:2}/{len(teams)}] {abbrev} ...", file=sys.stderr)
        try:
            data = get_zone_time(info["id"], season, game_type)
        except RuntimeError as exc:
            print(f"   skipped: {exc}", file=sys.stderr)
            continue

        shots = data.get("shotDifferential") or {}
        for z in data.get("zoneTimeDetails", []):
            rows.append({
                "team": abbrev,
                "team_name": info["name"],
                "strength": z["strengthCode"],
                "oz_pct": z["offensiveZonePctg"] * 100,
                "oz_rank": z["offensiveZoneRank"],
                "nz_pct": z["neutralZonePctg"] * 100,
                "nz_rank": z["neutralZoneRank"],
                "dz_pct": z["defensiveZonePctg"] * 100,
                "dz_rank": z["defensiveZoneRank"],
                "oz_league_avg": z["offensiveZoneLeagueAvg"] * 100,
                "nz_league_avg": z["neutralZoneLeagueAvg"] * 100,
                "dz_league_avg": z["defensiveZoneLeagueAvg"] * 100,
                "shot_attempt_diff": shots.get("shotAttemptDifferential"),
                "sog_diff": shots.get("sogDifferential"),
            })
        time.sleep(0.2)  # be polite to the API
    return rows


def print_table(rows, strength, sort_key):
    subset = [r for r in rows if r["strength"] == strength]
    reverse = sort_key != "dz"  # low defensive zone time is good
    subset.sort(key=lambda r: r[f"{sort_key}_pct"], reverse=reverse)

    labels = {"all": "All situations", "es": "Even strength",
              "pp": "Power play", "pk": "Penalty kill"}
    print(f"\nNHL team zone time - {labels[strength]}  (sorted by {sort_key.upper()}%)\n")
    print(f"{'#':>2}  {'Team':<4} {'Name':<22} {'OZ%':>6} {'Rk':>3}  "
          f"{'NZ%':>6} {'Rk':>3}  {'DZ%':>6} {'Rk':>3}  {'OZ-DZ':>6}")
    print("-" * 74)
    for i, r in enumerate(subset, 1):
        print(f"{i:>2}  {r['team']:<4} {r['team_name'][:22]:<22} "
              f"{r['oz_pct']:6.1f} {r['oz_rank']:>3}  "
              f"{r['nz_pct']:6.1f} {r['nz_rank']:>3}  "
              f"{r['dz_pct']:6.1f} {r['dz_rank']:>3}  "
              f"{r['oz_pct'] - r['dz_pct']:+6.1f}")
    if subset:
        r = subset[0]
        print(f"\nLeague avg: OZ {r['oz_league_avg']:.1f}%  "
              f"NZ {r['nz_league_avg']:.1f}%  DZ {r['dz_league_avg']:.1f}%")


def save_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # -sig: Excel reads accents correctly
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} rows to {path}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description="Gather NHL team zone time data (NHL EDGE).")
    p.add_argument("--season", help="Season like 20252026 (default: current)")
    p.add_argument("--playoffs", action="store_true", help="Playoff data instead of regular season")
    p.add_argument("--strength", choices=STRENGTHS, default="all", help="Strength to show in the table")
    p.add_argument("--sort", choices=("oz", "nz", "dz"), default="oz", help="Column to sort by")
    p.add_argument("--csv", metavar="FILE", help="Save all strengths for all teams to a CSV file")
    args = p.parse_args()

    if args.playoffs and not args.season:
        p.error("--playoffs needs --season (e.g. --season 20242025)")

    rows = collect(args.season, 3 if args.playoffs else 2)
    if not rows:
        sys.exit("No zone time data returned.")
    print_table(rows, args.strength, args.sort)
    if args.csv:
        save_csv(rows, args.csv)


if __name__ == "__main__":
    main()
