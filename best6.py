"""Nightly Best 6 for every market (threes, rebounds, assists; double-doubles come from doubles.json).

Each night, for each market, every player's main line is the one closest to a coin flip, and the pick is the side
the model likes more. The 6 most likely picks make the night's Best 6. Plays priced worse than MAX_JUICE are skipped,
and players under MIN_MIN projected minutes are left out. The six are saved before the first tip (and refreshed until
then), graded from the boxscores, and rolled up into best6_summary.json, which the strip at the top of every page shows.
No odds are needed; prices only filter out expensive plays.
"""
import json
from datetime import datetime, timezone

import nba_pipeline as m
import sim
from market import parse_key

OUT = m.ROOT / "docs" / "data" / "best6.json"           # tonight's six per market
LOG = m.ROOT / "docs" / "data" / "best6_log.json"       # every night's six, with results
SUMMARY = m.ROOT / "docs" / "data" / "best6_summary.json"
TOP6 = m.ROOT / "docs" / "data" / "top6_live.json"      # replay of Oct 20 onward (sim_top6.py)
FAMS = ("thr", "reb", "ast")
LABELS = {"dd": "Double-doubles", "thr": "3-pointers", "reb": "Rebounds", "ast": "Assists"}
MAX_JUICE = -198
MIN_MIN = 15


def pick_for(p, fam):
    """The side of this player's main line the model likes best, or None."""
    lines = {}
    for k, v in p.items():
        if isinstance(v, dict) and "p" in v:
            f, side, pt = parse_key(k)
            if f == fam:
                lines.setdefault(pt, {})[side] = (k, v)
    if not lines:
        return None
    def p_over(sides):
        return sides["o"][1]["p"] if "o" in sides else 1 - sides["u"][1]["p"]
    pt = min(lines, key=lambda x: abs(p_over(lines[x]) - 0.5))
    opts = [(v["p"], k, v) for k, v in lines[pt].values()
            if not (v.get("price") is not None and v["price"] < MAX_JUICE)]
    if not opts:
        return None
    chance, key, cell = max(opts, key=lambda o: o[0])
    return {"key": key, "chance": round(chance, 4), "price": cell.get("price"), "book": cell.get("book")}


def build(board, now, skip_started):
    starts = {g["id"]: g.get("start") for g in board.get("games", [])}
    out = {}
    for fam in FAMS:
        cands = []
        for p in board.get("players", []):
            if p.get("min", 0) < MIN_MIN or (skip_started and sim.started(starts, p["game_id"], now)):
                continue
            pk = pick_for(p, fam)
            if pk:
                cands.append({"player_id": p["id"], "name": p["name"], "team": p["team"], "opp": p["opp"],
                              "game_id": p["game_id"], "status": p.get("status", ""), **pk})
        cands.sort(key=lambda c: -c["chance"])
        out[fam] = [{**c, "rank": i + 1} for i, c in enumerate(cands[:6])]
    return out


def grade(rows):
    cache = {}
    for r in rows:
        if r.get("hit") is not None:
            continue
        if r["game_id"] not in cache:
            cache[r["game_id"]] = sim.boxscore_stats(r["game_id"])
        final, stats = cache[r["game_id"]]
        if final:
            r["hit"] = (1 if sim.hit(stats[r["player_id"]], r["key"]) else 0) if r["player_id"] in stats else -1


def nights_of(rows_by_date, hitkey, order):
    """Nights whose six are all graded: {date: (hits, graded)}."""
    out = {}
    for date, rs in rows_by_date.items():
        six = sorted(rs, key=order)[:6]
        if len(six) == 6 and all(r.get(hitkey) is not None for r in six):
            out[date] = (sum(r[hitkey] == 1 for r in six), sum(r[hitkey] != -1 for r in six))
    return out


def summary(log):
    top = sim.load(TOP6, {})
    dd_log = sim.load(sim.DOUBLES_LOG, [])
    res = {}
    for mk in ("dd",) + FAMS:
        replay = ((top.get("markets", {}).get("dd") if mk == "dd" else top.get("extra", {}).get(mk)) or {}).get("nights", [])
        nights = {n["date"]: (n["hits"], 6) for n in replay}
        by = {}
        if mk == "dd":
            for r in dd_log:
                by.setdefault(r["date"], []).append(r)
            live = nights_of(by, "hit_dd", lambda r: -r["p_dd"])
        else:
            for r in log:
                if r["market"] == mk:
                    by.setdefault(r["date"], []).append(r)
            live = nights_of(by, "hit", lambda r: r["rank"])
        for d, v in live.items():
            nights.setdefault(d, v)
        hits = sum(h for h, g in nights.values()); picks = sum(g for h, g in nights.values())
        last = max(nights) if nights else None
        res[mk] = {"label": LABELS[mk], "nights": len(nights), "hits": hits, "picks": picks,
                   "rate": round(hits / picks, 4) if picks else None,
                   "last": {"date": last, "hits": nights[last][0], "picks": nights[last][1]} if last else None}
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "markets": res}


def track(board):
    now = datetime.now(timezone.utc)
    log = sim.load(LOG, [])
    grade(log)
    date = board.get("date")
    tonight = {}
    if board.get("games") and date:
        starts = [g.get("start") for g in board["games"]]
        slate_started = any(sim.started({"x": s}, "x", now) for s in starts)
        if not slate_started:   # until the first tip the six keep updating (injury news, new prices)
            log = [r for r in log if r["date"] != date]
        have = {r["market"] for r in log if r["date"] == date}
        for fam, picks in build(board, now, slate_started).items():
            if fam in have:
                continue
            for p in picks:
                log.append({"date": date, "market": fam, **p, "logged": now.isoformat(timespec="minutes"), "hit": None})
        tonight = {fam: sorted([r for r in log if r["date"] == date and r["market"] == fam], key=lambda r: r["rank"]) for fam in FAMS}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(log, separators=(",", ":")))
    OUT.write_text(json.dumps({"date": date, "generated": now.isoformat(timespec="minutes"), "markets": tonight}, separators=(",", ":")))
    s = summary(log)
    SUMMARY.write_text(json.dumps(s, separators=(",", ":")))
    print("Best 6: " + ", ".join(f"{v['label']} {v['hits']}/{v['picks']}" for v in s["markets"].values()))
