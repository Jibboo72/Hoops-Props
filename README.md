# Buckets: NBA 3-pointer and rebound props

Same setup as Scoresheet (NHL), switched to basketball. Model first, paper-bet sim, nightly board.

## Setup (about 10 minutes, all from your phone's browser)
1. Create an empty GitHub repo and upload these files.
2. Settings > Secrets and variables > Actions > add `ODDS_API_KEY` (same key as the NHL app; credits are shared).
3. Settings > Pages > deploy from branch `main`, folder `/docs`.
4. Actions tab, run in this order:
   1. **Probe**: confirms GitHub can reach the NBA data feeds. If a line says status 200, you're good.
   2. **Backtest**: pulls 2024-25 and 2025-26 and scores the model.
   3. **Tune**: lets the tuner adjust settings (it checks them on a later half of the season before keeping any).
   4. **Tonight**: builds the board and logs paper bets. It then runs itself three times a day.

## How to read it
- Board page: best plays, "most likely" plays, and every prop with model chance, fair price, best price, edge.
- Sim page: paper record. Judge it after a few thousand graded props, not a few nights.
- Not modeled: injuries and lineup news. Always check the injury report. Minutes are the biggest driver.

## Local checks
`python selftest.py --quick` runs the whole loop on made-up league data.

## Odds credits
The Tonight page shows how many Odds API credits are left and when they reset (the 28th). The **Credits** workflow (daily, or run by hand) checks the balance for free and updates that line.

## Odds are off by default
Tonight runs on the model alone (no Odds API credits). To turn prices back on, add a repo variable named `USE_ODDS`
with value `true` (Settings > Secrets and variables > Actions > Variables).

## Doubles
The Doubles tab ranks tonight's double-double and triple-double chances and each player's bump over his usual rate.
Chances are tracked and graded in `docs/data/doubles_log.json`, no odds needed.

## Round-robin rating (Doubles tab)
Each night `board.py` rates the Best 6 double-doubles as a $30 round robin, two ways, and writes it to the `parlay`
block of `docs/data/doubles.json` (code in `parlay.py`). The Doubles tab shows it as the "Round robin tonight" card.

- **2-pick:** all 15 pairs of the 6 at $2 each. **3-pick:** all 20 trios at $1.50 each.
- **The 6 legs** are the same 6 the page shows: highest chance first, skipping anyone whose best price is worse than -198.
- **Each leg's chance** is the page's blend (half model, half the market's no-cut chance when a book posts Yes and No).
  The model's half is first scaled by a calibration factor `k` = (hits + prior) / (expected + prior) over this season's
  graded Best 6 picks (the replay in `top6_live.json` plus live nights in `doubles_log.json`), with a prior worth 50
  picks at 1.0, kept between 0.75 and 1.0 so it never inflates the model. It updates every run. On Nov 6 it was 0.98
  (47 hits on 48.4 expected over 95 picks; the replay alone ran hot at 0.87, the two live nights went 10 for 12).
- **Price:** a round robin goes in at one book, so each format is priced at the book that posts all 6 and gives the most
  expected profit (`book`). `best_price` shows the same bet at the best price for each leg, for reference only. If no
  book has all 6, the rating uses best price per leg; a leg with no price uses its fair price less 7%, and `notes` says so.
- **Math:** all 64 hit/miss outcomes of the 6 legs, treated as independent (same-game picks are listed in `same_game`).
- **Score** = 5 + ROI / 0.07 + 4 x (chance to profit - usual chance to profit), clamped to 1-10 and shown rounded.
  5 is break-even, each point is 7% ROI (8 is about +21%, 2 about -21%). The usual chance to profit on a break-even night
  is 40% for 2-pick and 33% for 3-pick (this season's 14 replayed Best 6 nights at fair prices), so the small chance
  adjustment favours the steadier bet at equal ROI. Book cuts compound in parlays, so most nights land around 3 to 5;
  a 6 or better means the prices beat our chances. Scale check: 1,500 random 6-player sets from Nov 6's priced players
  at their best single book scored 1.7 to 3.5 (middle half) for 2-pick; Nov 6's real Best 6 scored 4 and 3.
- **Better format** = more expected profit; within 50 cents it's a tie and 2-pick wins (less swing).

Fields (`doubles.json` → `parlay`): `picks[]` (`name`, `p_model`, `p`, `price`, `book`, `priced`), `calibration`
(`k`, `picks`, `hits`, `expected`), `priced_legs`, `books_with_all_6`, `formats["2"|"3"]` (`rating` 1-10, `score`,
`book`, `bets`, `stake_each`, `total`, `exp_profit`, `roi`, `p_profit`, `p_lose_all`, `breakeven_hits` = hits that
always profit, `can_profit_at` = fewest hits that can profit, `payout_by_hits`, `best_price`), `better` ("2" or "3"),
`same_game`, `notes`, `rules`. `parlay` is null when fewer than 6 players are on the board.

With odds on, only the first Tonight run of the day (15:17 UTC, 10:17 AM Eastern) builds the board, so that run's
rating is the day's final one. With odds off every run rebuilds it, and the rating uses estimated prices.
