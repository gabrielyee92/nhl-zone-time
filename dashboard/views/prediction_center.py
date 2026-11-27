import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import theme
from dashboard.data import TARGET_LABEL, season_label
from dashboard.views.common import limitations, short_name


def render(d):
    st.title("Prediction Center")
    theme.legend_note()
    cur = d["current"]
    target = st.sidebar.radio("Zone", ["oz_pct", "dz_pct"], format_func=TARGET_LABEL.get, key="pc_t")
    is_oz = target == "oz_pct"
    tl = TARGET_LABEL[target]
    m = d["metrics"][target]

    # ---- metrics
    theme.section("Model accuracy (leave-one-season-out)", "model",
                  "The model is trained on all completed seasons but one, then graded on the season it "
                  "never saw, repeated for every season.")
    c = st.columns(5)
    c[0].metric("Typical error (MAE)", f"{m['mae']:.2f} pts")
    c[1].metric("RMSE", f"{m['rmse']:.2f} pts")
    c[2].metric("Out-of-sample R²", f"{m['r2']:.2f}",
                help="Share of team-to-team differences the model explains on unseen seasons.")
    c[3].metric("Baseline MAE", f"{m['baseline_mae']:.2f} pts",
                help="Error from guessing the league average for every team.")
    c[4].metric("Ridge penalty (alpha)", f"{d['alpha'][target]:g}",
                help="Chosen from 0.1-100 by the same cross-validation.")

    # ---- expected vs actual, current season
    preds = d["preds"]
    if preds.empty:
        st.warning("No current-season data, so there are no current predictions.")
    else:
        key = "oz" if is_oz else "dz"
        p = preds.assign(actual=preds[f"actual_{key}"], expected=preds[f"expected_{key}"])
        p["diff"] = p["actual"] - p["expected"]
        good = p["diff"] >= 0 if is_oz else p["diff"] <= 0
        theme.section(f"Expected vs actual {tl}, {season_label(cur, cur)}", "model",
                      "x = model expectation from the team's stats; y = NHL EDGE actual. Points above "
                      "the diagonal have more of this zone than their stats suggest.")
        left, right = st.columns(2)
        with left:
            lo, hi = min(p["actual"].min(), p["expected"].min()) - 0.5, max(p["actual"].max(), p["expected"].max()) + 0.5
            fig = go.Figure()
            fig.add_scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="actual = expected",
                            line=dict(color=theme.MUTED, dash="dot"))
            big = p["diff"].abs().rank(ascending=False) <= 8  # label the 8 biggest gaps
            fig.add_scatter(x=p["expected"], y=p["actual"], mode="markers+text", name="Teams",
                            text=[short_name(t) if b else "" for t, b in zip(p["team"], big)],
                            textposition="top center",
                            textfont=dict(size=10, color=theme.MUTED),
                            marker=dict(size=11, color=[theme.GOOD if g else theme.BAD for g in good]),
                            customdata=p[["team", "diff"]],
                            hovertemplate="%{customdata[0]}<br>Expected %{x:.1f}% (model)<br>"
                                          "Actual %{y:.1f}% (EDGE)<br>Diff %{customdata[1]:+.2f}<extra></extra>")
            fig.update_xaxes(title=f"Expected {tl} (model)", range=[lo, hi])
            fig.update_yaxes(title=f"Actual {tl} (NHL EDGE)", range=[lo, hi])
            theme.chart(fig, 520)
        with right:
            s = p.sort_values("diff", ascending=not is_oz)
            colors = [theme.GOOD if (v >= 0) == is_oz else theme.BAD for v in s["diff"]]
            fig = go.Figure(go.Bar(y=s["team"], x=s["diff"], orientation="h", marker_color=colors,
                                   text=s["diff"].map("{:+.1f}".format), textposition="outside",
                                   hovertemplate="%{y}: %{x:+.2f} pts<extra></extra>"))
            fig.update_layout(yaxis=dict(autorange="reversed"))
            fig.update_xaxes(title="Actual minus expected (pts)")
            theme.chart(fig, 520)
        st.caption(f"A gap smaller than the model's typical error ({m['mae']:.2f} pts) is within normal "
                   "noise. Green = better than expected for the team.")

    # ---- forecast
    fc = d["forecast"]
    theme.section("End-of-season forecast", "model")
    if not fc:
        st.warning("Forecast unavailable (current-season or stats-to-date data could not be loaded).")
    else:
        w = fc["weight"][target]
        st.caption(f"Combines last season's actual {tl} (weight ≈ {1 - w:.0%}) with this season's expected "
                   f"value so far (≈ {w:.0%}). Backtested on {fc['n_hist']} team-seasons rebuilt as of "
                   f"{fc['as_of'][5:]} (≈{fc['avg_gp']:.0f} games in). Bars = 80% range "
                   f"(±1.28 × RMSE; not calibration-checked).")
        t = fc["table"].copy()
        if is_oz:
            t["f"], t["now"], t["lo"], t["hi"] = t["forecast_oz"], t["oz_now"], t["oz_low"], t["oz_high"]
        else:
            half = 1.28 * fc["rmse"]["dz_pct"]
            t["f"], t["now"] = t["forecast_dz"], t["dz_now"]
            t["lo"], t["hi"] = t["f"] - half, t["f"] + half
        t = t.sort_values("f", ascending=not is_oz)
        fig = go.Figure()
        fig.add_scatter(y=t["team"], x=t["f"], mode="markers", name="Forecast final (model)",
                        marker=dict(symbol="diamond", size=11, color=theme.MODEL),
                        error_x=dict(type="data", symmetric=False, array=t["hi"] - t["f"],
                                     arrayminus=t["f"] - t["lo"], color=theme.MODEL, thickness=1.5),
                        hovertemplate="%{y}<br>Forecast %{x:.1f}%<extra></extra>")
        fig.add_scatter(y=t["team"], x=t["now"], mode="markers", name="Season to date (actual)",
                        marker=dict(symbol="circle", size=9, color=theme.ACTUAL),
                        hovertemplate="%{y}<br>Now %{x:.1f}%<extra></extra>")
        fig.update_layout(yaxis=dict(autorange="reversed"))
        fig.update_xaxes(title=f"{tl}")
        theme.chart(fig, 860)

        theme.section("Forecast backtest: average error by method", "model",
                      "Lower is better. Each method predicts the final value from the same point in past seasons.")
        mae = pd.Series(fc["mae"][target]).sort_values()
        fig = go.Figure(go.Bar(x=mae.values, y=mae.index, orientation="h",
                               marker_color=[theme.MODEL if k == "forecast" else theme.NEUTRAL for k in mae.index],
                               text=[f"{v:.2f}" for v in mae.values], textposition="outside"))
        fig.update_layout(yaxis=dict(autorange="reversed"))
        fig.update_xaxes(title="Mean absolute error (pts)")
        theme.chart(fig, 260)

    # ---- error analysis
    theme.section("Prediction errors on past seasons", "model",
                  "Cross-validated: each team-season predicted by a model that never saw that season. "
                  "Error = predicted minus actual.")
    cv = d["cv"][d["cv"]["target"] == target].copy()
    cv["Season"] = cv["season"].map(lambda s: season_label(s))
    left, mid, right = st.columns(3)
    with left:
        fig = go.Figure(go.Histogram(x=cv["error"], nbinsx=25, marker_color=theme.MODEL))
        fig.add_vline(x=0, line_color=theme.MUTED, line_dash="dot")
        fig.update_xaxes(title="Error (pts)")
        fig.update_yaxes(title="Team-seasons")
        theme.chart(fig, 340)
    with mid:
        fig = go.Figure()
        for s, g in cv.groupby("Season"):
            fig.add_box(y=g["error"], name=s, marker_color=theme.MODEL, boxpoints="all", jitter=0.4,
                        pointpos=0, customdata=g[["name"]],
                        hovertemplate="%{customdata[0]}<br>%{y:+.2f} pts<extra></extra>")
        fig.add_hline(y=0, line_color=theme.MUTED, line_dash="dot")
        fig.update_layout(showlegend=False)
        fig.update_yaxes(title="Error (pts)")
        theme.chart(fig, 340)
    with right:
        lo, hi = cv[["actual", "predicted"]].min().min() - 0.5, cv[["actual", "predicted"]].max().max() + 0.5
        fig = go.Figure()
        fig.add_scatter(x=[lo, hi], y=[lo, hi], mode="lines", line=dict(color=theme.MUTED, dash="dot"),
                        showlegend=False)
        fig.add_scatter(x=cv["predicted"], y=cv["actual"], mode="markers", showlegend=False,
                        marker=dict(color=theme.MODEL, size=7, opacity=0.8),
                        customdata=cv[["name", "Season"]],
                        hovertemplate="%{customdata[0]} %{customdata[1]}<br>Predicted %{x:.1f}<br>"
                                      "Actual %{y:.1f}<extra></extra>")
        fig.update_xaxes(title="Predicted (model)")
        fig.update_yaxes(title="Actual (EDGE)")
        theme.chart(fig, 340)

    worst = cv.reindex(cv["error"].abs().sort_values(ascending=False).index).head(10)
    st.markdown("**Largest misses**")
    st.dataframe(worst[["Season", "name", "actual", "predicted", "error"]].rename(columns={
        "name": "Team", "actual": "Actual (EDGE)", "predicted": "Predicted (model)", "error": "Error"}),
        hide_index=True, width="stretch",
        column_config={c: st.column_config.NumberColumn(format="%.2f")
                       for c in ("Actual (EDGE)", "Predicted (model)", "Error")})
    if fc:
        bt = fc["backtest"]
        bt = bt[bt["target"] == target]
        r = np.corrcoef(bt["forecast"], bt["actual"])[0, 1]
        st.caption(f"Forecast backtest: {len(bt)} team-seasons, correlation between forecast and final "
                   f"actual r = {r:.2f}.")
    limitations(d)
