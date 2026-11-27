"""
NHL Zone Time Analytics - Streamlit dashboard.

Run locally:   streamlit run streamlit_app.py
All data access goes through dashboard/data.py; model logic stays in nhl_zone_model.py.
"""

import streamlit as st

st.set_page_config(page_title="NHL Zone Time Analytics", page_icon="🏒", layout="wide",
                   initial_sidebar_state="expanded")

from dashboard import data, theme  # noqa: E402
from dashboard.views import (overview, prediction_center, statistics, team_explorer,  # noqa: E402
                             trends)

theme.register_plotly()
theme.inject_css()

d = data.load()

PAGES = [
    st.Page(lambda: overview.render(d), title="Overview", icon=":material/leaderboard:",
            url_path="overview", default=True),
    st.Page(lambda: team_explorer.render(d), title="Team Explorer", icon=":material/search:",
            url_path="team"),
    st.Page(lambda: prediction_center.render(d), title="Prediction Center",
            icon=":material/insights:", url_path="predictions"),
    st.Page(lambda: statistics.render(d), title="Statistical Analysis",
            icon=":material/functions:", url_path="statistics"),
    st.Page(lambda: trends.render(d), title="Historical Trends", icon=":material/timeline:",
            url_path="trends"),
]
page = st.navigation(PAGES)

with st.sidebar:
    st.markdown("### 🏒 NHL Zone Time")
    st.caption("Where the puck spends the game, and what the model expects.")
    st.divider()

page.run()

with st.sidebar:
    st.divider()
    s = d["status"]
    st.caption(f"Season: **{data.season_label(d['current'], d['current'])}**  \n"
               f"Data loaded: {s['fetched_at']}  \n"
               f"Current-season data refreshes every {data.LIVE_TTL // 3600} h.")
    for w in s["warnings"]:
        st.warning(w)
    if st.button("Refresh data now", width="stretch"):
        data.refresh_live()
        st.rerun()
