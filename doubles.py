"""Double-doubles and triple-doubles, from the model alone (no odds needed).

A double-double is two of points, rebounds and assists at 10 or more; a triple-double is all three.
Each stat's chance of reaching 10 comes from the same projections the other markets use. The three are
treated as independent, which the backtest checks (see doubles_backtest).

For each player the page shows his chance tonight next to his usual rate, and the ratio between them
("boost"): how much better than a normal game this game looks for him.
"""
import numpy as np

import nba_pipeline as m

STATS = ("pts", "reb", "ast")
# Calibration, fitted on 2025-26 (22,616 player-games). Treating the three stats as independent gets the middle
# right but overstates how far a game can move a player from his usual rate (DD) and understates triple-doubles
# (big games lift all three stats together). So: double-doubles are pulled 40% of the way back toward the
# player's usual rate, and triple-doubles are scaled up 30% then pulled 20% toward the usual rate.
DD_BLEND = 0.6
TD_SCALE, TD_BLEND = 1.3, 0.8


def chances(lam_pts, lam_reb, lam_ast, nb):
    """(P double-double, P triple-double). Inputs may be numbers or arrays."""
    p = [m.dist_sf(9, np.asarray(lam, float), nb[s]) for lam, s in ((lam_pts, "pts"), (lam_reb, "reb"), (lam_ast, "ast"))]
    p1, p2, p3 = p
    dd = p1 * p2 + p1 * p3 + p2 * p3 - 2 * p1 * p2 * p3
    return dd, p1 * p2 * p3


def calibrated(lam_pts, lam_reb, lam_ast, nb, typ_dd, typ_td):
    """(P double-double, P triple-double) after calibration, given the player's usual rates."""
    dd, td = chances(lam_pts, lam_reb, lam_ast, nb)
    typ_dd, typ_td = np.asarray(typ_dd, float), np.asarray(typ_td, float)
    return (np.clip(typ_dd + DD_BLEND * (dd - typ_dd), 0, 1),
            np.clip(typ_td + TD_BLEND * (TD_SCALE * td - typ_td), 0, 1))


def _bins(p, y, edges):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mk = (p >= lo) & (p < hi)
        if mk.sum() >= 30:
            out.append({"lo": lo, "hi": hi, "n": int(mk.sum()), "pred": round(float(p[mk].mean()), 4),
                        "actual": round(float(y[mk].mean()), 4)})
    return out


def doubles_backtest(proj, cfg=m.CONFIG):
    """How well the model's chances match what happened, and whether a 'boosted' game really hits more often."""
    nb = {**m.CONFIG["nb_r"], **cfg.get("nb_r", {})}
    dd, td = calibrated(proj["lam_pts"].to_numpy(), proj["lam_reb"].to_numpy(), proj["lam_ast"].to_numpy(), nb,
                        proj["typ_dd"].to_numpy(), proj["typ_td"].to_numpy())
    out = {}
    for name, p, y, typ, min_typ, edges in (
            ("dd", dd, proj["dd"].to_numpy(float), proj["typ_dd"].to_numpy(float), 0.10,
             [0, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.01]),
            ("td", td, proj["td"].to_numpy(float), proj["typ_td"].to_numpy(float), 0.02,
             [0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 1.01])):
        bm, bb = m.brier(p, y), m.brier(typ, y)
        boost = np.where(typ >= min_typ, p / np.maximum(typ, 1e-9), np.nan)
        rows = []
        for lo, hi, label in ((0, 0.8, "under 0.8x"), (0.8, 0.95, "0.8x to 0.95x"), (0.95, 1.05, "about normal"),
                              (1.05, 1.25, "1.05x to 1.25x"), (1.25, 99, "over 1.25x")):
            mk = (boost >= lo) & (boost < hi)
            if mk.sum() >= 30:
                rows.append({"label": label, "n": int(mk.sum()), "typical": round(float(typ[mk].mean()), 4),
                             "model": round(float(p[mk].mean()), 4), "actual": round(float(y[mk].mean()), 4)})
        out[name] = {"n": int(len(y)), "base_rate": round(float(y.mean()), 4), "avg_pred": round(float(p.mean()), 4),
                     "brier_model": round(bm, 5), "brier_usual_rate": round(bb, 5), "skill": round(1 - bm / bb, 4),
                     "calibration": _bins(p, y, edges), "boost": rows, "min_typical": min_typ}
    return out
