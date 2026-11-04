# Buckets (NBA props) — data map

Master map of every betting app and how they connect:
[`callsheet-data/DATA_MAP.md`](https://github.com/Jibboo72/callsheet-data/blob/main/DATA_MAP.md).
Update both when a file or link changes.

The app is served by GitHub Pages from `docs/` (`jibboo72.github.io/Hoops-Props/`).

## What this repo publishes (`docs/data/`)

| File | What's in it | Written by | When (UTC cron) | Read by |
|---|---|---|---|---|
| `board.json` | Tonight's board: games, players, markets, odds status, max price, rules | `board.py` (tonight.yml; odds only if repo variable `USE_ODDS` = true, using secret `ODDS_API_KEY`) | 16:00, 19:00, 22:00 daily | `board.html` / `board.js`, **SportsMF** |
| `doubles.json` | Tonight's double-double / triple-double chances per player, with each player's usual rate (model only, no odds). Raw chances are unrounded; the page shows anything under 1% as 1% and builds the 2x (≥3%) and 3x (≥1%) pools itself | `board.py` (tonight.yml) | with the board | `doubles.html` / `doubles.js` |
| `doubles_log.json` | Tracked double/triple-double chances, graded after games | `sim.py` (tonight.yml) | with the board | `doubles.js` |
| `sim_log.json` | Simulated results log | `sim.py` (tonight.yml) | with the board | `sim.js`, `structures.js` |
| `calib/YYYY-MM-DD.json` | Daily calibration snapshot | tonight.yml | with the board | history |
| `credits.json` | Odds API credits left | `credits.py` (credits.yml) | 12:00 daily | `board.js` |
| `backtest.json` | Model backtest (incl. `doubles` section) | `tune.py` (tune.yml) / `nba_pipeline.py` (backtest.yml) | manual | `app.js` |
| `backtest_live.json` | Backtest of this season only (2026-27 so far), each game projected from earlier games | `nba_pipeline.py --live` (backtest.yml, `live` input) | manual | `app.js` (`app.html?season=live`) |
| `top6_live.json` | This season's nightly top-6 2x and 3x picks and whether each hit (singles and 2-team round robins) | `sim_top6.py` (top6.yml) | manual | nothing yet |

## Working data (`data/`, not served)

`games_20242025.csv`, `games_20252026.csv` (game logs), `tuned_config.json`
(model settings from `tune.py`), `name_aliases.json` (player name matching).

## Sources

ESPN NBA site API (games, logs, pre-game injury report; free) and The Odds API (prices; off by default, flip repo variable `USE_ODDS` to true to turn on).

## Who else reads it

**SportsMF** reads `docs/data/board.json` for the Props tab on NBA game pages.
It matches games by `games[].id` (the ESPN event id) and uses `players[]`
(`game_id`, `name`, `team`, `min`, `exp_thr/reb/ast`), `markets`, `max_price`,
and each market's `p`, `fair`, `price`, `book`, `ev`, `likely`. Keep those stable.

With odds off, `board.json` has model-only fair prices: no `price`, `book`, `ev` or `likely` on markets. Players listed Out on ESPN's injury report are left out of `players[]`; others get an optional `status` field.
