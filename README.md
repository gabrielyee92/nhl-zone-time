# NHL Zone Time Analytics

Where the puck spends the game for every NHL team (offensive, neutral and defensive zone time
from NHL EDGE puck tracking), what a ridge regression model expects it to be, and where each team
is forecast to finish. Includes an interactive Streamlit dashboard.

## Project layout

| File | What it does |
|---|---|
| `nhl_zone_time.py` | Downloads current zone time for all teams (all / even strength / power play / penalty kill). CLI + CSV. |
| `nhl_zone_model.py` | Builds the training data (2021-22 onward), fits the ridge model, validates it, predicts the current season and forecasts end-of-season values. `fit_all()` returns everything as data; `main()` prints it. |
| `nhl_zone_live.py` | Re-runs everything when EDGE updates (watch mode or `--once` for Task Scheduler). |
| `nhl_zone_excel.py` | Builds the Excel workbook with charts. |
| `zone_model_cache.json` | Downloaded data for completed seasons. **Commit this**: the dashboard reads it so it doesn't re-download history. |
| `streamlit_app.py` | Dashboard entry point (sidebar navigation). |
| `dashboard/data.py` | The only bridge between the dashboard and the model/APIs. All caching lives here. |
| `dashboard/theme.py` | Dark theme, Plotly template, ACTUAL / MODEL / DERIVED labels. |
| `dashboard/views/*.py` | The five pages: Overview, Team Explorer, Prediction Center, Statistical Analysis, Historical Trends. |

## Run the dashboard locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

It opens at http://localhost:8501. The first load fetches the current season (about 30-60 s);
after that it is cached for 6 hours. Use **Refresh data now** in the sidebar to force an update.

## Deploy to Streamlit Community Cloud

1. Put this folder in a GitHub repository (include `zone_model_cache.json`; `.gitignore` already
   excludes local CSV/Excel outputs).
2. At https://share.streamlit.io choose **Create app → Deploy a public app from GitHub**, pick the
   repo and branch, and set **Main file path** to `streamlit_app.py`.
3. Under **Advanced settings**, choose Python **3.12** (or the newest version offered).
4. Deploy. Streamlit installs `requirements.txt` automatically.

To keep the hosted history current, re-run `python nhl_zone_model.py` locally after each season
(or whenever you like) and commit the updated `zone_model_cache.json`. The current season is always
downloaded live by the app.

## How the data flows

```
NHL EDGE (zone time) + NHL stats API (team stats)
        │
nhl_zone_model.build_dataset()  ← completed seasons from zone_model_cache.json, current season live
        │
nhl_zone_model.fit_all()        ← ridge model, leave-one-season-out validation, forecast
        │
dashboard/data.load()           ← converts to DataFrames, cached 6 h (st.cache_data)
        │
dashboard/views/*               ← charts and tables only; no model logic
```

API calls per cold start: about 40 with the cache file present (current season + "stats to date"
for past seasons), about 200 without it. Team situation splits are downloaded only when a page asks
for them, and completed seasons are cached permanently.

## Reading the dashboard

- **ACTUAL** = NHL data as published. **MODEL** = model output (expected, forecast, errors).
  **DERIVED** = calculated from NHL data (averages, ranks, z-scores, correlations).
- Model values use orange, dashed lines and open/diamond markers; actual values use solid colors.
- 1 percentage point of zone time ≈ 36 seconds per 60 minutes.

## Limitations

- EDGE zone time starts in 2021-22, so the model trains on ~160 team-seasons.
- The current season is partial; early numbers are noisy.
- EDGE and the NHL stats API are public but undocumented; they may change or rate-limit cloud servers.
  If the current season can't be downloaded, the dashboard shows completed seasons only and says so.
- Neutral zone % = 100 − OZ% − DZ%.
- Arizona Coyotes data ends in 2023-24. Utah Hockey Club (2024-25) and Utah Mammoth (2025-26 on)
  have different NHL team ids; the dashboard links them as one team, the model does not.
- The forecast is backtested by calendar date, does not use actual zone time to date, and its 80%
  range (±1.28 × RMSE) has not been calibration-checked.
- Coefficients show association, not causation; several predictors are strongly correlated.
