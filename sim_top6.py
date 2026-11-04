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
    for key, pcol, ycol in (("dd", "p_dd", "dd"), ("td", "p_td", "td")):
        nights, tot = [], dict(nights=0, picks=0, single_hits=0, pairs=0, pair_hits=0, nights_with_a_hit=0, nights_all_6=0)
        for date, g in proj.groupby("date"):
            top = g.sort_values(pcol, ascending=False).head(6)
            if len(top) < 6:
                continue
            h = int(top[ycol].sum())
            nights.append({"date": str(date), "hits": h, "pair_hits": comb(h, 2),
                           "picks": [{"name": r["name"], "team": r["team"], "chance": round(float(r[pcol]), 3), "hit": int(r[ycol])}
                                     for _, r in top.iterrows()]})
            tot["nights"] += 1; tot["picks"] += 6; tot["single_hits"] += h; tot["pairs"] += 15; tot["pair_hits"] += comb(h, 2)
            tot["nights_with_a_hit"] += h > 0; tot["nights_all_6"] += h == 6
        tot["single_hit_rate"] = round(tot["single_hits"] / max(tot["picks"], 1), 4)
        tot["pair_hit_rate"] = round(tot["pair_hits"] / max(tot["pairs"], 1), 4)
        tot["avg_chance"] = round(float(np.mean([p["chance"] for n in nights for p in n["picks"]])), 4) if nights else None
        out["markets"][key] = {"totals": tot, "nights": nights}
    (ROOT / "docs" / "data" / "top6_live.json").write_text(json.dumps(out, indent=1))
    for k, v in out["markets"].items():
        print(k, v["totals"])

if __name__ == "__main__":
    main()
