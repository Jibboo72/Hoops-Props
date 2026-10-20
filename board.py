#!/usr/bin/env python3
"""Tonight's NBA board: model odds for 3-pointers made and rebounds vs. sportsbook prices.

Usage: python board.py [YYYY-MM-DD]     (default: today, Eastern time)
Needs ODDS_API_KEY in the environment for prices; without it the board shows fair odds only.
"""
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

import market
import nba_data as d
import nba_pipeline as m
from nba_model import position_map

TUNED = m.ROOT / "data" / "tuned_config.json"
if TUNED.exists():  # settings chosen by tune.py
    m.CONFIG.update(json.loads(TUNED.read_text()))
ALIASES_FILE = m.ROOT / "data" / "name_aliases.json"   # {"nic claxton": "nicolas claxton"} for names books spell differently

SEASON, PRIOR = "20262027", "20252026"
OUT = m.ROOT / "docs" / "data" / "board.json"
ODDS_KEY = os.environ.get("ODDS_API_KEY", "").strip()
ODDS_BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"
MARKETS = {"thr": "player_threes", "reb": "player_rebounds"}   # two prop markets per game = 2 odds credits per game
BOOKS = "draftkings,fanduel,betmgm,hardrockbet,espnbet,betrivers,betparx"
# Odds cost: 2 credits per game for props + 2 for game lines. When the month's credits run low,
# skip game lines so prop prices last until the plan resets.
LINES_MIN_CREDITS = 150
ET = d.ET
NO_ODDS_THR = (1.5, 2.5)
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_FIX = {"GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}


def aliases():
    try:
        return json.loads(ALIASES_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def norm(s, alias=None):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv", "v"))
    return (alias or {}).get(s, s)


def decimal(price):
    return 1 + price / 100 if price > 0 else 1 + 100 / abs(price)


def fair_american(p):
    p = min(max(p, 0.01), 0.99)
    return -round(100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def name_index(frames, alias):
    """normalised name -> latest known {player_id, name, team, pos} from every game we have."""
    allrows = pd.concat([f for f in frames if f is not None and len(f)], ignore_index=True)
    last = allrows.sort_values(["date", "game_id"]).groupby("player_id").tail(1)
    pos = position_map(allrows)
    return {norm(r["name"], alias): {"player_id": int(r["player_id"]), "name": r["name"], "team": r["team"],
                                     "pos": pos.get(int(r["player_id"]), "")} for _, r in last.iterrows()}


def espn_rosters(alias):
    """Best effort: {normalised name: team} for players whose last team is not playing tonight (offseason moves)."""
    out = {}
    try:
        teams = requests.get(f"{ESPN}/teams", timeout=20).json()["sports"][0]["leagues"][0]["teams"]
        for t in teams:
            t = t["team"]
            ab = ESPN_FIX.get(t["abbreviation"], t["abbreviation"])
            r = requests.get(f"{ESPN}/teams/{t['id']}/roster", timeout=20).json()
            for a in r.get("athletes", []):
                out[norm(a.get("fullName") or a.get("displayName", ""), alias)] = ab
    except Exception:
        return {}
    return out


def fetch_odds(date, games):
    """Every book's price per player, per line, per side. Returns (odds, events, status, credits left).

    odds[(fam, name, event_id)] = {line: {"o": {book: price}, "u": {book: price}}}
    events[event_id] = {"home": "BOS", "away": "NYK", "game_id": "0022600001"}
    """
    if not ODDS_KEY:
        return {}, {}, "No odds key set. Showing fair odds only.", None
    try:
        events = requests.get(f"{ODDS_BASE}/events", params={"apiKey": ODDS_KEY}, timeout=30).json()
        todays = [e for e in events if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
                  .astimezone(ET).strftime("%Y-%m-%d") == date]
        odds, evs, left = {}, {}, None
        alias = aliases()
        for e in todays:
            home, away = market.team_abbrev(e["home_team"]), market.team_abbrev(e["away_team"])
            game = next((g for g in games if g["home"] == home and g["away"] == away), None)
            if not game:
                continue
            evs[e["id"]] = {"home": home, "away": away, "game_id": game["id"]}
            r = requests.get(f"{ODDS_BASE}/events/{e['id']}/odds", timeout=30, params={
                "apiKey": ODDS_KEY, "bookmakers": BOOKS, "markets": ",".join(MARKETS.values()), "oddsFormat": "american"})
            left = r.headers.get("x-requests-remaining", left)
            for book in r.json().get("bookmakers", []):
                for mk in book.get("markets", []):
                    fam = next((k for k, v in MARKETS.items() if v == mk["key"]), None)
                    for o in mk.get("outcomes", []) if fam else []:
                        pt = o.get("point")
                        if pt is None or abs(pt * 2 % 2 - 1) > 1e-9:   # half-point lines only (no pushes)
                            continue
                        side = "o" if o.get("name") == "Over" else "u" if o.get("name") == "Under" else None
                        if side is None:
                            continue
                        key = (fam, norm(o.get("description"), alias), e["id"])
                        odds.setdefault(key, {}).setdefault(float(pt), {"o": {}, "u": {}})[side][
                            book.get("title", book.get("key"))] = o["price"]
        n = len(evs)
        return odds, evs, f"Odds from {n} game{'' if n == 1 else 's'}. {left} odds credits left this month.", left
    except Exception as exc:  # the board still works without odds
        return {}, {}, f"Odds pull failed ({exc.__class__.__name__}). Showing fair odds only.", None


def data_candidates(frames, games, idx):
    """No odds: players who really play for each team (3+ of its last 10 games, and still on it)."""
    allrows = pd.concat([f for f in frames if f is not None and len(f)], ignore_index=True)
    cands = []
    for g in games:
        for team, opp, home in ((g["away"], g["home"], 0), (g["home"], g["away"], 1)):
            tg = allrows[allrows["team"] == team][["game_id", "date"]].drop_duplicates().sort_values("date").tail(10)
            recent = allrows[allrows["game_id"].isin(tg["game_id"]) & (allrows["team"] == team)]
            counts = recent.groupby("player_id").size()
            for pid in counts[counts >= 3].index:
                info = next((v for v in idx.values() if v["player_id"] == pid), None)
                if info and info["team"] == team:
                    cands.append({"player_id": int(pid), "name": info["name"], "team": team, "opp": opp, "home": home,
                                  "game_id": g["id"], "pos": info["pos"], "event_id": None})
    return cands


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ET).strftime("%Y-%m-%d")
    cfg = m.CONFIG
    sched = d.fetch_schedule(date)
    games = [{"id": g["id"], "start": g["start"], "away": g["away"], "home": g["home"]}
             for g in sched if g["date"] == date and g["type"] in d.BOARD_TYPES]
    out = {"date": date, "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "games": games, "players": [], "odds_status": ""}
    if not games:
        out["odds_status"] = "No NBA games on this date."
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, indent=1))
        print(out["odds_status"])
        return

    alias = aliases()
    played = d.fetch_season(SEASON)
    played = played[played["date"] < date] if len(played) else played
    prior = d.fetch_season(PRIOR)
    idx = name_index([prior, played], alias)

    odds, events, out["odds_status"], left = fetch_odds(date, games)
    low = left is not None and str(left).isdigit() and int(left) < LINES_MIN_CREDITS
    try:  # the market's game total and spread, from the books
        lines = market.game_lines(ODDS_KEY, ODDS_BASE, BOOKS, date, ET) if ODDS_KEY and not low else {}
    except Exception:
        lines = {}
    out["odds_status"] += " Game lines skipped to save credits." if low else f" Game lines for {len(lines) // 2} games."
    for g in games:
        gl = lines.get(g["home"])
        if gl:
            g["total"], g["spread_home"] = gl["total"], gl["spread"]

    # ---- who plays tonight ----
    cands, unmatched, rosters = [], [], None
    if odds:
        seen = set()
        for (fam, name, ev_id) in odds:
            if (name, ev_id) in seen:
                continue
            seen.add((name, ev_id))
            ev, info = events[ev_id], idx.get(name)
            team = info["team"] if info else None
            if info and team not in (ev["home"], ev["away"]):
                if rosters is None:
                    rosters = espn_rosters(alias)
                team = rosters.get(name)
            if not info or team not in (ev["home"], ev["away"]):
                unmatched.append(name)
                continue
            cands.append({"player_id": info["player_id"], "name": info["name"], "team": team,
                          "opp": ev["away"] if team == ev["home"] else ev["home"], "home": int(team == ev["home"]),
                          "game_id": ev["game_id"], "pos": info["pos"], "event_id": ev_id})
    else:
        cands = data_candidates([prior, played], games, idx)
    out["unmatched"] = sorted(set(unmatched))[:60]

    tonight = pd.DataFrame([{
        "season": SEASON, "player_id": c["player_id"], "name": c["name"], "pos": c["pos"], "game_id": c["game_id"],
        "date": date, "team": c["team"], "opp": c["opp"], "home": c["home"], "started": 0, "min": 0.0, "fg3m": 0.0,
        "fg3a": 0.0, "reb": 0.0, "oreb": 0.0, "fga": 0.0, "fta": 0.0, "tov": 0.0, "pts": 0.0, "ast": 0.0}
        for c in {c["player_id"]: c for c in cands}.values()], columns=d.COLS)
    if tonight.empty:
        out["odds_status"] += " No players matched the model's history yet."
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, indent=1))
        print(out["odds_status"])
        return
    proj = m.build_projections(pd.concat([played, tonight], ignore_index=True), prior, cfg)
    proj = proj[proj["date"] == date]
    event_of = {c["player_id"]: c["event_id"] for c in cands}
    exp_env, bd = cfg["env_exponent"], cfg["blowout_drop"]
    nb = cfg["nb_r"]

    for _, r in proj.iterrows():
        gl = lines.get(r["team"], {})
        ratio = market.env_ratio(gl.get("total"), r["pts_pred"])
        bm = 1.0
        if bd > 0 and gl and r["proj_min"] >= 26:   # lopsided games cost starters minutes
            bm = 1 - bd * float(np.clip((abs(gl["spread"]) - 8) / 10, 0, 1))
        lam = {"thr": float(r["lam_thr"]) * ratio ** exp_env["thr"] * bm,
               "reb": float(r["lam_reb"]) * ratio ** exp_env["reb"] * bm}
        row = {"id": int(r["player_id"]), "name": r["name"], "team": r["team"], "opp": r["opp"], "pos": r["pg"],
               "game_id": str(r["game_id"]), "min": round(float(r["proj_min"]), 1),
               "exp_thr": round(lam["thr"], 2), "exp_reb": round(lam["reb"], 2), "env": round(ratio, 3)}
        for fam in ("thr", "reb"):
            posted = odds.get((fam, norm(r["name"], alias), event_of.get(int(r["player_id"]))), {}) if odds else {}
            if not odds:  # fair odds only: one book-like line
                pts = NO_ODDS_THR if fam == "thr" else (math.floor(lam[fam]) + 0.5,)
                posted = {float(pt): {"o": {}, "u": {}} for pt in pts}
            for pt, sides in posted.items():
                p_over = float(m.dist_sf(int(math.floor(pt)), lam[fam], nb[fam]))
                for side, p in (("o", p_over), ("u", 1 - p_over)):
                    other = "u" if side == "o" else "o"
                    if odds and not sides[side]:
                        continue  # nobody is offering this side
                    cell = {"p_model": round(p, 4), "line": pt}
                    if sides[side]:
                        cell.update(prices=sides[side], other=sides[other])
                    row[market.make_key(fam, side, pt)] = cell
        out["players"].append(row)
    market.market_view(out["players"])

    keys = set()
    for row in out["players"]:  # final chance = model blended with the market, then EV at the best price
        for kind in [k for k, v in row.items() if isinstance(v, dict) and "p_model" in v]:
            keys.add(kind)
            mk, fam = row[kind], market.base(kind)
            w = market.MODEL_WEIGHT[fam]
            p = mk["p_model"] if mk.get("p_mkt") is None else w * mk["p_model"] + (1 - w) * mk["p_mkt"]
            mk.update(p=round(p, 4), fair=fair_american(p))
            if mk.get("prices"):
                book = max(mk["prices"], key=mk["prices"].get)
                mk.update(price=mk["prices"][book], book=book, ev=round(p * decimal(mk["prices"][book]) - 1, 4))
                mk["likely"] = bool(p >= market.LIKELY_MIN[fam] and mk["ev"] >= market.PRICE_CHECK
                                    and market.LIKELY_MIN_PRICE <= mk["price"] <= market.LIKELY_MAX_PRICE)
            mk.pop("other", None)
    out["markets"] = sorted(keys, key=lambda k: (market.parse_key(k)[0], market.parse_key(k)[2], market.parse_key(k)[1]))
    out["max_price"] = market.MAX_PRICE
    out["likely_rules"] = {"min": market.LIKELY_MIN, "max_price": market.LIKELY_MAX_PRICE,
                           "min_price": market.LIKELY_MIN_PRICE, "price_check": market.PRICE_CHECK}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(f"{date}: {len(games)} games, {len(out['players'])} players. {out['odds_status']}"
          + (f" {len(out['unmatched'])} priced names not matched." if out["unmatched"] else ""))


if __name__ == "__main__":
    main()
