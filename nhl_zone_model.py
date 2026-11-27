"""
Expected zone time model for NHL teams.

Idea (like "expected goals", but for zone time):
  1. For every past season with NHL EDGE tracking (2021-22 onward), collect each
     team's ACTUAL zone time (target) and its ordinary box-score / shot stats
     (features) from the NHL stats API.
  2. Fit a ridge regression: zone time ~ shot share, faceoffs, zone starts, ...
  3. Check accuracy honestly with leave-one-season-out cross-validation.
  4. Apply the model to the current season to get each team's EXPECTED
     offensive / defensive zone time, and compare it with what they actually had.

A team whose actual OZ% is well above its expected OZ% is spending more time in
the attacking zone than its underlying stats would suggest (and vice versa).

Pure Python standard library, no installs. Reuses helpers from nhl_zone_time.py.

Usage:
    python nhl_zone_model.py                 # train, validate, predict + forecast current season
    python nhl_zone_model.py --no-forecast   # skip the end-of-season forecast
    python nhl_zone_model.py --csv preds.csv # also save predictions
    python nhl_zone_model.py --refresh       # re-download data instead of using the cache
"""

import argparse
import csv
import datetime
import json
import math
import os
import sys
import time

from nhl_zone_time import STATS_API, WEB_API, get_json

FIRST_EDGE_SEASON = 20212022
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zone_model_cache.json")

# Feature name -> (stats endpoint, field). All per-game / percentage stats so
# partial seasons are comparable with full ones.
FEATURES = {
    "corsi_pct":       ("percentages", "satPct"),          # shot attempt share
    "zone_start_pct":  ("percentages", "zoneStartPct5v5"), # 5v5 OZ faceoff share
    "faceoff_pct":     ("summary", "faceoffWinPct"),
    "shots_for_pg":    ("summary", "shotsForPerGame"),
    "shots_against_pg": ("summary", "shotsAgainstPerGame"),
    "pp_pct":          ("summary", "powerPlayPct"),
    "pk_pct":          ("summary", "penaltyKillPct"),
    "hits_p60":        ("realtime", "hitsPer60"),
    "takeaways_p60":   ("realtime", "takeawaysPer60"),
    "giveaways_p60":   ("realtime", "giveawaysPer60"),
    "blocks_p60":      ("realtime", "blockedShotsPer60"),
}
TARGETS = ("oz_pct", "dz_pct")  # NZ% is whatever is left: 100 - OZ - DZ


# --------------------------------------------------------------------------- data

def current_season():
    return get_json(f"{WEB_API}/standings/now")["standings"][0]["seasonId"]


def season_ids(last):
    """All seasons from the first EDGE season up to and including `last`."""
    out, s = [], FIRST_EDGE_SEASON
    while s <= last:
        out.append(s)
        start = s // 10000 + 1
        s = start * 10000 + start + 1
    return out


def fetch_team_stats(season, until=None):
    """{teamId: {"name":..., "gp":..., feature: value, ...}} from the NHL stats API.

    until: optional "YYYY-MM-DD" to only count games up to that date.
    """
    teams = {}
    date_filter = f"%20and%20gameDate%3C=%22{until}%22" if until else ""
    for endpoint in {ep for ep, _ in FEATURES.values()}:
        url = (f"{STATS_API}/team/{endpoint}?limit=50"
               f"&cayenneExp=seasonId={season}%20and%20gameTypeId=2{date_filter}")
        for row in get_json(url)["data"]:
            t = teams.setdefault(row["teamId"], {"name": row["teamFullName"]})
            if endpoint == "summary":
                t["gp"] = row["gamesPlayed"]
            for feat, (ep, field) in FEATURES.items():
                if ep == endpoint:
                    t[feat] = row[field]
    return teams


def fetch_zone_time(team_id, season):
    """Actual all-situations zone time (in %) from NHL EDGE, or None."""
    try:
        data = get_json(f"{WEB_API}/edge/team-zone-time-details/{team_id}/{season}/2")
    except RuntimeError:
        return None
    for z in data.get("zoneTimeDetails", []):
        if z["strengthCode"] == "all":
            return {"oz_pct": z["offensiveZonePctg"] * 100,
                    "dz_pct": z["defensiveZonePctg"] * 100}
    return None


def load_cache(refresh=False):
    if not refresh and os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def build_dataset(seasons, current, cache):
    """List of rows (one per team-season). Past seasons are cached on disk."""
    rows = []
    for season in seasons:
        key = str(season)
        if key in cache and season != current:  # current season changes daily
            rows.extend(cache[key])
            continue
        print(f"Downloading {season} ...", file=sys.stderr)
        season_rows = []
        for team_id, stats in fetch_team_stats(season).items():
            if any(stats.get(f) is None for f in FEATURES):
                continue
            zt = fetch_zone_time(team_id, season)
            if zt is None:
                continue
            season_rows.append({"season": season, "team_id": team_id, **stats, **zt})
            time.sleep(0.15)
        cache[key] = season_rows
        rows.extend(season_rows)
    return rows


def same_date_in(season, today):
    """Today's month/day mapped into the given season (e.g. Nov 26 -> 2024-11-26)."""
    start_year, end_year = season // 10000, season % 10000
    year = start_year if today[5:7] >= "08" else end_year
    return f"{year}{today[4:]}"


def stats_to_date(season, until, cache):
    """Team stats for a past season as they stood on `until` (cached)."""
    key = f"todate|{season}|{until}"
    live = until >= datetime.date.today().isoformat()  # today's games may still be added
    if live:
        cache.pop(key, None)
        return fetch_team_stats(season, until)
    if key not in cache:
        print(f"Downloading {season} stats up to {until} ...", file=sys.stderr)
        stats = fetch_team_stats(season, until)
        cache[key] = {str(k): v for k, v in stats.items()}
    return {int(k): v for k, v in cache[key].items()}


# --------------------------------------------------------------------------- model

def solve(a, b):
    """Solve a x = b with Gaussian elimination (a is small and well conditioned)."""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                factor = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= factor * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


class RidgeModel:
    """Linear regression on standardized features with an L2 penalty."""

    def __init__(self, alpha=1.0):
        self.alpha = alpha

    def fit(self, rows, target, feats=None):
        feats = list(feats or FEATURES)
        self.feats = feats
        n = len(rows)
        self.mean = {f: sum(r[f] for r in rows) / n for f in feats}
        self.std = {f: math.sqrt(sum((r[f] - self.mean[f]) ** 2 for r in rows) / n) or 1.0
                    for f in feats}
        x = [[(r[f] - self.mean[f]) / self.std[f] for f in feats] for r in rows]
        self.intercept = sum(r[target] for r in rows) / n
        y = [r[target] - self.intercept for r in rows]

        k = len(feats)
        xtx = [[sum(x[i][p] * x[i][q] for i in range(n)) + (self.alpha if p == q else 0)
                for q in range(k)] for p in range(k)]
        xty = [sum(x[i][p] * y[i] for i in range(n)) for p in range(k)]
        self.coef = dict(zip(feats, solve(xtx, xty)))
        return self

    def predict(self, row):
        return self.intercept + sum(
            self.coef[f] * (row[f] - self.mean[f]) / self.std[f] for f in self.feats)


def loso_cv(rows, target, alpha):
    """Leave-one-season-out: train on all other seasons, test on the held-out one."""
    errors = []
    for season in sorted({r["season"] for r in rows}):
        train = [r for r in rows if r["season"] != season]
        test = [r for r in rows if r["season"] == season]
        model = RidgeModel(alpha).fit(train, target)
        errors += [model.predict(r) - r[target] for r in test]
    mae = sum(abs(e) for e in errors) / len(errors)
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
    return mae, rmse


def r_squared(rows, target, alpha):
    """Out-of-sample R^2 from the leave-one-season-out predictions."""
    _, rmse = loso_cv(rows, target, alpha)
    mean = sum(r[target] for r in rows) / len(rows)
    var = sum((r[target] - mean) ** 2 for r in rows) / len(rows)
    return 1 - rmse ** 2 / var


# --------------------------------------------------------------------------- forecast
#
# Forecast of each team's FINAL (end of regular season) zone time, made from:
#   prior_<t>  - the team's actual zone time last season
#   xnow_<t>   - expected zone time from this season's stats so far (model above)
# Trained by rebuilding every past season "as of today's date" and learning how
# those two numbers map to the final result. Validated leave-one-season-out.

FORECAST_FEATS = {t: (f"prior_{t}", f"xnow_{t}") for t in TARGETS}


def forecast_rows(full_rows, seasons, today, cache, alphas):
    """One row per team-season with prior, to-date expected, and final actual values."""
    by_key = {(r["season"], r["team_id"]): r for r in full_rows}
    league_avg = {t: sum(r[t] for r in full_rows) / len(full_rows) for t in TARGETS}
    rows = []
    for i, season in enumerate(seasons):
        if i == 0:
            continue  # no previous season to use as the prior
        prev = seasons[i - 1]
        # Expected-zone-time models that never saw this season's full data.
        others = [r for r in full_rows if r["season"] != season]
        xmodels = {t: RidgeModel(alphas[t]).fit(others, t) for t in TARGETS}
        for team_id, stats in stats_to_date(season, same_date_in(season, today), cache).items():
            if any(stats.get(f) is None for f in FEATURES):
                continue
            row = {"season": season, "team_id": team_id, "name": stats["name"],
                   "gp": stats.get("gp")}
            final = by_key.get((season, team_id))  # None for the current season
            before = by_key.get((prev, team_id))   # None for relocated / new teams
            for t in TARGETS:
                row[f"prior_{t}"] = before[t] if before else league_avg[t]
                row[f"xnow_{t}"] = xmodels[t].predict(stats)
                row[t] = final[t] if final else None
            rows.append(row)
    return rows


def compute_forecast(full_rows, seasons, current, today, cache, alphas, models, now_rows):
    """End-of-season forecast plus its backtest. Returns a dict; prints nothing."""
    rows = forecast_rows(full_rows, seasons, today, cache, alphas)
    hist = [r for r in rows if r["season"] != current and r["oz_pct"] is not None]
    live = [r for r in rows if r["season"] == current]
    for r in live:  # use the expected model trained on all past full seasons
        stats = next((n for n in now_rows if n["team_id"] == r["team_id"]), None)
        if stats:
            for t in TARGETS:
                r[f"xnow_{t}"] = models[t].predict(stats)

    avg_gp = sum(r["gp"] or 0 for r in hist) / max(len(hist), 1)
    fmodels, rmse, mae_by_target, share_by_target, backtest = {}, {}, {}, {}, []
    for t in TARGETS:
        feats = FORECAST_FEATS[t]
        errs = {"forecast": [], "last season only": [], "stats so far only": [],
                "league average": []}
        for season in sorted({r["season"] for r in hist}):
            train = [r for r in hist if r["season"] != season]
            test = [r for r in hist if r["season"] == season]
            m = RidgeModel(1.0).fit(train, t, feats)
            avg = sum(r[t] for r in train) / len(train)
            for r in test:
                pred = m.predict(r)
                errs["forecast"].append(pred - r[t])
                errs["last season only"].append(r[f"prior_{t}"] - r[t])
                errs["stats so far only"].append(r[f"xnow_{t}"] - r[t])
                errs["league average"].append(avg - r[t])
                backtest.append({"season": season, "team_id": r["team_id"], "name": r["name"],
                                 "target": t, "actual": r[t], "forecast": pred,
                                 "prior": r[f"prior_{t}"], "xnow": r[f"xnow_{t}"]})
        mae_by_target[t] = {k: sum(abs(e) for e in v) / len(v) for k, v in errs.items()}
        rmse[t] = math.sqrt(sum(e * e for e in errs["forecast"]) / len(errs["forecast"]))
        fmodels[t] = RidgeModel(1.0).fit(hist, t, feats)
        w = fmodels[t].coef
        share_by_target[t] = abs(w[feats[1]]) / (abs(w[feats[0]]) + abs(w[feats[1]]))

    actual_now = {n["team_id"]: n for n in now_rows}
    out = []
    for r in live:
        f_oz, f_dz = fmodels["oz_pct"].predict(r), fmodels["dz_pct"].predict(r)
        a = actual_now.get(r["team_id"], {})
        out.append({"team": r["name"], "gp": r["gp"],
                    "oz_now": a.get("oz_pct"), "forecast_oz": f_oz,
                    "oz_low": f_oz - 1.28 * rmse["oz_pct"], "oz_high": f_oz + 1.28 * rmse["oz_pct"],
                    "dz_now": a.get("dz_pct"), "forecast_dz": f_dz,
                    "forecast_nz": 100 - f_oz - f_dz})
    out.sort(key=lambda p: -p["forecast_oz"])
    return {"today": today, "n_hist": len(hist), "avg_gp": avg_gp, "mae": mae_by_target,
            "rmse": rmse, "weight_this_season": share_by_target, "backtest": backtest,
            "forecast": out, "live_rows": live}


def run_forecast(full_rows, seasons, current, today, cache, alphas, models, now_rows):
    fc = compute_forecast(full_rows, seasons, current, today, cache, alphas, models, now_rows)
    print_forecast(fc, current)
    return fc["forecast"]


def print_forecast(fc, current):
    today, rmse, out = fc["today"], fc["rmse"], fc["forecast"]
    print(f"\n=== End-of-season forecast ===")
    print(f"Backtest: {fc['n_hist']} team-seasons, each rebuilt as of {today[5:]} "
          f"(~{fc['avg_gp']:.0f} games in)")
    for t in TARGETS:
        print(f"  {t.upper()} avg error: "
              + ", ".join(f"{k} {v:.2f}" for k, v in fc["mae"][t].items())
              + f"   (weight on this season: {fc['weight_this_season'][t]:.0%})")

    print(f"\nForecast final zone time, {current}  (80% range = +/-{1.28 * rmse['oz_pct']:.1f} OZ pts)\n")
    print(f"{'#':>2}  {'Team':<24} {'GP':>3} {'OZ now':>7} {'fOZ%':>6} {'80% range':>12}   "
          f"{'DZ now':>7} {'fDZ%':>6} {'fNZ%':>6}")
    print("-" * 86)
    for i, p in enumerate(out, 1):
        now_oz = f"{p['oz_now']:7.1f}" if p["oz_now"] is not None else "      -"
        now_dz = f"{p['dz_now']:7.1f}" if p["dz_now"] is not None else "      -"
        print(f"{i:>2}  {p['team'][:24]:<24} {p['gp']:>3} {now_oz} {p['forecast_oz']:6.1f} "
              f"{p['oz_low']:5.1f}-{p['oz_high']:<5.1f}   {now_dz} {p['forecast_dz']:6.1f} "
              f"{p['forecast_nz']:6.1f}")


# --------------------------------------------------------------------------- fit_all
#
# Everything the model computes, returned as plain Python data (no printing), so
# other programs - e.g. the Streamlit dashboard - can reuse it. main() below just
# formats this for the terminal.

ALPHA_GRID = (0.1, 1, 3, 10, 30, 100)


def loso_predictions(rows, target, alpha):
    """Per-row leave-one-season-out predictions (same procedure as loso_cv)."""
    out = []
    for season in sorted({r["season"] for r in rows}):
        train = [r for r in rows if r["season"] != season]
        model = RidgeModel(alpha).fit(train, target)
        for r in rows:
            if r["season"] == season:
                out.append({"season": season, "team_id": r["team_id"], "name": r["name"],
                            "target": target, "actual": r[target], "predicted": model.predict(r)})
    return out


def fit_all(rows, seasons, current, cache, today=None, forecast=True):
    """Train, validate, predict and (optionally) forecast.

    rows: output of build_dataset(). Returns a dict with models, metrics,
    cross-validated predictions, current-season predictions and the forecast.
    """
    train = [r for r in rows if r["season"] != current]
    now = [r for r in rows if r["season"] == current]
    res = {"current": current, "seasons": seasons, "train": train, "now": now,
           "models": {}, "alpha": {}, "metrics": {}, "cv": [], "preds": [], "forecast": None}

    for target in TARGETS:
        # Pick the ridge penalty with the best cross-validated error.
        best = res["alpha"][target] = min(ALPHA_GRID, key=lambda a: loso_cv(train, target, a)[0])
        mae, rmse = loso_cv(train, target, best)
        mean = sum(r[target] for r in train) / len(train)
        base = sum(abs(r[target] - mean) for r in train) / len(train)
        res["metrics"][target] = {"mae": mae, "rmse": rmse, "baseline_mae": base,
                                  "r2": r_squared(train, target, best)}
        res["models"][target] = RidgeModel(best).fit(train, target)
        res["cv"] += loso_predictions(train, target, best)

    models = res["models"]
    for r in now:
        e_oz, e_dz = models["oz_pct"].predict(r), models["dz_pct"].predict(r)
        res["preds"].append({
            "team": r["name"], "season": current,
            "actual_oz": r["oz_pct"], "expected_oz": e_oz, "oz_diff": r["oz_pct"] - e_oz,
            "actual_dz": r["dz_pct"], "expected_dz": e_dz, "dz_diff": r["dz_pct"] - e_dz,
            "expected_nz": 100 - e_oz - e_dz,
        })
    res["preds"].sort(key=lambda p: -p["expected_oz"])

    if forecast and now:
        today = today or datetime.date.today().isoformat()
        res["forecast"] = compute_forecast(train, seasons, current, today, cache,
                                           res["alpha"], models, now)
    return res


# --------------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description="Expected NHL team zone time model.")
    p.add_argument("--csv", metavar="FILE", help="Save current-season predictions to CSV")
    p.add_argument("--refresh", action="store_true", help="Ignore cache and re-download")
    p.add_argument("--no-forecast", action="store_true", help="Skip the end-of-season forecast")
    args = p.parse_args()

    current = current_season()
    seasons = season_ids(current)
    cache = load_cache(args.refresh)
    rows = build_dataset(seasons, current, cache)
    train = [r for r in rows if r["season"] != current]
    now = [r for r in rows if r["season"] == current]
    print(f"\nTraining rows: {len(train)} team-seasons "
          f"({min(r['season'] for r in train)} to {max(r['season'] for r in train)})")

    if not now:
        res = fit_all(rows, seasons, current, cache, forecast=False)
    else:
        res = fit_all(rows, seasons, current, cache, forecast=not args.no_forecast)
    models = res["models"]
    for target in TARGETS:
        m = res["metrics"][target]
        print(f"\n{target.upper()}  (ridge alpha={res['alpha'][target]})")
        print(f"  Cross-validated error: {m['mae']:.2f} pts  "
              f"(guessing league average: {m['baseline_mae']:.2f} pts)   "
              f"R^2 = {m['r2']:.2f}")
        top = sorted(models[target].coef.items(), key=lambda kv: -abs(kv[1]))[:5]
        print("  Biggest drivers (pts per 1 std dev): "
              + ", ".join(f"{f} {c:+.2f}" for f, c in top))

    if not now:
        sys.exit("\nNo current-season data to predict yet.")

    preds = res["preds"]
    print(f"\nExpected vs actual zone time, {current} (sorted by expected OZ%)\n")
    print(f"{'#':>2}  {'Team':<24} {'xOZ%':>6} {'OZ%':>6} {'diff':>6}   "
          f"{'xDZ%':>6} {'DZ%':>6} {'diff':>6}")
    print("-" * 76)
    for i, p in enumerate(preds, 1):
        print(f"{i:>2}  {p['team'][:24]:<24} {p['expected_oz']:6.1f} {p['actual_oz']:6.1f} "
              f"{p['oz_diff']:+6.1f}   {p['expected_dz']:6.1f} {p['actual_dz']:6.1f} "
              f"{p['dz_diff']:+6.1f}")
    print("\ndiff = actual - expected. Positive OZ diff / negative DZ diff = better than stats suggest.")

    forecast = []
    if res["forecast"]:
        print_forecast(res["forecast"], current)
        forecast = res["forecast"]["forecast"]
    save_cache(cache)

    if args.csv:
        fc = {p["team"]: p for p in forecast}
        for p in preds:
            for k, v in fc.get(p["team"], {}).items():
                if k not in ("team", "oz_now", "dz_now"):
                    p[k] = v
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:  # -sig: Excel reads accents correctly
            w = csv.DictWriter(f, fieldnames=list(preds[0].keys()))
            w.writeheader()
            w.writerows(preds)
        print(f"\nSaved predictions to {args.csv}")


if __name__ == "__main__":
    main()
