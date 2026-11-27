"""Dark theme, colors, Plotly template and small UI helpers."""

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

BG, PANEL, GRID, TEXT, MUTED = "#0E1117", "#161B22", "#2A313C", "#E6EDF3", "#8B949E"
ACTUAL = "#4FC3F7"   # real NHL data
MODEL = "#FFB74D"    # model output (expected / forecast / error)
GOOD, BAD, NEUTRAL = "#66BB6A", "#EF5350", "#90A4AE"
ZONE = {"Offensive zone": GOOD, "Neutral zone": NEUTRAL, "Defensive zone": BAD}
PALETTE = [ACTUAL, "#BA68C8", "#4DB6AC", "#F06292", "#AED581", "#7986CB", "#FFD54F", "#A1887F"]


def register_plotly():
    t = go.layout.Template(pio.templates["plotly_dark"])
    t.layout.paper_bgcolor = "rgba(0,0,0,0)"
    t.layout.plot_bgcolor = "rgba(0,0,0,0)"
    t.layout.font = dict(family="Inter, Segoe UI, Helvetica, Arial, sans-serif", color=TEXT, size=13)
    t.layout.colorway = PALETTE
    t.layout.xaxis = dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    t.layout.yaxis = dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    t.layout.margin = dict(l=10, r=10, t=40, b=10)
    t.layout.hoverlabel = dict(bgcolor=PANEL, bordercolor=GRID, font_color=TEXT)
    t.layout.legend = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                           bgcolor="rgba(0,0,0,0)")
    pio.templates["nhl_dark"] = t
    pio.templates.default = "nhl_dark"


def inject_css():
    st.markdown(f"""
<style>
.badge {{display:inline-block;padding:1px 8px;border-radius:4px;font-size:0.68rem;font-weight:700;
        letter-spacing:.06em;margin-right:8px;vertical-align:middle;}}
.badge-actual {{background:rgba(79,195,247,.12);color:{ACTUAL};border:1px solid {ACTUAL};}}
.badge-model {{background:rgba(255,183,77,.12);color:{MODEL};border:1px solid {MODEL};}}
.badge-derived {{background:rgba(144,164,174,.12);color:{NEUTRAL};border:1px solid {NEUTRAL};}}
.stCaption, [data-testid="stCaptionContainer"] {{color:{MUTED};}}
div[data-testid="stMetric"] {{background:{PANEL};border:1px solid {GRID};border-radius:10px;
        padding:12px 16px;}}
div[data-testid="stMetricLabel"] p {{color:{MUTED};font-size:0.8rem;}}
.block-container {{padding-top:2rem;max-width:1400px;}}
h4 {{margin-top:1.2rem;}}
</style>""", unsafe_allow_html=True)


def badge(kind):
    label = {"actual": "ACTUAL", "model": "MODEL", "derived": "DERIVED"}[kind]
    return f'<span class="badge badge-{kind}">{label}</span>'


def section(title, kind=None, caption=None):
    """Section header with an ACTUAL / MODEL / DERIVED tag."""
    st.markdown(f"#### {badge(kind) if kind else ''}{title}", unsafe_allow_html=True)
    if caption:
        st.caption(caption)


def legend_note():
    st.markdown(
        f"{badge('actual')} NHL data &nbsp; {badge('model')} model output &nbsp; "
        f"{badge('derived')} calculated from NHL data (averages, ranks, z-scores)",
        unsafe_allow_html=True)


def chart(fig, height=None, key=None):
    if height:
        fig.update_layout(height=height)
    st.plotly_chart(fig, width="stretch", key=key, config={"displaylogo": False})
