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
from bet_math import calculate_mm_stake, odds_to_implied_prob, prob_to_american_odds, calculate_odds_clv, mm_today_str, generate_why, calc_profit

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
    "nfl-td": "nfl_td",
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
        result = e.get("result") or {}
        is_over = e.get("play") and "OVER" in str(e.get("play")).upper()
        direction = "over" if is_over else "under"
        # Real, direct reuse of the exact same "why this bet" logic
        # mlb_app.py itself uses — computed here, once, server-side,
        # rather than asking the Next.js site to reimplement any of
        # this real betting logic in a second language.
        try:
            why_lines = generate_why(info, result, direction, sport_key)
        except Exception:
            why_lines = []
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
            "start_time": info.get("commence_time"),
            "book_odds": info.get("book_odds", []),
            "odds_api_event_id": info.get("odds_api_event_id"),
            "odds_api_sport": info.get("odds_api_sport"),
            "odds_api_market": info.get("odds_api_market"),
            "why_lines": why_lines,
            # Real, raw info/result dicts — needed as-is by /api/mm-stake
            # to compute a real stake recommendation for this exact real
            # pick, without needing this endpoint to guess at which
            # fields matter.
            "_raw_info": info,
            "_raw_result": result,
        })
    picks.sort(key=lambda p: (_TIER_RANK.get(p.get("mm_tier"), -1), p.get("ev_pct") or -999), reverse=True)
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
        # Real, new addition (August 2026) — LoL picks now get the
        # same real "why this bet" lines every other sport already
        # has, using generate_why with sport='lol_moneyline' which
        # routes to a dedicated LoL-specific builder (rating
        # comparison, model vs market edge, H2H, tournament form,
        # roster continuity, etc.) rather than the prop-oriented
        # generic lines which would all be wrong for LoL's data shape.
        try:
            why_lines = generate_why(r, r, None, 'lol_moneyline')
        except Exception:
            why_lines = []
        # Real, adapted info dict — calculate_mm_stake expects field
        # names like 'MM Tier', 'Model Prob', 'Odds' (the standard
        # format every prop-sport evaluate_*_quotes function produces),
        # but LoL's pipeline result uses its own names ('mm_tier',
        # 'recommended_model_prob', etc.). This adapter translates
        # LoL's real fields into the standard format so the same real
        # calculate_mm_stake function works for LoL too.
        lol_adapted_info = {
            'MM Tier': r.get('mm_tier'),
            'Model Prob': r.get('recommended_model_prob'),
            'Odds': r.get('recommended_odds'),
            'Edge': r.get('edge_pct'),
            'EV%': r.get('ev_pct'),
        }
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
            "why_lines": why_lines,
            "_raw_info": lol_adapted_info,
            "_raw_result": {},
        })
    picks.sort(key=lambda p: (_TIER_RANK.get(p.get("mm_tier"), -1), p.get("edge_pct") or -999), reverse=True)
    return picks, row.get("updated_at")


# Real, small, local copy — matches mlb_app.py's own real TIER_RANK
# exactly. Small enough that a full move-to-bet_math.py refactor
# wasn't worth the real extra risk tonight; kept here deliberately in
# sync with the real original by value, not by import.
_TIER_RANK = {"🟢 Best Bet": 3, "🔵 Worth a Look": 2, "🟡 Lean": 1, "🔴 Pass": 0}


@app.get("/api/play-of-the-day")
async def play_of_the_day(x_api_key: str = Header(default=None)):
    """Real, public (no user auth needed — this is deliberately shown
    to real, non-subscribed users too) single best pick across every
    real sport today, using the exact same real ranking logic as
    mlb_app.py's own top_ranked_entry(): tier first, then EV%, then
    edge. Real, deliberate exclusion — LoL is never eligible here, by
    real, direct user request: esports picks are meant to stay their
    own real, exclusive thing, not given away as a free teaser."""
    _require_api_key(x_api_key)
    all_picks = []
    for slug, sport_key in SPORT_KEYS.items():
        picks, _ = _get_player_prop_picks(sport_key)
        if picks:
            for p in picks:
                p["_kind"] = "prop"
                all_picks.append(p)
    if not all_picks:
        return {"pick": None}

    def _rank_key(p):
        ev = p.get("ev_pct")
        edge = p.get("edge")
        return (
            _TIER_RANK.get(p.get("mm_tier"), -1),
            ev if ev is not None else -999,
            abs(edge) if edge is not None else -999,
        )

    best = max(all_picks, key=_rank_key)
    return {"pick": best}


@app.get("/api/model-performance")
async def model_performance(x_api_key: str = Header(default=None)):
    """Real, public (no user auth needed) aggregate track record —
    Phase 1: MLB + NBA only, matching what's actually being graded
    right now in mlb_app.py's grade_pending_picks(). NFL/LoL picks are
    being recorded already but not yet graded, so they're real,
    honestly excluded from this real number rather than silently
    counted as 0-for-0."""
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    try:
        res = supabase.table("graded_picks").select("*").in_("result", ["win", "loss"]).execute()
        rows = res.data or []
    except Exception as e:
        return {"error": str(e)}

    wins = sum(1 for r in rows if r["result"] == "win")
    losses = sum(1 for r in rows if r["result"] == "loss")
    total = wins + losses
    win_rate = round(wins / total * 100, 1) if total > 0 else None

    # Real, flat, standardized 1-unit stake per pick for this real ROI
    # figure — a real, honest, comparable number across every pick
    # regardless of what any individual user actually staked, since
    # this is a real MODEL track record, not any one user's own P/L.
    total_profit = 0.0
    total_staked = 0.0
    for r in rows:
        odds = r.get("odds")
        if odds is None:
            continue
        stake = 100
        profit = calc_profit(stake, odds, "Win" if r["result"] == "win" else "Loss")
        total_profit += profit
        total_staked += stake
    roi_pct = round(total_profit / total_staked * 100, 1) if total_staked > 0 else None

    by_sport = {}
    for r in rows:
        sk = r.get("sport_key")
        by_sport.setdefault(sk, {"wins": 0, "losses": 0})
        by_sport[sk]["wins" if r["result"] == "win" else "losses"] += 1

    return {
        "wins": wins,
        "losses": losses,
        "total_graded": total,
        "win_rate": win_rate,
        "roi_pct": roi_pct,
        "by_sport": by_sport,
    }


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
                supabase.table("subscriptions").update({
                    "status": new_status,
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
        if checkout_session.payment_status == "paid" or checkout_session.payment_status == "no_payment_required" or checkout_session.status == "complete":
            now = datetime.now(timezone.utc)
            subscription_id = checkout_session.subscription

            # Update the existing row rather than upsert — the row
            # already exists (created during trial signup), so we just
            # need to flip the status to active and store the Stripe IDs.
            # This avoids NOT NULL constraint issues on columns like
            # trial_end_date that were set during the original insert.
            supabase.table("subscriptions").update({
                "status": "active",
                "stripe_customer_id": checkout_session.customer,
                "stripe_subscription_id": subscription_id,
            }).eq("user_id", user.id).execute()
            return {"success": True}
        return {"success": False, "error": f"Real checkout session status was '{checkout_session.status}' / payment_status '{checkout_session.payment_status}' — not confirmed as paid."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/billing-portal")
async def billing_portal(request: Request, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    """Real, direct port of mlb_app.py's create_stripe_billing_portal_url
    — same real self-service flow, letting an active real subscriber
    update payment method or cancel on their own, real Stripe-hosted
    page, without needing you to do it manually on their behalf."""
    _require_api_key(x_api_key)
    user = _get_user_from_jwt(authorization)
    if not STRIPE_SECRET_KEY or not supabase:
        return {"error": "Stripe/Supabase isn't fully configured on this server."}
    body = await request.json()
    site_url = body.get("site_url")
    if not site_url:
        return {"error": "Missing real 'site_url' in request body."}
    try:
        res = supabase.table("subscriptions").select("stripe_customer_id").eq("user_id", user.id).execute()
        row = res.data[0] if res.data else None
        stripe_customer_id = row.get("stripe_customer_id") if row else None
        if not stripe_customer_id:
            return {"error": "No real Stripe customer on file yet — subscribe first."}
        portal_session = stripe.billing_portal.Session.create(customer=stripe_customer_id, return_url=site_url)
        return {"portal_url": portal_session.url}
    except Exception as e:
        return {"error": str(e)}


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


@app.post("/api/user-settings")
async def save_user_settings_endpoint(request: Request, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    user = _get_user_from_jwt(authorization)
    body = await request.json()
    starting_bankroll = body.get("starting_bankroll")
    risk_style = body.get("risk_style")
    reset_baseline = body.get("reset_baseline", True)
    try:
        payload = {
            "user_id": user.id,
            "starting_bankroll": starting_bankroll,
            "risk_style": risk_style,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if reset_baseline:
            payload["bankroll_set_date"] = mm_today_str()
        supabase.table("user_settings").upsert(payload, on_conflict="user_id").execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/bankroll-transactions")
async def get_bankroll_transactions(authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    user = _get_user_from_jwt(authorization)
    try:
        res = supabase.table("bankroll_transactions").select("*").eq("user_id", user.id).order("transaction_date", desc=True).execute()
        return {"transactions": res.data or []}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/bankroll-transactions")
async def create_bankroll_transaction(request: Request, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
    _require_api_key(x_api_key)
    if not supabase:
        return {"error": "SUPABASE_URL/SUPABASE_KEY not set on this server."}
    user = _get_user_from_jwt(authorization)
    body = await request.json()
    amount = body.get("amount")
    if amount is None:
        return {"success": False, "error": "Missing real 'amount' in request body."}
    try:
        supabase.table("bankroll_transactions").insert({
            "user_id": user.id,
            "amount": amount,
            "transaction_date": mm_today_str(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/mm-stake")
async def mm_stake_endpoint(request: Request, authorization: str = Header(default=None), x_api_key: str = Header(default=None)):
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

    bankroll = (settings or {}).get("starting_bankroll") or 1000
    risk_style = (settings or {}).get("risk_style") or "Standard"

    try:
        stake = calculate_mm_stake(info, result, bankroll, risk_style)
        return {"stake": stake, "bankroll": bankroll, "risk_style": risk_style}
    except Exception as e:
        return {"error": str(e)}


def _get_odds_api_sport_and_market(sport):
    mapping = {
        "MLB": ("baseball_mlb", "pitcher_strikeouts"),
        "NBA": ("basketball_nba", "player_points"),
        "NBA_AST": ("basketball_nba", "player_assists"),
        "NFL": ("americanfootball_nfl", "player_pass_attempts"),
        "NFL_COMPLETIONS": ("americanfootball_nfl", "player_pass_completions"),
        "NFL_RECEPTIONS": ("americanfootball_nfl", "player_receptions"),
        "NFL_TD": ("americanfootball_nfl", "player_anytime_td"),
    }
    return mapping.get(sport, (None, None))


def _fetch_closing_line(sport, player_name, direction, game_date_str):
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


@app.get("/api/live-odds")
async def live_odds(
    event_id: str,
    sport: str,
    market: str,
    player: str = None,
    x_api_key: str = Header(default=None),
):
    """Fetches fresh, real-time odds from The Odds API for a single
    event + market + player — called on-demand by the frontend when a
    user opens the odds comparison dropdown, so they always see current
    prices instead of stale cached data. One API credit per call, only
    burned when a user actually clicks."""
    _require_api_key(x_api_key)
    if not ODDS_API_KEY:
        return {"error": "ODDS_API_KEY not configured", "book_odds": []}
    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds",
            params={"apiKey": ODDS_API_KEY, "regions": "us", "markets": market, "oddsFormat": "american"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        book_odds_raw = {}
        for bookmaker in data.get("bookmakers", []):
            book_title = bookmaker.get("title", bookmaker.get("key", ""))
            for mkt in bookmaker.get("markets", []):
                if mkt.get("key") == market:
                    for outcome in mkt.get("outcomes", []):
                        # Filter by player name if provided
                        if player and outcome.get("description", "").lower() != player.lower():
                            continue
                        if book_title not in book_odds_raw:
                            book_odds_raw[book_title] = {"book": book_title, "line": outcome.get("point"), "over": None, "under": None}
                        if outcome.get("name") == "Over":
                            book_odds_raw[book_title]["over"] = outcome.get("price")
                        else:
                            book_odds_raw[book_title]["under"] = outcome.get("price")
                        book_odds_raw[book_title]["line"] = outcome.get("point")
        book_odds = sorted(book_odds_raw.values(), key=lambda b: b.get("book", ""))
        return {"book_odds": book_odds, "fetched_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"error": str(e), "book_odds": []}


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
