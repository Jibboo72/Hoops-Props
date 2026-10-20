#!/usr/bin/env python3
"""End-to-end self-test on a synthetic league with KNOWN true rates. No internet needed.

It builds three fake seasons of boxscores in the same JSON shape as ESPN's feeds, serves them through the
real parser and cache code, then runs the backtest, tonight's board (with a fake odds feed) and the sim.
Because the true rates are known, it can check that the model recovers them instead of just "running".

  python selftest.py            full run (about a minute)
  python selftest.py --quick    smaller league, for CI
"""
import json
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np

import nba_data

QUICK = "--quick" in sys.argv
STATIONARY = "--stationary" in sys.argv   # no drift in anyone's true rates: recency should then HURT
RNG = np.random.default_rng(20261020)
GAMES = 300 if QUICK else 1230

# ---------------------------------------------------------------- synthetic league
ROLES = [("G", 31, 4), ("G", 31, 4), ("F", 31, 4), ("F", 31, 4), ("C", 31, 4),
         ("G", 22, 5), ("F", 22, 5), ("C", 22, 5), ("G", 12, 5), ("F", 12, 5), ("C", 12, 5), ("G", 3, 3), ("F", 3, 3)]
A_BASE = {"G": 0.19, "F": 0.14, "C": 0.05}
SHARE = {"G": 0.065, "F": 0.10, "C": 0.155}
Q_BASE = {"G": 0.115, "F": 0.05, "C": 0.05}   # assists per minute


def make_league():
    teams = {}
    pid = 200000
    for t in nba_data.TEAMS:
        roster = []
        for i, (pos, mu, sd) in enumerate(ROLES):
            roster.append({"id": pid, "name": f"{t} Player{i}", "pos": pos, "mu": mu, "mu_cur": float(mu), "sd": sd,
                           "za": 0.0, "zs": 0.0, "zq": 0.0, "starter": i < 5,
                           "q": float(np.clip(Q_BASE[pos] * np.exp(RNG.normal(0, 0.25)), 0.01, 0.3)),
                           "a": float(np.clip(A_BASE[pos] + RNG.normal(0, 0.04), 0.01, 0.4)),
                           "pct": float(np.clip(RNG.normal(0.355, 0.03), 0.25, 0.45)),
                           "share": SHARE[pos] * float(np.exp(RNG.normal(0, 0.1)))})
            pid += 1
        teams[t] = {"roster": roster, "pace": RNG.normal(0, 0.03), "reb": RNG.normal(0, 0.03),
                    "o3a": RNG.normal(0, 0.04), "o3p": RNG.normal(0, 0.02)}
    return teams


def drift(p):
    """Real players change: shot volume and rebounding wander, and roles shift now and then."""
    if STATIONARY:
        return
    p["za"] = 0.97 * p["za"] + float(RNG.normal(0, 0.06))
    p["zs"] = 0.97 * p["zs"] + float(RNG.normal(0, 0.035))
    p["zq"] = 0.97 * p["zq"] + float(RNG.normal(0, 0.05))
    if RNG.random() < 0.02:
        p["mu_cur"] = float(np.clip(p["mu_cur"] * RNG.uniform(0.7, 1.3), 4, 38))
    p["mu_cur"] += 0.04 * (p["mu"] - p["mu_cur"])


def mins_str(m):
    return f"PT{int(m):02d}M{(m - int(m)) * 60:05.2f}S"


def play_game(teams, home, away, gid, day, truth):
    """One synthetic game -> CDN-shaped boxscore JSON. truth[(gid, pid)] = (true lam threes, true lam reb)."""
    H, A = teams[home], teams[away]
    pace = 100.0 * (1 + H["pace"] + A["pace"])
    gtot = 88.0 * (1 + H["reb"] + A["reb"]) * (pace / 100.0) ** 0.5 * float(np.exp(RNG.normal(0, 0.05)))
    ot = RNG.random() < 0.06
    side_json, side_rows = {}, {}
    for me, opp, name in ((H, A, home), (A, H, away)):
        mins = []
        for p in me["roster"]:
            m = 0.0 if RNG.random() < 0.04 else float(np.clip(RNG.normal(p["mu_cur"], p["sd"]), 0, 44))
            mins.append(m)
        tot = sum(mins)
        mins = [m * (265.0 if ot else 240.0) / tot for m in mins] if tot > 0 else mins
        mins = [min(m, 46.0) for m in mins]
        players = []
        for p, m in zip(me["roster"], mins):
            if m <= 0:
                players.append({"personId": p["id"], "name": p["name"], "position": "", "starter": "0",
                                "status": "INACTIVE", "statistics": {}})
                continue
            noise = float(np.exp(RNG.normal(0, 0.15)))
            a_eff, share_eff = p["a"] * float(np.exp(p["za"])), p["share"] * float(np.exp(p["zs"]))
            lam3a = a_eff * m * (pace / 100.0) * (1 + opp["o3a"]) * noise
            fg3a = int(RNG.poisson(lam3a))
            pct = p["pct"] * (1 + opp["o3p"])
            fg3m = int(RNG.binomial(fg3a, min(pct, 0.9)))
            lam_reb = share_eff * gtot * m / (265.0 / 5 if ot else 48.0)
            reb = int(RNG.poisson(lam_reb))
            fga = int(RNG.poisson(pace * 0.88 * m / 240.0 * 1.0))
            fta = int(RNG.poisson(0.25 * fga))
            tov = int(RNG.poisson(0.14 * pace * m / 240.0))
            lam_ast = p["q"] * float(np.exp(p["zq"])) * m * (pace / 100.0)
            ast = int(RNG.poisson(lam_ast * float(np.exp(RNG.normal(0, 0.12)))))
            truth[(gid, p["id"])] = (a_eff * m * (pace / 100.0) * (1 + opp["o3a"]) * p["pct"] * (1 + opp["o3p"]), lam_reb, lam_ast)
            drift(p)
            players.append({"personId": p["id"], "name": p["name"], "position": p["pos"] if p["starter"] else "",
                            "starter": "1" if p["starter"] else "0", "status": "ACTIVE",
                            "statistics": {"minutes": mins_str(m), "threePointersMade": fg3m, "threePointersAttempted": fg3a,
                                           "reboundsTotal": reb, "reboundsOffensive": int(reb * 0.27),
                                           "fieldGoalsAttempted": fga, "freeThrowsAttempted": fta, "turnovers": tov,
                                           "points": int(2.1 * fga * 0.5 + fg3m), "assists": ast}})
        side_json[name] = {"teamTricode": name, "players": players}
    return {"meta": {"code": 200}, "game": {
        "gameId": gid, "gameStatus": 3, "gameStatusText": "Final", "gameEt": f"{day}T19:30:00-04:00",
        "homeTeam": side_json[home], "awayTeam": side_json[away]}}


def make_season(teams, start, yy, truth, final_through=None, n_games=None):
    """Returns (box dict, schedule game list). Games after `final_through` stay unplayed (status 1)."""
    boxes, sched, n, day = {}, [], 0, start
    n_games = n_games or GAMES
    while n < n_games:
        k = int(RNG.integers(5, 11))
        order = list(RNG.permutation(nba_data.TEAMS))[:2 * k]
        for i in range(k):
            n += 1
            if n > n_games:
                break
            home, away = order[2 * i], order[2 * i + 1]
            gid = f"002{yy}{n:05d}"
            played = final_through is None or day <= final_through
            sched.append({"gameId": gid, "gameStatus": 3 if played else 1, "gameDateEst": f"{day}T00:00:00Z",
                          "gameDateTimeUTC": f"{day}T23:30:00Z",
                          "awayTeam": {"teamTricode": away}, "homeTeam": {"teamTricode": home}})
            if played:
                boxes[gid] = play_game(teams, home, away, gid, day, truth)
        day += timedelta(days=1)
    return boxes, sched


ESPN_OUT = {"GSW": "GS", "NYK": "NY", "NOP": "NO", "SAS": "SA", "UTA": "UTAH", "WAS": "WSH"}  # ESPN's short codes
KEYS = ["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
        "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "freeThrowsMade-freeThrowsAttempted",
        "rebounds", "assists", "turnovers", "offensiveRebounds"]


def espn_event(gid, home, away, day, final):
    ab = lambda t: ESPN_OUT.get(t, t)  # noqa: E731
    return {"id": gid, "date": f"{day}T23:30Z", "season": {"year": 2035, "type": 2},
            "status": {"type": {"completed": final, "state": "post" if final else "pre"}},
            "competitions": [{"competitors": [{"homeAway": "home", "team": {"abbreviation": ab(home)}},
                                              {"homeAway": "away", "team": {"abbreviation": ab(away)}}]}]}


def espn_summary(box):
    """Turns the generator's box (NBA-shaped) into the shape ESPN's summary endpoint returns."""
    g = box["game"]
    day = g["gameEt"][:10]
    ab = lambda t: ESPN_OUT.get(t, t)  # noqa: E731
    blocks = []
    for side in ("homeTeam", "awayTeam"):
        t = g[side]
        aths = []
        for p in t["players"]:
            st = p.get("statistics") or {}
            ath = {"id": str(p["personId"]), "displayName": p["name"], "position": {"abbreviation": p.get("position") or "F"}}
            if p.get("status") == "INACTIVE" or not st:
                aths.append({"athlete": ath, "starter": False, "didNotPlay": True, "stats": []})
                continue
            mins = str(int(round(nba_data.minutes_of(st["minutes"]))))
            aths.append({"athlete": ath, "starter": p.get("starter") == "1", "didNotPlay": False, "stats": [
                mins, str(st["points"]), f"0-{st['fieldGoalsAttempted']}",
                f"{st['threePointersMade']}-{st['threePointersAttempted']}", f"0-{st['freeThrowsAttempted']}",
                str(st["reboundsTotal"]), str(st["assists"]), str(st["turnovers"]), str(st["reboundsOffensive"])]})
        blocks.append({"team": {"abbreviation": ab(t["teamTricode"])}, "statistics": [{"keys": KEYS, "athletes": aths}]})
    comp = espn_event(g["gameId"], g["homeTeam"]["teamTricode"], g["awayTeam"]["teamTricode"], day, True)["competitions"][0]
    comp["date"], comp["status"] = f"{day}T23:30Z", {"type": {"completed": True, "state": "post"}}
    return {"header": {"id": g["gameId"], "competitions": [comp]}, "boxscore": {"players": blocks}}


class FakeCDN:
    """Stands in for requests: serves ESPN-shaped scoreboards and summaries from memory."""
    def __init__(self):
        self.boxes, self.sched, self.calls = {}, [], 0
        self._idx, self._n = {}, -1

    def by_day(self):
        if self._n != len(self.boxes):
            self._idx, self._n = {}, len(self.boxes)
            for gid, box in self.boxes.items():
                g = box["game"]
                self._idx.setdefault(g["gameEt"][:10], {})[gid] = espn_event(
                    gid, g["homeTeam"]["teamTricode"], g["awayTeam"]["teamTricode"], g["gameEt"][:10], True)
        return self._idx

    def get_json(self, url, params=None, tries=4, quiet=False):
        self.calls += 1
        if url == nba_data.SCOREBOARD_URL:
            d = params["dates"]
            iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            events = dict(self.by_day().get(iso, {}))
            for g in self.sched:
                if g["gameDateTimeUTC"][:10] == iso and g["gameId"] not in events:
                    events[g["gameId"]] = espn_event(g["gameId"], g["homeTeam"]["teamTricode"],
                                                     g["awayTeam"]["teamTricode"], iso, g["gameStatus"] == 3)
            return {"events": list(events.values())}
        gid = url.rsplit("event=", 1)[-1]
        box = self.boxes.get(gid)
        return espn_summary(box) if box else None


# ---------------------------------------------------------------- fake odds feed (The Odds API shape)
def american(p):
    p = min(max(p, 0.02), 0.97)
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


class Resp:
    def __init__(self, data, headers=None):
        self._d, self.headers, self.status_code = data, headers or {"x-requests-remaining": "480"}, 200

    def json(self):
        return self._d


class FakeOdds:
    """Books that know each player's TRUE rate (so the market is sharper than any model), post the usual
    half-point line, and charge about 4.5% vig. Three books with a little disagreement between them."""
    BOOKS = ("DraftKings", "FanDuel", "BetMGM")

    def __init__(self, teams, games, day, total_mean):
        import market
        self.teams, self.games, self.day, self.total_mean, self.mk = teams, games, day, total_mean, market
        self.names = {g["gameId"]: (f"{g['homeTeam']['teamTricode']} {market.NICKNAMES[g['homeTeam']['teamTricode']].title()}",
                                    f"{g['awayTeam']['teamTricode']} {market.NICKNAMES[g['awayTeam']['teamTricode']].title()}")
                      for g in games}

    def event(self, g):
        h, a = self.names[g["gameId"]]
        return {"id": f"ev{g['gameId']}", "commence_time": f"{self.day}T23:30:00Z", "home_team": h, "away_team": a}

    def props(self, g):
        from scipy import stats
        out = {b: {"key": b.lower(), "title": b, "markets": []} for b in self.BOOKS}
        for fam, key in (("thr", "player_threes"), ("reb", "player_rebounds"), ("ast", "player_assists")):
            mk = {b: {"key": key, "outcomes": []} for b in self.BOOKS}
            for tri in (g["homeTeam"]["teamTricode"], g["awayTeam"]["teamTricode"]):
                for p in self.teams[tri]["roster"]:
                    if p["mu_cur"] < 14:
                        continue
                    lam = (p["a"] * float(np.exp(p["za"])) * p["mu_cur"] * p["pct"] if fam == "thr"
                           else p["q"] * float(np.exp(p["zq"])) * p["mu_cur"] if fam == "ast"
                           else p["share"] * float(np.exp(p["zs"])) * 88.0 * p["mu_cur"] / 48.0)
                    line = np.floor(lam) + 0.5
                    for b in self.BOOKS:
                        ln = line + (RNG.choice([-1, 1]) if RNG.random() < 0.15 and line > 1 else 0)
                        p_over = float(stats.poisson.sf(int(np.floor(ln)), lam)) + float(RNG.normal(0, 0.015))
                        for side, pr in (("Over", p_over), ("Under", 1 - p_over)):
                            mk[b]["outcomes"].append({"name": side, "description": p["name"], "point": float(ln),
                                                      "price": american(pr * 1.045)})
            for b in self.BOOKS:
                out[b]["markets"].append(mk[b])
        return list(out.values())

    def lines(self, g):
        total = self.total_mean + float(RNG.normal(0, 3))
        spread = float(np.round(RNG.normal(0, 5) * 2) / 2)
        h, a = self.names[g["gameId"]]
        return [{"key": b.lower(), "title": b, "markets": [
            {"key": "totals", "outcomes": [{"name": "Over", "point": total, "price": -110}, {"name": "Under", "point": total, "price": -110}]},
            {"key": "spreads", "outcomes": [{"name": h, "point": spread, "price": -110}, {"name": a, "point": -spread, "price": -110}]}]}
                for b in self.BOOKS]

    def get(self, url, params=None, timeout=None, **kw):
        if url.endswith("/events"):
            return Resp([self.event(g) for g in self.games])
        if url.endswith("/odds") and "/events/" in url:
            gid = url.split("/events/ev")[1].split("/")[0]
            g = next(x for x in self.games if x["gameId"] == gid)
            return Resp({**self.event(g), "bookmakers": self.props(g)})
        if url.endswith("/odds"):
            return Resp([{**self.event(g), "bookmakers": self.lines(g)} for g in self.games])
        raise AssertionError(f"unexpected URL {url}")


# ---------------------------------------------------------------- checks
def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        check.failed += 1


check.failed = 0


def build_world(cdn, start_year=2034, stationary=False):
    """Two finished seasons plus the start of a third. Dates sit far in the future so the sim's
    "never log after tip-off" rule cannot trip over the real clock."""
    global STATIONARY, RNG
    STATIONARY = stationary
    RNG = np.random.default_rng(20261020 + (1 if stationary else 0))
    truth, teams = {}, make_league()
    b1, _ = make_season(teams, date(start_year, 10, 22), "24", truth)
    b2, _ = make_season(teams, date(start_year + 1, 10, 21), "25", truth)
    cdn.boxes, cdn.sched = {}, []
    cdn.boxes.update(b1)
    cdn.boxes.update(b2)
    return teams, truth


def stage_model(cdn, truth):
    import nba_pipeline as m
    print("\n== Data layer ==")
    prior = nba_data.fetch_season("20242025")
    test = nba_data.fetch_season("20252026")
    check("reads a finished season day by day", prior["game_id"].nunique() == GAMES, f"{prior['game_id'].nunique()} games")
    per_team = prior.groupby(["game_id", "team"]).size()
    check("about 10-13 players per team-game", 9 <= per_team.mean() <= 13, f"{per_team.mean():.1f}")
    check("minutes per team-game ~240", abs(prior.groupby(["game_id", "team"])["min"].sum().mean() - 240) < 12)
    calls, before = cdn.calls, len(test)
    again = nba_data.fetch_season("20252026")
    check("second fetch adds nothing new", len(again) == before, f"{len(again)} rows")
    if not QUICK:
        check("finished season is not re-walked", cdn.calls - calls <= 2, f"{cdn.calls - calls} calls")

    # Opening night: the new season has no finished games yet, so its table is empty (text columns)
    import pandas as pd
    tonight = test.tail(10).copy()
    tonight[["min", "fg3m", "fg3a", "reb", "oreb", "fga", "fta", "tov", "pts", "ast"]] = 0.0
    tonight["date"], tonight["game_id"] = "2099-01-01", "future1"
    opening = m.build_projections(pd.concat([pd.DataFrame(columns=nba_data.COLS), tonight], ignore_index=True), prior)
    check("opening night works with an empty current season", len(opening) > 0 and not opening["lam_thr"].isna().any(),
          f"{len(opening)} rows")

    print("\n== Model vs. ground truth (2025-26, prior = 2024-25) ==")
    proj = m.build_projections(test, prior)
    check("no NaN projections", not proj[["lam_thr", "lam_reb", "proj_min"]].isna().any().any())
    keys = list(zip(proj["game_id"], proj["player_id"]))
    tl = np.array([truth.get(k, (np.nan, np.nan, np.nan)) for k in keys])
    ok = ~np.isnan(tl[:, 0])
    for fam, col, i in (("threes", "lam_thr", 0), ("rebounds", "lam_reb", 1), ("assists", "lam_ast", 2)):
        a, b = proj[col].to_numpy()[ok], tl[ok, i]
        corr = float(np.corrcoef(a, b)[0, 1])
        check(f"{fam}: projection tracks true mean", corr > 0.82, f"corr {corr:.3f}, mean proj {a.mean():.3f} vs true {b.mean():.3f}")
    mild = dict(m.CONFIG, recent_weight=0.3, recent_weight_reb=0.3)
    for label, cfg in (("moderate recency (0.30)", mild), ("shipped default (0.65)", m.CONFIG)):
        res = m.backtest(m.build_projections(test, prior, cfg), cfg)
        for fam in ("thr", "reb", "ast"):
            s = res[fam]["lines"]["main"]
            line = f"{res[fam]['label']}, book-like line, {label}: skill {s['skill']:+.1%}, calibration miss {s['ece']:.1%}, n={s['n']:,}"
            if cfg is mild:
                check(line, s["skill"] > 0 and s["ece"] < 0.025)
            else:
                print(f"  [info] {line}")


def stage_tune(cdn):
    import nba_pipeline as m
    import tune
    print("\n== Tuner: does it find the right recency weight in each world? ==")
    found = {}
    for stationary in (True, False):
        build_world(cdn, 2034, stationary)
        for f in Path(nba_data.DATA_DIR).glob("games_*"):
            f.unlink()
        prior, test = nba_data.fetch_season("20242025"), nba_data.fetch_season("20252026")
        tune.SPLIT = sorted(test["date"].unique())[len(test["date"].unique()) // 2]
        groups = [g for g in tune.GROUPS if g[0] in ("three rate", "rebounds")]
        cfg, proj, report = tune.tune(test, prior, dict(m.CONFIG), groups, verbose=False)
        found[stationary] = (cfg["recent_weight"], cfg["recent_weight_reb"])
        print(f"  {'stationary' if stationary else 'drifting  '} world -> threes recency {cfg['recent_weight']}, "
              f"rebounds recency {cfg['recent_weight_reb']}, spread {cfg['nb_r']}")
    check("tuner pulls recency DOWN when nothing really changes", found[True][1] <= 0.3, f"reb {found[True][1]}")
    check("tuner keeps at least as much recency when players really drift (noisy, so with some slack)",
          sum(found[False]) >= sum(found[True]) - 0.2, f"drifting {found[False]} vs stationary {found[True]}")


def stage_season(cdn):
    """A mini season through the real board.py and sim.py: price, log, play the games, grade, repeat."""
    import requests
    import board
    import market
    import nba_pipeline as m
    import sim
    print("\n== Mini season: board -> sim -> grade, with a fake odds feed ==")
    teams, truth = build_world(cdn, 2034, False)
    nba_data.today_et = lambda: date(2037, 1, 1)   # the 2026-27 season is "current": still being played
    for f in Path(nba_data.DATA_DIR).glob("games_*"):
        f.unlink()
    n26 = 300 if QUICK else 600
    b3, s3 = make_season(teams, date(2036, 10, 20), "26", truth, final_through=date(2036, 11, 19), n_games=n26)
    cdn.boxes.update(b3)
    cdn.sched = s3
    out = Path(tempfile.mkdtemp())
    board.OUT, sim.BOARD, sim.LOG, sim.CALIB = out / "board.json", out / "board.json", out / "sim_log.json", out / "calib"
    board.ODDS_KEY = "test"
    pts = [sum(p["statistics"].get("points", 0) for t in ("homeTeam", "awayTeam") for p in b["game"][t]["players"])
           for b in list(b2 for b2 in cdn.boxes.values())[-400:]]
    total_mean = float(np.mean(pts))
    unplayed = sorted({g["gameDateEst"][:10] for g in s3 if g["gameStatus"] == 1})[:6]
    real_get = requests.get
    first = True
    for day in unplayed:
        games = [g for g in s3 if g["gameDateEst"][:10] == day]
        requests.get = FakeOdds(teams, games, day, total_mean).get
        board.sys.argv = ["board.py", day]
        board.main()
        b = json.loads(board.OUT.read_text())
        if first:
            first = False
            ps = b["players"]
            check("board has players and all three markets", len(ps) > 20 and {"thr", "reb", "ast"} <= {market.base(k) for k in b["markets"]},
                  f"{len(ps)} players, {len(b['markets'])} market keys")
            priced = [(p, k) for p in ps for k in b["markets"] if p.get(k, {}).get("ev") is not None]
            check("props are priced with EV", len(priced) > 50, f"{len(priced)} priced props")
            check("every priced prop has finite fair odds and EV",
                  all(np.isfinite(p[k]["ev"]) and p[k]["fair"] for p, k in priced))
            both = [p for p in ps if "reb_o4.5" in p and "reb_u4.5" in p]
            if both:
                check("over + under model chances sum to 1", abs(both[0]["reb_o4.5"]["p_model"] + both[0]["reb_u4.5"]["p_model"] - 1) < 1e-3)
            check("every priced name matched a player", not b.get("unmatched"), str(b.get("unmatched"))[:80])
            check("market total reached the games", all("total" in g for g in b["games"]), "")
        sim.main()
        for g in games:   # play tonight's games, then the next run grades them
            h, a = g["homeTeam"]["teamTricode"], g["awayTeam"]["teamTricode"]
            cdn.boxes[g["gameId"]] = play_game(teams, h, a, g["gameId"], day, truth)
            g["gameStatus"] = 3
    requests.get = real_get
    sim.main()
    log = json.loads(sim.LOG.read_text())
    graded = [x for x in log if x["status"] in ("win", "loss")]
    check("sim logged plays and graded them", len(log) > 10 and len(graded) > 10, f"{len(log)} logged, {len(graded)} graded")
    check("nothing logged after tip-off / no duplicates", len({(x["date"], x["player_id"], x["market"]) for x in log}) == len(log))
    rows = [r for f in sorted(sim.CALIB.glob("*.json")) for r in json.loads(f.read_text())]
    done = [r for r in rows if r["hit"] in (0, 1)]
    check("calibration log graded", len(done) > 200, f"{len(done)} graded priced props")
    if len(done) > 200:
        hp = np.array([r["hit"] for r in done], float)
        pm = np.array([r["p_model"] for r in done], float)
        pk = np.array([r["p_mkt"] for r in done if r["p_mkt"] is not None], float)
        hk = np.array([r["hit"] for r in done if r["p_mkt"] is not None], float)
        check("model chances are calibrated overall", abs(pm.mean() - hp.mean()) < 0.03, f"model {pm.mean():.3f} vs hit rate {hp.mean():.3f}")
        print(f"  [info] Brier on {len(hk)} props: model {np.mean((pm[:len(hk)] - hk) ** 2) if len(pm) == len(hk) else float('nan'):.4f}, "
              f"market {np.mean((pk - hk) ** 2):.4f}  (the fake market knows the true rates, so it should win)")


if __name__ == "__main__":
    import json as _json  # noqa: F401
    tmp = Path(tempfile.mkdtemp())
    nba_data.DATA_DIR = tmp / "data"
    cdn = FakeCDN()
    nba_data.get_json = cdn.get_json
    WINDOWS = {"20242025": (date(2034, 10, 1), date(2035, 4, 20)), "20252026": (date(2035, 10, 1), date(2036, 4, 20)),
               "20262027": (date(2036, 10, 1), date(2037, 4, 20))}
    nba_data.season_window = WINDOWS.__getitem__
    nba_data.today_et = lambda: date(2040, 1, 1)
    print(f"Generating synthetic league ({GAMES} games per season)...")
    teams, truth = build_world(cdn, 2034, False)
    stage_model(cdn, truth)
    stage_tune(cdn)
    stage_season(cdn)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'ALL CHECKS PASSED' if not check.failed else str(check.failed) + ' CHECK(S) FAILED'}")
    sys.exit(1 if check.failed else 0)
