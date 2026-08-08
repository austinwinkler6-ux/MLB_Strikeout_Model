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
    pip install fastapi uvicorn supabase stripe requests

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
                          endpoint's real Stripe re-verification step,
                          and the real checkout endpoints below —
                          everything else works fine without it, those
                          steps just get silently skipped/disabled.
    STRIPE_PRICE_ID    — same value your main Streamlit app uses. Only
                          needed for real checkout — the real
                          subscription/status checking works fine
                          without it.
    ODDS_API_KEY       — same value your main Streamlit app uses. Only
                          needed for real closing-line/CLV lookups —
                          everything else works fine without it.

RUN LOCALLY
-----------
    python api_server.py
    # then visit http://localhost:8000/api/health to check it's alive
"""

import os
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import requests

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
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

if STRIPE_SECRET_KEY:
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

# Real, direct import — bet_math.py is a real, pure Python module (no
# Streamlit dependency at all) that already sits alongside this file
# on Railway. Reusing the exact same, already-tested calculate_mm_
# stake function here avoids re-implementing that real, genuinely
# complex Kelly-staking logic (tier ranges, odds dampening, workload/
# confidence checks) a second time in a different language, where a
# subtle real mistake could easily go unnoticed.
from bet_math import calculate_mm_stake, odds_to_implied_prob, prob_to_american_odds, calculate_odds_clv

# Real, direct match to the exact same real constants mlb_app.py
# already uses — must stay in sync if either ever changes.
TRIAL_LENGTH_DAYS = 3
STRIPE_RECHECK_INTERVAL_SECONDS = 6 * 60 * 60

# Real, direct match to the exact same real constant in mlb_app.py —
# the admin account always gets real, full access regardless of trial/
# subscription state there, and needs to get the exact same real
# bypass here too, or their own real access would be tied to an
# ordinary trial that can genuinely expire.
ADMIN_EMAIL = "austinwinkler6@icloud.com"

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
        is_over = e.get("play") and "OVER" in str(e.get("play")).upper()
        picks.append({
            "player": e.get("name"),
            "sport": e.get("sport_label"),
            "line": e.get("line"),
            "recommended_pick": e.get("play"),
            "over_under": "Over" if is_over else "Under",
            "projection": info.get("Projection"),
            "model_probability": info.get("Model Prob"),
            "no_vig_probability": info.get("No Vig Prob"),
            "market_odds": info.get("FanDuel Over") if is_over else info.get("FanDuel Under"),
            "edge": e.get("edge"),
            "ev_pct": e.get("ev_pct"),
            "mm_tier": e.get("tier"),
            "confidence_level": info.get("Confidence Level"),
            "matchup": f"{info.get('away')} @ {info.get('home')}" if info.get("away") else None,
            # Real, raw info dict — needed as-is by /api/mm-stake to
            # compute a real stake recommendation for this exact real
            # pick, without needing this endpoint to guess at which
            # fields matter.
            "_raw_info": info,
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

    # Real, direct match to mlb_app.py's own admin bypass — the admin
    # account always gets real, full access, no real trial row ever
    # needed or created for them.
    if email and email.lower() == ADMIN_EMAIL.lower():
        return {"status": "active", "days_left_in_trial": None, "unlimited": True}

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


@app.post("/api/create-checkout-session")
async def create_checkout_session(request: Request, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, direct port of mlb_app.py's create_stripe_checkout_url —
    same real Stripe Checkout Session, same real allow_promotion_codes
    behavior. The real difference: success_url/cancel_url point back at
    whichever real site actually made this request (sent as
    'site_url' in the real request body, using the real browser's own
    window.location.origin) instead of the fixed real APP_BASE_URL
    Streamlit uses — this endpoint may get called from more than one
    real frontend over time."""
    _require_api_key(x_api_key)
    user = _get_user_from_jwt(authorization)
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        return {"error": "Stripe isn't configured on this server (STRIPE_SECRET_KEY/STRIPE_PRICE_ID)."}
    body = await request.json()
    site_url = body.get("site_url")
    if not site_url:
        return {"error": "Missing real 'site_url' in request body."}
    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            client_reference_id=user.id,
            customer_email=user.email,
            allow_promotion_codes=True,
            success_url=f"{site_url}?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{site_url}?checkout=cancelled",
        )
        return {"checkout_url": checkout_session.url}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/confirm-checkout")
async def confirm_checkout(request: Request, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, direct port of mlb_app.py's handle_stripe_checkout_return
    — same real reasoning: no live webhook receiver here either, so a
    real, successful subscription is confirmed by verifying the real
    checkout session directly against Stripe's own API when the real
    frontend calls this after landing back with
    ?checkout=success&session_id=..., rather than trusting the
    redirect alone."""
    _require_api_key(x_api_key)
    user = _get_user_from_jwt(authorization)
    if not STRIPE_SECRET_KEY:
        return {"success": False, "error": "Stripe isn't configured on this server."}
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        return {"success": False, "error": "Missing real 'session_id' in request body."}
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        if checkout_session.payment_status == "paid" or checkout_session.status == "complete":
            now = datetime.now(timezone.utc)
            subscription_id = checkout_session.subscription
            period_end_iso = None
            if subscription_id:
                sub = stripe.Subscription.retrieve(subscription_id)
                period_end_iso = datetime.fromtimestamp(sub.current_period_end, tz=timezone.utc).isoformat()
            supabase.table("subscriptions").upsert({
                "user_id": user.id, "status": "active",
                "stripe_customer_id": checkout_session.customer,
                "stripe_subscription_id": subscription_id,
                "current_period_end": period_end_iso,
                "last_stripe_check": now.isoformat(),
            }, on_conflict="user_id").execute()
            return {"success": True}
        return {"success": False, "error": f"Real checkout session status was '{checkout_session.status}' / payment_status '{checkout_session.payment_status}' — not confirmed as paid."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _sanitize_nan(v):
    """Real, direct match to mlb_app.py's own sanitization — a real,
    genuine NaN float breaks JSON encoding ('Out of range float values
    are not JSON compliant'), so any real NaN gets converted to a real
    None before ever reaching Supabase."""
    try:
        if isinstance(v, float) and v != v:  # NaN != NaN is real, always True
            return None
    except Exception:
        pass
    return v


@app.get("/api/user-settings")
async def get_user_settings_endpoint(authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, direct port of mlb_app.py's get_user_settings — same real
    table, same real user_id scoping. Returns None fields if the real
    user hasn't set up their real bankroll/risk style yet, rather than
    erroring — the real caller (the "Log" flow) falls back to a real,
    sensible default in that case."""
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    user = _get_user_from_jwt(authorization)
    try:
        res = supabase.table("user_settings").select("*").eq("user_id", user.id).execute()
        if res.data:
            return res.data[0]
        return {"starting_bankroll": None, "risk_style": None}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/mm-stake")
async def mm_stake_endpoint(request: Request, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, direct computation of the MM Stake recommendation for a
    specific real pick — uses the SAME real calculate_mm_stake function
    mlb_app.py itself calls, imported directly rather than
    reimplemented, fetching the real, current user's own real bankroll/
    risk style first. Real request body: {"info": {...pick fields...},
    "result": {...optional confidence_tier/workload_tier...}}"""
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    user = _get_user_from_jwt(authorization)
    body = await request.json()
    info = body.get("info") or {}
    result = body.get("result") or {}

    try:
        res = supabase.table("user_settings").select("*").eq("user_id", user.id).execute()
        settings = res.data[0] if res.data else None
    except Exception:
        settings = None

    # Real, sensible default — same real fallback Streamlit itself
    # effectively uses for a real, brand-new user who hasn't set a
    # real bankroll yet.
    bankroll = (settings or {}).get("starting_bankroll") or 1000
    risk_style = (settings or {}).get("risk_style") or "Standard"

    try:
        stake = calculate_mm_stake(info, result, bankroll, risk_style)
        return {"stake": stake, "bankroll": bankroll, "risk_style": risk_style}
    except Exception as e:
        return {"error": str(e)}


def _get_odds_api_sport_and_market(sport):
    """Real, direct port of mlb_app.py's get_odds_api_sport_and_market."""
    mapping = {
        "MLB": ("baseball_mlb", "pitcher_strikeouts"),
        "NBA": ("basketball_nba", "player_points"),
        "NBA_AST": ("basketball_nba", "player_assists"),
        "NFL": ("americanfootball_nfl", "player_pass_attempts"),
        "NFL_COMPLETIONS": ("americanfootball_nfl", "player_pass_completions"),
        "NFL_RECEPTIONS": ("americanfootball_nfl", "player_receptions"),
    }
    return mapping.get(sport, (None, None))


def _fetch_closing_line(sport, player_name, direction, game_date_str):
    """Real, direct port of mlb_app.py's fetch_closing_line — same real
    Odds API historical endpoints, same real consensus-line logic. Real,
    honest simplification: no real 7-day caching layer here (unlike
    Streamlit's own @st.cache_data) — this is called rarely enough (a
    real user manually refreshing their own real bets, not on every
    real page load) that this is a real, acceptable tradeoff for now
    rather than adding real caching infrastructure this endpoint alone
    doesn't yet need."""
    api_sport, market = _get_odds_api_sport_and_market(sport)
    if not api_sport or not ODDS_API_KEY:
        return None, None
    try:
        snapshot_time = f"{game_date_str}T12:00:00Z"
        events_res = requests.get(
            f"https://api.the-odds-api.com/v4/historical/sports/{api_sport}/events",
            params={"apiKey": ODDS_API_KEY, "date": snapshot_time}, timeout=20,
        )
        events_res.raise_for_status()
        events = events_res.json().get("data", [])
        for event in events:
            event_id = event["id"]
            commence_time = event["commence_time"]
            odds_res = requests.get(
                f"https://api.the-odds-api.com/v4/historical/sports/{api_sport}/events/{event_id}/odds",
                params={"apiKey": ODDS_API_KEY, "regions": "us", "markets": market, "oddsFormat": "american", "date": commence_time},
                timeout=20,
            )
            odds_res.raise_for_status()
            data = odds_res.json().get("data", {}) or {}
            points = []
            for bookmaker in data.get("bookmakers", []):
                for mkt in bookmaker.get("markets", []):
                    if mkt["key"] == market:
                        for outcome in mkt["outcomes"]:
                            if (outcome.get("description", "").lower() == player_name.lower()
                                    and outcome.get("name", "").lower() == direction.lower()):
                                points.append({"line": outcome["point"], "odds": outcome["price"]})
            if points:
                from collections import Counter
                line_counts = Counter(p["line"] for p in points)
                consensus_line = line_counts.most_common(1)[0][0]
                matching_points = [p for p in points if p["line"] == consensus_line]
                avg_prob = sum(odds_to_implied_prob(p["odds"]) for p in matching_points) / len(matching_points)
                avg_odds = prob_to_american_odds(avg_prob)
                return consensus_line, avg_odds
        return None, None
    except Exception:
        return None, None


@app.post("/api/refresh-closing-line/{bet_id}")
async def refresh_closing_line(bet_id: str, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, single, atomic operation covering what mlb_app.py's own
    Closing Line Tracker does across several real steps: looks up ONE
    real, specific bet (verifying it genuinely belongs to the real,
    requesting user first), fetches its real closing line/odds, computes
    real CLV, and updates the real bet record — all in one real call."""
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    if not ODDS_API_KEY:
        return {"error": "ODDS_API_KEY not set on this server."}
    user = _get_user_from_jwt(authorization)
    try:
        res = supabase.table("bets").select("*").eq("id", bet_id).eq("user_id", user.id).execute()
        if not res.data:
            return {"error": "Real bet not found, or doesn't belong to you."}
        bet = res.data[0]
    except Exception as e:
        return {"error": str(e)}

    sport = bet.get("sport")
    player_name = bet.get("pitcher")
    direction = bet.get("over_under")
    game_date = bet.get("date")
    placed_odds = bet.get("odds")

    if not all([sport, player_name, direction, game_date]):
        return {"error": "This bet is missing sport/player/over_under/date — can't look up a closing line for it."}

    closing_line, closing_odds = _fetch_closing_line(sport, player_name, direction, game_date)
    if closing_line is None:
        return {"success": False, "error": "No real closing line found for this bet yet — try again closer to game time, or the game may be too far in the past for the historical API."}

    odds_clv = calculate_odds_clv(placed_odds, closing_odds) if placed_odds and closing_odds else None

    try:
        supabase.table("bets").update({
            "closing_line": closing_line, "closing_odds": closing_odds, "odds_clv": odds_clv,
        }).eq("id", bet_id).eq("user_id", user.id).execute()
        return {"success": True, "closing_line": closing_line, "closing_odds": closing_odds, "odds_clv": odds_clv}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/bets")
async def get_bets(sport: str = None, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, direct port of mlb_app.py's load_bets — same real,
    explicit user_id scoping (not relying on any real database-level
    RLS policy, which hasn't been verified to exist — this app's own
    real service_role key already bypasses RLS regardless, so this
    endpoint does the real, same explicit filtering in code that
    mlb_app.py already does)."""
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    user = _get_user_from_jwt(authorization)
    try:
        query = supabase.table("bets").select("*").eq("user_id", user.id)
        if sport:
            query = query.eq("sport", sport)
        res = query.order("created_at", desc=True).execute()
        return {"bets": res.data or []}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/bets")
async def create_bet(request: Request, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, direct port of mlb_app.py's save_bet — same real NaN
    sanitization, same real user_id stamping (the real, authenticated
    user's own ID, from their real JWT — never trusted from the
    real request body itself, so a real user can never log a bet
    under someone else's real account)."""
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    user = _get_user_from_jwt(authorization)
    body = await request.json()
    bet = {k: _sanitize_nan(v) for k, v in body.items()}
    bet["user_id"] = user.id
    try:
        supabase.table("bets").insert(bet).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.patch("/api/bets/{bet_id}")
async def update_bet_endpoint(bet_id: str, request: Request, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, direct port of mlb_app.py's update_bet — same real
    double-scoped update (.eq('id', bet_id).eq('user_id', user.id)),
    so a real user can never update a bet that isn't genuinely theirs,
    even if they somehow guessed another real bet's real ID."""
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    user = _get_user_from_jwt(authorization)
    body = await request.json()
    updates = {k: _sanitize_nan(v) for k, v in body.items()}
    try:
        supabase.table("bets").update(updates).eq("id", bet_id).eq("user_id", user.id).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/bets/{bet_id}")
async def delete_bet_endpoint(bet_id: str, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, direct port of mlb_app.py's delete_bet — same real
    double-scoped delete, same real protection against deleting
    another real user's bet."""
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    user = _get_user_from_jwt(authorization)
    try:
        supabase.table("bets").delete().eq("id", bet_id).eq("user_id", user.id).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


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
