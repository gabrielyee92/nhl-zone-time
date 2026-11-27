import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import theme
from dashboard.data import TARGET_LABEL, season_label
from dashboard.views.common import fmt_season, limitations, season_options


def render(d):
    st.title("Historical Trends")
    theme.legend_note()
    h, cur = d["history"].copy(), d["current"]
    metric = st.sidebar.radio("Metric", ["oz_pct", "dz_pct", "nz_pct"], format_func=TARGET_LABEL.get,
                              key="ht_metric")
    ml = TARGET_LABEL[metric]
    h["Season"] = h["season"].map(lambda s: season_label(s, cur))
    order = [season_label(s, cur) for s in sorted(h["season"].unique())]
    if (h["is_current"]).any():
        st.caption(f"{season_label(cur, cur)} is partial (season to date).")

    # ---- heatmap
    theme.section(f"{ml} by team and season", "actual",
                  "NHL EDGE, all situations. Teams sorted by their latest value. Blank = no data for that "
                  "franchise id that season.")
    pivot = h.pivot_table(index="team", columns="Season", values=metric)[order]
    pivot = pivot.sort_values(order[-1], ascending=(metric == "dz_pct"), na_position="last")
    scale = "RdYlGn_r" if metric == "dz_pct" else ("RdYlGn" if metric == "oz_pct" else "Blues")
    text = pivot.round(1).astype(object).where(pivot.notna(), "")
    fig = go.Figure(go.Heatmap(z=pivot.values, x=pivot.columns, y=pivot.index, colorscale=scale,
                               text=text.values, texttemplate="%{text}",
                               textfont=dict(size=10), hoverongaps=False,
                               hovertemplate="%{y}<br>%{x}: %{z:.1f}%<extra></extra>"))
    fig.update_layout(yaxis=dict(autorange="reversed"))
    theme.chart(fig, 900)

    # ---- team lines
    theme.section("Compare teams over time", "actual", "Dotted = league team average (derived).")
    teams = pivot.index.tolist()
    picks = st.multiselect("Teams", teams, default=teams[:3], key="ht_teams")
    league = h.groupby("Season")[metric].mean().reindex(order)
    fig = go.Figure()
    fig.add_scatter(x=order, y=league.values, name="League average", mode="lines",
                    line=dict(color=theme.MUTED, dash="dot", width=2))
    for t in picks:
        g = h[h["team"] == t].set_index("Season").reindex(order)
        fig.add_scatter(x=order, y=g[metric], name=t, mode="lines+markers", connectgaps=False,
                        line=dict(width=3))
    fig.update_yaxes(title=f"{ml} (NHL EDGE)")
    theme.chart(fig, 420)

    # ---- change between seasons
    theme.section("Change between two seasons", "derived",
                  "Teams present in both seasons (by franchise id).")
    opts = season_options(d)
    c1, c2 = st.columns(2)
    to = c2.selectbox("To", opts, index=0, format_func=fmt_season(d), key="ht_to")
    frm = c1.selectbox("From", opts, index=min(1, len(opts) - 1), format_func=fmt_season(d), key="ht_from")
    a = h[h["season"] == frm].set_index("franchise_id")
    b = h[h["season"] == to].set_index("franchise_id")
    both = a.index.intersection(b.index)
    if frm == to or len(both) == 0:
        st.info("Pick two different seasons that share teams.")
    else:
        chg = (b.loc[both, metric] - a.loc[both, metric]).rename("chg").to_frame()
        chg["team"] = b.loc[both, "team"]
        chg = chg.sort_values("chg", ascending=(metric == "dz_pct"))
        good = (chg["chg"] >= 0) if metric != "dz_pct" else (chg["chg"] <= 0)
        colors = [theme.GOOD if g else theme.BAD for g in good] if metric != "nz_pct" else theme.ACTUAL
        fig = go.Figure(go.Bar(y=chg["team"], x=chg["chg"], orientation="h", marker_color=colors,
                               text=chg["chg"].map("{:+.1f}".format), textposition="outside",
                               hovertemplate="%{y}: %{x:+.2f} pts<extra></extra>"))
        fig.update_layout(yaxis=dict(autorange="reversed"))
        fig.update_xaxes(title=f"Change in {ml} (pts), {season_label(frm, cur)} to {season_label(to, cur)}")
        theme.chart(fig, 820)
        dropped = len(a) + len(b) - 2 * len(both)
        if dropped:
            st.caption(f"{dropped} team-season(s) left out because the team isn't in both seasons "
                       "(Arizona Coyotes, 2021-24, has no successor in the data).")

    # ---- unusual performances
    theme.section("Unusual team performances", "derived",
                  "Flagged when a team is 2+ standard deviations from that season's average (DERIVED), "
                  "or when the model's cross-validated prediction missed by 2x its typical error (MODEL).")
    z = h.groupby("season")[metric].transform(lambda s: (s - s.mean()) / s.std(ddof=0))
    h["z"] = z
    flags = h[h["z"].abs() >= 2][["Season", "team", metric, "z"]].copy()
    flags["Why flagged"] = flags["z"].map(lambda v: f"{abs(v):.1f} SD {'above' if v > 0 else 'below'} league")
    if metric in ("oz_pct", "dz_pct"):
        cv = d["cv"][d["cv"]["target"] == metric].copy()
        rmse = d["metrics"][metric]["rmse"]
        miss = cv[cv["error"].abs() >= 2 * rmse].copy()
        miss["Season"] = miss["season"].map(lambda s: season_label(s, cur))
        miss = miss.merge(h[["season", "team_id", "team", metric]], on=["season", "team_id"])
        miss["Why flagged"] = miss["error"].map(
            lambda e: f"Model missed by {abs(e):.1f} pts ({'over' if e > 0 else 'under'}-predicted)")
        flags = pd.concat([flags, miss[["Season", "team", metric, "Why flagged"]]], ignore_index=True)
    if flags.empty:
        st.info("No team-seasons meet either threshold.")
    else:
        flags = flags.sort_values(["Season", "team"], ascending=[False, True])
        st.dataframe(flags[["Season", "team", metric, "Why flagged"]].rename(
            columns={"team": "Team", metric: f"{ml} (actual)"}), hide_index=True, width="stretch",
            column_config={f"{ml} (actual)": st.column_config.NumberColumn(format="%.1f%%")})

    fig = go.Figure()
    for s in order:
        g = h[h["Season"] == s]
        fig.add_scatter(x=[s] * len(g), y=g["z"], mode="markers", showlegend=False,
                        marker=dict(size=9, color=[theme.BAD if abs(v) >= 2 else theme.ACTUAL for v in g["z"]],
                                    opacity=0.85),
                        customdata=g[["team", metric]],
                        hovertemplate="%{customdata[0]}<br>" + ml + " %{customdata[1]:.1f}%<br>z = %{y:.2f}"
                                      "<extra></extra>")
    for y in (-2, 2):
        fig.add_hline(y=y, line_dash="dot", line_color=theme.BAD)
    fig.update_yaxes(title="z-score within season")
    theme.chart(fig, 380)
    limitations(d)
