"""NBA prop model: projects 3-pointers made and rebounds for each player-game, using only earlier games.

THREES  lam = (3PA per minute, recency-weighted) x projected minutes x pace x opponent 3PA allowed
              x (3P%, regressed to the league) x opponent 3P% allowed
REBOUNDS lam = (rebound share of the rebounds available while on the floor, recency-weighted)
              x projected minutes / 48 x projected total rebounds in the game (both teams)

Both share the same first step: projected minutes. Counts are then run through a Poisson or negative
binomial (see nba_pipeline.dist_sf) to get the chance of clearing a line.
Every tunable number lives in CONFIG. tune.py picks the best values and saves them to data/tuned_config.json.
"""
import numpy as np
import pandas as pd

CONFIG = {
    # Recency: last 5 games, leaning on them hard (65%). Josh's call; the tuner only moves the strength.
    "recent_n": 5, "recent_weight": 0.65, "recent_weight_reb": 0.65,
    "recent_prior_games": 1.0,   # the recent window is regressed to the season by this many games of minutes
    "prior_games": 20,           # last season counts as this many games of evidence
    # Minutes
    "min_prior_games": 8, "min_recent_weight": 0.60,
    # Threes
    "pct_prior_att": 250,        # 3P% regression, in attempts
    "opp3a_clamp": [0.88, 1.12], "opp3p_clamp": [0.94, 1.06], "opp_pct_prior_att": 900,
    # Rebounds
    "reb_prior_games": 20, "reb_total_clamp": [0.88, 1.12],
    # Team context
    "team_k": 10, "team_prior_keep": 0.6,   # games of shrink, and how much of last year's team style carries over
    "pace_clamp": [0.92, 1.08],
    "home_edge": 0.0, "b2b_drop": 0.0,
    "env_exponent": {"thr": 0.5, "reb": 0.5},   # how far the market's game total moves each market (board.py)
    "blowout_drop": 0.0,                        # minutes lost by starters in lopsided games; off until data exists
    # Filters and distributions
    "min_history_games": 8, "min_proj_min": 12.0,
    "nb_candidates": [None, 40, 20, 12, 8, 5],   # None = Poisson
    "nb_r": {"thr": 20, "reb": 12},              # the spread in use; tune.py replaces these with the best fit
    "thr_lines": [0.5, 1.5, 2.5, 3.5, 4.5],
    "reb_lines": [2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5],
}
TEAM_STATS = ("pace", "reb", "pts", "o3a")


def pos_group(p):
    s = p if isinstance(p, str) else ""
    return "B" if "C" in s else "W" if "F" in s else "G" if "G" in s else "X"


def position_map(*frames):
    """player_id -> most common listed position (boxscores often leave bench players blank)."""
    allrows = pd.concat([f[["player_id", "pos"]] for f in frames if f is not None and len(f)], ignore_index=True)
    allrows = allrows[allrows["pos"].fillna("") != ""]
    if allrows.empty:
        return {}
    return allrows.groupby("player_id")["pos"].agg(lambda s: s.value_counts().index[0]).to_dict()


def team_games(df):
    """One row per team per game: own and opponent totals, plus per-48 versions (overtime removed)."""
    g = df.groupby(["game_id", "date", "team", "opp", "home"], as_index=False).agg(
        tmin=("min", "sum"), fg3a=("fg3a", "sum"), fg3m=("fg3m", "sum"), reb=("reb", "sum"),
        fga=("fga", "sum"), fta=("fta", "sum"), oreb=("oreb", "sum"), tov=("tov", "sum"), pts=("pts", "sum"))
    g["poss"] = g["fga"] + 0.44 * g["fta"] - g["oreb"] + g["tov"]
    opp = g[["game_id", "team", "fg3a", "fg3m", "reb", "pts", "poss"]].rename(columns={
        "team": "opp", "fg3a": "o_fg3a", "fg3m": "o_fg3m", "reb": "o_reb", "pts": "o_pts", "poss": "o_poss"})
    g = g.merge(opp, on=["game_id", "opp"], how="left")
    for c in ("o_fg3a", "o_fg3m", "o_reb", "o_pts", "o_poss"):
        g[c] = g[c].fillna(0.0)
    ot = (g["tmin"] / 240.0).where(g["tmin"] > 0, 1.0)
    g["g_reb"], g["g_pts"] = g["reb"] + g["o_reb"], g["pts"] + g["o_pts"]
    g["pace48"] = (g["poss"] + g["o_poss"]) / 2.0 / ot
    g["reb48"], g["pts48"] = g["g_reb"] / ot, g["g_pts"] / ot
    g["o_fg3a48"], g["o_fg3m48"] = g["o_fg3a"] / ot, g["o_fg3m"] / ot
    g["o3a"] = np.where(g["pace48"] > 0, g["o_fg3a48"] / g["pace48"].where(g["pace48"] > 0, 1.0), 0.0)
    return g


def prep(df, posmap):
    """Adds each player's share of available rebounds (rebounds up for grabs while he was on the floor)."""
    df = df.copy()
    tg = team_games(df)
    df = df.merge(tg[["game_id", "team", "tmin", "g_reb"]], on=["game_id", "team"], how="left")
    safe = df["tmin"].where(df["tmin"] > 0, 1.0)
    df["avail"] = np.where(df["tmin"] > 0, df["g_reb"] * df["min"] * 5.0 / safe, 0.0)
    df["pg"] = df["player_id"].map(posmap).map(pos_group)
    return df


def league_baselines(prior, posmap):
    prior = prep(prior, posmap)
    tg = team_games(prior)
    base = {"min": float(prior["min"].mean()),
            "thr_a_pm": prior["fg3a"].sum() / max(prior["min"].sum(), 1.0),
            "thr_pct": prior["fg3m"].sum() / max(prior["fg3a"].sum(), 1.0),
            "reb_rate": prior["reb"].sum() / max(prior["avail"].sum(), 1.0),
            "avail_pg": float(prior["avail"].sum() / max(len(prior), 1)),
            "reb_rate_pg": {g: d["reb"].sum() / max(d["avail"].sum(), 1.0) for g, d in prior.groupby("pg")},
            "lg": {"pace": tg["pace48"].mean(), "reb": tg["reb48"].mean(), "pts": tg["pts48"].mean(),
                   "o3a": tg["o3a"].mean(), "o3pct": tg["o_fg3m"].sum() / max(tg["o_fg3a"].sum(), 1.0)}}
    team = tg.groupby("team").agg(pace=("pace48", "mean"), reb=("reb48", "mean"),
                                  pts=("pts48", "mean"), o3a=("o3a", "mean"))
    base["team"] = {c: team[c].to_dict() for c in TEAM_STATS}
    return base, prior


def prior_player_table(prior_rows):
    return prior_rows.groupby("player_id").agg(
        p_gp=("game_id", "count"), p_min=("min", "sum"), p_fg3m=("fg3m", "sum"), p_fg3a=("fg3a", "sum"),
        p_reb=("reb", "sum"), p_avail=("avail", "sum")).reset_index()


def build_projections(test, prior, cfg=CONFIG):
    """test: every player-game of this season so far (plus tonight's rows with min=0).
    prior: last season. Returns one row per player-game with lam_thr and lam_reb."""
    posmap = position_map(prior, test)
    base, prior_rows = league_baselines(prior, posmap)
    df = prep(test, posmap).sort_values(["player_id", "date", "game_id"]).reset_index(drop=True)
    lgb = base["lg"]

    # ---- Team context, strictly pre-game ----
    tg = team_games(df).sort_values(["team", "date", "game_id"]).reset_index(drop=True)
    cols = {"pace48": "pace", "reb48": "reb", "pts48": "pts", "o3a": "o3a", "o_fg3a48": "ofa", "o_fg3m48": "ofm"}
    t = tg.groupby("team")
    for c, s in cols.items():
        tg[f"c_{s}"] = t[c].cumsum() - tg[c]
    tg["c_gp"] = t.cumcount()
    tg["rest"] = pd.to_datetime(tg["date"]).groupby(tg["team"]).diff().dt.days
    daily = tg.groupby("date").agg(pace=("pace48", "sum"), reb=("reb48", "sum"), pts=("pts48", "sum"),
                                   o3a=("o3a", "sum"), ofa=("o_fg3a48", "sum"), ofm=("o_fg3m48", "sum"),
                                   n=("pace48", "size")).sort_index()
    cum, K = daily.cumsum().shift(1).fillna(0), 64.0   # league averages to date, leaning on last season early
    for s in ("pace", "reb", "pts", "o3a"):
        cum[f"lg_{s}"] = (cum[s] + lgb[s] * K) / (cum["n"] + K)
    cum["lg_o3pct"] = (cum["ofm"] + lgb["o3pct"] * 3000.0) / (cum["ofa"] + 3000.0)
    df = df.merge(cum[[f"lg_{s}" for s in ("pace", "reb", "pts", "o3a")] + ["lg_o3pct"]],
                  left_on="date", right_index=True, how="left")
    own = tg[["game_id", "team", "c_gp", "c_pace", "c_reb", "c_pts", "rest"]].rename(
        columns={"c_gp": "t_gp", "c_pace": "t_pace", "c_reb": "t_reb", "c_pts": "t_pts"})
    oth = tg[["game_id", "team", "c_gp", "c_pace", "c_reb", "c_pts", "c_o3a", "c_ofa", "c_ofm"]].rename(columns={
        "team": "opp", "c_gp": "o_gp", "c_pace": "o_pace", "c_reb": "o_reb", "c_pts": "o_pts",
        "c_o3a": "o_o3a", "c_ofa": "o_ofa", "c_ofm": "o_ofm"})
    df = df.merge(own, on=["game_id", "team"], how="left").merge(oth, on=["game_id", "opp"], how="left")
    TK, keep = float(cfg["team_k"]), cfg["team_prior_keep"]

    def shrunk(stat, who, tot, gp):
        """This team's per-game average of a stat, regressed toward last season's team style (itself partly regressed)."""
        tbl = base["team"][stat]
        target = df[who].map(lambda x: lgb[stat] + keep * (tbl.get(x, lgb[stat]) - lgb[stat])).astype(float)
        return (df[tot].fillna(0) + target * TK) / (df[gp].fillna(0) + TK)

    A_pace, B_pace = shrunk("pace", "team", "t_pace", "t_gp"), shrunk("pace", "opp", "o_pace", "o_gp")
    A_reb, B_reb = shrunk("reb", "team", "t_reb", "t_gp"), shrunk("reb", "opp", "o_reb", "o_gp")
    A_pts, B_pts = shrunk("pts", "team", "t_pts", "t_gp"), shrunk("pts", "opp", "o_pts", "o_gp")
    B_o3a = shrunk("o3a", "opp", "o_o3a", "o_gp")
    # The player's own rate was measured in his team's games, so only the opponent's pace is new information.
    df["pace_ratio"] = (1.0 + (B_pace - df["lg_pace"]) / A_pace).clip(*cfg["pace_clamp"])
    df["opp3a_factor"] = (B_o3a / df["lg_o3a"]).clip(*cfg["opp3a_clamp"])
    k3 = cfg["opp_pct_prior_att"]
    opp_pct = (df["o_ofm"].fillna(0) + df["lg_o3pct"] * k3) / (df["o_ofa"].fillna(0) + k3)
    df["opp3p_factor"] = (opp_pct / df["lg_o3pct"]).clip(*cfg["opp3p_clamp"])
    lo, hi = cfg["reb_total_clamp"]
    df["g_reb_pred"] = (A_reb + B_reb - df["lg_reb"]).clip(df["lg_reb"] * lo, df["lg_reb"] * hi)
    df["pts_pred"] = A_pts + B_pts - df["lg_pts"]   # the model's own expected game total (points), for the market blend
    h, b = cfg["home_edge"], cfg["b2b_drop"]
    ctx = np.where(df["home"] == 1, 1 + h, 1 - h) * np.where(df["rest"] == 1, 1 - b, 1.0)

    # ---- Player history, strictly pre-game ----
    g = df.groupby("player_id")
    for c in ("min", "fg3m", "fg3a", "reb", "avail"):
        df[f"c_{c}"] = g[c].cumsum() - df[c]
    df["c_gp"] = g.cumcount()
    n = int(cfg["recent_n"])
    for c in ("min", "fg3a", "reb", "avail"):
        df[f"r_{c}"] = g[c].transform(lambda s: s.shift(1).rolling(n, min_periods=1).sum()).fillna(0)
    df["r_gp"] = g["min"].transform(lambda s: s.shift(1).rolling(n, min_periods=1).count()).fillna(0)
    df = df.merge(prior_player_table(prior_rows), on="player_id", how="left")
    for c in ("p_gp", "p_min", "p_fg3m", "p_fg3a", "p_reb", "p_avail"):
        df[c] = df[c].fillna(0)
    cg, pg_ = df["c_gp"].clip(lower=1), df["p_gp"].clip(lower=1)

    # ---- Minutes ----
    prior_min = np.where(df["p_gp"] > 0, df["p_min"] / pg_, np.where(df["c_gp"] > 0, df["c_min"] / cg, base["min"]))
    mp = cfg["min_prior_games"]
    season_min = (df["c_min"] + prior_min * mp) / (df["c_gp"] + mp)
    recent_min = np.where(df["r_gp"] > 0, df["r_min"] / df["r_gp"].clip(lower=1), season_min)
    wm = cfg["min_recent_weight"]
    df["proj_min"] = np.where(df["r_gp"] >= 3, wm * recent_min + (1 - wm) * season_min, season_min)

    # ---- Threes: attempts per minute x regressed 3P% ----
    k = 150.0
    prior_a = (df["p_fg3a"] + base["thr_a_pm"] * k) / (df["p_min"] + k)
    t_eq = cfg["prior_games"] * prior_min
    season_a = (df["c_fg3a"] + prior_a * t_eq) / (df["c_min"] + t_eq)
    t_r = cfg["recent_prior_games"] * prior_min
    recent_a = (df["r_fg3a"] + season_a * t_r) / (df["r_min"] + t_r)
    wr = cfg["recent_weight"]
    df["a_rate"] = np.where(df["r_gp"] >= 3, (1 - wr) * season_a + wr * recent_a, season_a)
    kp = cfg["pct_prior_att"]
    df["pct3"] = (df["p_fg3m"] + df["c_fg3m"] + base["thr_pct"] * kp) / (df["p_fg3a"] + df["c_fg3a"] + kp)
    df["lam_thr"] = (df["a_rate"] * df["proj_min"] * df["pace_ratio"] * df["opp3a_factor"]
                     * df["pct3"] * df["opp3p_factor"] * ctx)

    # ---- Rebounds: share of available rebounds while on the floor ----
    lg_r = df["pg"].map(lambda x: base["reb_rate_pg"].get(x, base["reb_rate"]))
    prior_av = np.where(df["p_gp"] > 0, df["p_avail"] / pg_, np.where(df["c_gp"] > 0, df["c_avail"] / cg, base["avail_pg"]))
    kr = 400.0
    prior_r = (df["p_reb"] + lg_r * kr) / (df["p_avail"] + kr)
    t_eq_r = cfg["reb_prior_games"] * prior_av
    season_r = (df["c_reb"] + prior_r * t_eq_r) / (df["c_avail"] + t_eq_r)
    t_rr = cfg["recent_prior_games"] * prior_av
    recent_r = (df["r_reb"] + season_r * t_rr) / (df["r_avail"] + t_rr)
    wrr = cfg["recent_weight_reb"]
    df["trb"] = np.where(df["r_gp"] >= 3, (1 - wrr) * season_r + wrr * recent_r, season_r)
    df["lam_reb"] = df["trb"] * (df["proj_min"] / 48.0) * df["g_reb_pred"] * ctx

    # ---- Naive baseline: raw per-game average this season (last season if under 5 games) ----
    use_cur = df["c_gp"] >= 5
    df["naive_thr"] = np.where(use_cur, df["c_fg3m"] / cg, df["p_fg3m"] / pg_)
    df["naive_reb"] = np.where(use_cur, df["c_reb"] / cg, df["p_reb"] / pg_)
    keep_rows = ((df["c_gp"] + df["p_gp"]) >= cfg["min_history_games"]) & (df["proj_min"] >= cfg["min_proj_min"])
    return df[keep_rows].copy()
