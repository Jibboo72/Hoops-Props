#!/usr/bin/env python3
"""NBA auto-tuner.

Tries model settings one group at a time on 2025-26: it picks on games before Jan 1 and checks the
winner on games after. A setting is kept only if it also beats the current one on the later games,
so we don't just fit one season's noise.

The recency WINDOW stays at the last 5 games (Josh's call). The tuner only moves how hard that window
pulls, so it can say whether 65% on the last 5 is right or too much.

Writes data/tuned_config.json (read by board.py) and refreshes docs/data/backtest.json so the
Backtest page shows the tuned model.
"""
import itertools
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np

import nba_pipeline as m

SPLIT = "2026-01-01"
TUNED = m.ROOT / "data" / "tuned_config.json"
# (group, which score decides it, settings to try)
GROUPS = [
    ("minutes", "all", {"min_recent_weight": [0.3, 0.45, 0.6, 0.75], "min_prior_games": [4, 8, 16]}),
    ("three rate", "thr", {"recent_weight": [0.15, 0.3, 0.45, 0.65, 0.8], "recent_prior_games": [1.0, 2.0, 4.0],
                           "prior_games": [10, 20, 35]}),
    ("three accuracy", "thr", {"pct_prior_att": [100, 250, 500], "opp_pct_prior_att": [450, 900, 1800]}),
    ("rebounds", "reb", {"recent_weight_reb": [0.15, 0.3, 0.45, 0.65, 0.8], "reb_prior_games": [10, 20, 35]}),
    ("context", "all", {"team_k": [6, 10, 20], "team_prior_keep": [0.3, 0.6, 0.9],
                        "home_edge": [0.0, 0.01, 0.02], "b2b_drop": [0.0, 0.02, 0.04]}),
]
DISPERSION = [5, 8, 12, 20, 40]


def scores(proj):
    """Lower is better for every score. Returns (fit half, check half). Each is the best count-fit NLL."""
    out = []
    for half in (proj["date"] < SPLIT, proj["date"] >= SPLIT):
        d = proj[half]
        out.append({
            "thr": min(-float(np.mean(m.dist_logpmf(d["fg3m"].to_numpy(), d["lam_thr"].to_numpy(), r))) for r in DISPERSION),
            "reb": min(-float(np.mean(m.dist_logpmf(d["reb"].to_numpy(), d["lam_reb"].to_numpy(), r))) for r in DISPERSION)})
    return out


def score_of(s, key, ref):
    if key != "all":
        return s[key]
    return sum(s[k] / ref[k] for k in ("thr", "reb"))  # relative, so each market counts equally


def best_dispersion(proj, col, stat):
    lam, y = proj[col].to_numpy(), proj[stat].to_numpy()
    return max(DISPERSION, key=lambda r: float(np.mean(m.dist_logpmf(y, lam, r))))


def tune(test, prior, start_cfg=None, groups=GROUPS, verbose=True):
    cfg = dict(m.CONFIG if start_cfg is None else start_cfg)
    fit0, check0 = scores(m.build_projections(test, prior, cfg))
    report = {"before": check0, "kept": {}}
    for name, key, grid in groups:
        keys = list(grid)
        ref_fit, ref_check = dict(fit0), dict(check0)
        best_cfg, best_fit, best_check, best_fit_s = None, score_of(fit0, key, ref_fit), None, None
        for combo in itertools.product(*(grid[k] for k in keys)):
            trial = dict(cfg, **dict(zip(keys, combo)))
            fit, check = scores(m.build_projections(test, prior, trial))
            if score_of(fit, key, ref_fit) < best_fit - 1e-9:
                best_cfg, best_fit, best_check, best_fit_s = trial, score_of(fit, key, ref_fit), check, fit
        if best_cfg and score_of(best_check, key, ref_check) < score_of(check0, key, ref_check):
            cfg, fit0, check0 = best_cfg, best_fit_s, best_check
            report["kept"][name] = {k: cfg[k] for k in keys}
            if verbose:
                print(f"{name}: kept {report['kept'][name]}")
        elif verbose:
            print(f"{name}: nothing beat the current settings on the second half, kept as is")
    proj = m.build_projections(test, prior, cfg)
    cfg["nb_r"] = {"thr": best_dispersion(proj, "lam_thr", "fg3m"), "reb": best_dispersion(proj, "lam_reb", "reb")}
    report["after"] = check0
    report["improvement"] = {k: round(1 - check0[k] / report["before"][k], 5) for k in check0}
    return cfg, proj, report


def main():
    t0 = time.time()
    prior = m.fetch_season(m.PRIOR_SEASON)
    test = m.fetch_season(m.TEST_SEASON)
    start = dict(m.CONFIG)
    if TUNED.exists():
        start.update(json.loads(TUNED.read_text()))  # start from the last tuned settings
    cfg, proj, report = tune(test, prior, start)
    tuned = {k: cfg[k] for k in [k for _, _, g in GROUPS for k in g] + ["nb_r"]}
    TUNED.parent.mkdir(parents=True, exist_ok=True)
    TUNED.write_text(json.dumps(tuned, indent=1))
    markets = m.backtest(proj, cfg)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "season_tested": "2025-26", "prior_season": "2024-25",
           "counts": {"player_games": int(len(proj)), "players": int(proj["player_id"].nunique()),
                      "games": int(proj["game_id"].nunique())},
           "config": cfg, "tuning": report, "markets": markets}
    m.OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    m.OUT_FILE.write_text(json.dumps(out, indent=1, default=str))
    for k, v in report["improvement"].items():
        print(f"  {k}: {v:+.2%} better on the second half")
    print(f"Done in {time.time() - t0:.0f}s. Tuned settings: {tuned}")


if __name__ == "__main__":
    main()
