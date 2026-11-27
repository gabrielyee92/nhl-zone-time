import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import theme
from dashboard.data import FEATURE_INFO, FEATURES, SITUATIONS, season_label, team_details
from dashboard.views.common import add_ranks, gp_note, limitations, season_rows


def render(d):
    st.title("Team Explorer")
    theme.legend_note()
    h, cur = d["history"], d["current"]

    latest_season = int(h["season"].max())
    latest = season_rows(d, latest_season).sort_values("name")
    name = st.sidebar.selectbox("Team", latest["name"].tolist(), key="te_team")
    team_id = int(latest.loc[latest["name"] == name, "team_id"].iloc[0])

    ranked = add_ranks(season_rows(d, latest_season))
    row = ranked[ranked["team_id"] == team_id].iloc[0]
    n = len(ranked)
    st.subheader(f"{name} - {season_label(latest_season, cur)}")
    note = gp_note(d, ranked[ranked["team_id"] == team_id])
    if note:
        st.info(note)

    theme.section("Season so far", "actual", "NHL EDGE, all situations. Ranks are out of "
                  f"{n} teams (derived).")
    c = st.columns(4)
    c[0].metric("Offensive zone %", f"{row['oz_pct']:.1f}%", f"rank {row['oz_rank']} of {n}",
                delta_color="off")
    c[1].metric("Neutral zone %", f"{row['nz_pct']:.1f}%")
    c[2].metric("Defensive zone %", f"{row['dz_pct']:.1f}%", f"rank {row['dz_rank']} of {n}",
                delta_color="off", help="Rank 1 = least time in own end")
    gp = row.get("gp")
    c[3].metric("Games played", "-" if pd.isna(gp) else int(gp))

    preds = d["preds"]
    p = preds[preds["team"] == name]
    fc = d["forecast"]["table"] if d["forecast"] else None
    f = fc[fc["team"] == name] if fc is not None else None
    if not p.empty:
        theme.section("Model view", "model",
                      "Expected = what the team's other stats predict. Forecast = predicted final "
                      "regular-season value.")
        p = p.iloc[0]
        c = st.columns(4)
        c[0].metric("Expected OZ %", f"{p['expected_oz']:.1f}%",
                    f"{p['oz_diff']:+.1f} pts actual vs expected", delta_color="normal")
        c[1].metric("Expected DZ %", f"{p['expected_dz']:.1f}%",
                    f"{p['dz_diff']:+.1f} pts actual vs expected", delta_color="inverse")
        if f is not None and not f.empty:
            f = f.iloc[0]
            c[2].metric("Forecast final OZ %", f"{f['forecast_oz']:.1f}%",
                        f"80% range {f['oz_low']:.1f}-{f['oz_high']:.1f}", delta_color="off")
            c[3].metric("Forecast final DZ %", f"{f['forecast_dz']:.1f}%")
        else:
            c[2].caption("Forecast not available.")

    # ---- situations (current season, on demand from EDGE)
    theme.section("By game situation", "actual",
                  "NHL EDGE for this team and season. Dots = league average.")
    det = team_details(team_id, latest_season, cur)
    if det is None:
        st.warning("Situation data could not be downloaded for this team.")
    else:
        det = det.set_index("situation").reindex(list(SITUATIONS)).dropna(how="all").reset_index()
        labels = [SITUATIONS[s] for s in det["situation"]]
        fig = go.Figure()
        for col, lg, label in (("oz_pct", "oz_league", "Offensive zone"),
                               ("nz_pct", "nz_league", "Neutral zone"),
                               ("dz_pct", "dz_league", "Defensive zone")):
            rank = col.replace("pct", "rank")
            fig.add_bar(x=labels, y=det[col], name=label, marker_color=theme.ZONE[label],
                        text=det[col].map("{:.1f}%".format), textposition="outside",
                        customdata=det[[rank, lg]],
                        hovertemplate=label + " %{y:.1f}%<br>Rank %{customdata[0]}"
                                              "<br>League avg %{customdata[1]:.1f}%<extra></extra>")
            fig.add_scatter(x=labels, y=det[lg], mode="markers", showlegend=False,
                            marker=dict(symbol="circle-open", size=12, color=theme.TEXT,
                                        line=dict(width=2)),
                            hovertemplate="League avg %{y:.1f}%<extra></extra>")
        fig.update_layout(barmode="group", scattermode="group")
        fig.update_yaxes(title="Share of time (%)", range=[0, max(70, det[["oz_pct", "dz_pct"]].max().max() + 8)])
        theme.chart(fig, 420)

    # ---- history
    franchise = int(latest.loc[latest["team_id"] == team_id, "franchise_id"].iloc[0])
    hist = h[h["franchise_id"] == franchise].sort_values("season")
    league = h.groupby("season")[["oz_pct", "dz_pct"]].mean()
    cv = d["cv"]
    cv_oz = cv[cv["team_id"].isin(hist["team_id"]) & (cv["target"] == "oz_pct")].set_index("season")["predicted"]
    theme.section("Season by season", "actual",
                  "Solid = NHL EDGE actual. Dotted grey = league team average (derived). "
                  "Dashed orange = model's cross-validated expected OZ% (MODEL: trained without that season).")
    if len(hist) < 2:
        st.caption("Only one season of EDGE data for this franchise id.")
    xs = [season_label(s, cur) for s in hist["season"]]
    fig = go.Figure()
    fig.add_scatter(x=xs, y=hist["oz_pct"], name="Offensive zone % (actual)", mode="lines+markers",
                    line=dict(color=theme.GOOD, width=3))
    fig.add_scatter(x=xs, y=hist["dz_pct"], name="Defensive zone % (actual)", mode="lines+markers",
                    line=dict(color=theme.BAD, width=3))
    fig.add_scatter(x=xs, y=league.loc[hist["season"], "oz_pct"].values, name="League avg OZ/DZ",
                    mode="lines", line=dict(color=theme.MUTED, dash="dot"))
    ex = [cv_oz.get(s) for s in hist["season"]]
    fig.add_scatter(x=xs, y=ex, name="Expected OZ % (model)", mode="lines+markers",
                    line=dict(color=theme.MODEL, dash="dash"),
                    marker=dict(symbol="diamond-open", size=10), connectgaps=False)
    fig.update_yaxes(title="Share of time (%)")
    theme.chart(fig, 400)

    show = hist.assign(Season=xs)[["Season", "oz_pct", "nz_pct", "dz_pct"] + FEATURES]
    show = show.rename(columns={"oz_pct": "OZ %", "nz_pct": "NZ %", "dz_pct": "DZ %",
                                **{f: FEATURE_INFO[f][0] for f in FEATURES}})
    for f in FEATURES:
        if FEATURE_INFO[f][1] == "share":
            show[FEATURE_INFO[f][0]] = show[FEATURE_INFO[f][0]] * 100
    st.dataframe(show.round(1), hide_index=True, width="stretch")
    if hist["name"].nunique() > 1:
        st.caption("Team name changed over these seasons: " + ", ".join(hist["name"].unique()))

    with st.expander("Load situation splits for every season (one download per season)"):
        if st.button("Load", key=f"te_hist_{team_id}"):
            frames = []
            for s, tid in zip(hist["season"], hist["team_id"]):
                det_s = team_details(int(tid), int(s), cur)
                if det_s is not None:
                    frames.append(det_s.assign(season=season_label(s, cur)))
            if not frames:
                st.warning("No situation data could be downloaded.")
            else:
                allx = pd.concat(frames)
                fig = go.Figure()
                for sit in ("es", "pp", "pk"):
                    sub = allx[allx["situation"] == sit]
                    fig.add_scatter(x=sub["season"], y=sub["oz_pct"], name=f"{SITUATIONS[sit]} OZ %",
                                    mode="lines+markers")
                fig.update_yaxes(title="Offensive zone % (actual)")
                theme.chart(fig, 380)

    # ---- profile
    theme.section(f"Stat profile vs league, {season_label(latest_season, cur)}", "derived",
                  "Percentile among all teams this season (100 = highest value). Higher is not always "
                  "better, e.g. shots against or giveaways.")
    season_df = season_rows(d, latest_season)
    pct = {FEATURE_INFO[f][0]: season_df[f].rank(pct=True)[season_df["team_id"] == team_id].iloc[0] * 100
           for f in FEATURES}
    pct = pd.Series(pct).sort_values()
    fig = go.Figure(go.Bar(x=pct.values, y=pct.index, orientation="h", marker_color=theme.ACTUAL,
                           text=[f"{v:.0f}" for v in pct.values], textposition="outside",
                           hovertemplate="%{y}: %{x:.0f}th percentile<extra></extra>"))
    fig.add_vline(x=50, line_dash="dot", line_color=theme.MUTED)
    fig.update_xaxes(range=[0, 110], title="Percentile")
    theme.chart(fig, 420)
    limitations(d)
