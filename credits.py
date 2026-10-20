#!/usr/bin/env python3
"""Odds API credit check. The /sports call is free (it does not use credits), and every Odds API
response says how many credits are left, so this is a safe way to look at the balance any time.
Writes docs/data/credits.json, which the Tonight page shows."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent / "docs" / "data" / "credits.json"


def update():
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        print("No ODDS_API_KEY set, credits not checked.")
        return None
    try:
        r = requests.get("https://api.the-odds-api.com/v4/sports", params={"apiKey": key}, timeout=30)
        rem, used = r.headers.get("x-requests-remaining"), r.headers.get("x-requests-used")
        if rem is None:
            print(f"Odds API gave no credit info (status {r.status_code}).")
            return None
        out = {"remaining": int(float(rem)), "used": int(float(used)) if used not in (None, "") else None,
               "checked": datetime.now(timezone.utc).isoformat(timespec="minutes"), "reset_day": 28}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, indent=1))
        print(f"Odds credits left: {out['remaining']} (used {out['used']}).")
        return out
    except Exception as exc:
        print(f"Credit check failed: {exc.__class__.__name__}")
        return None


if __name__ == "__main__":
    update()
