# Buckets (NBA props) — data map

Master map of every betting app and how they connect:
[`callsheet-data/DATA_MAP.md`](https://github.com/Jibboo72/callsheet-data/blob/main/DATA_MAP.md).
Update both when a file or link changes.

The app is served by GitHub Pages from `docs/` (`jibboo72.github.io/Hoops-Props/`).

## What this repo publishes (`docs/data/`)

| File | What's in it | Written by | When (UTC cron) | Read by |
|---|---|---|---|---|
| `board.json` | Tonight's board: games, players, markets (threes priced; rebounds and assists always fair odds only), odds status, max price, rules | `board.py` (tonight.yml; odds only if repo variable `USE_ODDS` = true, using secret `ODDS_API_KEY`) | every 20 min at :07/:27/:47 from 13:00 to 23:59 UTC and :07/:37 from 00:00 to 04:59 UTC (GitHub drops or delays scheduled runs, so many chances; with odds off every run rebuilds the board, with odds on only the first run of the day) | `board.html` / `board.js`, **SportsMF** |
| `doubles.json` | Tonight's double-double / triple-double chances per player, with each player's usual rate. When a book prices a player's double-double (Yes), the player gets an `odds` block: `p_model`, `p_mkt` (only if a book posts both Yes and No), `p` (blend), `fair`, `prices`, `price`, `book`, `ev`, `likely`. Triple-doubles are model only. Top-level `parlay` block: tonight's round-robin rating of the Best 6 (2-pick 15 x $2, 3-pick 20 x $1.50), each format rated 1-10 with expected profit, ROI, chance to profit, chance to lose all, break-even hits and the book used (`parlay.py`, see README); null with fewer than 6 players. Raw chances are unrounded; the page shows anything under 1% as 1% and builds the 2x (≥3%) and 3x (≥1%) pools itself | `board.py` + `parlay.py` (tonight.yml) | with the board | `doubles.html` / `doubles.js` (incl. the Round robin card), `nav.js` (2-pick and 3-pick ratings in the top strip on every page); the channel's daily round-robin post |
| `doubles_log.json` | Tracked double/triple-double chances, graded after games; priced ones also carry `dd_price`, `dd_book`, `dd_prices`, `dd_p`, `dd_p_mkt`, `dd_ev`, `dd_likely` (first price seen) | `sim.py` (tonight.yml) | with the board | `doubles.js` |
| `sim_log.json` | Simulated results log | `sim.py` (tonight.yml) | with the board | `sim.js`, `structures.js` |
| `calib/YYYY-MM-DD.json` | Daily calibration snapshot | tonight.yml | with the board | history |
| `credits.json` | Odds API credits left | `credits.py` (credits.yml) | 12:00 daily | `board.js` |
| `backtest.json` | Model backtest (incl. `doubles` section) | `tune.py` (tune.yml) / `nba_pipeline.py` (backtest.yml) | manual | `app.js` |
| `backtest_live.json` | Backtest of this season only (2026-27 so far), each game projected from earlier games | `nba_pipeline.py --live` (backtest.yml, `live` input) | manual | `app.js` (`app.html?season=live`) |
| `top6_live.json` | This season's nightly top-6 2x and 3x picks (`markets` = most likely, `bump` = biggest jump over usual, `extra` = model-only threes/rebounds/assists replay) and whether each hit (singles and 2-team round robins) | `sim_top6.py` (top6.yml) | manual | `doubles.js` (Best 6 night by night, with 2-team and 3-team parlay counts) |
| `best6.json` | Tonight's Best 6 for threes, rebounds and assists (main line, side the model likes, skips plays worse than -198), plus `ratings`: each market's 1-10 betting-night grade on the round-robin scale (`parlay.rate_legs`; unpriced legs use fair less 7%) | `best6.py` via `sim.py` (tonight.yml) | with the board | `board.js`, `nav.js` (grade tiles in the top strip) |
| `best6_log.json` | Each night's Best 6 per market with results, frozen at first tip | `best6.py` via `sim.py` | with the board | `best6.py` (summary) |
| `best6_summary.json` | Hit rate per market (2x, 3PT, REB, AST): replay since Oct 20 plus live nights | `best6.py` via `sim.py` | with the board | `nav.js` (strip at the top of every page) |

## Working data (`data/`, not served)

`games_20242025.csv`, `games_20252026.csv` (game logs), `tuned_config.json`
(model settings from `tune.py`), `name_aliases.json` (player name matching).

## Sources

ESPN NBA site API (games, logs, pre-game injury report; free) and The Odds API (prices; off unless repo variable `USE_ODDS` is true).

Odds markets pulled, in priority order when credits are short: `player_double_double` (1 credit a game), then `player_threes` (1 credit a game), plus game lines (2 credits a night while 150+ credits are left). `credit_plan()` in `board.py` spreads the key's balance evenly until the 28th, keeping 25 in reserve; `NBA_SHARE` is 1.0 since Scoresheet stopped pulling odds (Nov 6, 2026). Note: this repo's `ODDS_API_KEY` secret reports its own balance in `credits.json`, separate from Scoresheet's key.

## Who else reads it

**SportsMF** reads `docs/data/board.json` for the Props tab on NBA game pages.
It matches games by `games[].id` (the ESPN event id) and uses `players[]`
(`game_id`, `name`, `team`, `min`, `exp_thr/reb/ast`), `markets`, `max_price`,
and each market's `p`, `fair`, `price`, `book`, `ev`, `likely`. Keep those stable.

With odds off, `board.json` has model-only fair prices: no `price`, `book`, `ev` or `likely` on markets. With odds on, only `thr_*` markets carry prices; `reb_*` and `ast_*` stay fair-only. Double-double prices live in `doubles.json`, not `board.json`, so SportsMF's Props tab is unchanged. Players listed Out on ESPN's injury report are left out of `players[]`; others get an optional `status` field.
