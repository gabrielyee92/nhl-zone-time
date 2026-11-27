import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import theme
from dashboard.data import FEATURE_INFO, FEATURES, TARGET_LABEL, season_label
from dashboard.views.common import fmt_season, limitations, season_options


def _label(col):
    return FEATURE_INFO[col][0] if col in FEATURE_INFO else TARGET_LABEL[col]


def render(d):
    st.title("Statistical Analysis")
    theme.legend_note()
    h, cur = d["history"], d["current"]

    opts = season_options(d)
    default = [s for s in opts if s != cur]
    chosen = st.sidebar.multiselect("Seasons", opts, default=default, format_func=fmt_season(d),
                                    key="sa_seasons")
    if not chosen:
        st.info("Pick at least one season in the sidebar.")
        return
    df = h[h["season"].isin(chosen)].copy()
    if cur in chosen:
        st.caption("Includes the in-progress season (partial data).")
    st.caption(f"{len(df)} team-seasons selected.")

    # ---- correlation heatmap
    theme.section("Correlation between predictors and zone time", "derived",
                  "Pearson correlation across the selected team-seasons. +1 = move together, "
                  "-1 = move opposite, 0 = no linear relationship.")
    cols = ["oz_pct", "dz_pct"] + FEATURES
    corr = df[cols].corr()
    labels = [_label(c) for c in cols]
    fig = go.Figure(go.Heatmap(z=corr.values, x=labels, y=labels, zmin=-1, zmax=1,
                               colorscale="RdBu", text=corr.round(2).values, texttemplate="%{text}",
                               textfont=dict(size=10),
                               hovertemplate="%{y} vs %{x}: %{z:.2f}<extra></extra>"))
    fig.update_layout(yaxis=dict(autorange="reversed"))
    fig.update_xaxes(tickangle=-40)
    theme.chart(fig, 620)

    # ---- feature vs target
    theme.section("Relationship explorer", "derived")
    a, b = st.columns(2)
    feat = a.selectbox("Predictor", FEATURES, format_func=_label, key="sa_feat")
    target = b.selectbox("Zone time", ["oz_pct", "dz_pct", "nz_pct"], format_func=TARGET_LABEL.get,
                         key="sa_target")
    x = df[feat] * (100 if FEATURE_INFO[feat][1] == "share" else 1)
    y = df[target]
    slope, intercept = np.polyfit(x, y, 1)
    r = np.corrcoef(x, y)[0, 1]
    fig = go.Figure()
    for s, g in df.groupby("season"):
        gx = g[feat] * (100 if FEATURE_INFO[feat][1] == "share" else 1)
        fig.add_scatter(x=gx, y=g[target], mode="markers", name=season_label(s, cur),
                        marker=dict(size=8, opacity=0.85), customdata=g[["name"]],
                        hovertemplate="%{customdata[0]}<br>%{x:.2f}, %{y:.1f}%<extra></extra>")
    xs = np.linspace(x.min(), x.max(), 50)
    fig.add_scatter(x=xs, y=slope * xs + intercept, mode="lines", name="Linear fit",
                    line=dict(color=theme.TEXT, dash="dash"))
    unit = " (%)" if FEATURE_INFO[feat][1] == "share" else ""
    fig.update_xaxes(title=_label(feat) + unit)
    fig.update_yaxes(title=TARGET_LABEL[target] + " (NHL EDGE)")
    theme.chart(fig, 460)
    st.caption(f"r = {r:.2f}, n = {len(df)}. Fit: each +1{'pt' if unit else ''} in {_label(feat).lower()} "
               f"goes with {slope:+.2f} pts of {TARGET_LABEL[target].lower()}. "
               f"{FEATURE_INFO[feat][2]}")

    # ---- coefficients
    theme.section("Ridge regression coefficients", "model",
                  "Model trained on all completed seasons (this does not follow the season filter). "
                  "Each bar = change in predicted zone time for a one-standard-deviation increase in "
                  "the predictor, holding the others fixed.")
    t = st.radio("Model", ["oz_pct", "dz_pct"], format_func=TARGET_LABEL.get, horizontal=True,
                 key="sa_coef_t")
    par = d["params"][t]
    coef = pd.Series(par["coef"]).sort_values(key=np.abs)
    fig = go.Figure(go.Bar(x=coef.values, y=[_label(f) for f in coef.index], orientation="h",
                           marker_color=[theme.GOOD if v > 0 else theme.BAD for v in coef.values],
                           text=[f"{v:+.2f}" for v in coef.values], textposition="outside",
                           hovertemplate="%{y}: %{x:+.3f} pts per 1 SD<extra></extra>"))
    fig.add_vline(x=0, line_color=theme.MUTED)
    fig.update_xaxes(title=f"Points of {TARGET_LABEL[t].lower()} per 1 SD increase")
    theme.chart(fig, 440)

    rows = []
    for f in coef.index[::-1]:
        share = FEATURE_INFO[f][1] == "share"
        sd = par["std"][f] * (100 if share else 1)
        effect = par["coef"][f]
        direction = "more" if effect > 0 else "less"
        rows.append({
            "Predictor": _label(f),
            "1 SD equals": f"{sd:.2f}{' pts' if share else ''}",
            "Effect (pts)": round(effect, 2),
            "Plain English": f"A team {sd:.2f}{' pts' if share else ''} higher on this stat is predicted to "
                             f"spend {abs(effect):.2f} pts {direction} time in the "
                             f"{'offensive' if t == 'oz_pct' else 'defensive'} zone.",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"Intercept (league average) = {par['intercept']:.2f}%. Ridge alpha = {par['alpha']:g}. "
               "Predictors overlap heavily (see heatmap), so coefficients show association, not cause; "
               "a predictor with a small coefficient can still be strongly correlated on its own.")

    # ---- team comparisons
    theme.section("Compare teams", "derived",
                  "z-score = how many standard deviations a team is from that season's league average "
                  "(0 = average). Computed within the chosen season.")
    s1, s2 = st.columns([1, 3])
    season = s1.selectbox("Season", opts, format_func=fmt_season(d), key="sa_cmp_season")
    sdf = h[h["season"] == season]
    names = sorted(sdf["name"])
    picks = s2.multiselect("Teams (up to 4)", names, default=names[:2], max_selections=4, key="sa_cmp")
    if picks:
        cols = ["oz_pct", "dz_pct"] + FEATURES
        z = (sdf[cols] - sdf[cols].mean()) / sdf[cols].std(ddof=0)
        z["name"] = sdf["name"]
        fig = go.Figure()
        for n in picks:
            zr = z[z["name"] == n].iloc[0]
            fig.add_bar(x=[_label(c) for c in cols], y=[zr[c] for c in cols], name=n)
        fig.add_hline(y=0, line_color=theme.MUTED)
        fig.update_layout(barmode="group")
        fig.update_xaxes(tickangle=-35)
        fig.update_yaxes(title="z-score")
        theme.chart(fig, 460)
        raw = sdf[sdf["name"].isin(picks)].set_index("name")[cols].T
        raw.index = [_label(c) for c in raw.index]
        st.dataframe(raw.round(3), width="stretch")
    limitations(d)
