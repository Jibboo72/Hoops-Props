"""NBA data: every player-game of a season, from ESPN's public JSON feeds.

Why ESPN: stats.nba.com stalls requests from cloud servers, and cdn.nba.com answers GitHub's servers
with "Access Denied" (the Probe workflow showed it). ESPN's site API answers GitHub fine.

  scoreboard : site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD
               -> every game on one day: id, start time, teams, final or not, season type
  boxscore   : site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=<id>
               -> every player's minutes, threes, rebounds and so on

A finished season is built by reading its scoreboard day by day (Oct 1 to Apr 20), then downloading the
boxscore of every regular-season game. Results are cached in data/games_<season>.csv.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
SCOREBOARD_URL = f"{ESPN}/scoreboard"
BOX_URL = ESPN + "/summary?event={gid}"
SCHEDULE_URL = SCOREBOARD_URL   # kept so older code that imports the name still works
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ET = ZoneInfo("America/New_York")
TEAMS = [
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]
# ESPN's short codes that differ from the usual three-letter ones
ESPN_ABBR = {"GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "CHO": "CHA"}
COLS = ["season", "player_id", "name", "pos", "game_id", "date", "team", "opp", "home", "started",
        "min", "fg3m", "fg3a", "reb", "oreb", "fga", "fta", "tov", "pts", "ast"]
NUMERIC = ["min", "fg3m", "fg3a", "reb", "oreb", "fga", "fta", "tov", "pts", "ast"]
GAMES_PER_SEASON = 1230
# ESPN season types: 1 preseason, 2 regular season, 3 playoffs, 5 play-in. Tonight's board uses all but preseason.
REGULAR = 2
BOARD_TYPES = (2, 3, 5)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
})


def get_json(url, params=None, tries=4, quiet=False):
    """JSON or None. A 403/404 means "not there"; anything else is retried, then raises unless quiet."""
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


def today_et():
    return datetime.now(ET).date()


def season_window(season):
    """First and last day to read for a season label like '20252026' (regular season only)."""
    return date(int(str(season)[:4]), 10, 1), date(int(str(season)[4:8]), 4, 20)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def minutes_of(v):
    """'34' -> 34.0, '34:12' -> 34.2, 'PT34M12.00S' -> 34.2, '' or '--' -> 0.0"""
    if v in (None, "", "--"):
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


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def split_pair(v):
    """'3-8' -> (3.0, 8.0)"""
    if isinstance(v, str) and "-" in v:
        a, b = v.split("-", 1)
        return to_float(a), to_float(b)
    return to_float(v), 0.0


def tricode(abbr):
    a = (abbr or "").upper()
    return ESPN_ABBR.get(a, a)


def et_day(iso):
    """'2025-10-22T23:30Z' -> '2025-10-22' on the Eastern calendar."""
    if not iso:
        return ""
    s = str(iso).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return str(iso)[:10]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).strftime("%Y-%m-%d")


def season_type_of(event):
    s = event.get("season")
    t = s.get("type") if isinstance(s, dict) else s
    if isinstance(t, dict):
        t = t.get("type")
    try:
        return int(t)
    except (TypeError, ValueError):
        return None


def parse_scoreboard(js):
    """One day's scoreboard -> list of {id, status, date, start, away, home, type}. status 3 means final."""
    out = []
    for e in (js or {}).get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        side = {c.get("homeAway"): tricode((c.get("team") or {}).get("abbreviation")) for c in comp.get("competitors", [])}
        home, away = side.get("home"), side.get("away")
        if home not in TEAMS or away not in TEAMS:   # All-Star games, international exhibitions
            continue
        st = ((e.get("status") or comp.get("status") or {}).get("type") or {})
        final = bool(st.get("completed")) or st.get("state") == "post"
        start = e.get("date") or comp.get("date")
        out.append({"id": str(e["id"]), "status": 3 if final else 1, "date": et_day(start), "start": start,
                    "away": away, "home": home, "type": season_type_of(e)})
    return out


def fetch_schedule(day=None):
    """Games on one Eastern date (default today), from the scoreboard."""
    day = day or today_et().strftime("%Y-%m-%d")
    js = get_json(SCOREBOARD_URL, params={"dates": day.replace("-", ""), "limit": 100})
    return parse_scoreboard(js)


def _stat_index(group):
    """Column positions for a stat group, using ESPN's own key names (or the short labels as a fallback)."""
    names = group.get("keys") or []
    labels = group.get("labels") or []
    idx = {}
    for i, k in enumerate(names):
        idx[str(k)] = i
    for i, k in enumerate(labels):
        idx.setdefault({"MIN": "minutes", "PTS": "points", "FG": "fieldGoalsMade-fieldGoalsAttempted",
                        "3PT": "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
                        "FT": "freeThrowsMade-freeThrowsAttempted", "REB": "rebounds", "AST": "assists",
                        "TO": "turnovers", "OREB": "offensiveRebounds"}.get(str(k), str(k)), i)
    return idx


def parse_boxscore(js, season, date_hint=None):
    """One ESPN summary JSON -> (rows, is_final). Rows are every player who actually played."""
    js = js or {}
    comp = (((js.get("header") or {}).get("competitions")) or [{}])[0]
    st = ((comp.get("status") or {}).get("type") or {})
    final = bool(st.get("completed")) or st.get("state") == "post"
    day = date_hint or et_day(comp.get("date"))
    gid = str((js.get("header") or {}).get("id") or comp.get("id") or "")
    home_of = {tricode((c.get("team") or {}).get("abbreviation")): c.get("homeAway") == "home"
               for c in comp.get("competitors", [])}
    teams = list(home_of)
    rows = []
    for blk in (js.get("boxscore") or {}).get("players", []):
        team = tricode((blk.get("team") or {}).get("abbreviation"))
        others = [t for t in teams if t != team]
        if team not in home_of or not others:
            continue
        opp = others[0]
        for group in blk.get("statistics", []):
            idx = _stat_index(group)
            if "minutes" not in idx:
                continue

            def at(stats, key, i=idx):
                j = i.get(key)
                return stats[j] if j is not None and j < len(stats) else None
            for a in group.get("athletes", []):
                stats = a.get("stats") or []
                if a.get("didNotPlay") or not stats:
                    continue
                mins = minutes_of(at(stats, "minutes"))
                if mins <= 0:
                    continue
                ath = a.get("athlete") or {}
                fg3m, fg3a = split_pair(at(stats, "threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
                _, fga = split_pair(at(stats, "fieldGoalsMade-fieldGoalsAttempted"))
                _, fta = split_pair(at(stats, "freeThrowsMade-freeThrowsAttempted"))
                try:
                    pid = int(ath.get("id"))
                except (TypeError, ValueError):
                    continue
                rows.append({
                    "season": str(season), "player_id": pid, "name": ath.get("displayName") or ath.get("shortName") or "",
                    "pos": (ath.get("position") or {}).get("abbreviation") or "", "game_id": gid, "date": day,
                    "team": team, "opp": opp, "home": 1 if home_of[team] else 0,
                    "started": 1 if a.get("starter") else 0,
                    "min": mins, "fg3m": fg3m, "fg3a": fg3a,
                    "reb": to_float(at(stats, "rebounds")), "oreb": to_float(at(stats, "offensiveRebounds")),
                    "fga": fga, "fta": fta, "tov": to_float(at(stats, "turnovers")),
                    "pts": to_float(at(stats, "points")), "ast": to_float(at(stats, "assists"))})
    return rows, final


# --------------------------------------------------------------------------
# Season cache
# --------------------------------------------------------------------------
def _fetch_day(day):
    js = get_json(SCOREBOARD_URL, params={"dates": day.strftime("%Y%m%d"), "limit": 100})
    return parse_scoreboard(js)


def _fetch_box(args):
    gid, season, day = args
    js = get_json(BOX_URL.format(gid=gid), quiet=True)
    if not js:
        return gid, None, False
    rows, final = parse_boxscore(js, season, day)
    if not rows:
        return gid, None, False
    for r in rows:
        r["game_id"] = str(gid)
    return gid, rows, final


def _frame(rows):
    df = pd.DataFrame(rows, columns=COLS)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["player_id", "game_id"])
    return df.astype({c: float for c in NUMERIC}).astype({"player_id": int, "home": int, "started": int})


def fetch_season(season, refresh=False, workers=8):
    """Cached per season in data/games_<season>.csv. Only games not yet in the cache are downloaded.

    Finished season: every day Oct 1 to Apr 20 is read once, then marked complete.
    Current season: only the last few cached days plus anything newer are read each run.
    refresh=True throws the cache away and starts over.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"games_{season}.csv"
    marker = DATA_DIR / f"games_{season}.complete"
    if refresh:
        marker.unlink(missing_ok=True)
    have = pd.DataFrame(columns=COLS) if refresh or not path.exists() else pd.read_csv(path, dtype={"game_id": str})
    if marker.exists() and len(have):
        print(f"{season}: cache is complete ({have['game_id'].nunique()} games).")
        return have
    done = set(have["game_id"].astype(str))
    first, last = season_window(season)
    today = today_et()
    finished = last < today
    if len(have) and not finished:   # current season: re-read only the recent days
        first = max(first, datetime.strptime(str(have["date"].max()), "%Y-%m-%d").date() - timedelta(days=4))
    last = min(last, today)
    days = [first + timedelta(n) for n in range((last - first).days + 1)]
    print(f"{season}: reading {len(days)} scoreboard days...")
    todo, seen = [], set()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for games in ex.map(_fetch_day, days):
            for g in games:
                if g["type"] == REGULAR and g["status"] == 3 and g["id"] not in done and g["id"] not in seen:
                    seen.add(g["id"])
                    todo.append((g["id"], season, g["date"]))
    print(f"  downloading {len(todo)} new boxscores..." if todo else f"  cache is current ({len(done)} games).")
    new, missing = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for gid, rows, final in ex.map(_fetch_box, todo):
            if rows is None or not final:
                missing += 1
            else:
                new += rows
    if missing:
        print(f"  {missing} of {len(todo)} boxscores were not available.")
    df = _frame(have.to_dict("records") + new)
    if not len(df) and len(todo) > 20 and missing == len(todo):
        raise RuntimeError("Games were found but no boxscores came back. Run the Probe workflow to see what ESPN answers.")
    if not len(df) and not todo and finished:
        raise RuntimeError(f"No finished games found for {season}. Run the Probe workflow to see what ESPN answers.")
    if len(df):
        df.to_csv(path, index=False)
        if finished and df["game_id"].nunique() >= GAMES_PER_SEASON - 10:
            marker.write_text(str(df["game_id"].nunique()))
        tg = df.groupby(["game_id", "team"]).size()
        print(f"  {len(df):,} player-games, {df['game_id'].nunique()} games, "
              f"{tg.mean() if len(tg) else 0:.1f} players per team-game")
    return df
