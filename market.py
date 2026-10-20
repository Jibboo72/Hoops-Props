"""NBA market view: what the betting market says about each game and each prop.

1. Game total (and spread) -> how fast and high-scoring tonight should be. Books' totals are sharp and
   already know about injuries and rest, so the model's game environment is pulled toward them.
2. Prop prices with the book's cut removed -> the market's fair chance for each prop. The final chance
   is a blend of the model and the market, so one stat quirk can't manufacture a huge edge on its own.

A prop key looks like "thr_o2.5" (over 2.5 threes) or "reb_u8.5" (under 8.5 rebounds).
"""
import statistics
import numpy as np
import requests

ENV_WEIGHT = 0.7     # how far the game environment moves toward the market's total
ENV_CLAMP = (0.90, 1.10)
# Final chance = this much model + the rest market. The model is unproven in the NBA until the sim has graded
# a few thousand props, so the market gets the larger share. The sim logs both chances to keep tuning this.
MODEL_WEIGHT = {"thr": 0.35, "reb": 0.35}
MAX_PRICE = 500      # main bets stop here; longer prices are still logged
# "Most likely to hit" strategy: pick by chance first, then let price decide.
LIKELY_MIN = {"thr": 0.55, "reb": 0.55}   # final chance needed to make the pool
LIKELY_MAX_PRICE = 200                    # nothing longer than +200
LIKELY_MIN_PRICE = -250                   # nothing shorter than -250
PRICE_CHECK = -0.03                       # never pay more than 3% over our fair price

NICKNAMES = {
    "ATL": "hawks", "BKN": "nets", "BOS": "celtics", "CHA": "hornets", "CHI": "bulls", "CLE": "cavaliers",
    "DAL": "mavericks", "DEN": "nuggets", "DET": "pistons", "GSW": "warriors", "HOU": "rockets", "IND": "pacers",
    "LAC": "clippers", "LAL": "lakers", "MEM": "grizzlies", "MIA": "heat", "MIL": "bucks", "MIN": "timberwolves",
    "NOP": "pelicans", "NYK": "knicks", "OKC": "thunder", "ORL": "magic", "PHI": "76ers", "PHX": "suns",
    "POR": "trail blazers", "SAC": "kings", "SAS": "spurs", "TOR": "raptors", "UTA": "jazz", "WAS": "wizards"}


def team_abbrev(name):
    """'Charlotte Hornets' -> 'CHA'. Whole words only: 'nets' must not match inside 'hornets'."""
    n = f" {(name or '').lower()} "
    return next((a for a, w in NICKNAMES.items() if f" {w} " in n), None)


def implied(price):
    return 1 / (1 + price / 100) if price > 0 else abs(price) / (abs(price) + 100)


def two_way(a, b):
    """Fair chance of side a once the cut is removed."""
    pa, pb = implied(a), implied(b)
    return pa / (pa + pb)


def make_key(fam, side, pt):
    return f"{fam}_{side}{pt}"


def parse_key(key):
    """'thr_o2.5' -> ('thr', 'o', 2.5)"""
    fam, rest = key.split("_", 1)
    return fam, rest[0], float(rest[1:])


def base(key):
    return key.split("_", 1)[0]


def game_lines(key, base_url, books, date, tz):
    """{team abbrev: {"total": market game total, "spread": that team's spread}} for tonight's games.
    One call for every game: 2 odds credits (spreads + totals)."""
    from datetime import datetime
    r = requests.get(f"{base_url}/odds", timeout=30, params={
        "apiKey": key, "bookmakers": books, "markets": "spreads,totals", "oddsFormat": "american"})
    out = {}
    for e in r.json():
        if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")).astimezone(tz).strftime("%Y-%m-%d") != date:
            continue
        home, away = team_abbrev(e["home_team"]), team_abbrev(e["away_team"])
        if not home or not away:
            continue
        totals, spreads = [], []
        for bk in e.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk["key"] == "totals":
                    pts = [o["point"] for o in mk.get("outcomes", []) if o.get("point") is not None]
                    if pts:
                        totals.append(pts[0])
                if mk["key"] == "spreads":
                    for o in mk.get("outcomes", []):
                        if o.get("name") == e["home_team"] and o.get("point") is not None:
                            spreads.append(o["point"])
        if not totals:
            continue
        total = statistics.median(totals)
        spread = statistics.median(spreads) if spreads else 0.0
        out[home], out[away] = {"total": total, "spread": spread}, {"total": total, "spread": -spread}
    return out


def env_ratio(market_total, model_total):
    """How much faster/higher-scoring the market expects tonight than the model does (before exponent)."""
    if not market_total or not model_total or model_total <= 0:
        return 1.0
    target = ENV_WEIGHT * market_total + (1 - ENV_WEIGHT) * model_total
    return float(np.clip(target / model_total, *ENV_CLAMP))


def market_view(rows):
    """Adds the market's fair chance to every priced prop, from books that post both sides of the same line."""
    for r in rows:
        for kind in [k for k, v in r.items() if isinstance(v, dict) and "p_model" in v]:
            m = r[kind]
            fair = [two_way(m["prices"][b], m["other"][b]) for b in m.get("prices", {}) if b in m.get("other", {})]
            if fair:
                m["p_mkt"] = round(statistics.median(fair), 4)
    return rows
