"""
Builds nhl_zone_dashboard.xlsx, an easy-to-read Excel workbook with charts,
from zone_time.csv and zone_predictions.csv.

Run it by hand, or let nhl_zone_live.py / the daily Task Scheduler job run it
after every update so the workbook always has the latest data.

    python nhl_zone_excel.py
"""

import csv
import datetime
import os
import sys

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.axis import ChartLines
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.marker import DataPoint
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText
from openpyxl.drawing.line import LineProperties
from openpyxl.drawing.text import CharacterProperties, Paragraph, ParagraphProperties
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
ZONE_CSV = os.path.join(HERE, "zone_time.csv")
PRED_CSV = os.path.join(HERE, "zone_predictions.csv")
OUT = os.path.join(HERE, "nhl_zone_dashboard.xlsx")

FONT = "Arial"
NAVY, GREEN, RED, GREY, BLUE, LIGHT = "1F3864", "2E7D32", "C62828", "9E9E9E", "1565C0", "D9E1F2"
PCT, PTS = "0.0%", '+0.0;-0.0;0.0'
PTS_LABEL = '+0.0" pts";-0.0" pts";0.0" pts"'


# ----------------------------------------------------------------------- helpers

def font(**kw):
    return Font(name=FONT, **kw)


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def header_row(ws, row, labels, col=1):
    for i, text in enumerate(labels):
        c = ws.cell(row=row, column=col + i, value=text)
        c.font = font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def title(ws, text, sub):
    ws["A1"] = text
    ws["A1"].font = font(bold=True, size=18, color=NAVY)
    ws["A2"] = sub
    ws["A2"].font = font(italic=True, size=10, color="595959")


def label_font(color="000000", size=900, bold=False):
    return RichText(p=[Paragraph(pPr=ParagraphProperties(
        defRPr=CharacterProperties(sz=size, b=bold, solidFill=color)),
        endParaRPr=CharacterProperties())])


def tidy_chart(ch, title_text, x_title=None, y_title=None):
    ch.title = title_text
    ch.title.overlay = False
    ch.roundedCorners = False
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    if x_title:
        ch.x_axis.title = x_title
        ch.x_axis.title.overlay = False
    if y_title:
        ch.y_axis.title = y_title
        ch.y_axis.title.overlay = False
    ch.y_axis.majorGridlines = ChartLines(
        spPr=GraphicalProperties(ln=LineProperties(solidFill="D9D9D9")))
    if ch.legend is not None:
        ch.legend.overlay = False
    return ch


def horizontal_bars(ws, title_text, cats, vals, value_title, num_fmt, colors=None,
                    legend=False, labels=True):
    """Ranked horizontal bar chart, first category at the top."""
    ch = BarChart()
    ch.type = "bar"
    ch.add_data(vals, titles_from_data=True)
    ch.set_categories(cats)
    tidy_chart(ch, title_text, y_title=value_title)
    ch.x_axis.scaling.orientation = "maxMin"  # rank 1 at the top
    ch.x_axis.tickLblPos = "low"              # team names on the left, clear of bars
    ch.y_axis.crosses = "max"                 # value axis at the bottom
    ch.y_axis.number_format = num_fmt
    ch.gapWidth = 40
    ch.width, ch.height = 17, 18
    if not legend:
        ch.legend = None
    for s in ch.series:
        s.invertIfNegative = False
    if colors:
        s = ch.series[0]
        for i, color in enumerate(colors):
            pt = DataPoint(idx=i, invertIfNegative=False)
            pt.graphicalProperties.solidFill = color
            pt.graphicalProperties.line.solidFill = color
            s.dPt.append(pt)
    if labels:
        for s in ch.series:
            s.dLbls = DataLabelList()
            s.dLbls.showVal = True
            s.dLbls.numFmt = num_fmt
            for attr in ("showSerName", "showCatName", "showLegendKey", "showPercent"):
                setattr(s.dLbls, attr, False)
    return ch


# ----------------------------------------------------------------------- data

def load():
    zone = read_csv(ZONE_CSV)
    preds = {p["team"]: p for p in read_csv(PRED_CSV)}
    by_team = {}
    for r in zone:
        t = by_team.setdefault(r["team"], {"abbrev": r["team"], "name": r["team_name"]})
        t[r["strength"]] = r
    teams = []
    for t in by_team.values():
        a = t["all"]
        p = preds.get(t["name"])
        if p is None:
            print(f"Warning: no prediction row for {t['name']}", file=sys.stderr)
            continue
        f = lambda d, k: float(d[k])
        teams.append({
            "name": t["name"], "abbrev": t["abbrev"], "gp": int(float(p["gp"])),
            "oz": f(a, "oz_pct") / 100, "oz_rank": int(a["oz_rank"]),
            "nz": f(a, "nz_pct") / 100, "dz": f(a, "dz_pct") / 100, "dz_rank": int(a["dz_rank"]),
            "x_oz": f(p, "expected_oz") / 100,
            "f_oz": f(p, "forecast_oz") / 100, "f_lo": f(p, "oz_low") / 100,
            "f_hi": f(p, "oz_high") / 100, "f_dz": f(p, "forecast_dz") / 100,
            "sat_diff": f(a, "shot_attempt_diff"),
            "league_oz": f(a, "oz_league_avg") / 100,
            "split": {s: (f(t[s], "oz_pct") / 100, f(t[s], "nz_pct") / 100, f(t[s], "dz_pct") / 100,
                          int(t[s]["oz_rank"]), int(t[s]["dz_rank"]))
                      for s in ("es", "pp", "pk") if s in t},
        })
    teams.sort(key=lambda t: -t["oz"])
    return teams


# ----------------------------------------------------------------------- sheets

def teams_sheet(wb, teams, updated):
    ws = wb.create_sheet("Teams")
    title(ws, "All 32 teams: zone time, expected and forecast",
          f"All situations. Sorted by offensive zone time. Updated {updated}. "
          "Use the filter arrows to sort by any column.")
    cols = ["Team", "Games", "Offensive zone %", "OZ rank", "Neutral zone %", "Defensive zone %",
            "DZ rank", "Expected OZ % (from stats)", "vs expected (pts)",
            "Forecast final OZ %", "Forecast low (80%)", "Forecast high (80%)",
            "Forecast final DZ %", "Shot attempt differential (EDGE)"]
    header_row(ws, 4, cols)
    ws.row_dimensions[4].height = 45
    first = 5
    for i, t in enumerate(teams):
        r = first + i
        vals = [t["name"], t["gp"], t["oz"], t["oz_rank"], t["nz"], t["dz"], t["dz_rank"],
                t["x_oz"], f"=(C{r}-H{r})*100", t["f_oz"], t["f_lo"], t["f_hi"], t["f_dz"],
                t["sat_diff"]]
        fmts = [None, "0", PCT, "0", PCT, PCT, "0", PCT, PTS, PCT, PCT, PCT, PCT, '+0.0;-0.0;0.0']
        for c, (v, fmt) in enumerate(zip(vals, fmts), 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = font(bold=(c == 1))
            if fmt:
                cell.number_format = fmt
                cell.alignment = Alignment(horizontal="center")
        if i % 2:
            for c in range(1, len(cols) + 1):
                ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor="F2F2F2")
    last = first + len(teams) - 1

    # Colour scales: green = good, red = bad.
    good_high = ColorScaleRule(start_type="min", start_color="F8696B", mid_type="percentile",
                               mid_value=50, mid_color="FFFFFF", end_type="max", end_color="63BE7B")
    good_low = ColorScaleRule(start_type="min", start_color="63BE7B", mid_type="percentile",
                              mid_value=50, mid_color="FFFFFF", end_type="max", end_color="F8696B")
    diverge = ColorScaleRule(start_type="num", start_value=-2, start_color="F8696B",
                             mid_type="num", mid_value=0, mid_color="FFFFFF",
                             end_type="num", end_value=2, end_color="63BE7B")
    for col in ("C", "H", "J"):
        ws.conditional_formatting.add(f"{col}{first}:{col}{last}", good_high)
    for col in ("F", "M"):
        ws.conditional_formatting.add(f"{col}{first}:{col}{last}", good_low)
    ws.conditional_formatting.add(f"I{first}:I{last}", diverge)
    ws.conditional_formatting.add(f"N{first}:N{last}", diverge)

    widths = [24, 8, 12, 8, 12, 12, 8, 14, 12, 13, 12, 12, 13, 14]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "B5"
    ws.auto_filter.ref = f"A4:{get_column_letter(len(cols))}{last}"

    note = last + 2
    notes = [
        "How to read: Offensive zone % = share of game time the puck is in the opponent's end (higher is better). "
        "Defensive zone % = time in your own end (lower is better). 1 point is about 36 seconds a game.",
        "vs expected = actual minus what the team's shot, faceoff and other stats predict. Positive = more attacking time than the stats explain.",
        "Forecast = predicted final regular-season number; 80% of the time the final should land between the low and high.",
        "Sources: NHL EDGE puck tracking (api-web.nhle.com) and NHL stats (api.nhle.com). Expected and forecast values come from nhl_zone_model.py.",
    ]
    for i, n in enumerate(notes):
        ws.cell(row=note + i, column=1, value=n).font = font(italic=True, size=9, color="595959")
    return ws, first, last


def details_sheet(wb, teams, updated):
    ws = wb.create_sheet("By Situation")
    title(ws, "Zone time by game situation",
          f"Updated {updated}. Sorted by even-strength offensive zone time.")
    groups = [("es", "Even strength (5-on-5)"), ("pp", "Power play"), ("pk", "Penalty kill")]
    ws.cell(row=4, column=1, value="")
    for gi, (_, label) in enumerate(groups):
        c0 = 2 + gi * 4
        ws.merge_cells(start_row=4, start_column=c0, end_row=4, end_column=c0 + 3)
        header_row(ws, 4, [label], col=c0)
    header_row(ws, 4, ["Team"])
    header_row(ws, 5, ["Team"] + ["OZ %", "OZ rank", "DZ %", "DZ rank"] * 3)
    ws.merge_cells("A4:A5")
    rows = sorted(teams, key=lambda t: -t["split"].get("es", (0,))[0])
    for i, t in enumerate(rows):
        r = 6 + i
        ws.cell(row=r, column=1, value=t["name"]).font = font(bold=True)
        for gi, (code, _) in enumerate(groups):
            oz, _, dz, ozr, dzr = t["split"].get(code, (None,) * 5)
            for j, (v, fmt) in enumerate(((oz, PCT), (ozr, "0"), (dz, PCT), (dzr, "0"))):
                cell = ws.cell(row=r, column=2 + gi * 4 + j, value=v)
                cell.number_format = fmt
                cell.font = font()
                cell.alignment = Alignment(horizontal="center")
        if i % 2:
            for c in range(1, 14):
                ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor="F2F2F2")
    last = 5 + len(rows)
    for gi in range(3):
        for off, rule_good_high in ((0, True), (2, False)):
            col = get_column_letter(2 + gi * 4 + off)
            lo, hi = ("F8696B", "63BE7B") if rule_good_high else ("63BE7B", "F8696B")
            ws.conditional_formatting.add(f"{col}6:{col}{last}", ColorScaleRule(
                start_type="min", start_color=lo, mid_type="percentile", mid_value=50,
                mid_color="FFFFFF", end_type="max", end_color=hi))
    ws.column_dimensions["A"].width = 24
    for c in range(2, 14):
        ws.column_dimensions[get_column_letter(c)].width = 9
    ws.freeze_panes = "B6"
    ws.cell(row=last + 2, column=1, value=(
        "Power play OZ% is naturally high and penalty kill DZ% naturally high - compare teams "
        "within the same situation, not across situations.")).font = font(italic=True, size=9, color="595959")


def chart_data_sheet(wb, teams):
    """Sorted copies of the numbers each chart plots."""
    ws = wb.create_sheet("Chart Data")
    title(ws, "Chart data (built automatically - do not edit)",
          "Each block is the sorted data behind one chart on the Dashboard.")
    n = len(teams)
    blocks = {}

    def block(col, name, header, rows, fmts):
        header_row(ws, 4, header, col=col)
        for i, row in enumerate(rows):
            for j, (v, fmt) in enumerate(zip(row, fmts)):
                c = ws.cell(row=5 + i, column=col + j, value=v)
                c.number_format = fmt or "General"
                c.font = font()
        blocks[name] = col
        for j in range(len(header)):
            ws.column_dimensions[get_column_letter(col + j)].width = 14 if j else 22

    league = teams[0]["league_oz"]
    s1 = sorted(teams, key=lambda t: -(t["oz"] - league))
    block(1, "vs_league", ["Team", "OZ % vs league avg (pts)"],
          [(t["name"], (t["oz"] - league) * 100) for t in s1], (None, PTS))
    s2 = sorted(teams, key=lambda t: -(t["oz"] - t["x_oz"]))
    block(4, "vs_expected", ["Team", "Actual minus expected (pts)"],
          [(t["name"], (t["oz"] - t["x_oz"]) * 100) for t in s2], (None, PTS))
    s3 = sorted(teams, key=lambda t: -t["f_oz"])
    block(7, "forecast", ["Team", "OZ % now", "Forecast final OZ %"],
          [(t["name"], t["oz"], t["f_oz"]) for t in s3], (None, PCT, PCT))
    s4 = sorted(teams, key=lambda t: -t["oz"])
    block(11, "split", ["Team", "Offensive zone", "Neutral zone", "Defensive zone"],
          [(t["name"], t["oz"], t["nz"], t["dz"]) for t in s4], (None, PCT, PCT, PCT))
    return ws, blocks, n, (s1, league), s2


def dashboard(wb, teams_ws, first, last, data_ws, blocks, n, s1, s2, updated, league):
    ws = wb.active
    ws.title = "Dashboard"
    ws.sheet_view.showGridLines = False
    title(ws, "NHL Zone Time Dashboard",
          f"Data through {updated}  |  NHL EDGE puck tracking  |  Rebuilt automatically every morning")
    ws.column_dimensions["A"].width = 2
    for c in range(2, 22):
        ws.column_dimensions[get_column_letter(c)].width = 10

    T = f"Teams!$A${first}:$A${last}"
    rng = lambda col: f"Teams!${col}${first}:${col}${last}"
    tiles = [
        ("League average\nOZ time", league, PCT, None),
        ("Most time attacking", f"=INDEX({T},MATCH(MAX({rng('C')}),{rng('C')},0))", None,
         (f"=MAX({rng('C')})", PCT)),
        ("Least time attacking", f"=INDEX({T},MATCH(MIN({rng('C')}),{rng('C')},0))", None,
         (f"=MIN({rng('C')})", PCT)),
        ("Most above expected", f"=INDEX({T},MATCH(MAX({rng('I')}),{rng('I')},0))", None,
         (f"=MAX({rng('I')})", PTS_LABEL)),
        ("Most below expected", f"=INDEX({T},MATCH(MIN({rng('I')}),{rng('I')},0))", None,
         (f"=MIN({rng('I')})", PTS_LABEL)),
        ("Forecast leader\n(end of season)", f"=INDEX({T},MATCH(MAX({rng('J')}),{rng('J')},0))", None,
         (f"=MAX({rng('J')})", PCT)),
    ]
    thin = Side(style="thin", color="BFBFBF")
    for i, (label, value, fmt, sub) in enumerate(tiles):
        c0 = 2 + i * 3
        for r in (4, 5, 6):
            ws.merge_cells(start_row=r, start_column=c0, end_row=r, end_column=c0 + 2)
            for c in range(c0, c0 + 3):
                cell = ws.cell(row=r, column=c)
                cell.fill = PatternFill("solid", fgColor=LIGHT)
                cell.border = Border(left=thin if c == c0 else None,
                                     right=thin if c == c0 + 2 else None,
                                     top=thin if r == 4 else None, bottom=thin if r == 6 else None)
        a = ws.cell(row=4, column=c0, value=label)
        a.font = font(size=9, color="595959", bold=True)
        b = ws.cell(row=5, column=c0, value=value)
        b.font = font(size=14, bold=True, color=NAVY)
        if fmt:
            b.number_format = fmt
        if sub:
            s = ws.cell(row=6, column=c0, value=sub[0])
            s.number_format = sub[1]
            s.font = font(size=11, color=NAVY)
        elif i == 0:
            ws.cell(row=6, column=c0, value="Source: NHL EDGE").font = font(size=8, italic=True, color="7F7F7F")
        for r in (4, 5, 6):
            ws.cell(row=r, column=c0).alignment = Alignment(horizontal="center", vertical="center",
                                                            wrap_text=True)
    ws.row_dimensions[4].height = 30
    ws.row_dimensions[5].height = 24
    ws.row_dimensions[6].height = 18

    ws["B8"] = ("How to read: offensive zone (OZ) % = share of the game the puck is in the opponent's end. "
                "Higher is better. 1 point is about 36 seconds a game. Green = good, red = bad.")
    ws["B8"].font = font(size=9, italic=True, color="595959")

    def ref(name, offset, rows=n, header=True):
        col = blocks[name] + offset
        return Reference(data_ws, min_col=col, min_row=4 if header else 5, max_row=4 + rows)

    # 1. vs league average
    sorted1, _ = s1
    colors = [GREEN if t["oz"] >= league else RED for t in sorted1]
    c1 = horizontal_bars(ws, "Time attacking vs league average", ref("vs_league", 0, header=False),
                         ref("vs_league", 1), "Points above (+) or below (-) league average", PTS, colors)
    ws.add_chart(c1, "B10")

    # 2. vs expected
    colors = [GREEN if t["oz"] >= t["x_oz"] else RED for t in s2]
    c2 = horizontal_bars(ws, "Better or worse than their stats suggest",
                         ref("vs_expected", 0, header=False), ref("vs_expected", 1),
                         "Actual minus expected OZ (pts)", PTS, colors)
    ws.add_chart(c2, "L10")

    # 3. Now vs forecast
    c3 = BarChart()
    c3.type = "bar"
    c3.add_data(Reference(data_ws, min_col=blocks["forecast"] + 1, max_col=blocks["forecast"] + 2,
                          min_row=4, max_row=4 + n), titles_from_data=True)
    c3.set_categories(ref("forecast", 0, header=False))
    tidy_chart(c3, "Where they'll finish: OZ % now vs forecast (axis starts at 36%)",
               y_title="Offensive zone %")
    c3.x_axis.scaling.orientation = "maxMin"
    c3.y_axis.crosses = "max"
    c3.y_axis.scaling.min = 0.36
    c3.y_axis.scaling.max = 0.47
    c3.y_axis.majorUnit = 0.01
    c3.y_axis.number_format = "0%"
    c3.legend.position = "t"
    c3.gapWidth = 50
    for s, color in zip(c3.series, (GREY, BLUE)):
        s.graphicalProperties.solidFill = color
        s.graphicalProperties.line.solidFill = color
    c3.width, c3.height = 17, 20
    ws.add_chart(c3, "B47")

    # 4. Zone split
    c4 = BarChart()
    c4.type = "bar"
    c4.grouping = "percentStacked"
    c4.overlap = 100
    c4.add_data(Reference(data_ws, min_col=blocks["split"] + 1, max_col=blocks["split"] + 3,
                          min_row=4, max_row=4 + n), titles_from_data=True)
    c4.set_categories(ref("split", 0, header=False))
    tidy_chart(c4, "Where the puck spends the game (all situations)", y_title="Share of game time")
    c4.x_axis.scaling.orientation = "maxMin"
    c4.y_axis.crosses = "max"
    c4.y_axis.number_format = "0%"
    c4.legend.position = "t"
    c4.gapWidth = 40
    for s, color, text in zip(c4.series, (GREEN, "BDBDBD", RED), ("FFFFFF", "000000", "FFFFFF")):
        s.graphicalProperties.solidFill = color
        s.graphicalProperties.line.solidFill = "FFFFFF"
        s.dLbls = DataLabelList()
        s.dLbls.showVal = True
        s.dLbls.numFmt = "0.0%"
        s.dLbls.txPr = label_font(text, bold=True)
        for attr in ("showSerName", "showCatName", "showLegendKey", "showPercent"):
            setattr(s.dLbls, attr, False)
    c4.width, c4.height = 17, 20
    ws.add_chart(c4, "L47")


# ----------------------------------------------------------------------- main

def build(out=OUT):
    teams = load()
    if not teams:
        raise RuntimeError("No team data found in the CSV files.")
    updated = datetime.datetime.fromtimestamp(os.path.getmtime(ZONE_CSV)).strftime("%b %d, %Y %I:%M %p")
    wb = Workbook()
    teams_ws, first, last = teams_sheet(wb, teams, updated)
    details_sheet(wb, teams, updated)
    data_ws, blocks, n, s1, s2 = chart_data_sheet(wb, teams)
    dashboard(wb, teams_ws, first, last, data_ws, blocks, n, s1, s2, updated, teams[0]["league_oz"])
    wb.move_sheet("Dashboard", offset=-wb.index(wb["Dashboard"]))
    wb.active = 0
    wb.save(out)
    return out


if __name__ == "__main__":
    try:
        print(f"Saved {build()}")
    except PermissionError:
        sys.exit("Could not save nhl_zone_dashboard.xlsx - close it in Excel and try again.")
