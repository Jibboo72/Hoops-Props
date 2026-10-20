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
