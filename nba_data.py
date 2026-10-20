"""NBA data: every player-game of a season, from the NBA's public CDN boxscore files.

Why the CDN and not stats.nba.com: stats.nba.com stalls requests that come from cloud servers
(Colab, GitHub Actions), which is what timed out in the first backtest attempt. cdn.nba.com serves
plain static JSON files and is built to be fetched by anyone, so it is the first thing to try.

  schedule : cdn.nba.com/static/json/staticData/scheduleLeagueV2.json   (current season only)
  boxscore : cdn.nba.com/static/json/liveData/boxscore/boxscore_<gameId>.json

Regular-season game ids are 002 + 2-digit season start year + 5-digit number (1..1230), so a finished
season can be walked id by id without a schedule file.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

CDN = "https://cdn.nba.com/static/json"
SCHEDULE_URL = f"{CDN}/staticData/scheduleLeagueV2.json"
BOX_URL = CDN + "/liveData/boxscore/boxscore_{gid}.json"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ET = ZoneInfo("America/New_York")
TEAMS = [
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]
COLS = ["season", "player_id", "name", "pos", "game_id", "date", "team", "opp", "home", "started",
        "min", "fg3m", "fg3a", "reb", "oreb", "fga", "fta", "tov", "pts", "ast"]
NUMERIC = ["min", "fg3m", "fg3a", "reb", "oreb", "fga", "fta", "tov", "pts", "ast"]
GAMES_PER_SEASON = 1230
BOARD_TYPES = ("002", "003", "004", "005")  # regular season, Cup knockouts, playoffs, play-in (not preseason 001)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
})


def get_json(url, params=None, tries=4, quiet=False):
    """JSON or None. The CDN answers 403 (not 404) for a file that does not exist, so both mean "not there"."""
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (403, 404):
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1.5 * (attempt + 1))
    if quiet:
        return None
    raise RuntimeError(f"Request failed after {tries} tries: {url}")


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def minutes_of(v):
    """'PT34M12.00S' -> 34.2, '34:12' -> 34.2, 34 -> 34.0, '' -> 0.0"""
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    m = re.match(r"PT(?:(\d+)M)?(?:([\d.]+)S)?$", s)
    if m:
        return int(m.group(1) or 0) + float(m.group(2) or 0) / 60.0
    if ":" in s:
        a, b = s.split(":")[:2]
        return float(a) + float(b) / 60.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def num(d, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def et_date(game):
    """The ET calendar date of a boxscore's game block."""
    s = game.get("gameEt") or ""
    if s:
        return s[:10]
    utc = game.get("gameTimeUTC") or ""
    if utc:
        return datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(ET).strftime("%Y-%m-%d")
    return ""


def parse_boxscore(js, season, date_hint=None):
    """One boxscore JSON -> (rows, is_final). Rows are every player who actually played."""
    g = (js or {}).get("game") or {}
    final = g.get("gameStatus") == 3 or str(g.get("gameStatusText", "")).lower().startswith("final")
    day = date_hint or et_date(g)
    rows = []
    for side, other, home in ((g.get("homeTeam") or {}, g.get("awayTeam") or {}, 1),
                              (g.get("awayTeam") or {}, g.get("homeTeam") or {}, 0)):
        team, opp = side.get("teamTricode"), other.get("teamTricode")
        if not team or not opp:
            continue
        for p in side.get("players", []):
            st = p.get("statistics") or {}
            mins = minutes_of(st.get("minutes") or st.get("minutesCalculated"))
            if mins <= 0 or str(p.get("status", "ACTIVE")).upper() == "INACTIVE":
                continue
            name = p.get("name") or f"{p.get('firstName', '')} {p.get('familyName', '')}".strip()
            rows.append({
                "season": str(season), "player_id": int(p["personId"]), "name": name,
                "pos": p.get("position") or "", "game_id": str(g.get("gameId") or ""), "date": day,
                "team": team, "opp": opp, "home": home,
                "started": 1 if str(p.get("starter", "0")) in ("1", "True", "true") else 0,
                "min": mins, "fg3m": num(st, "threePointersMade"), "fg3a": num(st, "threePointersAttempted"),
                "reb": num(st, "reboundsTotal"), "oreb": num(st, "reboundsOffensive"),
                "fga": num(st, "fieldGoalsAttempted"), "fta": num(st, "freeThrowsAttempted"),
                "tov": num(st, "turnovers"), "pts": num(st, "points"), "ast": num(st, "assists")})
    return rows, final


def parse_schedule(js):
    """The league schedule -> list of {id, status, date, start, away, home}."""
    out = []
    for d in ((js or {}).get("leagueSchedule") or {}).get("gameDates", []):
        for g in d.get("games", []):
            away, home = (g.get("awayTeam") or {}).get("teamTricode"), (g.get("homeTeam") or {}).get("teamTricode")
            if not away or not home:
                continue
            day = (g.get("gameDateEst") or g.get("gameDateTimeEst") or "")[:10]
            out.append({"id": str(g["gameId"]), "status": g.get("gameStatus"), "date": day,
                        "start": g.get("gameDateTimeUTC"), "away": away, "home": home})
    return out


def fetch_schedule():
    return parse_schedule(get_json(SCHEDULE_URL))


# --------------------------------------------------------------------------
# Season cache
# --------------------------------------------------------------------------
def season_prefix(season):
    return "002" + str(season)[2:4]


def _fetch_box(args):
    gid, season, day = args
    js = get_json(BOX_URL.format(gid=gid), quiet=True)
    if not js:
        return gid, None, False
    rows, final = parse_boxscore(js, season, day)
    return gid, rows, final


def _frame(rows):
    df = pd.DataFrame(rows, columns=COLS)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["player_id", "game_id"])
    return df.astype({c: float for c in NUMERIC}).astype({"player_id": int, "home": int, "started": int})


def fetch_season(season, refresh=False, workers=6):
    """Cached per season in data/games_<season>.csv. Only games not yet in the cache are downloaded.

    Current season: the schedule says which games are final. Finished season: every id 1..1230 is tried.
    refresh=True throws the cache away and starts over.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"games_{season}.csv"
    marker = DATA_DIR / f"games_{season}.complete"   # written once a finished season is fully downloaded
    if refresh:
        marker.unlink(missing_ok=True)
    have = pd.DataFrame(columns=COLS) if refresh or not path.exists() else pd.read_csv(path, dtype={"game_id": str})
    if marker.exists() and len(have):
        print(f"{season}: cache is complete ({have['game_id'].nunique()} games).")
        return have
    done = set(have["game_id"].astype(str))
    prefix = season_prefix(season)
    sched = [g for g in fetch_schedule() if g["id"].startswith(prefix)]
    new, missing, tried = [], 0, 0
    if sched:  # this season is the one on the CDN schedule: fetch what is final and not cached yet
        todo = [(g["id"], season, g["date"]) for g in sched if g["status"] == 3 and g["id"] not in done]
        print(f"{season}: downloading {len(todo)} new boxscores..." if todo else f"{season}: cache is current ({len(done)} games).")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for gid, rows, final in ex.map(_fetch_box, todo):
                tried += 1
                if rows is None or not final:
                    missing += 1
                else:
                    new += rows
        walked_all = False
    else:      # an older season: walk the ids 100 at a time and stop when a whole chunk is empty
        ids = [f"{prefix}{n:05d}" for n in range(1, GAMES_PER_SEASON + 1)]
        ids = [g for g in ids if g not in done]
        print(f"{season}: walking {len(ids)} game ids...")
        walked_all = True
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i in range(0, len(ids), 100):
                got = 0
                for gid, rows, final in ex.map(_fetch_box, [(g, season, None) for g in ids[i:i + 100]]):
                    tried += 1
                    if rows is None or not final:
                        missing += 1
                    else:
                        new += rows
                        got += 1
                if got == 0:
                    break
    if missing and tried:
        print(f"  {missing} of {tried} games were not available.")
    df = _frame(have.to_dict("records") + new)
    if not len(df) and tried > 20 and missing == tried:
        raise RuntimeError("No boxscores came back at all. cdn.nba.com looks blocked from this machine; "
                           "run the Probe workflow to see what each source answers.")
    if len(df):
        df.to_csv(path, index=False)
        if walked_all and df["game_id"].nunique() >= GAMES_PER_SEASON - 10:
            marker.write_text(str(df["game_id"].nunique()))
        tg = df.groupby(["game_id", "team"]).size()
        print(f"  {len(df):,} player-games, {df['game_id'].nunique()} games, "
              f"{tg.mean() if len(tg) else 0:.1f} players per team-game")
    return df
