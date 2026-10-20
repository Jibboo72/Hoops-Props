#!/usr/bin/env python3
"""
NBA prop model: threes made, rebounds and assists.

The data pull lives in nba_data.py and the model in nba_model.py. This file scores the model: it
projects every 2025-26 game using only earlier games and writes docs/data/backtest.json.
board.py, sim.py and tune.py import everything through here.

Run:  python nba_pipeline.py            (uses cached data if present)
      python nba_pipeline.py --refresh  (re-download everything)
"""
import json
import sys
from datetime import datetime, timezone

import numpy as np
from scipy import stats

from nba_data import DATA_DIR, ROOT, TEAMS, fetch_season, fetch_schedule, get_json  # noqa: F401
from nba_model import CONFIG, build_projections, team_games  # noqa: F401

PRIOR_SEASON = "20242025"
TEST_SEASON = "20252026"
OUT_FILE = ROOT / "docs" / "data" / "backtest.json"
EPS = 1e-6
FAMILIES = {"thr": ("threes", "lam_thr", "fg3m", "naive_thr", "thr_lines"),
            "reb": ("reb", "lam_reb", "reb", "naive_reb", "reb_lines"),
            "ast": ("assists", "lam_ast", "ast", "naive_ast", "ast_lines")}


def dist_sf(k, mu, r):
    """P(X > k) for Poisson (r=None) or negative binomial with size r. k may be an array."""
    mu = np.maximum(mu, EPS)
    if r is None:
        return stats.poisson.sf(k, mu)
    return stats.nbinom.sf(k, r, r / (r + mu))


def dist_cdf(k, mu, r):
    """P(X <= k)."""
    return 1.0 - dist_sf(k, mu, r)


def dist_logpmf(x, mu, r):
    mu = np.maximum(mu, EPS)
    if r is None:
        return stats.poisson.logpmf(x, mu)
    return stats.nbinom.logpmf(x, r, r / (r + mu))


def brier(p, y):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def logloss(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration(p, y, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    out, ece = [], 0.0
    for b in range(bins):
        m = idx == b
        if m.sum() == 0:
            continue
        pred, act = float(p[m].mean()), float(y[m].mean())
        ece += m.sum() / len(p) * abs(pred - act)
        out.append({"lo": round(float(edges[b]), 2), "hi": round(float(edges[b + 1]), 2),
                    "n": int(m.sum()), "pred": round(pred, 4), "actual": round(act, 4)})
    return out, float(ece)


def score_market(p, p_naive, y, early_mask):
    p, p_naive, y = np.asarray(p, float), np.asarray(p_naive, float), np.asarray(y, float)
    bm, bn = brier(p, y), brier(p_naive, y)
    cal, ece = calibration(p, y)

    def skill(mask):
        if mask.sum() < 50:
            return None
        return round(1 - brier(p[mask], y[mask]) / brier(p_naive[mask], y[mask]), 4)

    conf, top = p >= 0.60, p >= np.quantile(p, 0.95)
    return {
        "n": int(len(y)), "base_rate": round(float(y.mean()), 4), "avg_pred": round(float(p.mean()), 4),
        "brier_model": round(bm, 5), "brier_naive": round(bn, 5), "skill": round(1 - bm / bn, 4),
        "logloss_model": round(logloss(p, y), 5), "logloss_naive": round(logloss(p_naive, y), 5),
        "ece": round(ece, 4), "early_skill": skill(early_mask), "late_skill": skill(~early_mask),
        "confident": {"threshold": 0.60, "n": int(conf.sum()),
                      "pred": round(float(p[conf].mean()), 4) if conf.any() else None,
                      "hit": round(float(y[conf].mean()), 4) if conf.any() else None},
        "top5": {"n": int(top.sum()), "pred": round(float(p[top].mean()), 4), "hit": round(float(y[top].mean()), 4)},
        "calibration": cal}


def book_line(naive):
    """A stand-in for the book's line: the half point at or just above the player's own average."""
    return np.maximum(np.floor(np.asarray(naive, float)) + 0.5, 0.5)


def backtest(proj, cfg=CONFIG):
    early = (proj["c_gp"] < 15).to_numpy()
    out = {}
    for fam, (label, lam_col, stat_col, naive_col, lines_key) in FAMILIES.items():
        lam, actual, naive = proj[lam_col].to_numpy(), proj[stat_col].to_numpy(), proj[naive_col].to_numpy()
        fits = []
        for r in cfg["nb_candidates"]:
            ll = float(np.mean(dist_logpmf(actual, lam, r)))
            fits.append({"name": "Poisson" if r is None else f"Neg. binomial (r={r})", "r": r, "loglik": round(ll, 5)})
        best = max(fits, key=lambda f: f["loglik"])
        r = best["r"]
        m = {"label": {"thr": "3-pointers made", "reb": "Rebounds", "ast": "Assists"}[fam], "fits": fits, "chosen": best["name"],
             "avg_proj": round(float(lam.mean()), 3), "avg_actual": round(float(actual.mean()), 3), "lines": {}}
        for line in cfg[lines_key]:
            k = int(np.floor(line))
            m["lines"][f"{line}"] = score_market(dist_sf(k, lam, r), dist_sf(k, np.maximum(naive, 0.05), None),
                                                 (actual > line).astype(float), early)
        bl = book_line(naive)  # how a book would post it: what matters for betting
        m["lines"]["main"] = score_market(dist_sf(np.floor(bl), lam, r), dist_sf(np.floor(bl), np.maximum(naive, 0.05), None),
                                          (actual > bl).astype(float), early)
        out[fam] = m
    return out


def main():
    refresh = "--refresh" in sys.argv
    prior = fetch_season(PRIOR_SEASON, refresh)
    test = fetch_season(TEST_SEASON, refresh)
    proj = build_projections(test, prior)
    markets = backtest(proj)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "season_tested": "2025-26", "prior_season": "2024-25",
           "counts": {"player_games": int(len(proj)), "players": int(proj["player_id"].nunique()),
                      "games": int(proj["game_id"].nunique())},
           "config": CONFIG, "markets": markets}
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=1, default=str))
    print(f"Wrote {OUT_FILE}")
    for fam, m in markets.items():
        for line, s in m["lines"].items():
            print(f"  {m['label']} over {line}: skill {s['skill']:+.1%}, calibration miss {s['ece']:.1%}, n={s['n']:,}")


if __name__ == "__main__":
    main()
