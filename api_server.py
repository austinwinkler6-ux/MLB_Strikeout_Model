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
    pip install fastapi uvicorn supabase stripe

REQUIRED ENVIRONMENT VARIABLES
-------------------------------
    SUPABASE_URL       — same value your main Streamlit app uses
    SUPABASE_KEY       — same value your main Streamlit app uses (the
                          service_role key, not anon — needed to write
                          new trial rows for any real user)
    BRIDGE_API_KEY     — a real, private key YOU choose — required in a
                          real request header to access the picks
                          endpoints. Without this, anyone who finds
                          your API's URL could see every real pick your
                          model makes, for free.
    STRIPE_SECRET_KEY  — same value your main Streamlit app uses. Only
                          needed for the real /api/subscription-status
                          endpoint's real Stripe re-verification step —
                          everything else works fine without it, this
                          step just gets silently skipped.

RUN LOCALLY
-----------
    python api_server.py
    # then visit http://localhost:8000/api/health to check it's alive
"""

import os
from datetime import datetime, timedelta, timezone
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
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

if STRIPE_SECRET_KEY:
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

# Real, direct match to the exact same real constants mlb_app.py
# already uses — must stay in sync if either ever changes.
TRIAL_LENGTH_DAYS = 3
STRIPE_RECHECK_INTERVAL_SECONDS = 6 * 60 * 60

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
    """Real fix (August 2026, per direct user report — real, confirmed
    data existing in Supabase, yet the API kept showing 0 picks). This
    used to read from a real, OLDER, LoL-specific cache location
    (sport="LOL", the _cached_lol_full_pipeline's own real persistent
    cache) — but the actual real pipeline that feeds this whole API
    bridge writes LoL's real, finished picks to the SAME generic
    all-picks cache every other sport uses now (sport="lol_moneyline"),
    via build_todays_card_entries(). Two real, different cache
    locations, only one of which was ever actually being written to by
    the real, current auto-run flow — this was reading the wrong one."""
    if not supabase:
        return None, "SUPABASE_URL/SUPABASE_KEY not set on this server."
    row = _fetch_cache_row("lol_moneyline", _ALL_PICKS_CACHE_SENTINEL)
    if not row:
        return [], None
    entries = row.get("projection_data") or []
    picks = []
    for e in entries:
        r = e.get("info") or {}
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


def _get_user_from_jwt(authorization: str = Header(default=None)):
    """Real, direct verification of WHO is asking — completely
    different from _require_api_key above (which just checks a shared
    secret, proving "this is a request from our own real frontend,"
    not who the real, individual user is). This checks a real Supabase
    session JWT (sent by the Next.js app as a real 'Authorization:
    Bearer <token>' header, straight from the real, already-logged-in
    user's own real Supabase session) and asks Supabase itself to
    verify it and return the real, actual user it belongs to — the
    same real trust boundary Streamlit's own supabase.auth session
    already relies on, just verified server-side here instead."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing real Authorization: Bearer <token> header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_response = supabase.auth.get_user(token)
        return user_response.user
    except Exception:
        raise HTTPException(status_code=401, detail="Real, invalid or expired session token")


@app.get("/api/subscription-status")
async def subscription_status(authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, direct port of mlb_app.py's get_or_refresh_subscription —
    same real trial-creation, same real Stripe re-check throttling,
    same real returned shape ({status, days_left_in_trial, unlimited}).
    Kept as a real, single source of truth in ONE place conceptually
    (this function mirrors that one exactly) rather than letting the
    two real implementations quietly drift apart over time."""
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}

    user = _get_user_from_jwt(authorization)
    user_id = user.id
    email = user.email
    now = datetime.now(timezone.utc)

    try:
        res = supabase.table("subscriptions").select("*").eq("user_id", user_id).execute()
        row = res.data[0] if res.data else None
    except Exception:
        return {"status": "trialing", "days_left_in_trial": TRIAL_LENGTH_DAYS, "unlimited": False}

    if row is None:
        trial_end = now + timedelta(days=TRIAL_LENGTH_DAYS)
        try:
            supabase.table("subscriptions").insert({
                "user_id": user_id, "status": "trialing",
                "trial_start_date": now.isoformat(), "trial_end_date": trial_end.isoformat(),
            }).execute()
        except Exception:
            pass
        return {"status": "trialing", "days_left_in_trial": TRIAL_LENGTH_DAYS, "unlimited": False}

    status = row.get("status") or "trialing"
    stripe_subscription_id = row.get("stripe_subscription_id")
    last_check = row.get("last_stripe_check")

    if stripe_subscription_id and status in ("active", "past_due") and STRIPE_SECRET_KEY:
        should_recheck = True
        if last_check:
            try:
                last_check_dt = datetime.fromisoformat(str(last_check).replace("Z", "+00:00"))
                should_recheck = (now - last_check_dt).total_seconds() > STRIPE_RECHECK_INTERVAL_SECONDS
            except Exception:
                should_recheck = True
        if should_recheck:
            try:
                sub = stripe.Subscription.retrieve(stripe_subscription_id)
                new_status = "active" if sub.status in ("active", "trialing") else "expired"
                period_end = datetime.fromtimestamp(sub.current_period_end, tz=timezone.utc).isoformat()
                supabase.table("subscriptions").update({
                    "status": new_status, "current_period_end": period_end,
                    "last_stripe_check": now.isoformat(),
                }).eq("user_id", user_id).execute()
                status = new_status
            except Exception:
                pass

    if status == "active":
        return {"status": "active", "days_left_in_trial": None, "unlimited": True}

    if status == "trialing":
        trial_end_raw = row.get("trial_end_date")
        try:
            trial_end_dt = datetime.fromisoformat(str(trial_end_raw).replace("Z", "+00:00"))
        except Exception:
            trial_end_dt = now + timedelta(days=TRIAL_LENGTH_DAYS)
        if trial_end_dt <= now:
            try:
                supabase.table("subscriptions").update({"status": "expired"}).eq("user_id", user_id).execute()
            except Exception:
                pass
            return {"status": "expired", "days_left_in_trial": 0, "unlimited": False}
        days_left = max(1, int((trial_end_dt - now).total_seconds() // 86400) + 1)
        return {"status": "trialing", "days_left_in_trial": days_left, "unlimited": False}

    return {"status": "expired", "days_left_in_trial": 0, "unlimited": False}


@app.get("/api/lol-picks")
async def lol_picks(x_api_key: str = Header(default=None)):
    _require_api_key(x_api_key)
    picks, meta = _get_lol_picks()
    if picks is None:
        return {"error": meta, "picks": [], "count": 0}
    if not picks and meta is None:
        return {"error": "No cached picks available yet — the model hasn't run recently.", "picks": [], "count": 0}
    return {"picks": picks, "count": len(picks), "last_updated": meta}


@app.get("/api/all-picks")
async def all_picks(x_api_key: str = Header(default=None)):
    """Real, single, convenient endpoint returning every sport's real
    picks together in one real response, grouped by sport.

    Real fix (August 2026, per direct user report — "Unknown sport
    'all'" showing up instead of real combined picks). This route MUST
    be declared before the generic /api/{sport_slug}-picks route below
    — FastAPI/Starlette match real routes in real declaration order,
    and "/api/all-picks" itself matches that generic pattern with
    sport_slug="all", so the generic route was silently capturing this
    exact real request first and never reaching this one at all."""
    _require_api_key(x_api_key)
    result = {}
    errors = {}
    for slug, sport_key in SPORT_KEYS.items():
        picks, meta = _get_player_prop_picks(sport_key)
        if picks is None:
            # Real fix (August 2026, per direct user report — "0 total
            # picks" showing with no explanation) — this used to
            # discard the real error message (e.g. "SUPABASE_URL/
            # SUPABASE_KEY not set") and just show an empty list either
            # way, making a genuine configuration problem look
            # identical to "the cache is just empty right now."
            errors[slug] = meta
            result[slug] = []
        else:
            result[slug] = picks
    lol, lol_meta = _get_lol_picks()
    if lol is None:
        errors["lol"] = lol_meta
        result["lol"] = []
    else:
        result["lol"] = lol
    total = sum(len(v) for v in result.values())
    response = {"sports": result, "total_count": total, "time": datetime.now(timezone.utc).isoformat()}
    if errors:
        response["errors"] = errors
    return response


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
