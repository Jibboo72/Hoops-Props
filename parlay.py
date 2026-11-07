"""How good tonight is for Josh's 6-team double-double round robin, rated 1 to 10 for each format.

The 6 legs are the page's "Best 6 tonight": the 6 most likely double-doubles, leaving out anyone whose best
price is worse than MAX_JUICE (same rule as docs/doubles.js).

Two formats, $30 a night either way:
  2-pick: all 15 pairs of the 6, $2 each.
  3-pick: all 20 trios of the 6, $1.50 each.

Each leg's chance is the page's blended chance (model + market), with the model's half shrunk by a calibration
factor fitted on this season's graded Best 6 picks (the model has run a bit hot on the players it ranks highest).
Legs are treated as independent; picks from the same game are flagged.

Prices: a round robin is placed at one book, so each format is priced at the single book that posts all 6 and
gives the most expected profit. Best-price-per-leg is shown for reference only.

The 1-10 score (see README):
  score = 5 + ROI / ROI_PER_POINT + PROFIT_WEIGHT * (chance to profit - that format's usual chance to profit)
5 is break-even. Each point is ROI_PER_POINT of ROI (so 8 is about +21%, 2 about -21%). Clamped to 1..10.
"""
from itertools import combinations
from math import comb

import numpy as np

import market

STAKE_TOTAL = 30.0
FORMATS = {2: 2.0, 3: 1.5}      # legs per parlay: stake per parlay ($30 / 15 pairs, $30 / 20 trios)
PICKS = 6
MAX_JUICE = -198                # docs/doubles.js MAX_JUICE: never a leg priced worse than this
CAL_PRIOR = 50                  # calibration starts at 1.0 with the weight of 50 picks
CAL_RANGE = (0.75, 1.0)         # never inflates the model
EST_EV = -0.07                  # an unpriced leg is assumed to pay 7% under its fair price (typical Yes-side cut)
ROI_PER_POINT = 0.07            # one point of score per 7% ROI
PROFIT_WEIGHT = 4.0             # +0.4 for every 10 points of chance to profit above the format's usual
USUAL_PROFIT = {2: 0.40, 3: 0.33}   # chance to profit on a break-even night (season replay at fair prices, see README)
TIE = 0.50                      # expected profits within 50 cents: call it a tie, 2-pick wins (less swing)


def decimal(price):
    return 1 + price / 100 if price > 0 else 1 + 100 / abs(price)


def calibration(log, top6):
    """Shrink factor for the model's chance on Best 6 picks: (hits + prior) / (expected + prior).
    Uses the season replay (top6_live.json) plus live graded nights from doubles_log.json after it."""
    hits = exp = n = 0.0
    seen = set()
    for night in ((top6 or {}).get("markets", {}).get("dd", {}).get("nights", [])):
        seen.add(night["date"])
        for p in night["picks"]:
            hits += p["hit"]; exp += p["chance"]; n += 1
    by_day = {}
    for r in log or []:
        by_day.setdefault(r["date"], []).append(r)
    for day, rows in by_day.items():
        if day in seen:
            continue
        six = sorted(rows, key=lambda r: -r["p_dd"])[:PICKS]
        if len(six) < PICKS or any(r.get("hit_dd") not in (0, 1, -1) for r in six):
            continue
        for r in six:
            if r["hit_dd"] in (0, 1):
                hits += r["hit_dd"]; exp += r["p_dd"]; n += 1
    prior = CAL_PRIOR * (exp / n if n else 0.5)
    k = float(np.clip((hits + prior) / (exp + prior), *CAL_RANGE)) if n else 1.0
    return {"k": round(k, 4), "picks": int(n), "hits": int(hits), "expected": round(exp, 2)}


def best_six(players):
    """Same 6 the Doubles page shows: highest chance first, skipping anyone whose best price is worse than MAX_JUICE."""
    ok = [p for p in players if not (p.get("odds") and isinstance(p["odds"].get("price"), (int, float))
                                     and p["odds"]["price"] < MAX_JUICE)]
    return sorted(ok, key=lambda p: -p["p_dd"])[:PICKS]


def leg_chance(p, k):
    od = p.get("odds") or {}
    pm = k * p["p_dd"] if not od else k * od["p_model"]
    if od.get("p_mkt") is None:
        return pm
    w = market.MODEL_WEIGHT["dd"]
    return w * pm + (1 - w) * od["p_mkt"]


def outcomes(probs, decs, size, stake):
    """Every hit/miss outcome of the 6 legs (2^6 = 64): chance and total payout of the round robin."""
    n = len(probs)
    combos = list(combinations(range(n), size))
    pay_c = [stake * float(np.prod([decs[i] for i in c])) for c in combos]
    rows = []
    for mask in range(1 << n):
        hit = [(mask >> i) & 1 for i in range(n)]
        pr = float(np.prod([probs[i] if hit[i] else 1 - probs[i] for i in range(n)]))
        pay = sum(pc for c, pc in zip(combos, pay_c) if all(hit[i] for i in c))
        rows.append((sum(hit), pr, pay))
    return rows


def summarize(probs, decs, size, stake):
    rows = outcomes(probs, decs, size, stake)
    total = stake * comb(len(probs), size)
    exp_pay = sum(pr * pay for _, pr, pay in rows)
    by_hits = {}
    for h, pr, pay in rows:
        b = by_hits.setdefault(h, [pay, pay])
        b[0], b[1] = min(b[0], pay), max(b[1], pay)
    always = next((h for h in sorted(by_hits) if by_hits[h][0] >= total), None)
    can = next((h for h in sorted(by_hits) if by_hits[h][1] > total), None)
    return {"bets": comb(len(probs), size), "stake_each": stake, "total": total,
            "exp_profit": round(exp_pay - total, 2), "roi": round(exp_pay / total - 1, 4),
            "p_profit": round(sum(pr for _, pr, pay in rows if pay > total), 4),
            "p_lose_all": round(sum(pr for _, pr, pay in rows if pay == 0), 4),
            "breakeven_hits": always, "can_profit_at": can,
            "payout_by_hits": {str(h): [round(a, 2), round(b, 2)] for h, (a, b) in sorted(by_hits.items())}}


def score(stats, size):
    s = 5 + stats["roi"] / ROI_PER_POINT + PROFIT_WEIGHT * (stats["p_profit"] - USUAL_PROFIT[size])
    return round(float(np.clip(s, 1, 10)), 1)


def build(players, games, log=None, top6=None):
    """The parlay block for doubles.json. None when there aren't 6 players tonight."""
    six = best_six(players)
    if len(six) < PICKS:
        return None
    cal = calibration(log, top6)
    k = cal["k"]
    probs = [leg_chance(p, k) for p in six]
    priced = [bool((p.get("odds") or {}).get("prices")) for p in six]
    books = sorted({b for p in six for b in ((p.get("odds") or {}).get("prices") or {})})
    full = [b for b in books if all(b in ((p.get("odds") or {}).get("prices") or {}) for p in six)]

    def est(q):   # an unpriced leg: fair price less the usual cut
        return (1 + EST_EV) / q
    best_decs = [decimal(p["odds"]["price"]) if pr else est(q) for p, pr, q in zip(six, priced, probs)]

    fmts = {}
    for size, stake in FORMATS.items():
        ref = summarize(probs, best_decs, size, stake)
        pick, pick_stats = None, None
        for b in full:
            st = summarize(probs, [decimal(p["odds"]["prices"][b]) for p in six], size, stake)
            if pick_stats is None or st["exp_profit"] > pick_stats["exp_profit"]:
                pick, pick_stats = b, st
        stats = pick_stats or ref        # no single book has all 6: rate at the best price per leg, and say so
        f = {"name": f"{size}-pick", "book": pick, **stats, "score": score(stats, size),
             "best_price": {"exp_profit": ref["exp_profit"], "roi": ref["roi"], "p_profit": ref["p_profit"]}}
        f["rating"] = int(min(10, max(1, np.floor(f["score"] + 0.5))))
        fmts[str(size)] = f

    two, three = fmts["2"], fmts["3"]
    better = "3" if three["exp_profit"] > two["exp_profit"] + TIE else "2"

    by_game = {}
    for p in six:
        by_game.setdefault(p["game_id"], []).append(p["name"])
    names = {g["id"]: f"{g['away']} at {g['home']}" for g in games}
    same = [{"game": names.get(gid, gid), "players": ns} for gid, ns in by_game.items() if len(ns) > 1]

    notes = []
    n_priced = sum(priced)
    if n_priced < PICKS:
        notes.append(f"Only {n_priced} of the 6 have a price posted; the rest use an estimated price.")
    elif not full:
        notes.append("No single book prices all 6; rated at the best price for each leg.")
    if same:
        notes.append("Same-game picks are treated as independent: "
                     + "; ".join(f"{', '.join(s['players'])} ({s['game']})" for s in same) + ".")
    return {"picks": [{"id": p["id"], "name": p["name"], "team": p["team"], "game_id": p["game_id"],
                       "p_model": round(p["p_dd"], 4), "p": round(q, 4),
                       "price": (p.get("odds") or {}).get("price"), "book": (p.get("odds") or {}).get("book"),
                       "priced": pr} for p, q, pr in zip(six, probs, priced)],
            "calibration": cal, "priced_legs": n_priced, "books_with_all_6": full,
            "formats": fmts, "better": better, "same_game": same, "notes": notes,
            "rules": {"stake_total": STAKE_TOTAL, "max_juice": MAX_JUICE, "roi_per_point": ROI_PER_POINT,
                      "profit_weight": PROFIT_WEIGHT, "usual_profit": {str(k_): v for k_, v in USUAL_PROFIT.items()},
                      "tie": TIE, "est_ev_unpriced": EST_EV}}
