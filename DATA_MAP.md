# Buckets (NBA props) — data map

Master map of every betting app and how they connect:
[`callsheet-data/DATA_MAP.md`](https://github.com/Jibboo72/callsheet-data/blob/main/DATA_MAP.md).
Update both when a file or link changes.

The app is served by GitHub Pages from `docs/` (`jibboo72.github.io/Hoops-Props/`).

## What this repo publishes (`docs/data/`)

| File | What's in it | Written by | When (UTC cron) | Read by |
|---|---|---|---|---|
| `board.json` | Tonight's board: games, players, markets, odds status, max price, rules | `board.py` (tonight.yml, secret `ODDS_API_KEY`) | 16:00, 19:00, 22:00 daily | `board.html` / `board.js`, **SportsMF** |
| `sim_log.json` | Simulated results log | `sim.py` (tonight.yml) | with the board | `sim.js`, `structures.js` |
| `calib/YYYY-MM-DD.json` | Daily calibration snapshot | tonight.yml | with the board | history |
| `credits.json` | Odds API credits left | `credits.py` (credits.yml) | 12:00 daily | `board.js` |
| `backtest.json` | Model backtest | `tune.py` (tune.yml) / `nba_pipeline.py` (backtest.yml) | manual | `app.js` |

## Working data (`data/`, not served)

`games_20242025.csv`, `games_20252026.csv` (game logs), `tuned_config.json`
(model settings from `tune.py`), `name_aliases.json` (player name matching).

## Sources

ESPN NBA site API (games, logs) and The Odds API (prices).

## Who else reads it

**SportsMF** reads `docs/data/board.json` for the Props tab on NBA game pages.
It matches games by `games[].id` (the ESPN event id) and uses `players[]`
(`game_id`, `name`, `team`, `min`, `exp_thr/reb/ast`), `markets`, `max_price`,
and each market's `p`, `fair`, `price`, `book`, `ev`, `likely`. Keep those stable.
