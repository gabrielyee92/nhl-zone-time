import plotly.graph_objects as go
import streamlit as st

from dashboard import theme
from dashboard.data import SITUATIONS, current_situations
from dashboard.views.common import (add_ranks, fmt_season, gp_note, limitations, season_options,
                                    season_rows, short_name)


def _data(d, season, situation):
    """Team rows for one season and situation, plus a source note."""
    if situation == "all":
        return season_rows(d, season), "NHL EDGE, all situations."
    sit = current_situations()
    if sit is None:
        st.warning("Situation splits could not be downloaded. Showing all situations.")
        return season_rows(d, season), "NHL EDGE, all situations."
    df = sit[sit["strength"] == situation].rename(columns={"team_name": "name"})
    cur = season_rows(d, season)[["name", "gp", "team_id", "is_current"]]
    df = df.merge(cur, on="name", how="left")
    df["team"] = df["name"]
    return df, f"NHL EDGE, {SITUATIONS[situation].lower()} only."


def render(d):
    st.title("League Overview")
    theme.legend_note()

    seasons = season_options(d)
    season = st.sidebar.selectbox("Season", seasons, format_func=fmt_season(d), key="ov_season")
    situation = "all"
    if season == d["current"] and d["status"]["live_ok"]:
        situation = st.sidebar.radio("Game situation", list(SITUATIONS), format_func=SITUATIONS.get,
                                     key="ov_sit")
    else:
        st.sidebar.caption("Situation splits are available for the current season only.")

    df, source = _data(d, season, situation)
    df = add_ranks(df).sort_values("oz_pct", ascending=False)
    avg = {k: df[k].mean() for k in ("oz_pct", "nz_pct", "dz_pct")}
    note = gp_note(d, df) if "is_current" in df else None
    if note:
        st.info(note)

    c = st.columns(4)
    top, bottom = df.iloc[0], df.iloc[-1]
    c[0].metric("Average OZ% (team mean)", f"{avg['oz_pct']:.1f}%")
    c[1].metric("Most time attacking", short_name(top["name"]), f"{top['oz_pct']:.1f}% OZ",
                delta_color="off")
    c[2].metric("Least time attacking", short_name(bottom["name"]), f"{bottom['oz_pct']:.1f}% OZ",
                delta_color="off")
    c[3].metric("Spread, best to worst", f"{top['oz_pct'] - bottom['oz_pct']:.1f} pts",
                help="1 point of OZ% is about 36 seconds per 60 minutes.")

    left, right = st.columns([1.1, 1])
    with left:
        theme.section("Team rankings", "actual", source + " Ranks and margins are derived.")
        table = df.assign(margin=df["oz_pct"] - df["dz_pct"])[
            ["oz_rank", "name", "oz_pct", "nz_pct", "dz_pct", "dz_rank", "margin", "gp"]]
        st.dataframe(
            table, hide_index=True, width="stretch", height=560,
            column_config={
                "oz_rank": st.column_config.NumberColumn("OZ rank", width="small"),
                "name": st.column_config.TextColumn("Team"),
                "oz_pct": st.column_config.ProgressColumn(
                    "OZ %", format="%.1f%%", min_value=float(df["oz_pct"].min() - 1),
                    max_value=float(df["oz_pct"].max() + 0.5)),
                "nz_pct": st.column_config.NumberColumn("NZ %", format="%.1f%%"),
                "dz_pct": st.column_config.NumberColumn("DZ %", format="%.1f%%"),
                "dz_rank": st.column_config.NumberColumn("DZ rank", help="1 = least time in own end"),
                "margin": st.column_config.NumberColumn("OZ - DZ", format="%+.1f"),
                "gp": st.column_config.NumberColumn("GP", help="Games played (current season only)"),
            })
    with right:
        theme.section("Attack vs defence", "actual",
                      "Top-left = spends more time attacking and less defending. Lines = team average.")
        # Label only the 5 best and 5 worst margins; hover shows every team.
        margin = (df["oz_pct"] - df["dz_pct"]).rank()
        show = (margin <= 5) | (margin > len(df) - 5)
        fig = go.Figure(go.Scatter(
            x=df["dz_pct"], y=df["oz_pct"], mode="markers+text",
            text=[short_name(n) if s else "" for n, s in zip(df["name"], show)],
            textposition="top center",
            textfont=dict(size=10, color=theme.MUTED),
            marker=dict(size=10, color=df["oz_pct"] - df["dz_pct"], colorscale="RdYlGn",
                        line=dict(width=0)),
            customdata=df[["name"]], hovertemplate="%{customdata[0]}<br>OZ %{y:.1f}%<br>DZ %{x:.1f}%"
                                                    "<extra></extra>"))
        fig.add_hline(y=avg["oz_pct"], line_dash="dot", line_color=theme.MUTED)
        fig.add_vline(x=avg["dz_pct"], line_dash="dot", line_color=theme.MUTED)
        fig.update_xaxes(title="Defensive zone % (lower is better)", autorange="reversed")
        fig.update_yaxes(title="Offensive zone % (higher is better)")
        theme.chart(fig, 560)

    theme.section("Where the puck spends the game", "actual", source)
    fig = go.Figure()
    for col, label in (("oz_pct", "Offensive zone"), ("nz_pct", "Neutral zone"), ("dz_pct", "Defensive zone")):
        fig.add_bar(y=df["name"], x=df[col], name=label, orientation="h",
                    marker_color=theme.ZONE[label], text=df[col].map("{:.1f}".format),
                    textposition="inside", insidetextanchor="middle",
                    hovertemplate="%{y}<br>" + label + " %{x:.1f}%<extra></extra>")
    fig.update_layout(barmode="stack", yaxis=dict(autorange="reversed"), bargap=0.25)
    fig.update_xaxes(title="Share of game time (%)", range=[0, 100])
    theme.chart(fig, 820)

    theme.section("Offensive zone % compared with the team average", "derived",
                  "Bars show percentage points above or below the average of all teams in this view.")
    diff = df["oz_pct"] - avg["oz_pct"]
    fig = go.Figure(go.Bar(
        y=df["name"], x=diff, orientation="h",
        marker_color=[theme.GOOD if v >= 0 else theme.BAD for v in diff],
        text=diff.map("{:+.1f}".format), textposition="outside",
        hovertemplate="%{y}: %{x:+.2f} pts<extra></extra>"))
    fig.update_layout(yaxis=dict(autorange="reversed"))
    fig.update_xaxes(title="Points vs average")
    theme.chart(fig, 820)
    limitations(d)
