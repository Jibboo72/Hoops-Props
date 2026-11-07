"""Top-6 replay for this season: each night pick the 6 best double-double (2x) and triple-double (3x) chances,
then count singles hits and 2-team round robins (all 15 pairs of the 6). No odds, so results are hit counts only."""
import json
from datetime import datetime, timezone
from math import comb
import numpy as np
import nba_model as m
from nba_data import fetch_season, ROOT
from doubles import calibrated

def main():
    t = json.loads((ROOT / "data" / "tuned_config.json").read_text())
    t["nb_r"] = {**m.CONFIG["nb_r"], **t.get("nb_r", {})}
    m.CONFIG.update(t)
    proj = m.build_projections(fetch_season("20262027"), fetch_season("20252026"))
    dd, td = calibrated(proj["lam_pts"].to_numpy(), proj["lam_reb"].to_numpy(), proj["lam_ast"].to_numpy(),
                        m.CONFIG["nb_r"], proj["typ_dd"].to_numpy(), proj["typ_td"].to_numpy())
    proj = proj.assign(p_dd=dd, p_td=td)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "picks_per_night": 6,
           "note": "Players are chosen from those who played that night (lineups aren't known in advance), so this is a little generous.",
           "markets": {}}
    proj = proj.assign(bump_dd=np.where(proj["typ_dd"] >= 0.10, proj["p_dd"] / proj["typ_dd"].clip(lower=1e-9), np.nan),
                       bump_td=np.where(proj["typ_td"] >= 0.02, proj["p_td"] / proj["typ_td"].clip(lower=1e-9), np.nan))
    out["bump"] = {}   # same replay, but the 6 picks are the biggest jump over each player's usual rate
    for dest, key, pcol, ycol, scol, tcol in ((out["markets"], "dd", "p_dd", "dd", "p_dd", "typ_dd"),
                                              (out["markets"], "td", "p_td", "td", "p_td", "typ_td"),
                                              (out["bump"], "dd", "p_dd", "dd", "bump_dd", "typ_dd"),
                                              (out["bump"], "td", "p_td", "td", "bump_td", "typ_td")):
        nights, tot = [], dict(nights=0, picks=0, single_hits=0, pairs=0, pair_hits=0, trios=0, trio_hits=0, nights_with_a_hit=0, nights_all_6=0)
        for date, g in proj.groupby("date"):
            top = g.dropna(subset=[scol]).sort_values(scol, ascending=False).head(6)
            if len(top) < 6:
                continue
            h = int(top[ycol].sum())
            nights.append({"date": str(date), "hits": h, "pair_hits": comb(h, 2), "trio_hits": comb(h, 3),
                           "picks": [{"name": r["name"], "team": r["team"], "chance": round(float(r[pcol]), 3),
                                      "usual": round(float(r[tcol]), 3), "hit": int(r[ycol])} for _, r in top.iterrows()]})
            tot["nights"] += 1; tot["picks"] += 6; tot["single_hits"] += h; tot["pairs"] += 15; tot["pair_hits"] += comb(h, 2)
            tot["trios"] += 20; tot["trio_hits"] += comb(h, 3)
            tot["nights_with_a_hit"] += h > 0; tot["nights_all_6"] += h == 6
        tot["single_hit_rate"] = round(tot["single_hits"] / max(tot["picks"], 1), 4)
        tot["pair_hit_rate"] = round(tot["pair_hits"] / max(tot["pairs"], 1), 4)
        tot["trio_hit_rate"] = round(tot["trio_hits"] / max(tot["trios"], 1), 4)
        tot["avg_chance"] = round(float(np.mean([p["chance"] for n in nights for p in n["picks"]])), 4) if nights else None
        dest[key] = {"totals": tot, "nights": nights}
    import nba_pipeline as pl
    proj = proj[proj["proj_min"] >= 15]
    out["extra"] = {}   # threes, rebounds, assists: model-only main line (floor(projection)+0.5), the side the model likes
    for fam, (_, lam_col, stat_col, _, _) in pl.FAMILIES.items():
        lam = proj[lam_col].to_numpy(float)
        line = np.floor(lam) + 0.5
        p_over = pl.dist_sf(np.floor(lam), lam, m.CONFIG["nb_r"][fam])
        over = p_over >= 0.5
        actual = proj[stat_col].to_numpy(float)
        g2 = proj.assign(chance=np.where(over, p_over, 1 - p_over), pick_hit=np.where(over, actual > line, actual < line).astype(int))
        nights, tot = [], dict(nights=0, picks=0, single_hits=0)
        for date, g in g2.groupby("date"):
            top = g.sort_values("chance", ascending=False).head(6)
            if len(top) < 6:
                continue
            h = int(top["pick_hit"].sum())
            nights.append({"date": str(date), "hits": h, "pair_hits": comb(h, 2), "trio_hits": comb(h, 3)})
            tot["nights"] += 1; tot["picks"] += 6; tot["single_hits"] += h
        tot["single_hit_rate"] = round(tot["single_hits"] / max(tot["picks"], 1), 4)
        out["extra"][fam] = {"totals": tot, "nights": nights}
    (ROOT / "docs" / "data" / "top6_live.json").write_text(json.dumps(out, indent=1))
    for fam, v in out["extra"].items():
        print("extra", fam, v["totals"])
    for grp in ("markets", "bump"):
        for k, v in out[grp].items():
            print(grp, k, v["totals"])

if __name__ == "__main__":
    main()
