"""
Data layer: the ONLY place the dashboard talks to the model or the NHL APIs.

- Model logic lives in nhl_zone_model.py / nhl_zone_time.py and is imported, not copied.
- Completed seasons come from zone_model_cache.json (read-only here; never written).
- Current-season data is downloaded at most once every LIVE_TTL seconds.
- Per-team situation splits are downloaded only when a page asks for them.
"""

import datetime
import os
import sys

import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import nhl_zone_model as zm  # noqa: E402
import nhl_zone_time as zt   # noqa: E402

LIVE_TTL = 6 * 3600  # seconds; EDGE only updates after games finish

TARGET_LABEL = {"oz_pct": "Offensive zone %", "dz_pct": "Defensive zone %", "nz_pct": "Neutral zone %"}
SITUATIONS = {"all": "All situations", "es": "Even strength", "pp": "Power play", "pk": "Penalty kill"}

# name, unit ("share" = stored as 0-1 fraction), plain-English description
FEATURE_INFO = {
    "corsi_pct": ("Shot attempt share (Corsi %)", "share",
                  "Share of all shot attempts in the team's games that the team took."),
    "zone_start_pct": ("5v5 offensive-zone faceoff share", "share",
                       "Share of 5-on-5 non-neutral faceoffs taken in the offensive zone."),
    "faceoff_pct": ("Faceoff win %", "share", "Share of faceoffs won."),
    "shots_for_pg": ("Shots for per game", "count", "Shots on goal taken per game."),
    "shots_against_pg": ("Shots against per game", "count", "Shots on goal allowed per game."),
    "pp_pct": ("Power play %", "share", "Power play goals per power play opportunity."),
    "pk_pct": ("Penalty kill %", "share", "Share of opponent power plays killed."),
    "hits_p60": ("Hits per 60", "count", "Hits per 60 minutes."),
    "takeaways_p60": ("Takeaways per 60", "count", "Takeaways per 60 minutes."),
    "giveaways_p60": ("Giveaways per 60", "count", "Giveaways per 60 minutes."),
    "blocks_p60": ("Blocked shots per 60", "count", "Opponent shots blocked per 60 minutes."),
}
FEATURES = list(zm.FEATURES)

# NHL team ids that belong to the same franchise, mapped to the current id.
# Utah Hockey Club (59, 2024-25) was renamed Utah Mammoth (68, 2025-26 on).
# Arizona Coyotes (53) is NOT linked: that franchise was deactivated, not renamed.
FRANCHISE_ALIASES = {59: 68}


def season_label(season, current=None):
    s = int(season)
    label = f"{s // 10000}-{str(s % 10000)[2:]}"
    return f"{label} (in progress)" if current and s == current else label


def _season_from_date(d):
    y = d.year if d.month >= 8 else d.year - 1
    return y * 10000 + y + 1


def _model_params(m):
    return {"alpha": m.alpha, "intercept": m.intercept, "coef": dict(m.coef),
            "mean": dict(m.mean), "std": dict(m.std)}


@st.cache_data(ttl=LIVE_TTL, show_spinner="Loading NHL data and fitting the model...")
def load():
    """Everything the pages need, as DataFrames. Cached for LIVE_TTL."""
    status = {"fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%b %d, %Y %H:%M UTC"),
              "warnings": [], "live_ok": True, "forecast_ok": True,
              "cache_found": os.path.exists(zm.CACHE_FILE)}
    cache = zm.load_cache()  # in-memory copy; this app never saves it
    if not cache:
        status["warnings"].append("No cached history found, so every season was downloaded "
                                  "(about 1-2 minutes).")

    try:
        current = zm.current_season()
    except RuntimeError as exc:
        current = _season_from_date(datetime.date.today())
        status["warnings"].append(f"Could not reach the NHL standings API ({exc}). "
                                  f"Assuming current season {season_label(current)}.")
    seasons = zm.season_ids(current)

    try:
        rows = zm.build_dataset(seasons, current, cache)
    except RuntimeError as exc:
        status["live_ok"] = status["forecast_ok"] = False
        status["warnings"].append(f"Current-season data could not be downloaded ({exc}). "
                                  "Showing completed seasons only.")
        rows = zm.build_dataset(seasons[:-1], current, cache)

    try:
        res = zm.fit_all(rows, seasons, current, cache, forecast=status["live_ok"])
    except RuntimeError as exc:
        status["forecast_ok"] = False
        status["warnings"].append(f"Forecast unavailable: stats-to-date download failed ({exc}).")
        res = zm.fit_all(rows, seasons, current, cache, forecast=False)
    if res["forecast"] is None:
        status["forecast_ok"] = False

    history = pd.DataFrame(rows)
    history["nz_pct"] = 100 - history["oz_pct"] - history["dz_pct"]
    history["is_current"] = history["season"] == current
    if "gp" not in history:
        history["gp"] = pd.NA
    # Same franchise under different NHL team ids (display only; the model is unchanged).
    history["franchise_id"] = history["team_id"].replace(FRANCHISE_ALIASES)
    latest = history.sort_values("season").groupby("franchise_id")["name"].last()
    history["team"] = history["franchise_id"].map(latest)

    cv = pd.DataFrame(res["cv"])
    cv["error"] = cv["predicted"] - cv["actual"]

    out = {
        "status": status, "current": current, "seasons": seasons,
        "history": history, "cv": cv, "preds": pd.DataFrame(res["preds"]),
        "alpha": res["alpha"], "metrics": res["metrics"],
        "params": {t: _model_params(m) for t, m in res["models"].items()},
        "forecast": None,
    }
    fc = res["forecast"]
    if fc:
        out["forecast"] = {
            "table": pd.DataFrame(fc["forecast"]), "backtest": pd.DataFrame(fc["backtest"]),
            "mae": fc["mae"], "rmse": fc["rmse"], "weight": fc["weight_this_season"],
            "n_hist": fc["n_hist"], "avg_gp": fc["avg_gp"], "as_of": fc["today"],
        }
    return out


@st.cache_data(ttl=LIVE_TTL, show_spinner="Downloading current situation splits (32 teams)...")
def current_situations():
    """Current season, all four situations, all teams (via nhl_zone_time.collect)."""
    try:
        df = pd.DataFrame(zt.collect(quiet=True))
    except RuntimeError:
        return None
    return df if not df.empty else None


def _details(team_id, season):
    try:
        data = zt.get_json(f"{zt.WEB_API}/edge/team-zone-time-details/{team_id}/{season}/2")
    except RuntimeError:
        return None
    rows = []
    for z in data.get("zoneTimeDetails", []):
        rows.append({
            "situation": z["strengthCode"],
            "oz_pct": z["offensiveZonePctg"] * 100, "nz_pct": z["neutralZonePctg"] * 100,
            "dz_pct": z["defensiveZonePctg"] * 100,
            "oz_rank": z["offensiveZoneRank"], "nz_rank": z["neutralZoneRank"],
            "dz_rank": z["defensiveZoneRank"],
            "oz_league": z["offensiveZoneLeagueAvg"] * 100, "nz_league": z["neutralZoneLeagueAvg"] * 100,
            "dz_league": z["defensiveZoneLeagueAvg"] * 100,
        })
    return pd.DataFrame(rows) if rows else None


@st.cache_data(ttl=None, show_spinner=False)
def _details_past(team_id, season):
    return _details(team_id, season)  # completed seasons never change


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def _details_live(team_id, season):
    return _details(team_id, season)


def team_details(team_id, season, current):
    """One team's EDGE zone time by situation for one season (None if unavailable)."""
    fn = _details_live if season == current else _details_past
    return fn(int(team_id), int(season))


def refresh_live():
    load.clear()
    current_situations.clear()
    _details_live.clear()
