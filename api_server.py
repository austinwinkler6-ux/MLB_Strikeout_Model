"""
api_server.py — real API bridge for Model Metrics, ALL sports (August 2026)

WHY THIS IS DIFFERENT FROM BASE44'S ORIGINAL VERSION
------------------------------------------------------
Base44's own generated api_server.py reimplemented the entire LoL
pipeline from scratch — fetching Cito/Polymarket data itself and
recomputing ratings, head-to-head, and tiers independently. That threw
away every real, hard-won fix this project has and reintroduced bugs
already fixed.

This version never computes anything itself. It reads the REAL,
already-finished picks your actual Streamlit app already produces and
caches in Supabase — LoL's own full pipeline output cache, and (new in
this version) a matching cache for MLB, NBA Points, NBA Assists, NFL
Pass Attempts, NFL Pass Completions, and NFL Receptions, all populated
automatically every time your real app's auto-run finishes. Since
these caches are populated by your real, live app (via the cache-
warmer, or any real visitor), this API always reflects the exact same
picks your real app is showing — never a separate, drifting
reimplementation.

REQUIREMENTS
------------
    pip install fastapi uvicorn supabase

REQUIRED ENVIRONMENT VARIABLES
-------------------------------
    SUPABASE_URL    — same value your main Streamlit app uses
    SUPABASE_KEY    — same value your main Streamlit app uses
    BRIDGE_API_KEY  — a real, private key YOU choose — required in a
                      real request header to access this API. Without
                      this, anyone who finds your API's URL could see
                      every real pick your model makes, for free.

RUN LOCALLY
-----------
    python api_server.py
    # then visit http://localhost:8000/api/health to check it's alive
"""

import os
from datetime import datetime, timezone
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

app = FastAPI(title="Model Metrics API Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
BRIDGE_API_KEY = os.environ.get("BRIDGE_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Real sentinel values — must stay exactly in sync with the matching
# real constants in mlb_app.py (_LOL_PIPELINE_CACHE_SENTINEL and
# _ALL_PICKS_CACHE_SENTINEL). If those ever change there, update here too.
_LOL_PIPELINE_CACHE_SENTINEL = "__ALL_MATCHUPS__"
_ALL_PICKS_CACHE_SENTINEL = "__API_BRIDGE_ALL_PICKS__"

# Real, direct mapping from a real, public-facing sport name to the
# real internal sport_key your app already uses — matches
# build_todays_card_entries()'s own real sport_key values exactly.
SPORT_KEYS = {
    "mlb": "mlb_strikeouts",
    "nba-points": "nba_points",
    "nba-assists": "nba_assists",
    "nfl-attempts": "nfl_pass_attempts",
    "nfl-completions": "nfl_pass_completions",
    "nfl-receptions": "nfl_receptions",
}


def _require_api_key(x_api_key: str = Header(default=None)):
    if BRIDGE_API_KEY and x_api_key != BRIDGE_API_KEY:
        raise HTTPException(status_code=401, detail="Missing or incorrect X-API-Key header")


def _fetch_cache_row(sport_code, player_name):
    res = supabase.table("daily_cache").select("*") \
        .eq("sport", sport_code).eq("player_name", player_name) \
        .order("updated_at", desc=True).limit(1).execute()
    return res.data[0] if res.data else None


def _get_player_prop_picks(sport_key):
    """Real, generic transform for MLB/NBA/NFL's real, finished card
    entries (all sharing the same real shape: name, line, play, edge,
    ev_pct, tier, info) into a clean, real picks list."""
    if not supabase:
        return None, "SUPABASE_URL/SUPABASE_KEY not set on this server."
    row = _fetch_cache_row(sport_key, _ALL_PICKS_CACHE_SENTINEL)
    if not row:
        return [], None
    entries = row.get("projection_data") or []
    picks = []
    for e in entries:
        info = e.get("info") or {}
        picks.append({
            "player": e.get("name"),
            "sport": e.get("sport_label"),
            "line": e.get("line"),
            "recommended_pick": e.get("play"),
            "projection": info.get("Projection"),
            "model_probability": info.get("Model Prob"),
            "market_odds": info.get("FanDuel Over") if e.get("play") and "OVER" in str(e.get("play")).upper() else info.get("FanDuel Under"),
            "edge": e.get("edge"),
            "ev_pct": e.get("ev_pct"),
            "mm_tier": e.get("tier"),
            "confidence_level": info.get("Confidence Level"),
            "matchup": f"{info.get('away')} @ {info.get('home')}" if info.get("away") else None,
        })
    picks.sort(key=lambda p: p.get("ev_pct") or -999, reverse=True)
    return picks, row.get("updated_at")


def _get_lol_picks():
    if not supabase:
        return None, "SUPABASE_URL/SUPABASE_KEY not set on this server."
    row = _fetch_cache_row("LOL", _LOL_PIPELINE_CACHE_SENTINEL)
    if not row:
        return [], None
    pipeline_output = row.get("projection_data") or {}
    results = pipeline_output.get("results") or []
    picks = []
    for r in results:
        model_prob = r.get("recommended_model_prob")
        market_prob = r.get("recommended_market_prob")
        edge_pct = round((model_prob - market_prob) * 100, 1) if model_prob is not None and market_prob is not None else None
        odds = r.get("recommended_odds")
        picks.append({
            "home_team": r.get("team1_name"),
            "away_team": r.get("team2_name"),
            "sport": "LoL",
            "predicted_winner": r.get("recommended_team_name"),
            "recommended_pick": f"{r.get('recommended_team_name')} ({odds:+d})" if odds else r.get("recommended_team_name"),
            "confidence": round(model_prob * 100) if model_prob is not None else None,
            "model_probability": model_prob,
            "market_odds": odds,
            "implied_probability": market_prob,
            "edge_pct": edge_pct,
            "ev_pct": r.get("ev_pct"),
            "mm_tier": r.get("mm_tier"),
            "start_time": r.get("match_date"),
            "team1_rating": r.get("team1_rating"),
            "team2_rating": r.get("team2_rating"),
        })
    picks.sort(key=lambda p: p.get("edge_pct") or 0, reverse=True)
    return picks, row.get("updated_at")


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/lol-picks")
async def lol_picks(x_api_key: str = Header(default=None)):
    _require_api_key(x_api_key)
    picks, meta = _get_lol_picks()
    if picks is None:
        return {"error": meta, "picks": [], "count": 0}
    if not picks and meta is None:
        return {"error": "No cached picks available yet — the model hasn't run recently.", "picks": [], "count": 0}
    return {"picks": picks, "count": len(picks), "last_updated": meta}


@app.get("/api/{sport_slug}-picks")
async def sport_picks(sport_slug: str, x_api_key: str = Header(default=None)):
    """Real, single, generic endpoint covering every non-LoL sport —
    e.g. /api/mlb-picks, /api/nba-points-picks, /api/nfl-attempts-picks."""
    _require_api_key(x_api_key)
    sport_key = SPORT_KEYS.get(sport_slug)
    if not sport_key:
        return {"error": f"Unknown sport '{sport_slug}'. Real, valid options: {list(SPORT_KEYS.keys())} (or lol-picks separately)."}
    picks, meta = _get_player_prop_picks(sport_key)
    if picks is None:
        return {"error": meta, "picks": [], "count": 0}
    if not picks and meta is None:
        return {"error": "No cached picks available yet — the model hasn't run recently.", "picks": [], "count": 0}
    return {"picks": picks, "count": len(picks), "last_updated": meta}


@app.get("/api/all-picks")
async def all_picks(x_api_key: str = Header(default=None)):
    """Real, single, convenient endpoint returning every sport's real
    picks together in one real response, grouped by sport."""
    _require_api_key(x_api_key)
    result = {}
    for slug, sport_key in SPORT_KEYS.items():
        picks, _ = _get_player_prop_picks(sport_key)
        result[slug] = picks or []
    lol, _ = _get_lol_picks()
    result["lol"] = lol or []
    total = sum(len(v) for v in result.values())
    return {"sports": result, "total_count": total, "time": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
