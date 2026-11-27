"""Helpers shared by several pages."""

import pandas as pd
import streamlit as st

from dashboard.data import season_label


def short_name(name):
    """'Toronto Maple Leafs' -> 'Maple Leafs', 'Carolina Hurricanes' -> 'Hurricanes'."""
    two_word = ("Maple Leafs", "Golden Knights", "Blue Jackets", "Red Wings")
    for t in two_word:
        if name.endswith(t):
            return t
    return name.split()[-1]


def season_options(d, include_current=True):
    seasons = sorted(d["history"]["season"].unique(), reverse=True)
    if not include_current:
        seasons = [s for s in seasons if s != d["current"]]
    return [int(s) for s in seasons]


def fmt_season(d):
    return lambda s: season_label(s, d["current"])


def season_rows(d, season):
    h = d["history"]
    return h[h["season"] == season].copy()


def add_ranks(df):
    df["oz_rank"] = df["oz_pct"].rank(ascending=False, method="min").astype(int)
    df["dz_rank"] = df["dz_pct"].rank(ascending=True, method="min").astype(int)
    return df


def gp_note(d, df):
    if df["is_current"].any() and df["gp"].notna().any():
        gp = pd.to_numeric(df["gp"], errors="coerce").dropna()
        games = (f"{int(gp.min())} games played" if gp.min() == gp.max()
                 else f"teams have played {int(gp.min())}-{int(gp.max())} games")
        return f"Season in progress: {games}. Early-season numbers move a lot."
    return None


def limitations(d):
    st.divider()
    with st.expander("Data sources and limitations"):
        st.markdown(f"""
- **Sources.** Zone time: NHL EDGE puck tracking (`api-web.nhle.com`). Team stats used by the
  model: NHL stats API (`api.nhle.com`). These are public but undocumented endpoints and may change.
- **Coverage.** EDGE zone time exists from **2021-22** on. That gives {d['history']['season'].nunique() - 1}
  completed seasons ({len(d['history']) - (d['history']['is_current']).sum()} team-seasons) for training.
- **Current season is partial.** Numbers are season-to-date and are less stable early on.
- **Neutral zone %** is calculated as 100 - OZ% - DZ% (matches EDGE, which sums to 100%).
- **Situation splits** (even strength, power play, penalty kill) are downloaded on demand; history
  for completed seasons is only stored for all situations.
- **Franchise changes.** Arizona Coyotes data ends in 2023-24. Utah Hockey Club (2024-25) and
  Utah Mammoth (2025-26 on) have different NHL team ids; the dashboard shows them as one team, but
  the model treats them separately, so its 2025-26 backtest "prior" for Utah used the league average.
- **Model, not fact.** Expected values, forecasts and errors are model output. The forecast is
  backtested by rebuilding past seasons as of the same calendar date (not the same number of games),
  does not use actual zone time to date, and its 80% range is ±1.28 × backtest RMSE and has
  not been checked for calibration.
- **Correlation is not causation.** Coefficients describe association within this data. Several
  predictors overlap (e.g. shot share and shots against), which makes individual coefficients unstable.
""")
