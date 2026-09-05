import streamlit as st
import time
import requests
import statistics
import unicodedata
import pandas as pd
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from collections import Counter
from io import StringIO
from supabase import create_client, Client
from streamlit_cookies_controller import CookieController
from scipy import stats

# Real fix (July 2026, per external review, item 8) — these 18
# functions and 4 constants used to be defined inline here, duplicated
# from a second copy in bet_math.py that only existed for testing.
# Now genuinely extracted for real: mlb_app.py imports the actual,
# tested code (53 passing tests, verified line-for-line against what
# used to be here) instead of maintaining two copies that could quietly
# drift apart if one got edited without the other. bet_math.py must
# be deployed alongside this file — it's a required, real dependency
# now, not an optional testing artifact.
from bet_math import (
    remove_vig, projection_to_probability, calculate_ev, calculate_ev_pct,
    prob_to_american_odds, odds_to_cents, calculate_odds_edge_cents,
    odds_to_implied_prob, calculate_odds_clv, fmt_signed_num, calc_profit,
    calc_profit_this_month, calc_decimal_odds, has_book_disagreement,
    calculate_mm_stake, get_stake_deviation_pct, format_stake_deviation_message,
    mm_today_str, RISK_STYLE_CAPS, RISK_STYLE_RANGE_MULTIPLIER,
    TIER_STAKE_RANGES, STAKE_DEVIATION_PERFECT_THRESHOLD,
    # Real, moved here (August 2026) so api_server.py can call the exact
    # same real "why this bet" / workload-evidence logic this app uses,
    # with zero real risk of the two products' explanations drifting
    # apart over time. Behavior is completely unchanged — same real
    # functions, just imported instead of defined locally.
    fmt_odds, workload_evidence_line, generate_why,
)

# Real fix (July 2026) — nflreadpy's default download timeout is 30
# seconds, genuinely too tight for a large parquet file (like a full
# season's weekly player stats) on a slow or congested connection —
# this was causing real, reproducible ReadTimeoutErrors that killed
# entire backtest runs partway through. Bumped to 90 seconds, applied
# once here at startup so every nflreadpy call in the app benefits,
# rather than needing this set inside each individual function.
# Wrapped defensively — if this specific nflreadpy version doesn't
# support this config option, or the import itself fails for any
# reason, we don't want a config-setting failure to break the whole app
# before it even starts.
try:
    from nflreadpy.config import update_config as _update_nflreadpy_config
    _update_nflreadpy_config(timeout=90)
except Exception:
    pass

st.set_page_config(page_title="Model Metrics", page_icon="⚾", layout="wide")

# ==================== GLOBAL DESIGN SYSTEM ====================
def inject_custom_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap');

    :root {
        --mm-bg: #0A0E1A;
        --mm-panel: #11172A;
        --mm-panel-2: #161D33;
        --mm-border: #232B45;
        --mm-text: #E8EAF0;
        --mm-text-dim: #8A93AB;
        --mm-text-faint: #5B6479;
        --mm-accent: #E8A33D;
        --mm-accent-hover: #F2B457;
        --mm-success: #34D399;
        --mm-info: #60A5FA;
        --mm-warn: #FBBF24;
        --mm-danger: #F87171;
        --mm-mono: 'JetBrains Mono', monospace;
        --mm-display: 'Space Grotesk', sans-serif;
        --mm-body: 'Inter', sans-serif;
    }

    html, body, .stApp {
        background-color: var(--mm-bg) !important;
        font-family: var(--mm-body);
        color: var(--mm-text);
    }

    h1, h2, h3 {
        font-family: var(--mm-display) !important;
        letter-spacing: -0.01em;
    }

    p, span, div, label { font-family: var(--mm-body); }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: var(--mm-panel) !important;
        border-right: 1px solid var(--mm-border);
    }
    [data-testid="stSidebar"] .stRadio [role="radiogroup"] label {
        padding: 9px 12px;
        border-radius: 8px;
        margin-bottom: 2px;
        transition: background-color 0.15s ease;
        font-size: 0.95rem;
    }
    [data-testid="stSidebar"] .stRadio [role="radiogroup"] label:hover {
        background-color: var(--mm-panel-2);
    }
    [data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] p {
        color: var(--mm-text-faint) !important;
    }

    /* Buttons */
    .stButton > button {
        background-color: var(--mm-panel-2);
        color: var(--mm-text);
        border: 1px solid var(--mm-border);
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.15s ease;
        white-space: nowrap;
        padding-left: 10px;
        padding-right: 10px;
    }
    .stButton > button:hover {
        border-color: var(--mm-accent);
        color: var(--mm-accent);
    }
    .stButton > button[kind="primary"] {
        background-color: var(--mm-accent);
        color: #0A0E1A;
        border: none;
        font-weight: 600;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: var(--mm-accent-hover);
    }

    /* Metrics */
    [data-testid="stMetric"] {
        background-color: var(--mm-panel);
        border: 1px solid var(--mm-border);
        border-radius: 10px;
        padding: 14px 16px;
    }
    [data-testid="stMetricValue"] {
        font-family: var(--mm-mono) !important;
        color: var(--mm-text) !important;
    }
    [data-testid="stMetricLabel"] {
        color: var(--mm-text-dim) !important;
    }

    /* Numeric / data-heavy widgets get mono for scan-ability */
    .stDataFrame, .stDataFrame * {
        font-family: var(--mm-mono) !important;
    }
    [data-testid="stNumberInput"] input {
        font-family: var(--mm-mono);
    }

    /* Inputs */
    input, textarea, .stSelectbox div[data-baseweb="select"] {
        background-color: var(--mm-panel-2) !important;
        border-color: var(--mm-border) !important;
        color: var(--mm-text) !important;
        border-radius: 8px !important;
    }

    /* Expanders (Why this bet / Log bet) */
    [data-testid="stExpander"] {
        background-color: var(--mm-panel);
        border: 1px solid var(--mm-border);
        border-radius: 10px;
    }

    /* Never break mid-word in tight columns — wrap at spaces or overflow instead */
    [data-testid="column"] p, [data-testid="column"] span, [data-testid="column"] div {
        overflow-wrap: normal;
        word-break: keep-all;
    }

    /* Dividers */
    hr {
        border-color: var(--mm-border) !important;
    }

    /* Tier badges */
    .mm-badge {
        display: inline-block;
        font-family: var(--mm-body);
        font-weight: 600;
        font-size: 0.82rem;
        padding: 3px 11px;
        border-radius: 999px;
        white-space: nowrap;
        border: 1px solid transparent;
    }
    .mm-badge-best { background: rgba(52,211,153,0.12); color: var(--mm-success); border-color: rgba(52,211,153,0.35); }
    .mm-badge-playable { background: rgba(96,165,250,0.12); color: var(--mm-info); border-color: rgba(96,165,250,0.35); }
    .mm-badge-lean { background: rgba(251,191,36,0.12); color: var(--mm-warn); border-color: rgba(251,191,36,0.35); }
    .mm-badge-pass { background: rgba(248,113,113,0.12); color: var(--mm-danger); border-color: rgba(248,113,113,0.35); }
    .mm-badge-neutral { background: var(--mm-panel-2); color: var(--mm-text-dim); border-color: var(--mm-border); }

    /* Reusable card */
    .mm-card {
        background-color: var(--mm-panel);
        border: 1px solid var(--mm-border);
        border-radius: 12px;
        padding: 24px;
        box-sizing: border-box;
        box-shadow: 0 1px 2px rgba(0,0,0,0.24), 0 1px 3px rgba(0,0,0,0.16);
        transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
    }
    .mm-card:hover {
        border-color: #2E3757;
        box-shadow: 0 6px 16px rgba(0,0,0,0.3), 0 2px 6px rgba(0,0,0,0.2);
    }

    /* Real fix (August 2026, per direct user request — "make it look
       cleaner") — a handful of real, high-leverage polish passes on top
       of the existing, already-distinct design system (not a redesign):
       depth on cards (above), a refined scrollbar, visible keyboard
       focus (a real accessibility floor, not just decoration), and
       tighter typographic rhythm — small, deliberate details that read
       as "considered" rather than "default Streamlit," without
       changing the app's actual established identity. */

    /* Custom scrollbar — default OS scrollbars read as unfinished on a
       custom dark theme like this one. */
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: var(--mm-bg); }
    ::-webkit-scrollbar-thumb { background: var(--mm-border); border-radius: 6px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--mm-text-faint); }

    /* Real, tighter heading rhythm — Streamlit's own defaults leave
       inconsistent, slightly loose spacing above/below headings. */
    h1 { margin-bottom: 0.4em; }
    h2, h3 { margin-top: 1.1em; margin-bottom: 0.35em; }

    /* Tabs — a subtle underline treatment on the active tab, matching
       the accent color already used throughout, instead of Streamlit's
       plain default. */
    .stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--mm-border); }
    .stTabs [data-baseweb="tab"] { color: var(--mm-text-dim); font-weight: 500; }
    .stTabs [aria-selected="true"] { color: var(--mm-text) !important; }
    .stTabs [data-baseweb="tab-highlight"] { background-color: var(--mm-accent) !important; height: 2px; }

    /* Real dataframe polish — softer internal grid lines than
       Streamlit's default, so dense tables (the LoL diagnostics, bet
       history) read as considered rather than a bare spreadsheet. */
    [data-testid="stDataFrame"] { border: 1px solid var(--mm-border); border-radius: 10px; overflow: hidden; }

    /* Streamlit's own default top padding is large — trim it so page content
       (especially Home) starts higher up instead of leaving a big gap. */
    .block-container {
        padding-top: 4.5rem !important;
    }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

def tier_badge(tier_text, compact=False):
    """Render an MM Tier string as a colored pill badge.
    compact=True shrinks font/padding for tight row layouts (MLB/NBA tables)."""
    if not tier_text:
        return "<span class='mm-badge mm-badge-neutral'>—</span>"
    if "Best Bet" in tier_text:
        cls = "mm-badge-best"
    elif "Worth a Look" in tier_text:
        cls = "mm-badge-playable"
    elif "Lean" in tier_text:
        cls = "mm-badge-lean"
    elif "Pass" in tier_text:
        cls = "mm-badge-pass"
    else:
        cls = "mm-badge-neutral"
    style = "style='font-size:0.72rem; padding:2px 8px; white-space:normal; line-height:1.3;'" if compact else ""
    return f"<span class='mm-badge {cls}' {style}>{tier_text}</span>"

def short_tier_label(tier_text):
    """Abbreviates the longest confidence-tier label for tight row layouts only —
    full text still used everywhere else (Why this bet?, Bet Tracker, etc.)."""
    if not tier_text:
        return "—"
    if "Uncertain Workload" in tier_text:
        return "🔴 Uncertain"
    return tier_text

# Real, moved to bet_math.py (August 2026) so api_server.py can call the
# exact same real logic — imported at the top of this file now instead
# of defined here. Behavior unchanged.

ODDS_API_KEY = st.secrets["ODDS_API_KEY"]
ADMIN_EMAIL = "austinwinkler6@icloud.com"

# ---- PAYWALL / STRIPE ----
# Real addition (July 2026) — optional, same pattern as ANTHROPIC_API_KEY/
# CITO_API_KEY/BDL_API_KEY elsewhere in this app (st.secrets.get(...), not
# a hard-required st.secrets[...]). This is deliberate: the paywall code
# below can ship and deploy NOW, safely inert, without needing Stripe set
# up yet — PAYWALL_ENABLED only flips to True once all three real secrets
# (STRIPE_SECRET_KEY, STRIPE_PRICE_ID, APP_BASE_URL) are actually
# configured. Until then, every user gets full, unrestricted access and
# no paywall UI shows anywhere — a missing/incomplete Stripe setup should
# never accidentally lock out every real user or crash the app on boot.
STRIPE_SECRET_KEY = st.secrets.get("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = st.secrets.get("STRIPE_PRICE_ID")
APP_BASE_URL = st.secrets.get("APP_BASE_URL")
PAYWALL_ENABLED = bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID and APP_BASE_URL)
if PAYWALL_ENABLED:
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

TRIAL_LENGTH_DAYS = 3
# Real, throttled re-verification interval against Stripe's own API for
# any user with a real, currently-active subscription — this app uses a
# Checkout-redirect-then-verify flow rather than a live webhook receiver
# (Streamlit doesn't expose arbitrary custom routes the way a normal
# backend would), so this periodic re-check is what catches a real
# cancellation or failed renewal on Stripe's side without needing one.
# 6 hours is a real, deliberate balance — frequent enough that a real
# cancellation doesn't go unnoticed for long, infrequent enough that it
# doesn't add a real Stripe API call to every single page load.
STRIPE_RECHECK_INTERVAL_SECONDS = 6 * 60 * 60

# ---- EV CALCULATOR ----
EDGE_THRESHOLDS = {
    "mlb_strikeouts": 0.75,
    "nba_assists": 0.75,
    "nba_points": 1.5,
    "nfl_pass_attempts": 2.0,
    "nfl_pass_completions": 1.5,
    "nfl_receptions": 1.0,
}

def get_min_std_dev(cv, projection, sport='mlb_strikeouts'):
    if sport == 'mlb_strikeouts':
        if cv >= 0.50:
            return max(4.5, projection * 0.80)
        elif cv >= 0.35:
            return max(3.5, projection * 0.65)
        elif cv >= 0.20:
            return max(2.0, projection * 0.30)
        else:
            return max(1.6, projection * 0.25)
    elif sport == 'mlb_batter_hits':
        # Real, direct match to the backtest's own fallback formula
        # (project_batter_hits' std_dev computation) — a real minimum
        # floor under whatever std_dev this batter's own recent hits
        # variance produces, not a fresh guess.
        return max(0.8, projection * 0.5)
    elif sport == 'nba_points':
        return max(5.0, projection * 0.22)
    elif sport == 'nba_assists':
        return max(1.5, projection * 0.25)
    elif sport == 'nfl_pass_attempts':
        if cv >= 0.30:
            return max(6.0, projection * 0.22)
        elif cv >= 0.18:
            return max(4.5, projection * 0.16)
        else:
            return max(3.5, projection * 0.12)
    elif sport == 'nfl_pass_completions':
        # Real branch built (July 2026) — previously fell through to the
        # generic max(1.5, projection*0.25) fallback, never actually
        # calibrated for this stat. Scaled down from Attempts' pattern,
        # roughly proportional to Completions' validated ~4.7-4.9 MAE
        # range (vs. Attempts' ~6.9-7.1) — completions naturally have a
        # smaller typical magnitude and a somewhat tighter spread than
        # raw attempts, since a completion also has to clear a
        # catch/accuracy threshold beyond just being thrown.
        if cv >= 0.20:
            return max(4.5, projection * 0.20)
        elif cv >= 0.12:
            return max(3.5, projection * 0.15)
        else:
            return max(2.8, projection * 0.11)
    elif sport == 'nfl_receptions':
        # Real branch built (July 2026) — same gap as completions above.
        # Calibrated against Receptions Model A's validated ~1.4 MAE
        # (post-recalibration) — a genuinely smaller-magnitude stat than
        # either Attempts or Completions, so both the floor and the
        # multiplier are scaled down accordingly. share_cv now uses the
        # recalibrated 0.357/0.812 tier thresholds (not the old 0.20/
        # 0.35 QB-copied ones), so these CV bands are set relative to
        # THOSE, not Attempts' bands.
        if cv >= 0.65:
            return max(1.8, projection * 0.35)
        elif cv >= 0.40:
            return max(1.3, projection * 0.28)
        else:
            return max(0.9, projection * 0.20)
    return max(1.5, projection * 0.25)











def clv_emoji(v):
    """🟢/🔴/⚪ prefix based on CLV sign, for quick visual scanning."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if v > 0:
        return "🟢 "
    elif v < 0:
        return "🔴 "
    return "⚪ "

def fmt_odds_signed(v):
    """Formats American odds with an explicit + sign for positive values, — if missing."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    v = int(round(v))
    return f"+{v}" if v > 0 else str(v)

def market_result_label(clv_val, odds_clv_val):
    """Classifies how a bet did against the closing market, distinguishing *why*:
    - Line CLV is the primary signal. If the line moved in your favor, that's the
      whole story (Over 6.5 -120 closing Over 7.5 +115 is a crushed line — the
      price at that point isn't even a fair comparison to your price).
    - Only when the line didn't move at all does price become the deciding factor.
    - A line that moved against you is a miss regardless of price.
    This avoids collapsing two different kinds of market-beating (a better number
    vs. a better price) into one number that can look misleadingly bad."""
    if clv_val is None or (isinstance(clv_val, float) and pd.isna(clv_val)):
        return "—"
    if clv_val > 0:
        return "🟢 Beat by Line"
    if clv_val < 0:
        return "🔴 Lost to Close"
    # clv_val == 0 — line didn't move, so price is the deciding factor
    if odds_clv_val is None or (isinstance(odds_clv_val, float) and pd.isna(odds_clv_val)):
        return "⚪ Push"
    if odds_clv_val > 0:
        return "🟢 Beat by Price"
    if odds_clv_val < 0:
        return "🔴 Lost to Close"
    return "⚪ Push"

def get_tier(model_edge, ev_pct, cv, sport="mlb_strikeouts", workload_tier=None):
    """Tier primarily answers: is there positive expected value, and how
    strong is it? Confidence (cv + workload) and MM Stake (sizing) are mostly
    separate axes — a low-confidence pick with real EV is still a Lean with a
    small stake, not a Pass. Pass means the model doesn't see positive
    expected value, full stop.

    August 2026 — MLB STRIKEOUTS RETIER: backtested against real historical
    sportsbook odds (2025 season, 3189 graded bets). Only 15%+ EV picks
    were profitable:
      15-20% EV: 77 bets, 53.2% win, +9.37% ROI
      20%+ EV:   56 bets, 48.2% win, +3.70% ROI
    Everything below 15% EV was unprofitable. Tier thresholds updated to
    only surface picks in the profitable range.

    NFL TD tiers remain data-driven from their own 3-season backtest:
      Best Bet: 3-5% EV (non-QB) or 3-8% EV (QB)
      Worth a Look: 5-8% EV (non-QB)

    One exception: extreme uncertainty (Low confidence) acts as a one-notch
    brake on the initial tier."""

    same_direction = model_edge is not None and ev_pct is not None and model_edge > 0 and ev_pct > 0
    if not same_direction:
        return "🔴 Pass"

    # ── MLB STRIKEOUTS: backtest-proven tiers (Aug 2026) ──
    if sport == "mlb_strikeouts":
        if ev_pct >= 20.0:
            tier = "🟢 Best Bet"
        elif ev_pct >= 15.0:
            tier = "🔵 Worth a Look"
        else:
            return "🔴 Pass"

        if get_confidence_level(cv, workload_tier) == "🔴 Low":
            if tier == "🟢 Best Bet":
                tier = "🔵 Worth a Look"
        return tier

    # ── MLB BATTER HITS: backtest-proven tiers (Sep 2026) ──
    # Real, unusual finding — validated across TWO INDEPENDENT seasons
    # (2024 and 2025, not just a split-half of one), then further
    # tightened after finding the real edge is UNDER-direction-only
    # (see analyze_prop's own direction override, applied before this
    # function is reached) within a MODERATE EV zone — INVERTED from
    # every other sport on this platform, where high EV is usually
    # better, not worse:
    #   3-5% EV: 2024 +2.96%, 2025 +4.22% — held up both years
    #   5-8% EV: 2024 +2.38%, 2025 +9.71% — held up, though 2025 ran hot
    #   8-12% EV: 2024 +2.96%, 2025 +7.71% — held up, same pattern
    #   0-3% EV: 2024 -3.31%, 2025 +2.58% — FLIPPED SIGN between years,
    #     dropped from the tier entirely (the same kind of instability
    #     that killed a similarly-sized LoL "finding" under scrutiny)
    #   12%+ EV: consistently NEGATIVE both years and gets worse the
    #     higher it goes — the model's most confident batter-hits picks
    #     remain its least reliable, same pattern seen elsewhere on
    #     this platform.
    # Combined UNDER-only, 3-12% EV, both years: 2,509 bets, +9.58% ROI.
    if sport == "mlb_batter_hits":
        if ev_pct > 12.0:
            return "🔴 Pass"
        elif ev_pct >= 5.0:
            tier = "🟢 Best Bet"
        elif ev_pct > 3.0:
            tier = "🔵 Worth a Look"
        else:
            return "🔴 Pass"

        if get_confidence_level(cv, workload_tier) == "🔴 Low":
            if tier == "🟢 Best Bet":
                tier = "🔵 Worth a Look"
        return tier

    # ── NFL TD: backtest-proven tiers (Aug 2026) ──
    if sport == "nfl_td":
        # NFL TD uses its own tier logic in run_all_nfl_td_projections
        # This is a fallback — shouldn't normally be reached
        threshold = EDGE_THRESHOLDS.get(sport, 0.75)
        ev_threshold = 12.0
        model_strong = model_edge >= threshold
        ev_strong = ev_pct >= ev_threshold
        if model_strong and ev_strong:
            tier = "🟢 Best Bet"
        elif model_strong or ev_strong:
            tier = "🔵 Worth a Look"
        else:
            tier = "🟡 Lean"
        if get_confidence_level(cv, workload_tier) == "🔴 Low":
            if tier == "🟢 Best Bet":
                tier = "🔵 Worth a Look"
            elif tier == "🔵 Worth a Look":
                tier = "🟡 Lean"
        return tier

    # ── NBA + OTHER SPORTS: default tiers (pending backtest results) ──
    threshold = EDGE_THRESHOLDS.get(sport, 0.75)
    ev_threshold = 12.0

    model_strong = model_edge >= threshold
    ev_strong = ev_pct >= ev_threshold

    if model_strong and ev_strong:
        tier = "🟢 Best Bet"
    elif model_strong or ev_strong:
        tier = "🔵 Worth a Look"
    else:
        tier = "🟡 Lean"

    if get_confidence_level(cv, workload_tier) == "🔴 Low":
        if tier == "🟢 Best Bet":
            tier = "🔵 Worth a Look"
        elif tier == "🔵 Worth a Look":
            tier = "🟡 Lean"

    return tier

def get_pass_reason(model_edge, ev_pct, cv=None, workload_tier=None):
    """Pass now only ever means one thing — no positive expected value —
    so there are only two possible reasons left."""
    if model_edge is None or model_edge <= 0:
        return "No Projection Edge"
    if ev_pct is None or ev_pct <= 0:
        return "Negative EV"
    return None

def get_confidence_level(cv, workload_tier=None):
    """A separate axis from Tier — how much to trust the projection, not
    whether the bet is worth considering. Combines K-rate variance (cv) and
    workload/role stability into a single High/Medium/Low read."""
    highly_volatile_workload = bool(workload_tier and "Highly Volatile" in workload_tier)
    changing_workload = bool(workload_tier and "Changing" in workload_tier)
    if cv >= 0.50 or highly_volatile_workload:
        return "🔴 Low"
    elif cv >= 0.35 or changing_workload:
        return "🟠 Medium"
    else:
        return "🟢 High"


TIER_RANK = {"🟢 Best Bet": 3, "🔵 Worth a Look": 2, "🟡 Lean": 1, "🔴 Pass": 0}

def short_why(info, result, sport):
    """Compact 1-2 phrase summary for ranked list views (e.g. 'Stable + Great Matchup'),
    condensed from the same signals generate_why() uses in full."""
    parts = []
    tier = info.get('Tier')
    if tier:
        if "Reliable" in tier:
            parts.append("Reliable")
        elif "Volatile" in tier:
            parts.append("Volatile")
        elif "Uncertain Workload" in tier:
            parts.append("Uncertain Workload")

    matchup_label = None
    if result:
        if sport == 'mlb_strikeouts':
            opp_factor = result.get('opp_factor')
            if opp_factor:
                if opp_factor >= 1.05:
                    matchup_label = "Great Matchup"
                elif opp_factor <= 0.95:
                    matchup_label = "Tough Matchup"
        elif sport == 'nba_points':
            opp_def_rating = result.get('opp_def_rating')
            if opp_def_rating:
                if opp_def_rating >= league_avg_def_rating + 2:
                    matchup_label = "Great Matchup"
                elif opp_def_rating <= league_avg_def_rating - 2:
                    matchup_label = "Tough Matchup"
        elif sport == 'nba_assists':
            opp_ast_allowed = result.get('opp_ast_allowed')
            if opp_ast_allowed:
                if opp_ast_allowed >= 27:
                    matchup_label = "Great Matchup"
                elif opp_ast_allowed <= 23:
                    matchup_label = "Tough Matchup"

    if matchup_label:
        parts.append(matchup_label)
    else:
        edge = info.get('Edge')
        threshold = EDGE_THRESHOLDS.get(sport, 0.75)
        if edge is not None and abs(edge) >= threshold * 1.5:
            parts.append("Strong Edge")
        else:
            parts.append("Line Value")

    return " + ".join(parts[:2]) if parts else "—"

def _lol_pill(text, kind="neutral"):
    """Real, small, reusable badge-pill helper for LoL's compact "why"
    summaries — promoted to module level (August 2026, per direct user
    report — "today's card only gives why/MM stake for MLB props") so
    Today's Card can reuse the exact same real, proven pill UI already
    used on the LoL page itself, instead of duplicating it or falling
    back to nothing for LoL entries."""
    return f"<span class='mm-badge mm-badge-{kind}' style='margin-right:6px; margin-bottom:4px; display:inline-block;'>{text}</span>"


# Real, moved to bet_math.py (August 2026) so api_server.py can call the
# exact same real "why this bet" logic — imported at the top of this
# file now instead of defined here. Behavior unchanged.

def analyze_prop(projection, line, std_dev, cv, over_odds, under_odds, direction='over', sport='mlb_strikeouts', workload_tier=None, confidence_tier=None):
    if not over_odds or not under_odds:
        return None
    try:
        if float(line).is_integer():
            return None

        min_std = get_min_std_dev(cv, projection, sport)
        effective_std = max(std_dev, min_std)

        fair_over_prob, fair_under_prob = remove_vig(over_odds, under_odds)
        fair_prob = fair_over_prob if direction == 'over' else fair_under_prob

        raw_edge = projection - line if direction == 'over' else line - projection
        edge_magnitude = abs(raw_edge)

        # Inflate uncertainty for small edges
        if edge_magnitude < 0.5:
            effective_std *= 1.30
        elif edge_magnitude < 1.0:
            effective_std *= 1.15

        # Shrink small edges harder
        if edge_magnitude < 0.5:
            shrink = 0.35
        elif edge_magnitude < 1.0:
            shrink = 0.55
        else:
            shrink = 0.75

        if direction == 'over':
            adjusted_projection = line + (raw_edge * shrink)
        else:
            adjusted_projection = line - (raw_edge * shrink)

        model_prob = projection_to_probability(adjusted_projection, line, effective_std, direction)

        if sport == 'mlb_strikeouts':
            if cv >= 0.50:
                model_prob = min(0.55, model_prob)
            elif cv >= 0.35:
                model_prob = min(0.57, model_prob)
            elif cv >= 0.20:
                model_prob = min(0.63, model_prob)
            else:
                model_prob = min(0.68, model_prob)
        elif sport == 'nba_points':
            model_prob = max(0.25, min(0.70, model_prob))
        elif sport == 'nba_assists':
            model_prob = max(0.25, min(0.72, model_prob))
        else:
            model_prob = max(0.25, min(0.72, model_prob))

        # This is the probability before any workload/role-stability
        # suppression — used to compute Raw EV, i.e. what the price/edge alone
        # would imply if the model fully trusted the workload situation.
        raw_model_prob = model_prob

        # Workload/role instability is a separate signal from cv (K-rate
        # variance) — a pitcher can look consistent on cv while his innings
        # or role is genuinely unsettled, and that risk isn't captured above.
        highly_volatile_workload = bool(workload_tier and "Highly Volatile" in workload_tier)
        if highly_volatile_workload:
            model_prob = min(model_prob, 0.55)

        model_edge = round(projection - line, 2) if direction == 'over' else round(line - projection, 2)
        low_confidence = cv >= 0.50 or highly_volatile_workload

        odds = over_odds if direction == 'over' else under_odds

        # Penalize EV as the projection edge shrinks — a near-zero edge
        # shouldn't be able to show meaningful EV regardless of odds.
        edge_mag = abs(model_edge)
        if edge_mag < 0.3:
            edge_penalty = 0.25
        elif edge_mag < 0.5:
            edge_penalty = 0.35
        elif edge_mag < 0.75:
            edge_penalty = 0.60
        else:
            edge_penalty = 1.0

        # Raw EV: what the price/edge alone implies, ignoring workload
        # confidence — shown alongside the adjusted number so a user can see
        # "the price might be good, but the model doesn't trust the workload
        # enough to recommend it" instead of the number just disappearing.
        raw_ev_dollar = round(calculate_ev(raw_model_prob, odds) * edge_penalty, 2)
        raw_ev_pct = round(calculate_ev_pct(raw_model_prob, odds) * edge_penalty, 2)

        ev_dollar = calculate_ev(model_prob, odds) * edge_penalty
        ev_pct = calculate_ev_pct(model_prob, odds) * edge_penalty
        if highly_volatile_workload:
            ev_pct *= 0.55
            ev_dollar *= 0.55

        ev_pct = round(ev_pct, 2)
        ev_dollar = round(ev_dollar, 2)

        prob_edge = round((model_prob - fair_prob) * 100, 2)
        fair_odds = prob_to_american_odds(model_prob)
        edge_cents = calculate_odds_edge_cents(odds, fair_odds)

        computed_tier = get_tier(model_edge, ev_pct, cv, sport, workload_tier)
        # Real, direction-specific override for MLB Batter Hits (Sep
        # 2026) — split-half AND cross-season validated (2024: +8.19%
        # ROI on 1,562 unders in the 3-12% EV zone; 2025: +11.87% ROI
        # on 947 unders in the same zone; combined 2,509 bets, +9.58%
        # ROI). OVER-direction bets showed the opposite sign both
        # years independently (2024: -8.52% ROI on overs overall, 2025:
        # -5.6%) — plausibly real public-money bias (bettors like
        # backing a player to get a hit, pushing over lines to worse
        # value), not model noise. This lives here (not in get_tier
        # itself) specifically to avoid touching that shared function's
        # signature/behavior for every other sport on this platform.
        if sport == 'mlb_batter_hits' and direction == 'over' and computed_tier != "🔴 Pass":
            computed_tier = "🔴 Pass"

        return {
            'model_prob': model_prob,
            'no_vig_prob': round(fair_prob, 3),
            'prob_edge': prob_edge,
            'ev_dollar': ev_dollar,
            'ev_pct': ev_pct,
            'raw_ev_pct': raw_ev_pct,
            'raw_ev_dollar': raw_ev_dollar,
            'model_edge': model_edge,
            'fair_odds': fair_odds,
            'edge_cents': edge_cents,
            'low_confidence': low_confidence,
            'tier': computed_tier,
            'pass_reason': get_pass_reason(model_edge, ev_pct, cv, workload_tier),
            'confidence_level': get_confidence_level(cv, workload_tier),
            'effective_std': round(effective_std, 3),
            'adjusted_projection': round(adjusted_projection, 3),
            'opposite_odds': under_odds if direction == 'over' else over_odds,
        }
    except Exception as e:
        log_failure_reason('MALFORMED_RESPONSE', f"analyze_prop({sport}, proj={projection}, line={line}): {e}")
        return None


def find_best_book_line(book_odds_list, projection, std_dev, cv, sport, workload_tier=None, confidence_tier=None):
    """Analyze every book's line/odds for a player and return the best EV play.

    August 2026 — LINE SHOPPING: instead of defaulting to FanDuel or
    DraftKings, runs analyze_prop against EVERY book's line/odds separately
    and picks the one with the highest EV%. If BetMGM has a player at 22.5
    and FanDuel has them at 24.5, and the model projects 27, this will
    pick BetMGM because the edge is bigger.

    book_odds_list: list of dicts from the existing book_odds field,
                    each with keys: book, line, over, under
    Returns dict with best_book, best_line, best_direction, best_odds,
    best_ev_result, and all_book_results — or None if no valid analysis.
    """
    if not book_odds_list:
        return None

    all_results = []

    for book_entry in book_odds_list:
        book_name = book_entry.get('book', '')
        line = book_entry.get('line')
        over_odds = book_entry.get('over')
        under_odds = book_entry.get('under')

        if line is None or over_odds is None or under_odds is None:
            continue

        try:
            if float(line).is_integer():
                continue
        except (ValueError, TypeError):
            continue

        edge = projection - line
        if edge > 0:
            direction = 'over'
        elif edge < 0:
            direction = 'under'
        else:
            continue

        ev_result = analyze_prop(
            projection=projection, line=line,
            std_dev=std_dev, cv=cv,
            over_odds=over_odds, under_odds=under_odds,
            direction=direction, sport=sport,
            workload_tier=workload_tier, confidence_tier=confidence_tier
        )

        if ev_result is None:
            continue

        all_results.append({
            'book': book_name,
            'line': line,
            'direction': direction,
            'odds': over_odds if direction == 'over' else under_odds,
            'over_odds': over_odds,
            'under_odds': under_odds,
            'ev_result': ev_result,
        })

    if not all_results:
        return None

    all_results.sort(key=lambda x: x['ev_result']['ev_pct'], reverse=True)

    best = all_results[0]
    return {
        'best_book': best['book'],
        'best_line': best['line'],
        'best_direction': best['direction'],
        'best_odds': best['odds'],
        'best_over_odds': best['over_odds'],
        'best_under_odds': best['under_odds'],
        'best_ev_result': best['ev_result'],
        'all_book_results': all_results,
    }


# ---- SUPABASE CONNECTION ----
@st.cache_resource
def get_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = get_supabase()

def sign_up(email, password):
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        return res.user, None
    except Exception as e:
        return None, str(e)

def sign_in(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        return res.user, res.session, None
    except Exception as e:
        return None, None, str(e)

def resend_confirmation_email(email):
    """Real, honest resend helper (July 2026, per direct user request —
    closing a real signup loophole where unlimited fake/throwaway
    emails could each grab a fresh free trial) — for a real user whose
    original confirmation email expired, went to spam, or never
    arrived. Uses Supabase's own real resend endpoint rather than
    trying to recreate or fake this ourselves. Only relevant once
    "Confirm email" is turned on in the Supabase Dashboard (Auth →
    Providers → Email) — with that off, this is never reached."""
    try:
        supabase.auth.resend({"type": "signup", "email": email})
        return True, None
    except Exception as e:
        return False, str(e)

def sign_out():
    try:
        supabase.auth.sign_out()
    except:
        pass
    try:
        cookie_controller.remove('mm_refresh_token')
    except:
        pass
    st.session_state.clear()

# ---- AUTH WALL ----
cookie_controller = CookieController()

def try_restore_session_from_cookie():
    """'Stay logged in' — on a fresh browser session with no st.session_state
    yet, check for a saved refresh token cookie (set on login, 30-day expiry)
    and silently re-authenticate instead of showing the login screen again.
    Cookie components read the browser asynchronously, so this may take one
    extra rerun to actually take effect on a brand new tab — expected, not a bug.

    Real fix (August 2026, per direct user report) — Supabase rotates
    refresh tokens on each real use (the same real reason
    refresh_supabase_session_if_needed() already re-saves its own
    refreshed token back to the cookie, per that function's own real
    comment). This function was missing that same real step — after a
    real, successful restore here, the cookie still held the OLD, now-
    already-consumed token. If this function ever ran a second time
    before refresh_supabase_session_if_needed() got a chance to correct
    it (a real, genuine risk once page loads got meaningfully longer
    thanks to today's other real fixes, giving Streamlit's connection
    more real time to reconnect/rerun mid-load), the second real
    attempt would use that same stale, already-consumed token —
    Supabase correctly rejects it, silently bouncing a real, just-
    authenticated user back to the login screen. Now keeps the cookie
    in sync immediately after every real successful restore, closing
    that real gap."""
    if 'user' in st.session_state:
        return
    try:
        saved_refresh_token = cookie_controller.get('mm_refresh_token')
        if not saved_refresh_token:
            return
        refreshed = supabase.auth.refresh_session(saved_refresh_token)
        if refreshed and refreshed.session and refreshed.user:
            st.session_state['user'] = refreshed.user
            st.session_state['session'] = refreshed.session
            try:
                cookie_controller.set('mm_refresh_token', refreshed.session.refresh_token, max_age=60 * 60 * 24 * 30)
            except Exception:
                pass
    except Exception:
        # Saved token invalid/expired — fall through to a normal login screen.
        pass

try_restore_session_from_cookie()

if 'user' not in st.session_state:
    st.markdown("""
        <div style='text-align: center; padding-top: 60px;'>
            <img src='https://raw.githubusercontent.com/austinwinkler6-ux/mlb_strikeout_model/main/ModelMetricsLogo.png' width='225'/>
            <h2 style='margin-top: 20px; font-family: var(--mm-display);'>Welcome to Model Metrics</h2>
            <p style='color: var(--mm-text-dim); margin-top: 8px; font-family: var(--mm-mono); font-size: 0.85rem; letter-spacing: 0.06em;'>PROJECTIONS · +EV · CONFIDENCE TIERS</p>
        </div>
    """, unsafe_allow_html=True)

    auth_tab1, auth_tab2 = st.tabs(["Login", "Sign Up"])

    with auth_tab1:
        with st.form("login_form"):
            login_email = st.text_input("Email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_password")
            login_submitted = st.form_submit_button("Login", use_container_width=True)
        if login_submitted:
            user, session, error = sign_in(login_email, login_password)
            if error:
                # Real fix (July 2026, per direct user request) — once
                # "Confirm email" is enabled in Supabase, a real,
                # legitimate user who hasn't clicked their confirmation
                # link yet gets this same real error from Supabase.
                # Shown as a clear, expected message with a real way to
                # resend, instead of a generic "Login failed" error
                # that gives no indication of what to actually do.
                if "not confirmed" in error.lower():
                    st.warning("📧 Please confirm your email before logging in — check your inbox for a confirmation link (and your spam folder).")
                    if st.button("Resend confirmation email", key="resend_login_confirm"):
                        resent_ok, resend_error = resend_confirmation_email(login_email)
                        if resent_ok:
                            st.success("✅ Confirmation email resent — check your inbox.")
                        else:
                            st.error(f"Couldn't resend — real error: {resend_error}")
                else:
                    st.error(f"Login failed: {error}")
            else:
                st.session_state['user'] = user
                st.session_state['session'] = session
                try:
                    cookie_controller.set('mm_refresh_token', session.refresh_token, max_age=60 * 60 * 24 * 30)
                except Exception:
                    pass
                st.rerun()

    with auth_tab2:
        with st.form("signup_form"):
            signup_email = st.text_input("Email", key="signup_email")
            signup_password = st.text_input("Password", type="password", key="signup_password")
            signup_password2 = st.text_input("Confirm Password", type="password", key="signup_password2")
            signup_submitted = st.form_submit_button("Create Account", use_container_width=True)
        if signup_submitted:
            if signup_password != signup_password2:
                st.error("Passwords don't match!")
            elif len(signup_password) < 6:
                st.error("Password must be at least 6 characters!")
            else:
                user, error = sign_up(signup_email, signup_password)
                if error:
                    st.error(f"Sign up failed: {error}")
                else:
                    user2, session, error2 = sign_in(signup_email, signup_password)
                    if not error2:
                        # Real, immediate login succeeded — email
                        # confirmation is either OFF in your Supabase
                        # settings, or configured to auto-confirm. Keeps
                        # the exact same real, working flow as before
                        # either way.
                        st.session_state['user'] = user2
                        st.session_state['session'] = session
                        st.session_state['just_signed_up'] = True
                        try:
                            cookie_controller.set('mm_refresh_token', session.refresh_token, max_age=60 * 60 * 24 * 30)
                        except Exception:
                            pass
                        st.rerun()
                    elif "not confirmed" in error2.lower():
                        # Real fix (July 2026, per direct user request —
                        # closing a real signup loophole where unlimited
                        # fake/throwaway emails could each grab a fresh
                        # free trial). Once "Confirm email" is enabled in
                        # Supabase, this immediate real sign-in attempt
                        # correctly fails until the real email address
                        # gets confirmed — shown as a clean, expected
                        # "check your inbox" success message, not a
                        # confusing raw login error right after signing up.
                        st.success("✅ Account created! Check your email for a confirmation link, then come back and log in.")
                    else:
                        st.error(f"Account created, but automatic login failed — real error: {error2}. Try logging in manually from the Login tab.")
    st.stop()

# ---- LOGGED IN ----
user = st.session_state['user']
user_id = user.id
is_admin = user.email.lower() == ADMIN_EMAIL.lower()

# ---- SUBSCRIPTION / PAYWALL ----
def get_or_refresh_subscription(user_id, email):
    """Real subscription/trial status for the current user, read from the
    'subscriptions' table (see the required SQL migration). Creates a
    fresh TRIAL_LENGTH_DAYS-day trial row on the very first real check for
    any user who doesn't have one yet — this deliberately covers both a
    brand-new sign-up AND every existing user's first load after this
    feature shipped (every real user gets a real trial starting from when
    they first see this, rather than being silently locked out or
    silently grandfathered in with no trial at all).

    Periodically re-verifies a real, currently-active subscription against
    Stripe's own API (throttled to once per STRIPE_RECHECK_INTERVAL_
    SECONDS) — this app uses a real Checkout-redirect-then-verify flow
    rather than a live webhook receiver (Streamlit doesn't expose
    arbitrary custom routes the way a normal backend does), so this
    periodic re-check is what catches a real cancellation or failed
    renewal on Stripe's side without one.

    Returns {'status': 'trialing'|'active'|'expired', 'days_left_in_trial':
    int or None, 'unlimited': bool}. Fails OPEN on any real Supabase/
    Stripe error — treats the user as still-in-trial rather than crashing
    the page or hard-locking a real, possibly-paying user out over a
    transient error."""
    if not PAYWALL_ENABLED:
        return {"status": "active", "days_left_in_trial": None, "unlimited": True}

    now = datetime.now(ZoneInfo("UTC"))
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
            pass  # real, honest fallback — still treat this load as a fresh trial even if the insert failed
        return {"status": "trialing", "days_left_in_trial": TRIAL_LENGTH_DAYS, "unlimited": False}

    status = row.get("status") or "trialing"
    stripe_subscription_id = row.get("stripe_subscription_id")
    last_check = row.get("last_stripe_check")

    if stripe_subscription_id and status in ("active", "past_due"):
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
                period_end = datetime.fromtimestamp(sub.current_period_end, tz=ZoneInfo("UTC")).isoformat()
                supabase.table("subscriptions").update({
                    "status": new_status, "current_period_end": period_end,
                    "last_stripe_check": now.isoformat(),
                }).eq("user_id", user_id).execute()
                status = new_status
            except Exception:
                pass  # real, honest fallback — keep the last-known cached status rather than fail the page

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
        # Rounds UP to the nearest whole day — a trial with 2 hours left
        # still honestly reads as "1 day left," not "0 days left."
        days_left = max(1, int((trial_end_dt - now).total_seconds() // 86400) + 1)
        return {"status": "trialing", "days_left_in_trial": days_left, "unlimited": False}

    return {"status": "expired", "days_left_in_trial": 0, "unlimited": False}


def create_stripe_checkout_url(user_id, email):
    """Creates a real Stripe Checkout Session in subscription mode and
    returns its real, hosted checkout URL, or None if creation failed (a
    real Stripe/network error) — callers must handle a None return
    gracefully rather than assume success.

    Real addition (July 2026) — allow_promotion_codes=True adds a real,
    Stripe-hosted "Add promotion code" field directly on the Checkout
    page. This is Stripe's own native discount-code mechanism, not
    something built here: real Coupons (the actual discount — a percent
    off, a flat amount off, free/100% off) and real Promotion Codes (the
    customer-facing string tied to a Coupon, e.g. "FRIENDS100" or
    "HOLIDAY25") are both created and managed entirely in the Stripe
    Dashboard (Product catalog → Coupons), with zero code changes needed
    per code — expiration dates, max redemption counts, and which coupon
    a given code maps to are all real, first-class Stripe settings."""
    if not PAYWALL_ENABLED:
        return None
    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            client_reference_id=user_id,
            customer_email=email,
            allow_promotion_codes=True,
            success_url=f"{APP_BASE_URL}?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{APP_BASE_URL}?checkout=cancelled",
        )
        return checkout_session.url
    except Exception as e:
        st.session_state['_stripe_checkout_error'] = str(e)
        return None


def create_stripe_billing_portal_url(stripe_customer_id):
    """Real, standard self-service subscription management — creates a
    real Stripe Billing Portal session so a real, active subscriber can
    update their payment method or cancel on their own, without needing
    you to do it manually on their behalf. Returns None (not an error) if
    there's no real stripe_customer_id yet (e.g. never subscribed) or the
    real session creation call fails."""
    if not PAYWALL_ENABLED or not stripe_customer_id:
        return None
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=APP_BASE_URL,
        )
        return portal_session.url
    except Exception:
        return None


def handle_stripe_checkout_return(user_id):
    """Real, honest handling of the redirect back from Stripe Checkout —
    this app has no live webhook receiver (Streamlit doesn't expose
    arbitrary custom routes the way a normal backend does), so a real,
    successful subscription is confirmed HERE: by verifying the real
    checkout session directly against Stripe's own API when the person
    lands back on this app with ?checkout=success&session_id=... in the
    URL, rather than trusting the redirect alone (a bare redirect can be
    spoofed; a verified, real Stripe API lookup can't)."""
    if not PAYWALL_ENABLED:
        return
    params = st.query_params
    if params.get("checkout") == "success" and params.get("session_id"):
        try:
            checkout_session = stripe.checkout.Session.retrieve(params["session_id"])
            if checkout_session.payment_status == "paid" or checkout_session.status == "complete":
                now = datetime.now(ZoneInfo("UTC"))
                subscription_id = checkout_session.subscription
                period_end_iso = None
                if subscription_id:
                    sub = stripe.Subscription.retrieve(subscription_id)
                    period_end_iso = datetime.fromtimestamp(sub.current_period_end, tz=ZoneInfo("UTC")).isoformat()
                supabase.table("subscriptions").upsert({
                    "user_id": user_id, "status": "active",
                    "stripe_customer_id": checkout_session.customer,
                    "stripe_subscription_id": subscription_id,
                    "current_period_end": period_end_iso,
                    "last_stripe_check": now.isoformat(),
                }, on_conflict="user_id").execute()
                st.session_state.pop('_subscription_status', None)
                st.session_state['_just_subscribed'] = True
            else:
                st.session_state['_stripe_checkout_error'] = f"Real checkout session status was '{checkout_session.status}' / payment_status '{checkout_session.payment_status}' — not confirmed as paid."
        except Exception as e:
            st.session_state['_stripe_checkout_error'] = str(e)
        finally:
            st.query_params.clear()
            st.rerun()
    elif params.get("checkout") == "cancelled":
        st.query_params.clear()


def render_trial_banner(subscription_status, user_id, email):
    """Real, soft banner shown at the top of the main content area on
    EVERY page (per direct product decision) — a real trial countdown
    with a Subscribe button while trialing, a real 'trial ended' nudge
    once expired (Home's own dedicated CTA block handles the actual
    subscribe click for that state, so no duplicate button here), and
    nothing at all for a real, active subscriber or when the paywall
    isn't configured yet.

    Real fix (July 2026, per direct user report) — clicking "Subscribe"
    used to just set a flag and rerun, after which the REST of the
    current page (e.g. Home's full, multi-model background computation)
    kept rendering below the resulting checkout link — a real, visibly
    confusing "still churning in the background" mess right next to the
    checkout button. It also created a brand-new real Stripe Checkout
    Session on EVERY single page load for an expired user (since that
    branch ran unconditionally), not just when they'd actually clicked
    through — wasted real API calls.

    Now, once someone has actually clicked "Subscribe," this renders a
    minimal, real hand-off screen and stops the page entirely right
    there via st.stop() — nothing else on the page gets a chance to
    render underneath it, and it also attempts a real, best-effort
    browser auto-redirect to Stripe (with a guaranteed manual button as
    a fallback, since a meta-refresh tag isn't honored identically by
    every browser). Tracks which real nav page the click happened on
    (_checkout_flow_nav) so switching to a different sidebar page
    correctly exits this flow instead of getting stuck on it forever."""
    if not PAYWALL_ENABLED or subscription_status["status"] == "active":
        return
    if st.session_state.pop('_just_subscribed', False):
        st.success("✅ You're subscribed! Full access unlocked.")
        return

    current_nav = st.session_state.get('main_nav_radio')
    checkout_flow_active = (
        st.session_state.get('_show_checkout_link')
        and st.session_state.get('_checkout_flow_nav') == current_nav
    )

    if checkout_flow_active:
        st.session_state.pop('_show_checkout_link', None)
        st.session_state.pop('_checkout_flow_nav', None)
        checkout_url = create_stripe_checkout_url(user_id, email)
        if checkout_url:
            st.success("🔓 Redirecting you to a secure Stripe checkout page...")
            st.link_button("Continue to Checkout", checkout_url, use_container_width=True, type="primary")
            st.caption("Didn't redirect automatically? Click the button above.")
            st.markdown(f'<meta http-equiv="refresh" content="1; url={checkout_url}">', unsafe_allow_html=True)
        else:
            st.error(f"Couldn't start checkout — real error: {st.session_state.pop('_stripe_checkout_error', 'unknown error')}")
        st.stop()

    if subscription_status["status"] == "trialing":
        days_left = subscription_status["days_left_in_trial"]
        col_msg, col_btn = st.columns([4, 1])
        with col_msg:
            st.info(f"🎉 {days_left} day{'s' if days_left != 1 else ''} left in your free trial — subscribe now to keep full access after it ends.")
        with col_btn:
            st.markdown("<div style='padding-top: 6px;'></div>", unsafe_allow_html=True)
            if st.button("Subscribe", key="banner_subscribe_trial", use_container_width=True):
                st.session_state['_show_checkout_link'] = True
                st.session_state['_checkout_flow_nav'] = current_nav
                st.rerun()
    elif subscription_status["status"] == "expired":
        st.warning("🔒 Your free trial has ended. Subscribe to unlock full access to every model, Bet Tracker, and more.")


def refresh_supabase_session_if_needed():
    """Supabase access tokens expire (typically ~1 hour) — without this, any
    session left open longer than that starts throwing 'JWT expired' on every
    database call. Proactively refreshes using the stored refresh token,
    throttled to at most once every 10 minutes so it doesn't hammer the auth
    endpoint on every single rerun."""
    now = datetime.now(ZoneInfo("UTC")).timestamp()
    last_refresh = st.session_state.get('_session_refreshed_at', 0)
    if now - last_refresh < 600:
        return
    try:
        session = st.session_state.get('session')
        refresh_token = getattr(session, 'refresh_token', None)
        if not refresh_token:
            return
        refreshed = supabase.auth.refresh_session(refresh_token)
        if refreshed and refreshed.session:
            st.session_state['session'] = refreshed.session
            # Supabase rotates refresh tokens on each use — keep the "stay
            # logged in" cookie in sync or it'll silently go stale after the
            # first refresh and fail to restore the session on a new tab.
            try:
                cookie_controller.set('mm_refresh_token', refreshed.session.refresh_token, max_age=60 * 60 * 24 * 30)
            except Exception:
                pass
        st.session_state['_session_refreshed_at'] = now
    except Exception:
        # If the refresh token itself is invalid/expired (e.g. laptop closed
        # for days), the user will hit an auth error on their next action and
        # need to log out/back in — no clean way to force that from here.
        pass

refresh_supabase_session_if_needed()
supabase.postgrest.auth(st.session_state['session'].access_token)

# Real, deliberate order: handle any real return-from-Stripe-Checkout
# redirect FIRST (before anything else renders, since a successful real
# subscription triggers its own st.rerun() to refresh state cleanly),
# then compute the real subscription/trial status once per session
# (cached in session_state, not recomputed on every single rerun — this
# still calls Stripe at most once per STRIPE_RECHECK_INTERVAL_SECONDS
# regardless, but avoids a redundant real Supabase read on every rerun
# too). The admin account always gets real, full access regardless of
# real trial/subscription state — they need it to manage and test the
# site itself.
handle_stripe_checkout_return(user_id)
if '_subscription_status' not in st.session_state:
    st.session_state['_subscription_status'] = get_or_refresh_subscription(user_id, user.email)
subscription_status = st.session_state['_subscription_status']
if is_admin:
    subscription_status = {"status": "active", "days_left_in_trial": None, "unlimited": True}

# ---- DATABASE FUNCTIONS ----
def load_bets(sport=None):
    try:
        query = supabase.table("bets").select("*").eq("user_id", user_id)
        if sport:
            query = query.eq("sport", sport)
        return query.order("created_at", desc=True).execute().data or []
    except Exception as e:
        st.error(f"Error loading bets: {e}")
        return []

def get_already_bet_players_today(sport=None):
    """Returns the set of player/pitcher names already logged as a bet today
    for the current user — used to flag 'you already bet this' so the same
    play doesn't get accidentally logged twice."""
    try:
        today_str = mm_today_str()
        bets = load_bets(sport)
        return {b['pitcher'] for b in bets if b.get('date') == today_str and b.get('pitcher')}
    except Exception:
        return set()

def get_already_bet_players_today_by_sport():
    """Sport-specific version for pages that mix MLB/NBA Points/NBA Assists in
    one list (Today's Card, Home) — betting a player's points shouldn't flag
    his separate assists prop (or vice versa) as already bet."""
    # Real fix (July 2026) — now covers every real save-label sport (MLB,
    # NBA, NBA_AST, NFL, NFL_COMPLETIONS, NFL_RECEPTIONS, LOL) via
    # SAVE_LABEL_TO_MODEL_KEY's own keys, instead of a hardcoded 3-sport
    # tuple that silently never checked NFL or LoL bets at all — meaning
    # Today's Card and the Home page banner never showed "Already bet
    # today" for any NFL or LoL pick, even if you'd already bet it.
    return {sport: get_already_bet_players_today(sport) for sport in SAVE_LABEL_TO_MODEL_KEY.keys()}

def sport_key_to_bet_label(sport_key):
    # Real fix (July 2026) — the old version only handled 'mlb_strikeouts'
    # explicitly and routed everything else through nba_bet_sport_label(),
    # which only recognizes 'nba_points'/'nba_assists' and silently falls
    # through to 'NBA_AST' for anything else — meaning every NFL and LoL
    # sport_key was being mislabeled as NBA_AST, which broke "already bet"
    # checks and any other lookup keyed off this function for those sports.
    # Now uses the already-existing, canonical MODEL_KEY_TO_SAVE_LABEL dict
    # instead of hand-rolled branching.
    return MODEL_KEY_TO_SAVE_LABEL.get(sport_key, 'MLB')

def save_bet(bet):
    # Real fix (July 2026) — same centralized NaN sanitization as
    # update_bet below, applied here too since the same real risk
    # exists at initial bet-logging time, not just on later updates.
    def _sanitize_nan(v):
        if isinstance(v, float) and pd.isna(v):
            return None
        return v
    bet = {k: _sanitize_nan(v) for k, v in bet.items()}
    try:
        payload = {**bet, "user_id": user_id}
        supabase.table("bets").insert(payload).execute()
    except Exception as e:
        st.error(f"Error saving bet: {e}")

def update_bet(bet_id, updates):
    # Real fix (July 2026) — found via a real, persistent error report
    # ("Out of range float values are not JSON compliant: nan") that
    # kept happening even after fixing the 'Save Table Changes' path
    # specifically. Turned out there are multiple real update_bet call
    # sites (Save Table Changes, the Closing Line Tracker, the new
    # Refresh MLB Results feature) — patching each one individually is
    # fragile, since it's easy to miss one (which is exactly what
    # happened: the Closing Line Tracker's own CLV math had a real gap
    # — `bet.get('opening_line') or 0` doesn't catch a genuine NaN
    # float, since NaN is truthy in Python, not falsy). Sanitizing
    # centrally here means every current AND future caller is
    # automatically protected, with no need to remember to do this at
    # each call site.
    def _sanitize_nan(v):
        if isinstance(v, float) and pd.isna(v):
            return None
        return v
    updates = {k: _sanitize_nan(v) for k, v in updates.items()}
    try:
        supabase.table("bets").update(updates).eq("id", bet_id).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Error updating bet: {e}")

def delete_bet(bet_id):
    try:
        supabase.table("bets").delete().eq("id", bet_id).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Error deleting bet: {e}")

def load_predictions(sport=None):
    try:
        query = supabase.table("predictions").select("*").eq("user_id", user_id)
        if sport:
            query = query.eq("sport", sport)
        return query.order("created_at", desc=True).execute().data or []
    except Exception as e:
        st.error(f"Error loading predictions: {e}")
        return []

def save_prediction(pred):
    try:
        payload = {**pred, "user_id": user_id}
        # Real fix (July 2026, per external review) — the previous
        # check-then-insert pattern (query for an existing row, insert
        # only if none found) had a genuine race condition: two
        # simultaneous sessions could both check, both see nothing, and
        # both insert a duplicate row. A pre-insert query alone isn't a
        # real guarantee. Now uses a real upsert against a database-
        # level unique constraint on (user_id, sport, date, pitcher) —
        # see the SQL migration provided alongside this fix. If the
        # constraint doesn't exist yet in the actual database, this
        # falls back to a plain insert further below rather than
        # silently failing.
        try:
            supabase.table("predictions").upsert(payload, on_conflict="user_id,sport,date,pitcher").execute()
        except Exception as upsert_error:
            # Falls back to the old check-then-insert behavior if the
            # unique constraint hasn't been added to the database yet —
            # keeps this working (with the old, real-but-smaller race
            # window) rather than breaking prediction-saving entirely
            # until the SQL migration is run.
            existing = supabase.table("predictions").select("id") \
                .eq("user_id", user_id).eq("pitcher", payload.get("pitcher")) \
                .eq("date", payload.get("date")).eq("sport", payload.get("sport")) \
                .execute()
            if existing.data:
                return
            supabase.table("predictions").insert(payload).execute()
    except Exception as e:
        st.error(f"Error saving prediction: {e}")

def update_prediction(pred_id, updates):
    try:
        supabase.table("predictions").update(updates).eq("id", pred_id).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Error updating prediction: {e}")


# ---- BANKROLL / MM STAKE ----
# Scales the tier unit ranges themselves (not just the final $ cap) so Aggressive
# genuinely recommends bigger individual stakes and Conservative genuinely
# recommends smaller ones — matches the same 1%/2%/3% ratio as the caps above.

def get_user_settings():
    try:
        res = supabase.table("user_settings").select("*").eq("user_id", user_id).execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return None

def save_user_settings(starting_bankroll, risk_style, reset_baseline=True):
    """If reset_baseline=True (setting/resetting the bankroll amount), sets a
    NEW baseline dated today. If False (just changing risk style), leaves the
    existing baseline/date untouched — otherwise every risk-style change would
    silently wipe out accumulated profit-tracking history."""
    try:
        payload = {
            "user_id": user_id,
            "starting_bankroll": starting_bankroll,
            "risk_style": risk_style,
            "updated_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        }
        if reset_baseline:
            payload["bankroll_set_date"] = mm_today_str()
        supabase.table("user_settings").upsert(payload, on_conflict="user_id").execute()
        return True
    except Exception as e:
        st.error(f"Error saving settings: {e}")
        return False

def get_current_bankroll(settings, bets=None):
    """Live-computed: starting bankroll + sum of profit from bets settled
    on or after the baseline date. Never a stored/synced number, so it can't
    drift out of sync with the actual bet history."""
    if not settings or settings.get('starting_bankroll') is None:
        return None
    starting = settings['starting_bankroll']
    baseline_date = settings.get('bankroll_set_date') or '1900-01-01'
    if bets is None:
        bets = load_bets()
    profit_since = sum(
        (b.get('profit') or 0) for b in bets
        if b.get('result') != 'Pending' and b.get('date') and b['date'] >= baseline_date
    )
    return round(starting + profit_since, 2)





def get_risk_level_label(result):
    """Maps the pitcher's own reliability tier to a risk-level indicator for
    the MM Stake display — Uncertain Workload never reaches here since those
    are already filtered to Pass before a stake is ever calculated."""
    confidence_tier = result.get('confidence_tier', '') if result else ''
    if "Reliable" in confidence_tier:
        return "🟢 Low"
    elif "Volatile" in confidence_tier:
        return "🟡 Moderate"
    return "⚪ Unrated"

def get_bankroll_context():
    """One settings lookup per page load — bankroll + risk style used to
    personalize every MM Stake shown on that page."""
    settings = get_user_settings()
    bankroll = get_current_bankroll(settings) if settings else None
    risk_style = settings.get('risk_style', 'Standard') if settings else 'Standard'
    return bankroll, risk_style

def calc_max_drawdown_pct(bets, starting_bankroll, baseline_date):
    """Largest peak-to-trough decline in bankroll balance, walked chronologically
    from the baseline. Purely informational — helps a user see their worst
    stretch, not a prediction of future risk."""
    if not starting_bankroll:
        return None
    settled = sorted(
        [b for b in bets if b.get('result') != 'Pending' and b.get('date') and b['date'] >= baseline_date],
        key=lambda b: b.get('date', '')
    )
    if not settled:
        return 0.0
    balance = starting_bankroll
    peak = balance
    max_dd = 0.0
    for b in settled:
        balance += (b.get('profit') or 0)
        if balance > peak:
            peak = balance
        if peak > 0:
            dd = (peak - balance) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 1)


def calc_avg_stake_units(bets, bankroll):
    settled = [b for b in bets if b.get('result') != 'Pending' and b.get('bet_amount')]
    if not settled or not bankroll:
        return None
    avg_dollar = sum(b.get('bet_amount', 0) for b in settled) / len(settled)
    unit_value = bankroll * 0.01
    return round(avg_dollar / unit_value, 2) if unit_value > 0 else None

def render_mm_stake_block(info, result, bankroll, risk_style):
    """Shared MM Stake™ display — its own dropdown, same level as 'Why this
    bet?', never nested inside another expander (Streamlit doesn't support
    that). Same structure everywhere it appears, so branding/wording can't
    drift out of sync across pages."""
    if not bankroll:
        st.caption("💰 Set a bankroll in Settings to see your personalized MM Stake recommendation.")
        return
    stake = calculate_mm_stake(info, result, bankroll, risk_style)
    if not stake:
        return
    with st.expander("💰 MM Stake"):
        if stake.get('pass'):
            st.markdown("**Suggested Stake: Pass**")
            st.caption(f"Reason: {stake.get('reason', 'Model tier is Pass')}")
        else:
            st.markdown(f"### {stake['stake_units']} Units (${stake['stake_dollars']:,.2f})")
            st.caption(f"Risk Level: {get_risk_level_label(result)}")
            st.markdown("**Based on:**")
            for r in stake['reasoning']:
                icon = "⚠️" if ("reduced" in r.lower() or "capped" in r.lower()) else "✅"
                st.markdown(f"{icon} {r}")
        st.caption("*Suggested stake is guidance based on bankroll, EV, odds, and model confidence — not a guarantee.*")

# ---- STAKE DISCIPLINE ----
# Tracks whether a user actually bet what MM Stake recommended, using the
# recommendation captured at the moment each bet was logged — not recomputed
# later, since odds/tiers can shift and that wouldn't be a fair comparison.
STAKE_DEVIATION_FOLLOWED_THRESHOLD = 25  # within ±25% of recommended = "followed"



def calc_stake_discipline_stats(bets):
    """Computes Stake Discipline % and Avg Deviation across all bets that have
    a captured MM Stake recommendation, plus ROI split by whether the user
    followed the recommendation (within threshold) or exceeded it."""
    tracked = [
        b for b in bets
        if b.get('mm_stake_recommended') is not None and b.get('bet_amount') is not None
    ]
    if not tracked:
        return None

    deviations = []
    followed_bets = []
    exceeded_bets = []
    for b in tracked:
        dev = get_stake_deviation_pct(b['mm_stake_recommended'], b['bet_amount'])
        if dev is None:
            continue
        deviations.append(dev)
        if abs(dev) <= STAKE_DEVIATION_FOLLOWED_THRESHOLD:
            followed_bets.append(b)
        else:
            exceeded_bets.append(b)

    if not deviations:
        return None

    discipline_pct = round(len(followed_bets) / len(deviations) * 100, 1)
    avg_deviation = round(sum(deviations) / len(deviations), 1)

    def _roi(bet_list):
        settled = [b for b in bet_list if b.get('result') != 'Pending']
        if not settled:
            return None
        wagered = sum(b.get('bet_amount', 0) or 0 for b in settled)
        profit = sum(b.get('profit', 0) or 0 for b in settled)
        return round(profit / wagered * 100, 1) if wagered > 0 else None

    today_str = mm_today_str()
    today_tracked = [b for b in tracked if (b.get('date') or '') == today_str]
    today_followed = [
        b for b in today_tracked
        if abs(get_stake_deviation_pct(b['mm_stake_recommended'], b['bet_amount']) or 999) <= STAKE_DEVIATION_FOLLOWED_THRESHOLD
    ]

    return {
        'total_tracked': len(deviations),
        'bets_following': len(followed_bets),
        'discipline_pct': discipline_pct,
        'avg_deviation_pct': avg_deviation,
        'roi_following': _roi(followed_bets),
        'roi_exceeding': _roi(exceeded_bets),
        'today_followed': len(today_followed),
        'today_total': len(today_tracked),
    }

# ---- SHARED DAILY PROJECTION CACHE ----
# One computed projection per (date, sport, player) is shared across ALL users,
# instead of every visitor re-running the full model pipeline (and re-hitting
# every external API) for identical results. MLB gets special handling: a
# projection computed before lineups are posted is only "provisional" and gets
# re-checked periodically until a real lineup is found.
LINEUP_RECHECK_MINUTES = 60


# Real addition (July 2026, per external review) — version stamps for
# every saved prediction/bet, so it's possible to reproduce why the
# site recommended a specific bet even after the underlying formulas
# change later. Bump these whenever a real, meaningful change lands in
# the projection models or the EV/probability engine (analyze_prop) —
# not for every tiny tweak, but for anything that could change what a
# past bet's numbers actually meant.
MODEL_VERSION = "2026-07-23"
EV_ENGINE_VERSION = "v2"

# Real addition (July 2026, per external review, item 11) — the app
# mixes two genuinely different kinds of sport strings throughout:
# SAVE LABELS (used as the 'sport' column value in bets/predictions —
# 'MLB', 'NBA', 'NBA_AST', 'NFL', 'NFL_COMPLETIONS', 'NFL_RECEPTIONS')
# and MODEL KEYS (used internally by analyze_prop/get_min_std_dev/
# EDGE_THRESHOLDS — 'mlb_strikeouts', 'nba_points', 'nba_assists',
# 'nfl_pass_attempts', 'nfl_pass_completions', 'nfl_receptions'). A
# typo in either, in any one of the ~100+ places these get typed
# throughout the file, could silently make tracker filters or
# analytics miss real records with no error at all — exactly what
# happened with get_odds_api_sport_and_market() above, which was
# missing all three NFL branches entirely until this same review round.
# This dict is the canonical reference going forward — not a full,
# risky retrofit of every existing string literal (many of those are
# safe, validated, and working; rewriting ~100+ call sites for a
# cosmetic win wasn't worth the real risk of introducing a new mistake
# while doing it), but new code (including esports) should use these
# constants directly instead of retyping the strings.
SAVE_LABEL_TO_MODEL_KEY = {
    'MLB': 'mlb_strikeouts',
    'NBA': 'nba_points',
    'NBA_AST': 'nba_assists',
    'NFL': 'nfl_pass_attempts',
    'NFL_COMPLETIONS': 'nfl_pass_completions',
    'NFL_RECEPTIONS': 'nfl_receptions',
    'NFL_TD': 'nfl_td',
    'LOL': 'lol_moneyline',
}
MODEL_KEY_TO_SAVE_LABEL = {v: k for k, v in SAVE_LABEL_TO_MODEL_KEY.items()}

def get_json(url, *, params=None, headers=None, timeout=20):
    """Real fix (July 2026, per external review) — a shared helper for
    every HTTP GET across the app, replacing the widespread pattern of
    bare requests.get(url).json() with no timeout, no raise_for_status,
    and no protection against a malformed/non-JSON response. A single
    stalled provider (MLB Stats API, Odds API, umpire data, etc.) could
    otherwise hang the entire Streamlit run. Raises on a real HTTP
    error or a genuinely malformed response — callers already wrap
    their own try/except around external calls (matching the existing,
    established pattern throughout this app), so this doesn't swallow
    errors itself, it just makes sure a real one is always raised
    instead of silently returning something unusable."""
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()

def log_failure_reason(category, detail=""):
    """Real addition (July 2026, per external review, item 9) — a
    shared, lightweight counter for genuinely structured failure
    tracking, extending the same session_state-log pattern already used
    in a few places (e.g. Receptions' missing-targets log) to a
    consistent, app-wide convention. Not a replacement for the existing
    try/except blocks — those correctly protect users from crashes —
    but a way to record WHY something failed instead of a bare except
    silently reducing a real, specific problem (an upstream timeout, a
    missing player match, a malformed response) down to an
    indistinguishable None or an empty result. Call this from inside
    an except block right before falling back to None/empty/skip.
    Categories worth using consistently: 'UPSTREAM_TIMEOUT',
    'MISSING_PLAYER_MATCH', 'INSUFFICIENT_SAMPLE', 'MISSING_TEAM_MERGE',
    'MISSING_LINEUP', 'UNAVAILABLE_ODDS', 'MALFORMED_RESPONSE'."""
    st.session_state.setdefault('_failure_log', []).append({
        'category': category, 'detail': str(detail)[:300],
        'timestamp': datetime.now(ZoneInfo("UTC")).isoformat(),
    })

def get_cached_projection(cache_date_str, sport, player_name):
    try:
        res = supabase.table("daily_cache").select("*") \
            .eq("cache_date", cache_date_str).eq("sport", sport).eq("player_name", player_name) \
            .execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return None

def _json_safe(value):
    """Recursively converts numpy/pandas scalar types (returned by things like
    .mean()/.std() inside the projection engines) into native Python types,
    since Supabase's JSON encoder can't serialize numpy types directly and
    would silently fail every cache write otherwise."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, 'item') and callable(getattr(value, 'item', None)):
        try:
            return value.item()
        except Exception:
            return value
    return value

def upsert_cached_projection(cache_date_str, sport, player_name, projection_data, has_lineup_data=True):
    try:
        supabase.table("daily_cache").upsert({
            "cache_date": cache_date_str,
            "sport": sport,
            "player_name": player_name,
            "projection_data": _json_safe(projection_data),
            "has_lineup_data": has_lineup_data,
            "updated_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        }, on_conflict="cache_date,sport,player_name").execute()
    except Exception:
        pass

# Real fix (August 2026, per direct user report — "I literally just ran
# this 10 minutes ago why do I have to wait all over again") — found the
# real, root cause: @st.cache_data's cache lives entirely in the running
# server process's memory. Every single real deploy (and we've been
# deploying constantly tonight, one fix after another) restarts that
# process, WIPING the cache instantly regardless of its real TTL — a
# fresh, cold cache every time, no matter how recently it was warmed
# before that deploy. This adds a SECOND, real, persistent cache layer
# in Supabase (the same daily_cache table MLB/NBA/NFL already use) that
# genuinely survives real server restarts, using a fixed real sentinel
# player_name since this covers the WHOLE real LoL slate at once, not
# one player. Uses real, direct time-based freshness (checking
# updated_at against a real max age) instead of the once-a-day pattern
# those sports use, matching LoL's own real 2-hour freshness need.
_LOL_PIPELINE_CACHE_SENTINEL = "__ALL_MATCHUPS__"

def get_persistent_lol_pipeline_cache(max_age_seconds=7200):
    """Real, direct check of the persistent, Supabase-backed LoL cache
    — returns the real, cached pipeline output dict if a row exists AND
    is still within max_age_seconds, else None (a real, honest cache
    miss, whether from no row existing yet or the row being too old)."""
    try:
        res = supabase.table("daily_cache").select("*") \
            .eq("sport", "LOL").eq("player_name", _LOL_PIPELINE_CACHE_SENTINEL) \
            .order("updated_at", desc=True).limit(1).execute()
        if not res.data:
            return None
        row = res.data[0]
        updated_at_str = row.get("updated_at")
        if not updated_at_str:
            return None
        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        age_seconds = (datetime.now(ZoneInfo("UTC")) - updated_at).total_seconds()
        if age_seconds > max_age_seconds:
            return None
        return row.get("projection_data")
    except Exception:
        return None

def set_persistent_lol_pipeline_cache(pipeline_output):
    """Real, direct write to the persistent, Supabase-backed LoL cache
    — called right after a real, fresh pipeline computation, so the
    NEXT real request (even from a genuinely fresh server process after
    a real deploy) can skip straight to this instead of a full real
    recompute."""
    try:
        supabase.table("daily_cache").upsert({
            "cache_date": mm_today_str(),
            "sport": "LOL",
            "player_name": _LOL_PIPELINE_CACHE_SENTINEL,
            "projection_data": _json_safe(pipeline_output),
            "has_lineup_data": True,
            "updated_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        }, on_conflict="cache_date,sport,player_name").execute()
    except Exception:
        pass

# Real addition (August 2026, per direct user request — "I want it to
# cover all of them now", extending the API bridge to every sport, not
# just LoL). MLB/NBA/NFL's real, EXISTING daily_cache rows only ever
# stored each real player's raw model output (projection, std_dev,
# etc.) — never the real, FINISHED pick (with live odds, EV%, tier,
# all attached) the way LoL's own pipeline cache does. Rather than have
# a separate real API process re-derive that final pricing itself
# (real, duplicate-logic risk, the exact thing this whole bridge was
# built to avoid), this adds the SAME real "cache the whole, finished
# result" pattern LoL already has — generalized to work for any real
# sport code, not just LoL specifically. Uses a real, distinct sentinel
# player_name from LoL's own, so these rows never collide with either
# LoL's cache or the existing real per-player MLB/NBA/NFL rows.
_ALL_PICKS_CACHE_SENTINEL = "__API_BRIDGE_ALL_PICKS__"

def get_persistent_all_picks_cache(sport_code, max_age_seconds=7200):
    """Real, direct check of the persistent, Supabase-backed 'all
    finished picks for this sport' cache — returns the real, cached
    picks list if a row exists AND is still within max_age_seconds,
    else None."""
    try:
        res = supabase.table("daily_cache").select("*") \
            .eq("sport", sport_code).eq("player_name", _ALL_PICKS_CACHE_SENTINEL) \
            .order("updated_at", desc=True).limit(1).execute()
        if not res.data:
            return None
        row = res.data[0]
        updated_at_str = row.get("updated_at")
        if not updated_at_str:
            return None
        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        age_seconds = (datetime.now(ZoneInfo("UTC")) - updated_at).total_seconds()
        if age_seconds > max_age_seconds:
            return None
        return row.get("projection_data")
    except Exception:
        return None

def set_persistent_all_picks_cache(sport_code, picks_list):
    """Real, direct write to the persistent, Supabase-backed 'all
    finished picks for this sport' cache — called right after Today's
    Card's own real entries are built, so the real API bridge (or
    anything else) can read one real, ready-to-use list per sport
    without ever recomputing or re-deriving anything itself."""
    try:
        supabase.table("daily_cache").upsert({
            "cache_date": mm_today_str(),
            "sport": sport_code,
            "player_name": _ALL_PICKS_CACHE_SENTINEL,
            "projection_data": _json_safe(picks_list),
            "has_lineup_data": True,
            "updated_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        }, on_conflict="cache_date,sport,player_name").execute()
    except Exception:
        pass

def store_ai_insight(cache_date_str, sport, player_name, insight_text, thesis_label):
    """Saves a generated Model Insight onto the existing shared cache row, so
    it's computed once per pitcher/day and reused by every user after that."""
    try:
        supabase.table("daily_cache").update({
            "ai_insight": insight_text,
            "thesis_label": thesis_label,
        }).eq("cache_date", cache_date_str).eq("sport", sport).eq("player_name", player_name).execute()
    except Exception:
        pass

# ---- THESIS CLASSIFICATION (rule-based, no AI call — free) ----
def classify_thesis(info, result, sport):
    """Labels the *kind* of edge a prop represents, using only signals the model
    already computes (trend gaps, workload, EV, direction). Heuristic, not
    guaranteed — a best-effort categorization to help users understand the
    shape of the edge, not a certainty claim.
    Checked in priority order: sharp trend-based theses first (most specific/
    valuable read), falling back to matchup/park/umpire-driven theses, then
    general workload-character tags as the final catch-all."""
    if not result or not info:
        return None
    edge = info.get('Edge')
    ev = info.get('EV%')
    direction = info.get('Direction', 'over')
    if edge is None or ev is None:
        return None

    if sport == 'mlb_strikeouts':
        season_k_pct = result.get('season_k_pct')
        last5_k = result.get('last5_k')
        last10_k = result.get('last10_k')
        expected_bf = result.get('expected_bf')
        recent_5ip_count = result.get('recent_5ip_starts_count')
        last5_avg_ip = result.get('last5_avg_ip')
        season_avg_ip = result.get('season_avg_ip')
        opp_factor = result.get('opp_factor')
        park_factor = result.get('park_factor')
        umpire_factor = result.get('umpire_factor')
        workload_tier = result.get('workload_tier', '')
        confidence_tier = result.get('confidence_tier', '')

        season_implied_k_per_start = (season_k_pct * expected_bf) if (season_k_pct and expected_bf) else None
        workload_recovering = (
            recent_5ip_count is not None and recent_5ip_count >= 2 and
            last5_avg_ip is not None and season_avg_ip is not None and
            last5_avg_ip >= season_avg_ip * 0.85
        )

        if (direction == 'over' and edge > 0 and workload_recovering and
                last5_k is not None and season_implied_k_per_start and
                last5_k < season_implied_k_per_start * 0.80):
            return "🟢 Bounce-Back Spot"

        if direction == 'over' and edge > 0 and last5_k is not None and last10_k is not None and last5_k > last10_k * 1.15:
            return "🔥 Breakout Opportunity"

        if direction == 'under' and last5_k is not None and last10_k is not None and last5_k > last10_k * 1.20:
            return "⚠️ Regression Risk"

        if (direction == 'over' and edge and edge > 1.0 and
                last5_avg_ip is not None and season_avg_ip is not None and
                last5_avg_ip < season_avg_ip * 0.70 and
                (recent_5ip_count is None or recent_5ip_count <= 1)):
            return "💰 Market Overreaction"

        # Matchup/environment-driven theses
        if direction == 'over' and edge > 0 and opp_factor and opp_factor >= 1.08:
            return "🎯 Strikeout Matchup"
        if direction == 'over' and edge > 0 and park_factor and park_factor >= 1.05:
            return "🏟 Park Advantage"
        if direction == 'over' and edge > 0 and umpire_factor and umpire_factor >= 1.02:
            return "🧤 Favorable Umpire"

        # General workload-character fallback
        if edge > 0 and "Stable" in workload_tier and "Reliable" in confidence_tier:
            return "🧱 Stable Workhorse"
        if "Highly Volatile" in workload_tier or "Uncertain Workload" in confidence_tier:
            return "⚠️ Uncertain Workload"

    return None

# ---- AI MODEL INSIGHT (Claude API call — costs money, cached per pitcher/day) ----
ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY")
# Using Haiku since this task (facts -> plain sentences) doesn't need Sonnet-level
# reasoning — roughly 3x cheaper. Verify this is still a current model string in
# Anthropic's docs (docs.claude.com) before relying on it long-term — model names
# get retired/updated over time.
AI_INSIGHT_MODEL = "claude-haiku-4-5-20251001"

def build_insight_facts(pitcher_name, info, result, sport):
    """Assembles ONLY verified facts already computed by the model into a plain
    list — this is what gets handed to the AI, so it can't reference anything
    beyond what's actually true and in the data."""
    facts = []
    if sport == 'mlb_strikeouts':
        if result.get('season_k_pct') is not None:
            facts.append(f"Season K%: {round(result['season_k_pct']*100,1)}%")
        if result.get('last5_k') is not None:
            facts.append(f"Strikeouts in last 5 starts (avg): {result['last5_k']}")
        if result.get('last10_k') is not None:
            facts.append(f"Strikeouts in last 10 starts (avg): {result['last10_k']}")
        if result.get('last5_avg_ip') is not None:
            facts.append(f"Innings pitched, last 5 starts (avg): {result['last5_avg_ip']}")
        if result.get('season_avg_ip') is not None:
            facts.append(f"Innings pitched, season average: {result['season_avg_ip']}")
        if result.get('recent_5ip_starts_count') is not None:
            facts.append(f"Starts of 5+ IP in his last 5 outings: {result['recent_5ip_starts_count']}")
        if result.get('workload_tier'):
            facts.append(f"Workload/role stability tier: {result['workload_tier']}")
        if result.get('confidence_tier'):
            facts.append(f"Performance-variance tier: {result['confidence_tier']}")
        if result.get('opp_factor') is not None:
            facts.append(f"Opponent strikeout-rate factor vs league average: {result['opp_factor']}")
        if result.get('park_factor') is not None and result.get('park_factor') != 1.0:
            facts.append(f"Park factor: {result['park_factor']} (>1.0 favors pitcher/strikeouts)")
        if result.get('umpire_name') and result.get('umpire_factor'):
            facts.append(f"Home plate umpire: {result['umpire_name']}, strike-zone factor {result['umpire_factor']} (>1.0 favors strikeouts)")
    facts.append(f"Model projection: {info.get('Projection')}")
    facts.append(f"Book line: {info.get('FanDuel Line') or info.get('DraftKings Line')}")
    facts.append(f"Model edge: {info.get('Edge')}")
    facts.append(f"Expected value: {info.get('EV%')}%")
    facts.append(f"Direction: {info.get('Direction')}")
    return facts

def get_signals_used(result, sport):
    """Returns a friendly list of which data categories fed into the insight —
    lets users see it's grounded in the model's own signals, not invented."""
    signals = []
    if not result:
        return signals
    if sport == 'mlb_strikeouts':
        if result.get('last5_k') is not None or result.get('last10_k') is not None:
            signals.append("Recent Form")
        if result.get('workload_tier') or result.get('last5_avg_ip') is not None:
            signals.append("Workload Trend")
        if result.get('opp_factor') is not None:
            signals.append("Opponent Matchup")
        if result.get('park_factor') is not None and result.get('park_factor') != 1.0:
            signals.append("Park Factor")
        if result.get('umpire_name'):
            signals.append("Umpire")
    else:
        if result.get('last5_avg') is not None or result.get('last10_avg') is not None:
            signals.append("Recent Form")
        if result.get('expected_minutes') is not None:
            signals.append("Workload Trend")
        if result.get('opp_def_rating') is not None or result.get('opp_ast_allowed') is not None:
            signals.append("Opponent Matchup")
        if result.get('opp_pace') is not None:
            signals.append("Pace")
    signals.append("Betting Market Line")
    return signals

def render_ai_insight_block(insight, thesis_label, result, sport):
    """Consistent rendering used everywhere the AI insight shows up — header
    order and the fixed 'why this matters' footer live in exactly one place
    so they can't drift out of sync. (result/sport kept in the signature for
    future use even though not currently referenced in the body.)"""
    if not insight:
        return
    st.markdown("---")
    st.markdown("🧠 **Model Thesis**")
    if thesis_label:
        st.markdown(f"**{thesis_label}**")
    st.markdown(insight)
    st.caption("*Why this matters: the goal isn't to predict every outcome correctly — it's to identify situations where the model's assessment differs meaningfully from the current market.*")

def generate_ai_insight(pitcher_name, info, result, sport, thesis_label):
    """Calls Claude to turn the model's own facts into a short, evidence-only
    explanation. Explicitly instructed to never invent context (injury status,
    health, certainty) that isn't in the supplied facts, and to never phrase
    anything as a certain outcome."""
    if not ANTHROPIC_API_KEY:
        return None
    facts = build_insight_facts(pitcher_name, info, result, sport)
    facts_text = "\n".join(f"- {f}" for f in facts)
    thesis_note = f"\nThe model has tagged this as: {thesis_label}" if thesis_label else ""
    mm_tier = info.get('MM Tier', 'unrated')
    reliability_tier = result.get('confidence_tier', '') if result else ''

    prompt = f"""You are writing a short "Model Thesis" note for a sports betting analytics app, explaining why a statistical model's projection may differ from the sportsbook's line for {pitcher_name}.

Here are the ONLY facts you may use. Do not use any outside knowledge about this player, their health, or their team:
{facts_text}
{thesis_note}
This prop's overall tier: {mm_tier}
This prop's reliability read: {reliability_tier}

Write the note in this exact structure:
1. ONE bolded sentence (markdown **bold**) stating the model's overall read — analytical, not a stat restatement. Example: "**The model believes {pitcher_name} is undervalued because his recent strikeout profile is stronger than today's market line.**"
2. 2-3 sentences of supporting analysis. Explain what the market APPEARS TO BE PRICING versus what the underlying data supports — don't just list numbers. Bad: "Averaging 5.88 innings over his last 5 starts." Good: "The sportsbook appears to be pricing him closer to a shorter outing than his recent workload actually supports."
3. One closing line starting with "**Overall Thesis:**" that ties the reasoning back to this prop's tier and reliability read above — the model's overall take on whether this edge is worth acting on given both the edge size and the confidence level.

Strict rules:
- NEVER say a bet "will hit," "is a lock," "is guaranteed," or anything implying certainty about a future outcome.
- Always phrase conclusions as "the model believes," "the data suggests," "the market appears to be...", never as fact about what will happen.
- Never state or imply anything about health, injury, or motivation not explicitly in the facts.
- Never invent context not present in the facts.
- Write in plain, confident, analytical language — like a sharp bettor explaining their read, not a disclaimer-heavy legal notice.
- No preamble, no "Based on the facts provided" — just the 3-part note itself."""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": AI_INSIGHT_MODEL,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        text_blocks = [b['text'] for b in data.get('content', []) if b.get('type') == 'text']
        return "".join(text_blocks).strip() if text_blocks else None
    except Exception:
        return None

def get_or_generate_ai_insight(cache_date_str, sport, player_name, info, result):
    """Reads the AI insight off the shared cache if already generated today;
    otherwise generates it once and saves it for every other user to reuse."""
    cached = get_cached_projection(cache_date_str, sport, player_name)
    if cached and cached.get('ai_insight'):
        return cached['ai_insight'], cached.get('thesis_label')

    # Real fix (July 2026) — was originally a hardcoded ternary chain
    # that only recognized 'MLB' and 'NBA', silently routing anything
    # else (including all three NFL models, once they existed) to
    # 'nba_assists' by default. Now uses the centralized
    # SAVE_LABEL_TO_MODEL_KEY constant (item 11) instead of its own
    # separate, hand-typed copy of the same mapping.
    model_key = SAVE_LABEL_TO_MODEL_KEY.get(sport, 'mlb_strikeouts')
    thesis_label = classify_thesis(info, result, model_key)
    insight = generate_ai_insight(player_name, info, result, model_key, thesis_label)
    if insight:
        store_ai_insight(cache_date_str, sport, player_name, insight, thesis_label)
    return insight, thesis_label

def _cache_is_stale_provisional(cached_row):
    """A provisional (no-lineup) MLB cache entry is worth re-checking once
    enough time has passed that a lineup might have posted since."""
    if cached_row.get('has_lineup_data'):
        return False
    updated_at = cached_row.get('updated_at')
    if not updated_at:
        return True
    try:
        updated_dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        age_minutes = (datetime.now(ZoneInfo("UTC")) - updated_dt).total_seconds() / 60
        return age_minutes >= LINEUP_RECHECK_MINUTES
    except Exception:
        return True

# ---- PUBLIC MODEL PERFORMANCE STATS ----
# Admin-curated trust page data. Predictions/bets are per-user by design (RLS),
# so instead of trying to aggregate live across every user's private history,
# admin publishes a snapshot of their own tracked results to a public table that
# any user can read — same pattern as a "verified track record" page.
def publish_model_performance(sport_key):
    """Computes current MAE (from admin's predictions) and ROI/beat-close (from
    admin's bets) for a sport, and publishes the snapshot to the public stats table."""
    try:
        preds = load_predictions(sport_key)
        preds_with_actual = [p for p in preds if p.get('actual') is not None]
        total_projections = len(preds_with_actual)
        mae = None
        if preds_with_actual:
            errors = [abs(p['projection'] - p['actual']) for p in preds_with_actual]
            mae = round(sum(errors) / len(errors), 2)

        bets = load_bets(sport_key)
        settled = [b for b in bets if b.get('result') != 'Pending']
        total_bets = len(settled)
        roi = None
        profit_series = []
        if settled:
            total_wagered = sum(b.get('bet_amount', 0) or 0 for b in settled)
            total_profit = sum(b.get('profit', 0) or 0 for b in settled)
            roi = round(total_profit / total_wagered * 100, 1) if total_wagered else None
            cumulative = 0
            for b in sorted(settled, key=lambda b: b.get('date', '')):
                cumulative += b.get('profit', 0) or 0
                profit_series.append({'date': b.get('date'), 'cumulative_profit': round(cumulative, 2)})

        clv_bets = [b for b in settled if b.get('clv') is not None]
        beat_close_pct = None
        if clv_bets:
            beat_close_pct = round(sum(1 for b in clv_bets if (b.get('clv') or 0) > 0) / len(clv_bets) * 100, 1)

        supabase.table("model_performance_stats").upsert({
            "sport": sport_key,
            "total_projections": total_projections,
            "mae": mae,
            "total_bets": total_bets,
            "roi": roi,
            "beat_close_pct": beat_close_pct,
            "profit_series": _json_safe(profit_series),
            "updated_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        }, on_conflict="sport").execute()
        return True
    except Exception as e:
        st.error(f"Error publishing stats: {e}")
        return False

def get_published_model_performance(sport_key):
    try:
        res = supabase.table("model_performance_stats").select("*").eq("sport", sport_key).execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return None

def cached_run_projection(pitcher_name, opponent_team, home_team, season, cache_date_str):
    """Shared-cache wrapper around run_projection(). Reuses a cached result unless
    it's a provisional (pre-lineup) MLB entry old enough to be worth re-checking,
    OR it was computed by an older version of the model logic (see
    MLB_PROJECTION_MODEL_VERSION) — a real fix (July 2026) for a real problem:
    without this, a genuine fix to the calculation itself had zero visible effect
    on any pitcher already cached for today, and only a manual, per-pitcher
    force-refresh worked. Now any real model-logic change automatically
    invalidates every stale cached entry, with no manual intervention needed."""
    cached = get_cached_projection(cache_date_str, 'MLB', pitcher_name)
    cached_version = (cached.get('projection_data') or {}).get('_model_version') if cached else None
    is_stale_model_version = cached is not None and cached_version != MLB_PROJECTION_MODEL_VERSION
    if cached and not _cache_is_stale_provisional(cached) and not is_stale_model_version:
        return cached['projection_data']

    result = run_projection(pitcher_name, opponent_team, home_team, season)
    if result:
        has_lineup = result.get('lineup_factor') is not None
        upsert_cached_projection(cache_date_str, 'MLB', pitcher_name, result, has_lineup_data=has_lineup)
        return result
    # Model run failed — fall back to the stale cached version rather than nothing
    return cached['projection_data'] if cached else None

def cached_run_nba_projection(run_fn, sport_label, player_name, opp_abbrev, home_team, away_team, home_or_away, season, cache_date_str):
    """Shared-cache wrapper for NBA projections. No lineup-reveal dynamic like MLB,
    so once cached for the day it's trusted for the rest of the day."""
    cached = get_cached_projection(cache_date_str, sport_label, player_name)
    if cached:
        return cached['projection_data']

    result = run_fn(player_name, opp_abbrev, home_team, away_team, home_or_away, season)
    if result:
        upsert_cached_projection(cache_date_str, sport_label, player_name, result, has_lineup_data=True)
    return result

def cached_run_nfl_projection(run_fn, sport_label, player_name, cache_date_str, *run_fn_args, **run_fn_kwargs):
    """Real fix (August 2026) — extends the exact same proven,
    persistent, cross-user daily_cache pattern already working well
    for MLB and NBA to NFL, which previously had ZERO computation
    caching at all: every single visitor's session fully recomputed
    every real QB/receiver projection from scratch, every single time
    — confirmed as the single biggest real contributor to the "wait ~5
    minutes to see props" complaint, since NFL alone could mean 15-30+
    real, live projection runs per visitor with no reuse whatsoever.

    Genuinely generic across all three real NFL models (unlike NBA's
    cached_run_nba_projection, which assumes one fixed real function
    signature shared by both NBA variants) — the three real NFL
    projection functions (Pass Attempts, Pass Completions, Receptions)
    have real, different signatures (Receptions needs an extra real
    qb_name argument the other two don't), so run_fn is called as
    run_fn(*run_fn_args, **run_fn_kwargs) — the caller decides exactly
    how to invoke its own real model function; this wrapper only owns
    the real caching logic wrapped around that call, reusing the same
    generic daily_cache table (already sport-agnostic — sport_label is
    just a string column, 'NFL'/'NFL_COMPLETIONS'/'NFL_RECEPTIONS' work
    exactly the same way 'MLB'/'NBA'/'NBA_AST' already do, no schema
    changes needed at all)."""
    cached = get_cached_projection(cache_date_str, sport_label, player_name)
    if cached:
        return cached['projection_data']

    result = run_fn(*run_fn_args, **run_fn_kwargs)
    if result:
        upsert_cached_projection(cache_date_str, sport_label, player_name, result, has_lineup_data=True)
    return result

def force_run_and_cache_mlb(pitcher_name, opponent_team, home_team, season, cache_date_str):
    """Always computes fresh (used by the manual ▶️ Run button, which exists
    specifically to force a recompute) but still updates the shared cache
    afterward so every other user benefits from the fresh result too."""
    result = run_projection(pitcher_name, opponent_team, home_team, season)
    if result:
        has_lineup = result.get('lineup_factor') is not None
        upsert_cached_projection(cache_date_str, 'MLB', pitcher_name, result, has_lineup_data=has_lineup)
    return result

def force_run_and_cache_nba(run_fn, sport_label, player_name, opp_abbrev, home_team, away_team, home_or_away, season, cache_date_str):
    """Always computes fresh (manual ▶️ Run button) but still updates the shared cache."""
    result = run_fn(player_name, opp_abbrev, home_team, away_team, home_or_away, season)
    if result:
        upsert_cached_projection(cache_date_str, sport_label, player_name, result, has_lineup_data=True)
    return result

def build_todays_card_entries():
    """Pulls together whatever's currently loaded in session state (every
    model in the app — MLB, both NBA prop types, all three NFL prop
    types, and LoL) into one unified, ranked list. Shared by Today's
    Card and the Home page 'Today's Highest Rated Bet' section so they
    never show different data.

    Real fix (July 2026) — originally only included MLB + NBA; NFL and
    LoL existed as real, working models elsewhere in the app but were
    invisible here, meaning Today's Card wasn't actually showing every
    model's real output. NFL follows the exact same player-prop shape
    already used for MLB/NBA (session_state[f'{key}_results'], 'Projection'/
    'MM Tier'/etc on the info dict). LoL is structurally different — a
    real matchup (two teams, a recommended side, model vs market
    probability) rather than a player + line — so it's mapped into the
    same card-entry shape rather than reusing the player-prop loop."""
    card_entries = []

    mlb_pitchers = st.session_state.get('all_pitchers', {})
    mlb_results = st.session_state.get('pitcher_results', {})
    for name, info in mlb_pitchers.items():
        # Real, deliberate exclusion (August 2026, per direct user
        # request — "take out all plays that read pass") — a Pass
        # tier isn't a real actionable pick, so it never belonged in
        # this real, curated "today's picks" list to begin with. The
        # full per-sport analysis tables elsewhere in this app still
        # show every real player regardless of tier, unaffected by
        # this — this only trims the real, actionable picks feed.
        if info.get('Projection') is not None and info.get('MM Tier') and info.get('MM Tier') != "🔴 Pass":
            card_entries.append({
                'sport_label': '⚾ MLB', 'sport_key': 'mlb_strikeouts', 'name': name,
                'line': info.get('Best Line') or info.get('FanDuel Line') or info.get('DraftKings Line'),
                'play': info.get('Play'), 'edge': info.get('Edge'),
                'ev_pct': info.get('EV%'), 'tier': info.get('MM Tier'),
                'info': info, 'result': mlb_results.get(name),
                'best_book': info.get('Best Book'),
                'alt_book_lines': info.get('Alt Book Lines', []),
            })

    # MLB Batter Hits (Sep 2026) — backtested and split-half validated
    # (12,658 bets, +4.65%/+5.50% ROI). Tier thresholds here reflect
    # the validated INVERTED profitable zone (0-12% EV), handled
    # entirely inside get_tier's mlb_batter_hits branch — MM Tier
    # already correctly excludes the confirmed-unprofitable 12%+ zone,
    # so the same "!= Pass" filter used everywhere else is correct here.
    mlb_batters = st.session_state.get('all_mlb_batters', {})
    batter_hits_results = st.session_state.get('batter_hits_results', {})
    for name, info in mlb_batters.items():
        if info.get('Projection') is not None and info.get('MM Tier') and info.get('MM Tier') != "🔴 Pass":
            card_entries.append({
                'sport_label': '⚾ MLB Hits', 'sport_key': 'mlb_batter_hits', 'name': name,
                'line': info.get('Best Line'),
                'play': info.get('Play'), 'edge': info.get('Edge'),
                'ev_pct': info.get('EV%'), 'tier': info.get('MM Tier'),
                'info': info, 'result': batter_hits_results.get(name),
                'best_book': info.get('Best Book'),
                'alt_book_lines': info.get('Alt Book Lines', []),
            })

    # NBA Points and NBA Assists REMOVED from Today's Card feed (Sep
    # 2026) — both backtested twice against real historical odds with
    # consistent, repeated negative results:
    #   NBA Points: 18,218 bets (-5.93% ROI), rerun with a real pace-
    #     calculation fix confirmed the same result (9,785 bets,
    #     -6.41% ROI) — every EV bucket negative both times.
    #   NBA Assists: 17,004 bets (-7.74% ROI), every EV bucket
    #     negative; a smaller real-production-model retest (94 bets)
    #     also came back negative (-9.6% ROI).
    # Same treatment as NFL pass attempts/completions/receptions and
    # LoL above — backend code kept intact (run_all_nba_projections
    # and both projection functions still work) in case a future
    # rebuild (real opponent defensive rating, which is currently a
    # disabled neutral fallback — see run_nba_points_projection's own
    # comment — or real game-total integration) brings these back
    # profitable. Just not surfaced to users until then.

    # Real addition (July 2026) — all three NFL prop models, same
    # player-prop pattern as MLB/NBA above. Session-state keys confirmed
    # from run_nfl_display()'s real call sites for each model.
    nfl_models = [
        ('all_td_scorers', 'nfl_td_results', '🏈 NFL TD', 'nfl_td'),
    ]
    for all_players_key, results_key, sport_label, sport_key in nfl_models:
        nfl_players = st.session_state.get(all_players_key, {})
        nfl_results = st.session_state.get(results_key, {})
        for name, info in nfl_players.items():
            if info.get('Projection') is not None and info.get('MM Tier') and info.get('MM Tier') != "🔴 Pass":
                card_entries.append({
                    'sport_label': sport_label, 'sport_key': sport_key, 'name': name,
                    'line': info.get('FanDuel Line') or info.get('DraftKings Line'),
                    'play': info.get('Play'), 'edge': info.get('Edge'),
                    'ev_pct': info.get('EV%'), 'tier': info.get('MM Tier'),
                    'info': info, 'result': nfl_results.get(name),
                })

    # LoL REMOVED from Today's Card feed (Aug 2026) — backtested against
    # real historical Polymarket prices (649 graded bets, walk-forward,
    # leak-free): -27.44% ROI overall, and no profitable filter/tier
    # combination survived a larger sample (favorite/underdog cuts, EV%
    # buckets, best-of format, H2H sample size, and combinations of
    # these were all tested — see lol_backtest.py). Unlike MLB
    # strikeouts, there's no clean EV threshold to retier into here;
    # the model itself isn't beating the market, not just showing the
    # wrong picks. Same treatment as the NFL pass attempts/completions/
    # receptions models above — pipeline and backend code kept intact
    # (cito_api.py, lol_elo.py, polymarket_api.py, run_lol_matchup_
    # projections all still work) in case a future rebuild (real roster
    # tracking, player-level data, or fixing the series_win_probability
    # amplification the backtest surfaced) brings it back profitable.
    # Just not surfaced to users until then.

    return card_entries

def top_ranked_entry(card_entries):
    """Returns the single highest-ranked entry (tier, then EV%, then edge) or None."""
    if not card_entries:
        return None
    ranked = sorted(
        card_entries,
        key=lambda e: (
            TIER_RANK.get(e['tier'], -1),
            e['ev_pct'] if e['ev_pct'] is not None else -999,
            abs(e['edge']) if e['edge'] is not None else -999
        ),
        reverse=True
    )
    return ranked[0]

# ---- MODEL TRACK RECORD (PHASE 1: MLB + NBA) ----
# Real, new addition (August 2026, per direct user request — "how has
# the model been" shown to non-subscribed users on the new site).
# Deliberately separate from the existing "bets" table, which only
# ever reflects what ONE real user chose to log — this tracks every
# real, actionable pick the model itself makes, graded automatically
# against the real final result, independent of anyone's own betting
# decisions. Phased deliberately: NFL and LoL picks are still
# RECORDED here (so nothing needs to change again once Phase 2 ships),
# but only actually GRADED for MLB and NBA right now — NFL has no real
# games to verify grading logic against until the season starts, and
# LoL's data has been the most fragile part of this whole app all
# session, so real automatic grading for it needs real games to test
# against first.

def record_picks_for_grading(card_entries):
    """Real, upserting insert of every real, actionable (non-Pass)
    pick into the graded_picks table — safe to call on every real
    auto-run, since the real (pick_date, sport_key, player_name)
    unique constraint means re-running today's auto-run multiple times
    never creates real duplicate rows, just refreshes the same one.

    Phase 2 (August 2026) — now stores LoL-specific data (recommended
    team name in direction, recommended odds in odds, recommended
    team's Cito slug in game_pk) so the grading function can look up
    the actual match result later without needing to re-run the full
    LoL resolution pipeline."""
    if not supabase:
        return
    today_str = mm_today_str()

    # Real, single, lightweight lookup — built once per real auto-run,
    # not once per pitcher, specifically so MLB grading later has a
    # real game_pk to work with without needing to touch or modify the
    # real, deep MLB projection pipeline itself.
    mlb_game_pk_by_pitcher = {}
    try:
        for s in get_starters_for_date(today_str):
            mlb_game_pk_by_pitcher[s['pitcher']] = s['game_pk']
    except Exception:
        pass

    for e in card_entries:
        tier = e.get('tier')
        if not tier or tier == "🔴 Pass":
            continue  # only real, actionable picks belong in a real track record
        info = e.get('info') or {}
        sport_key = e.get('sport_key')

        # ---- LoL-specific payload ----
        # LoL is a moneyline bet, not an over/under prop — the
        # concepts of "direction" (over/under) and "odds" (FanDuel
        # over/under price) don't apply. Instead:
        # - direction: stores the recommended team NAME (used to
        #   identify which side was picked when grading)
        # - odds: stores the recommended American odds (used for
        #   ROI calculation in model-performance)
        # - game_pk: stores the recommended team's Cito slug (used
        #   to fetch match history for grading)
        if sport_key == 'lol_moneyline':
            rec_team = info.get('recommended_team_name')
            rec_side = info.get('recommended_side')
            rec_odds = info.get('recommended_odds')
            if rec_side == 'team1':
                rec_slug = info.get('team1_slug')
            else:
                rec_slug = info.get('team2_slug')

            payload = {
                "pick_date": today_str,
                "sport_key": sport_key,
                "sport_label": e.get('sport_label'),
                "player_name": e['name'],
                "line": e.get('line'),
                "direction": rec_team,
                "odds": rec_odds,
                "mm_tier": tier,
                "ev_pct": e.get('ev_pct'),
                "game_pk": rec_slug,
            }
            try:
                supabase.table("graded_picks").upsert(
                    payload, on_conflict="pick_date,sport_key,player_name"
                ).execute()
            except Exception:
                pass
            continue

        # ---- Standard prop-sport payload (MLB/NBA/NFL) ----
        play_text = str(e.get('play') or '')
        is_over = "OVER" in play_text.upper()
        direction = "over" if "OVER" in play_text.upper() else ("under" if "UNDER" in play_text.upper() else None)
        odds = info.get('FanDuel Over') if is_over else info.get('FanDuel Under')
        if odds is None:
            odds = info.get('DraftKings Over') if is_over else info.get('DraftKings Under')

        payload = {
            "pick_date": today_str,
            "sport_key": sport_key,
            "sport_label": e.get('sport_label'),
            "player_name": e['name'],
            "line": e.get('line'),
            "direction": direction,
            "odds": odds,
            "mm_tier": tier,
            "ev_pct": e.get('ev_pct'),
        }
        if sport_key == 'mlb_strikeouts':
            payload["game_pk"] = mlb_game_pk_by_pitcher.get(e['name'])

        try:
            supabase.table("graded_picks").upsert(
                payload, on_conflict="pick_date,sport_key,player_name"
            ).execute()
        except Exception:
            pass  # real, best-effort — a real recording failure should never break the real auto-run


def _nfl_date_to_week(pick_date_str, season):
    """Maps a pick date to the NFL week it belongs to, using the real
    schedule. Needed for grading NFL picks — the weekly player stats
    are keyed by week number, not date, so this bridge is required to
    look up actual results. Returns the week number (int) or None if
    no matching game is found within 1 day of the pick date."""
    try:
        schedules = get_nfl_schedules([int(season)])
        schedules = schedules.copy()
        schedules['gameday_dt'] = pd.to_datetime(schedules['gameday'], errors='coerce')
        pick_dt = pd.Timestamp(pick_date_str)
        # Exact date match first
        same_day = schedules[schedules['gameday_dt'].dt.normalize() == pick_dt.normalize()]
        if not same_day.empty:
            return int(same_day.iloc[0]['week'])
        # If no exact match (e.g. a pick recorded slightly before/after
        # midnight relative to the game), find the closest game within
        # 1 day — NFL games are spread across Thu/Sun/Mon so a 1-day
        # window is safe without risk of matching the wrong week.
        schedules['_date_diff'] = (schedules['gameday_dt'] - pick_dt).abs()
        closest = schedules.nsmallest(1, '_date_diff')
        if not closest.empty and closest.iloc[0]['_date_diff'].days <= 1:
            return int(closest.iloc[0]['week'])
        return None
    except Exception:
        return None


def _grade_one_pick(row):
    """Returns (actual_stat, result) for one real, pending row, or
    (None, None) if the real actual result genuinely isn't available
    yet (a real game that hasn't been played, or box score data that
    hasn't posted yet — NOT the same as a real 0-for-something, which
    IS a real, gradeable result).

    Phase 2 (August 2026) — NFL and LoL grading added alongside the
    existing MLB and NBA grading."""
    sport_key = row.get('sport_key')
    player_name = row.get('player_name')
    line = row.get('line')
    direction = row.get('direction')

    # ---- MLB STRIKEOUTS ----
    if sport_key == 'mlb_strikeouts':
        if line is None or direction is None:
            return None, None
        game_pk = row.get('game_pk')
        if not game_pk:
            return None, None
        actual = get_actual_strikeouts(game_pk, player_name)
        if actual is None:
            return None, None
        if actual == line:
            return actual, "push"
        won = (actual > line) if direction == "over" else (actual < line)
        return actual, ("win" if won else "loss")

    # ---- NBA POINTS / ASSISTS ----
    elif sport_key in ('nba_points', 'nba_assists'):
        if line is None or direction is None:
            return None, None
        try:
            box_df = get_bdl_games_for_date(row['pick_date'])
        except Exception:
            return None, None
        if box_df is None or box_df.empty:
            return None, None
        stat_col = 'ast' if sport_key == 'nba_assists' else 'pts'
        for _, r in box_df.iterrows():
            p = r.get('player') or {}
            full_name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            if full_name.lower() == str(player_name).lower():
                val = r.get(stat_col)
                if val is not None:
                    if val == line:
                        return val, "push"
                    won = (val > line) if direction == "over" else (val < line)
                    return val, ("win" if won else "loss")
                break
        return None, None

    # ---- NFL PASS ATTEMPTS / COMPLETIONS / RECEPTIONS ----
    elif sport_key in ('nfl_pass_attempts', 'nfl_pass_completions', 'nfl_receptions'):
        if line is None or direction is None:
            return None, None
        # Determine the NFL season from the pick date — if the pick is
        # in Jan/Feb, it belongs to the prior year's season.
        try:
            pick_year = int(row['pick_date'][:4])
            pick_month = int(row['pick_date'][5:7])
            nfl_season = pick_year if pick_month >= 3 else pick_year - 1
        except (ValueError, TypeError):
            return None, None

        week = _nfl_date_to_week(row['pick_date'], nfl_season)
        if week is None:
            return None, None

        stat_col_map = {
            'nfl_pass_attempts': 'attempts',
            'nfl_pass_completions': 'completions',
            'nfl_receptions': 'receptions',
        }
        stat_col = stat_col_map.get(sport_key)
        if not stat_col:
            return None, None

        try:
            weekly = get_nfl_player_stats([nfl_season])
        except Exception:
            return None, None

        # Real, defensive filtering — same season_type guard already
        # used in get_qb_starter_rows and get_wr_te_rows, applied here
        # too so a preseason or playoff row can never accidentally
        # grade a regular-season pick.
        if 'season_type' in weekly.columns:
            weekly = weekly[weekly['season_type'] == 'REG']

        # Match by player name + week. For receptions, match across
        # all receiving-eligible positions (WR/TE/RB/FB), same as the
        # live pipeline's RECEPTION_POSITIONS.
        if sport_key == 'nfl_receptions':
            player_rows = weekly[
                (weekly['player_display_name'] == player_name) &
                (weekly['week'] == week) &
                (weekly['position'].isin(RECEPTION_POSITIONS))
            ]
        else:
            player_rows = weekly[
                (weekly['player_display_name'] == player_name) &
                (weekly['week'] == week) &
                (weekly['position'] == 'QB')
            ]

        if player_rows.empty:
            return None, None

        actual = player_rows.iloc[0].get(stat_col)
        if actual is None or (isinstance(actual, float) and pd.isna(actual)):
            return None, None
        actual = int(actual)

        if actual == line:
            return actual, "push"
        won = (actual > line) if direction == "over" else (actual < line)
        return actual, ("win" if won else "loss")

    # ---- LOL MONEYLINE ----
    elif sport_key == 'lol_moneyline':
        # LoL is a moneyline bet (team win/loss), not an over/under
        # prop — there's no "line" to compare against, just whether
        # the recommended team won. The recommended team's name is
        # stored in the `direction` field (repurposed from over/under
        # since that concept doesn't apply to moneyline), and the
        # recommended team's Cito slug is stored in `game_pk` — both
        # set by record_picks_for_grading's LoL-specific block.
        recommended_team_name = row.get('direction')
        team_slug = row.get('game_pk')
        if not recommended_team_name or not team_slug:
            return None, None

        try:
            from cito_api import get_lol_team_matches, extract_completed_matches
            cito_api_key = st.secrets.get("CITO_API_KEY")
            if not cito_api_key:
                return None, None
            team_matches = _call_cito_with_backoff(
                get_lol_team_matches, cito_api_key, team_slug
            )
            completed = extract_completed_matches(team_matches)
        except Exception:
            return None, None

        pick_date = row['pick_date']
        for match in completed:
            # Match by date — Cito startTime is a full ISO timestamp,
            # pick_date is YYYY-MM-DD, so compare just the date part.
            match_date = (match.get('startTime') or '')[:10]
            if match_date != pick_date:
                continue

            winner_slug = match.get('winner')
            if not winner_slug:
                continue  # match completed but winner not recorded yet

            # Check if the recommended team won
            if winner_slug == team_slug:
                return 1, "win"
            elif winner_slug:
                # The other team won
                return 0, "loss"

        return None, None  # no completed match found for this date

    else:
        return None, None


def _resolve_mlb_game_pk(pitcher_name, date_str):
    """Real, derived game_pk lookup for a user-logged MLB bet — the
    `bets` table (unlike `graded_picks`) doesn't store game_pk at log
    time, since a user can log a bet from any pick card without the
    site needing to persist that internal ID for them. Reconstructed
    here from pitcher name + date using the same real starters lookup
    (get_starters_for_date) already proven elsewhere on this platform."""
    try:
        starters = get_starters_for_date(date_str)
    except Exception:
        return None
    for s in starters:
        if s.get('pitcher', '').lower() == pitcher_name.lower():
            return s.get('game_pk')
    return None


def _grade_one_user_bet(bet):
    """Returns (actual_stat, result) for one real, pending USER-LOGGED
    bet (from the `bets` table), or (None, None) if the real actual
    result genuinely isn't available yet.

    Sep 2026 — critical difference from _grade_one_pick: grades
    against the bet's own REAL bet_line (the actual number the user
    took, which the 'Log' form lets them edit if they shopped a
    different book than the one recommended) — not any original
    recommended line. Also uses the bet's own real stored odds/
    bet_amount for real profit computation, not recomputed or assumed
    values. This is exactly why bet_line was added — grading against
    the wrong line would silently mis-grade any bet where the user
    took a different number than the site's original recommendation."""
    sport = bet.get('sport')
    player_name = bet.get('pitcher')
    date_str = bet.get('date')
    line = bet.get('bet_line')
    direction = (bet.get('over_under') or '').lower()

    if not sport or not player_name or not date_str or line is None or direction not in ('over', 'under'):
        return None, None

    if sport == 'MLB':
        game_pk = _resolve_mlb_game_pk(player_name, date_str)
        if not game_pk:
            return None, None
        actual = get_actual_strikeouts(game_pk, player_name)
        if actual is None:
            return None, None
        if actual == line:
            return actual, 'Push'
        won = (actual > line) if direction == 'over' else (actual < line)
        return actual, ('Win' if won else 'Loss')

    elif sport in ('NBA', 'NBA_AST'):
        try:
            box_df = get_bdl_games_for_date(date_str)
        except Exception:
            return None, None
        if box_df is None or box_df.empty:
            return None, None
        stat_col = 'ast' if sport == 'NBA_AST' else 'pts'
        for _, r in box_df.iterrows():
            p = r.get('player') or {}
            full_name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            if full_name.lower() == str(player_name).lower():
                val = r.get(stat_col)
                if val is not None:
                    if val == line:
                        return val, 'Push'
                    won = (val > line) if direction == 'over' else (val < line)
                    return val, ('Win' if won else 'Loss')
                break
        return None, None

    elif sport in ('NFL', 'NFL_COMPLETIONS', 'NFL_RECEPTIONS'):
        try:
            pick_year = int(date_str[:4])
            pick_month = int(date_str[5:7])
            nfl_season = pick_year if pick_month >= 3 else pick_year - 1
        except (ValueError, TypeError):
            return None, None
        week = _nfl_date_to_week(date_str, nfl_season)
        if week is None:
            return None, None
        stat_col_map = {'NFL': 'attempts', 'NFL_COMPLETIONS': 'completions', 'NFL_RECEPTIONS': 'receptions'}
        stat_col = stat_col_map.get(sport)
        try:
            weekly = get_nfl_player_stats([nfl_season])
        except Exception:
            return None, None
        if 'season_type' in weekly.columns:
            weekly = weekly[weekly['season_type'] == 'REG']
        if sport == 'NFL_RECEPTIONS':
            player_rows = weekly[
                (weekly['player_display_name'] == player_name) & (weekly['week'] == week) &
                (weekly['position'].isin(RECEPTION_POSITIONS))
            ]
        else:
            player_rows = weekly[
                (weekly['player_display_name'] == player_name) & (weekly['week'] == week) &
                (weekly['position'] == 'QB')
            ]
        if player_rows.empty:
            return None, None
        actual = player_rows.iloc[0].get(stat_col)
        if actual is None or (isinstance(actual, float) and pd.isna(actual)):
            return None, None
        actual = int(actual)
        if actual == line:
            return actual, 'Push'
        won = (actual > line) if direction == 'over' else (actual < line)
        return actual, ('Win' if won else 'Loss')

    elif sport == 'NFL_TD':
        try:
            pick_year = int(date_str[:4])
            pick_month = int(date_str[5:7])
            nfl_season = pick_year if pick_month >= 3 else pick_year - 1
        except (ValueError, TypeError):
            return None, None
        week = _nfl_date_to_week(date_str, nfl_season)
        if week is None:
            return None, None
        try:
            weekly = get_nfl_player_stats([nfl_season])
        except Exception:
            return None, None
        if 'season_type' in weekly.columns:
            weekly = weekly[weekly['season_type'] == 'REG']
        player_rows = weekly[(weekly['player_display_name'] == player_name) & (weekly['week'] == week)]
        if player_rows.empty:
            return None, None
        row = player_rows.iloc[0]
        if 'rushing_tds' in weekly.columns and 'receiving_tds' in weekly.columns:
            total_tds = (row.get('rushing_tds') or 0) + (row.get('receiving_tds') or 0)
        elif 'rushing_tds' in weekly.columns:
            total_tds = row.get('rushing_tds') or 0
        else:
            return None, None
        if total_tds == line:
            return total_tds, 'Push'
        won = (total_tds > line) if direction == 'over' else (total_tds < line)
        return total_tds, ('Win' if won else 'Loss')

    elif sport == 'MLB_BATTER_HITS':
        # Simpler than the other MLB grading branch above — no game_pk
        # resolution needed at all. The batter's own season gameLog
        # (get_batter_game_log_live, already fetched for live
        # projections) has one real entry per date with real hits for
        # that specific game — just look up the bet's own date
        # directly.
        try:
            pick_year = int(date_str[:4])
        except (ValueError, TypeError):
            return None, None
        games = get_batter_game_log_live(player_name, pick_year, required_date=date_str)
        match = next((g for g in games if g['date'] == date_str), None)
        if match is None:
            return None, None
        actual = match['hits']
        if actual == line:
            return actual, 'Push'
        won = (actual > line) if direction == 'over' else (actual < line)
        return actual, ('Win' if won else 'Loss')

    else:
        # LoL and anything else — not auto-gradable. LoL bets store a
        # "TeamA vs TeamB" matchup string in `pitcher` (no resolvable
        # team slug) and have no real numeric line (it's a moneyline
        # market, not an over/under), so this is a genuine, honest
        # gap rather than a guess. Left pending.
        return None, None


def grade_pending_bets():
    """Real, automatic grading pass over every real pending USER-
    LOGGED bet from a real PAST date. Mirrors grade_pending_picks()
    but targets the `bets` table (a user's own logged bets, shown on
    the Bet Tracker page) instead of `graded_picks` (the model's own
    recommendation-history tracking) — and removes the need for a
    user to ever self-report Win/Loss, so results can't be misreported
    (accidentally or otherwise). Safe to call on every auto-run: bets
    that genuinely can't be graded yet (game not finished, stats not
    posted) are silently left pending and retried next cycle."""
    if not supabase:
        return
    today_str = mm_today_str()
    try:
        res = supabase.table("bets").select("*") \
            .eq("result", "Pending").lt("date", today_str) \
            .limit(200).execute()
        pending = res.data or []
    except Exception:
        return

    for bet in pending:
        try:
            actual, result = _grade_one_user_bet(bet)
            if result is None:
                continue
            bet_amount = bet.get('bet_amount')
            odds = bet.get('odds')
            if result == 'Push':
                profit = 0.0
            elif bet_amount is not None and odds is not None:
                if result == 'Win':
                    profit = round((odds / 100 * bet_amount) if odds > 0 else (100 / abs(odds) * bet_amount), 2)
                else:
                    profit = round(-bet_amount, 2)
            else:
                profit = None
            supabase.table("bets").update({
                "actual": actual, "result": result, "profit": profit,
            }).eq("id", bet["id"]).execute()
        except Exception:
            continue  # one bad row should never stop the rest from grading


def grade_pending_picks():
    """Real, best-effort grading pass over every real pending pick from
    a real PAST date (never today's — those games likely haven't
    finished yet). Safe to call on every real auto-run: picks that
    genuinely can't be graded yet (game not finished, box score not
    posted) are silently left pending and get tried again on the real
    next auto-run."""
    if not supabase:
        return
    today_str = mm_today_str()
    try:
        res = supabase.table("graded_picks").select("*") \
            .eq("result", "pending").lt("pick_date", today_str) \
            .limit(200).execute()
        pending = res.data or []
    except Exception:
        return

    for row in pending:
        try:
            actual, result = _grade_one_pick(row)
            if result is None:
                continue
            supabase.table("graded_picks").update({
                "actual_stat": actual,
                "result": result,
                "graded_at": datetime.now(ZoneInfo("UTC")).isoformat(),
            }).eq("id", row["id"]).execute()
        except Exception:
            continue  # real, best-effort — one bad row should never stop the rest from grading


park_factors = {
    'Los Angeles Angels': 0.97, 'Baltimore Orioles': 1.02, 'Boston Red Sox': 0.95,
    'Chicago White Sox': 1.01, 'Cleveland Guardians': 0.98, 'Detroit Tigers': 0.99,
    'Houston Astros': 1.03, 'Kansas City Royals': 0.96, 'Minnesota Twins': 1.02,
    'New York Yankees': 1.04, 'Athletics': 0.98, 'Seattle Mariners': 1.05,
    'Tampa Bay Rays': 1.01, 'Texas Rangers': 0.97, 'Toronto Blue Jays': 1.00,
    'Arizona Diamondbacks': 1.02, 'Atlanta Braves': 1.01, 'Chicago Cubs': 0.96,
    'Cincinnati Reds': 0.99, 'Colorado Rockies': 0.88, 'Los Angeles Dodgers': 1.03,
    'Miami Marlins': 1.00, 'Milwaukee Brewers': 1.01, 'New York Mets': 1.02,
    'Philadelphia Phillies': 0.98, 'Pittsburgh Pirates': 0.97, 'San Diego Padres': 1.04,
    'San Francisco Giants': 0.96, 'St. Louis Cardinals': 0.99, 'Washington Nationals': 1.00
}

# ---- NBA LOOKUP ----
nba_abbrev_to_name = {
    'ATL': 'Atlanta Hawks', 'BOS': 'Boston Celtics', 'BKN': 'Brooklyn Nets',
    'CHA': 'Charlotte Hornets', 'CHI': 'Chicago Bulls', 'CLE': 'Cleveland Cavaliers',
    'DAL': 'Dallas Mavericks', 'DEN': 'Denver Nuggets', 'DET': 'Detroit Pistons',
    'GSW': 'Golden State Warriors', 'HOU': 'Houston Rockets', 'IND': 'Indiana Pacers',
    'LAC': 'LA Clippers', 'LAL': 'Los Angeles Lakers', 'MEM': 'Memphis Grizzlies',
    'MIA': 'Miami Heat', 'MIL': 'Milwaukee Bucks', 'MIN': 'Minnesota Timberwolves',
    'NOP': 'New Orleans Pelicans', 'NYK': 'New York Knicks', 'OKC': 'Oklahoma City Thunder',
    'ORL': 'Orlando Magic', 'PHI': 'Philadelphia 76ers', 'PHX': 'Phoenix Suns',
    'POR': 'Portland Trail Blazers', 'SAC': 'Sacramento Kings', 'SAS': 'San Antonio Spurs',
    'TOR': 'Toronto Raptors', 'UTA': 'Utah Jazz', 'WAS': 'Washington Wizards'
}

nba_name_to_abbrev = {v: k for k, v in nba_abbrev_to_name.items()}
league_avg_def_rating = 114.0
league_avg_pace = 98.5
league_avg_team_score = 112.0

# ---- AUTO LOAD MLB PITCHERS ----
@st.cache_data(ttl=3600)
def get_all_pitchers():
    url = "https://statsapi.mlb.com/api/v1/sports/1/players?season=2026&gameType=R"
    try:
        data = get_json(url)
    except Exception as e:
        st.error(f"Couldn't load the MLB pitcher list — real error: {e}")
        return []
    pitchers = []
    for player in data['people']:
        if player.get('primaryPosition', {}).get('code') == '1':
            pitchers.append(player['fullName'])
    return sorted(pitchers)

@st.cache_data(ttl=3600)
def get_batter_k_pcts():
    url = "https://baseballsavant.mlb.com/leaderboard/custom?year=2026&type=batter&filter=&sort=4&sortDir=desc&min=10&selections=k_percent&chart=false&x=k_percent&y=k_percent&r=no&chartType=beeswarm&csv=true"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    df = pd.read_csv(StringIO(response.text))
    df['full_name'] = df['last_name, first_name'].apply(lambda x: f"{x.split(', ')[1]} {x.split(', ')[0]}")
    df['k_pct'] = df['k_percent'] / 100
    return df[['full_name', 'k_pct', 'player_id']]

@st.cache_data(ttl=1800)
@st.cache_data(ttl=1800)
def get_todays_confirmed_lineups(game_date_str):
    """Real, confirmed starting lineups for today's games, via MLB
    Stats API's lineups hydration. Returns {player_name_lower: {
    'team': ..., 'opponent': ..., 'home_team': ..., 'is_home': ...}}.
    Lineups typically post 2-4 hours before first pitch — this can
    legitimately be empty/partial earlier in the day, which callers
    should treat as 'not yet available', not an error."""
    result = {}
    try:
        data = get_json(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={game_date_str}&hydrate=lineups,probablePitcher")
        for game in data.get('dates', [{}])[0].get('games', []):
            home_team = game['teams']['home']['team']['name']
            away_team = game['teams']['away']['team']['name']
            lineups = game.get('lineups', {})
            for side, team_name, opp_name, is_home in [
                ('homePlayers', home_team, away_team, True),
                ('awayPlayers', away_team, home_team, False),
            ]:
                for player in lineups.get(side, []):
                    name = player.get('fullName', '')
                    if name:
                        result[name.lower()] = {
                            'team': team_name, 'opponent': opp_name,
                            'home_team': home_team, 'away_team': away_team, 'is_home': is_home,
                        }
    except Exception:
        pass
    return result


def get_batter_current_team(player_id):
    """Real fallback for when today's lineup isn't posted yet —
    reads the player's own currentTeam from their MLB Stats API
    profile (standard biographical field, not day-specific), so a
    projection can still run before lineups drop."""
    try:
        data = get_json(f"https://statsapi.mlb.com/api/v1/people/{player_id}")
        person = data.get('people', [{}])[0]
        return person.get('currentTeam', {}).get('name')
    except Exception:
        return None


def resolve_batter_matchup(player_name, game_date_str):
    """Real matchup resolution for a live batter-hits pick: confirmed
    lineup first (most accurate — confirms they're actually playing
    today), falls back to the player's current team + today's
    schedule if lineups aren't posted yet. Returns (team, opponent,
    home_team, away_team, is_home, opposing_pitcher) or all-None if
    genuinely unresolvable."""
    lineups = get_todays_confirmed_lineups(game_date_str)
    entry = lineups.get(player_name.lower())

    if entry is None:
        player_id = get_mlb_player_id_cached(player_name)
        if not player_id:
            return None, None, None, None, None, None
        current_team = get_batter_current_team(player_id)
        if not current_team:
            return None, None, None, None, None, None
        try:
            starters = get_starters_for_date(game_date_str)
        except Exception:
            starters = []
        game_row = next((s for s in starters if s.get('team') == current_team), None)
        if not game_row:
            return None, None, None, None, None, None
        is_home = game_row['home_team'] == current_team
        entry = {
            'team': current_team, 'opponent': game_row['opponent'],
            'home_team': game_row['home_team'],
            'away_team': game_row['opponent'] if is_home else current_team,
            'is_home': is_home,
        }

    try:
        starters = get_starters_for_date(game_date_str)
    except Exception:
        starters = []
    opposing_pitcher = next((s['pitcher'] for s in starters if s.get('team') == entry['opponent']), None)

    return entry['team'], entry['opponent'], entry['home_team'], entry.get('away_team'), entry['is_home'], opposing_pitcher


def get_mlb_player_id_cached(player_name):
    """Cached player-ID lookup for batters — separate cache from the
    pitcher lookup elsewhere in this file, since they're resolved at
    different call sites and there's no shared cache between them."""
    return _resolve_batter_id_direct(player_name)


_batter_id_cache_live = {}

def _resolve_batter_id_direct(player_name):
    if player_name in _batter_id_cache_live:
        return _batter_id_cache_live[player_name]
    try:
        search = get_json(f"https://statsapi.mlb.com/api/v1/people/search?names={player_name}&sportId=1")
        people = search.get('people', [])
        pid = people[0]['id'] if people else None
    except Exception:
        pid = None
    _batter_id_cache_live[player_name] = pid
    return pid


_batter_gamelog_cache_live = {}

def get_batter_game_log_live(player_name, season, required_date=None):
    """Real, direct port of the backtest's get_batter_game_log —
    same MLB Stats API pattern already proven live for pitchers
    (statsapi.mlb.com/people/{id}/stats?stats=gameLog&group=X),
    swapped to group=hitting.

    Real fix (Sep 2026, per direct user report — a bet stayed
    Pending for 1-2 hours after its game finished, well past a full
    hourly cron cycle): this cache previously had NO expiration at
    all. If a player's game log got fetched once earlier in the day
    (e.g. for live pick generation, before their game happened), that
    stale, pre-game data would sit in this in-memory dict FOREVER
    (the app process runs continuously, it doesn't restart between
    cron cycles) — so grading would keep hitting the same stale
    cache and never see the now-completed game, leaving the bet
    Pending indefinitely. required_date, when passed (grading always
    passes it), checks whether that specific date is actually present
    in the cached data; if not, forces one fresh re-fetch rather than
    trusting a cache that's proven to be missing exactly the game we
    need. Live projection calls (which don't pass required_date) keep
    the original fast-cache behavior, since they don't have this same
    staleness risk — they're always projecting a FUTURE game, never
    checking for a specific just-completed one."""
    cache_key = f"{player_name}_{season}"
    cached = _batter_gamelog_cache_live.get(cache_key)
    needs_refresh = cached is None or (
        required_date is not None and not any(g['date'] == required_date for g in cached)
    )
    if not needs_refresh:
        return cached

    player_id = get_mlb_player_id_cached(player_name)
    if not player_id:
        _batter_gamelog_cache_live[cache_key] = cached or []
        return cached or []
    try:
        resp = get_json(f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group=hitting&season={season}&sportId=1")
        splits = resp['stats'][0]['splits'] if resp.get('stats') else []
    except Exception:
        splits = []
    games = []
    for game in splits:
        g = game.get('stat', {})
        try:
            games.append({
                'date': game['date'],
                'hits': int(g.get('hits', 0)), 'at_bats': int(g.get('atBats', 0)),
                'plate_appearances': int(g.get('plateAppearances', 0)),
            })
        except (ValueError, TypeError, KeyError):
            continue
    _batter_gamelog_cache_live[cache_key] = games
    return games


_pitcher_gamelog_cache_live = {}

def get_pitcher_hits_allowed_log_live(pitcher_name, season):
    """Real, direct port of the backtest's get_pitcher_hits_allowed_log."""
    cache_key = f"{pitcher_name}_{season}"
    if cache_key in _pitcher_gamelog_cache_live:
        return _pitcher_gamelog_cache_live[cache_key]
    player_id = get_mlb_player_id_cached(pitcher_name)
    if not player_id:
        _pitcher_gamelog_cache_live[cache_key] = []
        return []
    try:
        resp = get_json(f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group=pitching&season={season}&sportId=1")
        splits = resp['stats'][0]['splits'] if resp.get('stats') else []
    except Exception:
        splits = []
    games = []
    for game in splits:
        g = game.get('stat', {})
        try:
            games.append({
                'date': game['date'], 'hits_allowed': int(g.get('hits', 0)),
                'batters_faced': int(g.get('battersFaced', 0)),
            })
        except (ValueError, TypeError, KeyError):
            continue
    _pitcher_gamelog_cache_live[cache_key] = games
    return games


_league_hits_allowed_baseline_cache = {}

def get_league_avg_hits_allowed_rate_live(season, date_bucket):
    """Real, direct port of the backtest's league-baseline approximation
    — uses whatever pitcher logs have already been fetched this run to
    avoid a separate expensive full-league call, falling back to a
    real, standard MLB constant if not enough data has been seen yet."""
    fallback = 0.245
    cache_key = (season, date_bucket)
    if cache_key in _league_hits_allowed_baseline_cache:
        return _league_hits_allowed_baseline_cache[cache_key]
    all_recent_rates = []
    for pitcher_games in _pitcher_gamelog_cache_live.values():
        prior = [g for g in pitcher_games if g['date'] < date_bucket]
        if len(prior) < 3:
            continue
        recent = sorted(prior, key=lambda g: g['date'], reverse=True)[:10]
        bf = sum(g['batters_faced'] for g in recent)
        ha = sum(g['hits_allowed'] for g in recent)
        if bf > 0:
            all_recent_rates.append(ha / bf)
    result = round(sum(all_recent_rates) / len(all_recent_rates), 4) if len(all_recent_rates) >= 15 else fallback
    _league_hits_allowed_baseline_cache[cache_key] = result
    return result


def run_batter_hits_projection(player_name, opposing_pitcher, home_team, away_team, season, before_date=None):
    """LIVE batter hits projection — direct port of the backtest's
    project_batter_hits (validated: 12,658 bets, split-half consistent,
    +4.65%/+5.50% ROI in the 0-12% EV zone). projected_hits =
    expected_AB * projected_hit_rate, where projected_hit_rate blends
    this batter's own real rate with the opposing starter's real
    hits-allowed rate (vs league average) and the real park factor —
    same shape as the strikeouts model's own opp_factor * park_factor
    combination.

    before_date: for live use, pass today's date (or leave None to use
    mm_today_str()) — games strictly before this date are used, so a
    game already in progress today never leaks into its own projection."""
    try:
        cutoff = before_date or mm_today_str()

        games = get_batter_game_log_live(player_name, season)
        prior = [g for g in games if g['date'] < cutoff]
        if len(prior) < 5:
            return None
        prior_sorted = sorted(prior, key=lambda g: g['date'], reverse=True)
        recent = prior_sorted[:15]
        total_ab = sum(g['at_bats'] for g in recent)
        total_hits = sum(g['hits'] for g in recent)
        if total_ab <= 0:
            return None
        expected_ab = round(total_ab / len(recent), 2)
        own_hit_rate = round(total_hits / total_ab, 4)
        batter_n = len(recent)

        if opposing_pitcher:
            p_games = get_pitcher_hits_allowed_log_live(opposing_pitcher, season)
            p_prior = [g for g in p_games if g['date'] < cutoff]
            if len(p_prior) >= 3:
                p_recent = sorted(p_prior, key=lambda g: g['date'], reverse=True)[:10]
                total_bf = sum(g['batters_faced'] for g in p_recent)
                total_ha = sum(g['hits_allowed'] for g in p_recent)
                pitcher_ha_rate = round(total_ha / total_bf, 4) if total_bf > 0 else None
            else:
                pitcher_ha_rate = None
        else:
            pitcher_ha_rate = None

        league_avg = get_league_avg_hits_allowed_rate_live(season, cutoff)
        opp_factor = (pitcher_ha_rate / league_avg) if (pitcher_ha_rate is not None and league_avg > 0) else 1.0

        park_factor = park_factors.get(home_team, 1.0)
        combined_factor = max(0.80, min(1.20, opp_factor * park_factor))
        projected_hit_rate = round(own_hit_rate * combined_factor, 4)
        projected_hits = round(expected_ab * projected_hit_rate, 2)

        hits_series = pd.Series([g['hits'] for g in recent])
        std_dev = round(hits_series.std(), 2) if len(hits_series) > 1 and pd.notna(hits_series.std()) and hits_series.std() > 0 else max(0.8, projected_hits * 0.5)

        cv = round(std_dev / max(projected_hits, 1.0), 3)

        return {
            'projection': projected_hits, 'std_dev': std_dev, 'cv': cv,
            'expected_ab': expected_ab, 'own_hit_rate': own_hit_rate,
            'opp_factor': round(opp_factor, 3), 'park_factor': park_factor,
            'batter_games_sample': batter_n,
        }
    except Exception as e:
        log_failure_reason('MALFORMED_RESPONSE', f"run_batter_hits_projection({player_name}): {e}")
        return None


def get_pitcher_game_info(pitcher_name, game_date=None):
    try:
        check_date = game_date or mm_today_str()
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=probablePitcher"
        data = get_json(url)
        if not data['dates']:
            return None, None, None
        for game in data['dates'][0]['games']:
            home = game['teams']['home']['team']['name']
            away = game['teams']['away']['team']['name']
            home_pitcher = game['teams']['home'].get('probablePitcher', {}).get('fullName', '')
            away_pitcher = game['teams']['away'].get('probablePitcher', {}).get('fullName', '')
            if pitcher_name.lower() == home_pitcher.lower():
                return home, away, home
            elif pitcher_name.lower() == away_pitcher.lower():
                return away, home, home
    except Exception as e:
        log_failure_reason('MISSING_PLAYER_MATCH', f"get_pitcher_game_info({pitcher_name}): {e}")
    return None, None, None

# fmt_odds moved to bet_math.py (August 2026) — imported at the top of
# this file now instead of defined here. Behavior unchanged.

def get_starters_for_date(game_date_str):
    try:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={game_date_str}&hydrate=probablePitcher,linescore"
        data = get_json(url)
        starters = []
        for game in data['dates'][0]['games']:
            home = game['teams']['home']['team']['name']
            away = game['teams']['away']['team']['name']
            game_pk = game['gamePk']
            home_pitcher = game['teams']['home'].get('probablePitcher', {}).get('fullName')
            away_pitcher = game['teams']['away'].get('probablePitcher', {}).get('fullName')
            if home_pitcher:
                starters.append({'pitcher': home_pitcher, 'team': home, 'opponent': away, 'home_team': home, 'game_pk': game_pk})
            if away_pitcher:
                starters.append({'pitcher': away_pitcher, 'team': away, 'opponent': home, 'home_team': home, 'game_pk': game_pk})
        return starters
    except Exception as e:
        log_failure_reason('MISSING_PLAYER_MATCH', f"get_starters_for_date({game_date_str}): {e}")
        return []


def get_actual_strikeouts(game_pk, pitcher_name):
    try:
        url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
        data = get_json(url)
        for side in ['home', 'away']:
            for pid in data['teams'][side]['pitchers']:
                player = data['teams'][side]['players'].get(f'ID{pid}', {})
                name = player.get('person', {}).get('fullName', '')
                if name.lower() == pitcher_name.lower():
                    return player.get('stats', {}).get('pitching', {}).get('strikeOuts', None)
    except Exception as e:
        log_failure_reason('MISSING_PLAYER_MATCH', f"get_actual_strikeouts({pitcher_name}, game {game_pk}): {e}")
    return None


# ---- MLB PROJECTION ENGINE ----
# Real fix (July 2026) — a real, general solution to a real problem
# found today: the shared cache (daily_cache table) has no way to know
# when the underlying MODEL LOGIC itself changes, only when a given
# pitcher/day combination was last computed. This meant real fixes to
# run_projection() (the streak-counting fix, the stale-season-baseline
# fix, the pitches-per-inning fix) had zero visible effect on any
# pitcher who already had a cached entry for today — every "Run All
# Projections" click just kept reusing the old, pre-fix result, and
# only a manual, per-pitcher "▶️ Run" click forced a fresh recompute.
# That's not a sustainable fix — it shouldn't require manually
# re-running every single prop after a real model change.
#
# MLB_PROJECTION_MODEL_VERSION is tagged onto every real result run_
# projection() produces (see the '_model_version' key near the end of
# the function). cached_run_projection() below now checks this tag
# against the CURRENT version before trusting a cached entry — any
# cached entry from an older model version (including every existing
# entry today, which has no tag at all) is automatically treated as
# stale and recomputed fresh, with no manual intervention needed.
# Bump this string any time a real, meaningful change is made to the
# actual calculation logic inside run_projection() — a cosmetic/
# display-only change doesn't need a bump, but anything that changes
# what number gets computed does.
MLB_PROJECTION_MODEL_VERSION = "2026-07-26-v3-workload-fixes"

def run_projection(pitcher_name, opponent_team, home_team, season, weather_adj=1.0, before_date=None,
                   use_umpire=True, use_park=True, use_lineup=True, use_pitch_count=True, use_total=True):
    try:
        league_avg_k_pct_vr = 0.222
        league_avg_k_pct_vl = 0.218
        league_avg_favor = 0.43

        search = get_json(f"https://statsapi.mlb.com/api/v1/people/search?names={pitcher_name}&sportId=1")
        player_data = search['people'][0]
        player_id = player_data['id']
        pitcher_hand = player_data['pitchHand']['code']

        season_stat = get_json(f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=pitching&season={season}&sportId=1")['stats'][0]['splits'][0]['stat']

        season_k = int(season_stat['strikeOuts'])
        season_bf = int(season_stat['battersFaced'])
        season_k_pct = round(season_k / season_bf, 3)
        season_pitches_total = int(season_stat.get('numberOfPitches', 0))
        season_strikes = int(season_stat.get('strikes', 0))
        season_strike_pct = round(season_strikes / season_pitches_total, 3) if season_pitches_total > 0 else 0.65

        splits = get_json(f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group=pitching&season={season}&sportId=1")['stats'][0]['splits']

        games = []
        for game in splits:
            game_date = game['date']
            if before_date and game_date >= before_date:
                continue
            g = game['stat']
            pitches = int(g.get('numberOfPitches', 0))
            strikes = int(g.get('strikes', 0))
            ip = float(g['inningsPitched'])
            games.append({
                'date': game_date, 'opponent': game['opponent']['name'],
                'strikeouts': int(g['strikeOuts']), 'innings': ip,
                'batters_faced': int(g['battersFaced']), 'pitches': pitches,
                'strike_pct': round(strikes / pitches, 3) if pitches > 0 else 0.65,
                'pitches_per_inning': round(pitches / ip, 2) if ip > 0 else 17.0
            })

        if len(games) < 3:
            return None

        df = pd.DataFrame(games).iloc[::-1].reset_index(drop=True)

        last5_avg_ip = round(df['innings'].head(5).mean(), 2)
        last10_avg_ip = round(df['innings'].head(10).mean(), 2)
        last3_avg_ip = round(df['innings'].head(3).mean(), 2)
        season_avg_ip = round(df['innings'].mean(), 2)
        season_avg_bf = round(df['batters_faced'].mean(), 2)
        last5_k_pct = round(df['strikeouts'].head(5).sum() / df['batters_faced'].head(5).sum(), 3)
        last10_k_pct = round(df['strikeouts'].head(10).sum() / df['batters_faced'].head(10).sum(), 3)
        recent_strike_pct = round(df['strike_pct'].head(5).mean(), 3)

        # Real fix (July 2026) — moved earlier (was previously computed
        # further down) so it's available here too. See the full
        # explanation where it's used below in the IP-weighting logic.
        last5_ip_values = df['innings'].head(5)
        recent_5ip_starts_count = int((last5_ip_values >= 5.0).sum())

        last10_ip = df['innings'].head(10)
        last10_ip_std = round(last10_ip.std(), 2) if len(last10_ip) > 1 else 0.0
        ip_cv = round(last10_ip_std / last10_avg_ip, 3) if last10_avg_ip > 0 else 1.0

        # Real fix (July 2026) — found via the same real Avila case.
        # ip_cv measures variance across the last 10 starts, but for a
        # pitcher with a genuine, settled role change (reliever ->
        # starter), those 10 starts mix two real, different roles
        # together — producing a misleadingly high "volatile" reading
        # even when his recent pattern (last 5 starts) is actually
        # clear and stable. A strong recent_5ip_starts_count is real,
        # direct evidence the role has settled, so it overrides the
        # backward-looking ip_cv reading rather than being contradicted
        # by it — the two were confusingly disagreeing with each other
        # before this fix (e.g. showing both "🔴 Highly Volatile Usage"
        # and a stable-looking recent IP figure side by side).
        if recent_5ip_starts_count >= 4:
            workload_tier = "🟢 Stable Starter (Recently Settled)"
        elif ip_cv < 0.20:
            workload_tier = "🟢 Stable Starter"
        elif ip_cv < 0.35:
            workload_tier = "🟡 Recently Changing Workload"
        else:
            workload_tier = "🔴 Highly Volatile Usage"

        last10_strikeouts = df['strikeouts'].head(10)
        last10_k_avg = round(last10_strikeouts.mean(), 2)
        last10_k_std = round(last10_strikeouts.std(), 2) if len(last10_strikeouts) > 1 else 0.0
        cv = round(last10_k_std / last10_k_avg, 3) if last10_k_avg > 0 else 1.0

        if cv < 0.35: confidence_tier = "🟢 Reliable"
        elif cv < 0.50: confidence_tier = "🟠 Volatile"
        else: confidence_tier = "🔴 Uncertain Workload"

        last3_pitches = round(df['pitches'].head(3).mean(), 1)

        # Real fix (August 2026, per direct user report — Ranger
        # Suarez case: last 3 starts were 2.2/4.0/4.2 IP, the 2.2 a
        # real, explainable bad outing (got hit hard, pulled early),
        # not a genuine workload change — yet he's "only thrown under
        # 4 innings once all year." The plain last3_pitches average
        # let that ONE rough night drag the whole real projection down
        # to 3.75 IP, well below even his OTHER two recent starts.
        # Detects a single, clear outlier among the last 3 real starts
        # (one start well below the other two, not a real, sustained
        # pattern) and uses the average of the other two instead —
        # for both the main blend below AND the downward-cap check —
        # so one bad, explainable night doesn't single-handedly
        # override an otherwise-consistent real workload pattern.
        last3_ip_list = df['innings'].head(3).tolist()
        last3_pitches_list = df['pitches'].head(3).tolist()
        if len(last3_ip_list) == 3:
            _sorted_ip = sorted(last3_ip_list)
            _shortest_ip, _mid_ip, _longest_ip = _sorted_ip
            _other_two_avg_ip = (_mid_ip + _longest_ip) / 2
            if _other_two_avg_ip > 0 and _shortest_ip < _other_two_avg_ip * 0.6:
                _outlier_idx = last3_ip_list.index(_shortest_ip)
                _remaining_pitches = [p for i, p in enumerate(last3_pitches_list) if i != _outlier_idx]
                if _remaining_pitches:
                    last3_pitches = round(sum(_remaining_pitches) / len(_remaining_pitches), 1)

        last10_pitches = round(df['pitches'].head(10).mean(), 1)
        season_avg_pitches = round(df['pitches'].mean(), 1)
        career_high_pitches = df['pitches'].max()
        # Real, final fix (July 2026) — found via live debugging with
        # real, exact intermediate values. The old calculation averaged
        # each game's own per-game pitches/innings RATIO — statistically
        # wrong, since a single game with a tiny IP denominator (e.g. a
        # brief early-season relief outing, 10 pitches over 0.1 IP)
        # produces an absurd per-game rate (100 pitches/inning) that
        # then dominates a simple average across 10 games. Confirmed
        # via live debug output: this was producing ~40 pitches/inning
        # for a real pitcher (normal range is ~15-17), which meant
        # dividing his real, correctly-blended expected pitch count by
        # this inflated rate produced an absurdly low innings estimate
        # — the actual reason the projection stayed capped at 1.97 IP
        # even after both earlier fixes correctly raised the blended
        # IP estimate to a real ~4.7. Now computes a real, robust total-
        # pitches-over-total-innings rate, which weights each game's
        # contribution by how many real innings it represents, instead
        # of treating a 0.1-inning outing as equally informative as a
        # normal 6-inning start.
        last10_pitches_sum = df['pitches'].head(10).sum()
        last10_innings_sum = df['innings'].head(10).sum()
        pitches_per_inning = round(last10_pitches_sum / last10_innings_sum, 2) if last10_innings_sum > 0 else 17.0

        if use_pitch_count:
            expected_pitch_count = round((season_avg_pitches * 0.30) + (last10_pitches * 0.30) + (last3_pitches * 0.40), 1)
            # Real fix (July 2026) — this downward cap used to fire
            # purely off last3_pitches (just 3 starts), so the SAME
            # single fluke outing that broke the old IP-streak logic
            # (e.g. Valdez's 0.2 IP outing) would also drag last3_pitches
            # down and cap the projection here too — via the min() below,
            # this was still clamping the final number down even after
            # the IP-weighting fix above, which is why that fix alone
            # didn't visibly change anything. Now skipped when there's
            # already strong, real evidence (recent_5ip_starts_count >= 4)
            # of an established starter role — a fluke shouldn't cap a
            # projection we already have real reason to trust.
            if last3_pitches < season_avg_pitches * 0.80 and recent_5ip_starts_count < 4:
                expected_pitch_count = min(expected_pitch_count, last3_pitches * 1.05)
            elif last3_pitches > season_avg_pitches * 1.10:
                expected_pitch_count = min(expected_pitch_count * 1.05, career_high_pitches)
            elif len(df) > 0 and df['pitches'].iloc[0] > season_avg_pitches * 1.15:
                expected_pitch_count = min(expected_pitch_count, season_avg_pitches)
            pitch_based_ip = round(expected_pitch_count / pitches_per_inning, 2)
        else:
            expected_pitch_count = season_avg_pitches
            pitch_based_ip = season_avg_ip

        pitcher_skill = round((season_k_pct * 0.70) + (last10_k_pct * 0.15) + (last5_k_pct * 0.15), 3)
        last3_starter = (last3_avg_ip >= 4.8) or (sum(df['innings'].head(3) >= 5.0) >= 2)

        # Real fix (July 2026) — found via a second real case (Luinder
        # Avila) even after the streak-counting fix above. His last 5
        # starts (6.1/5/5/4/5 IP) correctly trigger recent_5ip_starts_
        # count >= 4, but his season_avg_ip is itself contaminated —
        # he started the season as a reliever (short, 1-2 IP outings)
        # before genuinely becoming a starter. The OLD tier ordering
        # meant that once >=4 matched, the code never checked whether
        # season_avg_ip was even reliable — it just applied 35% weight
        # to it regardless, which was enough to drag a real, strong
        # recent projection back down toward a stale, role-mismatched
        # season baseline. Now checks BOTH conditions together: a
        # confirmed strong recent role does NOT automatically mean the
        # season baseline is trustworthy too — those are two separate,
        # independent questions.
        season_ip_looks_stale = last5_avg_ip > season_avg_ip * 1.5 or last5_avg_ip < season_avg_ip * 0.6

        if recent_5ip_starts_count >= 4 and not season_ip_looks_stale:
            # Strong, consistent recent starter role, AND the season
            # baseline still looks like it reflects the same role —
            # safe to blend in some of that broader, lower-variance data.
            ip_season_w, ip_last10_w, ip_last5_w = 0.35, 0.40, 0.25
        elif recent_5ip_starts_count >= 4 and season_ip_looks_stale:
            # Strong recent role, but the season average reflects a
            # genuinely different prior role (e.g. reliever -> starter)
            # — don't blend in data that doesn't describe who he is now.
            ip_season_w, ip_last10_w, ip_last5_w = 0.10, 0.20, 0.70
        elif recent_5ip_starts_count == 3:
            # Solid majority, but less certain — lean harder into recent workload
            ip_season_w, ip_last10_w, ip_last5_w = 0.15, 0.25, 0.60
        elif last3_starter:
            ip_season_w, ip_last10_w, ip_last5_w = 0.20, 0.30, 0.50
        elif season_ip_looks_stale:
            ip_season_w, ip_last10_w, ip_last5_w = 0.20, 0.30, 0.50
        else:
            ip_season_w, ip_last10_w, ip_last5_w = 0.30, 0.40, 0.30

        expected_innings = round(min(
            round((season_avg_ip * ip_season_w) + (last10_avg_ip * ip_last10_w) + (last5_avg_ip * ip_last5_w), 2),
            pitch_based_ip
        ), 2)
        expected_bf = round(expected_innings * (season_avg_bf / season_avg_ip), 1)
        velo_factor = round(1.0 + ((recent_strike_pct - season_strike_pct) * 0.8), 3)

        league_avg_k_pct = league_avg_k_pct_vr if pitcher_hand == 'R' else league_avg_k_pct_vl
        team_data = get_json(f"https://statsapi.mlb.com/api/v1/teams/stats?stats=season&group=hitting&season={season}&sportId=1")

        opp_k_pct = None
        for split in team_data['stats'][0]['splits']:
            if split['team']['name'] == opponent_team:
                opp_k_pct = round(int(split['stat']['strikeOuts']) / int(split['stat']['plateAppearances']), 3)
                break

        final_opp_k_pct = opp_k_pct or league_avg_k_pct
        lineup_k_pct = None

        if use_lineup:
            try:
                k_df = get_batter_k_pcts()
                check_date = before_date or mm_today_str()
                sched_data = get_json(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=lineups")
                if sched_data.get('dates'):
                    for game in sched_data['dates'][0]['games']:
                        ht = game['teams']['home']['team']['name']
                        at = game['teams']['away']['team']['name']
                        if home_team in ht or home_team in at:
                            lineups = game.get('lineups', {})
                            if lineups:
                                batting_lineup = lineups.get('awayPlayers', []) if opponent_team in at else lineups.get('homePlayers', [])
                                total = count = 0
                                for player in batting_lineup[:9]:
                                    match = k_df[k_df['full_name'].str.lower() == player['fullName'].lower()]
                                    if not match.empty:
                                        total += match['k_pct'].iloc[0]
                                        count += 1
                                if count >= 5:
                                    lineup_k_pct = round(total / count, 3)
                            break
                if lineup_k_pct and lineup_k_pct > 0:
                    final_opp_k_pct = round((lineup_k_pct * 0.60) + (final_opp_k_pct * 0.40), 3)
            except Exception as e:
                log_failure_reason('MISSING_LINEUP', f"{pitcher_name}: {e}")

        opp_factor = round(final_opp_k_pct / league_avg_k_pct, 3)
        park_factor = park_factors.get(home_team, 1.0) if use_park else 1.0

        umpire_factor = 1.0
        umpire_name = None
        if use_umpire:
            try:
                check_date = before_date or mm_today_str()
                sched_data = get_json(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=officials")
                if sched_data.get('dates'):
                    for game in sched_data['dates'][0]['games']:
                        if home_team in game['teams']['home']['team']['name'] or home_team in game['teams']['away']['team']['name']:
                            for official in game.get('officials', []):
                                if official['officialType'] == 'Home Plate':
                                    umpire_name = official['official']['fullName']
                            break
                if umpire_name:
                    ump_data = get_json("https://umpscorecards.com/api/umpires", headers={'User-Agent': 'Mozilla/5.0'})
                    for ump in ump_data['rows']:
                        if ump['umpire'].lower() == umpire_name.lower():
                            umpire_factor = max(0.97, min(1.03, round(1.0 + ((round(ump['favor_abs_mean'], 3) - league_avg_favor) * 0.5), 3)))
                            break
            except Exception as e:
                log_failure_reason('UNAVAILABLE_ODDS' if 'the-odds-api' in str(e).lower() else 'UPSTREAM_TIMEOUT', f"umpire data: {e}")

        total_factor = 1.0
        if use_total:
            try:
                if before_date:
                    params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals', 'oddsFormat': 'american', 'date': f"{before_date}T18:00:00Z"}
                    games_data = get_json("https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds", params=params).get('data', [])
                else:
                    params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals', 'oddsFormat': 'american'}
                    games_data = get_json("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds", params=params)

                for game in games_data:
                    if home_team in game.get('home_team', '') or home_team in game.get('away_team', ''):
                        for bookmaker in game.get('bookmakers', []):
                            for market in bookmaker.get('markets', []):
                                if market['key'] == 'totals':
                                    game_total = market['outcomes'][0]['point']
                                    total_factor = max(0.95, min(1.05, round(1 - ((game_total - 8.5) * 0.02), 3)))
                            break
                        break
            except Exception as e:
                log_failure_reason('UNAVAILABLE_ODDS', f"game total: {e}")

        base = expected_bf * pitcher_skill
        combined_factor = max(0.90, min(1.10, opp_factor * park_factor * umpire_factor * velo_factor * weather_adj * total_factor))
        final_projection = round(base * combined_factor, 1)

        return {
            'projection': final_projection, 'base': round(base, 2),
            'pitcher_hand': pitcher_hand, 'lineup_k_pct': final_opp_k_pct,
            'pitcher_skill': pitcher_skill, 'expected_bf': expected_bf,
            'expected_innings': expected_innings, 'expected_pitch_count': expected_pitch_count,
            'last5_avg_ip': last5_avg_ip,
            'umpire_name': umpire_name, 'umpire_factor': umpire_factor,
            'opp_factor': opp_factor, 'park_factor': park_factor,
            'velo_factor': velo_factor, 'total_factor': total_factor,
            'combined_factor': round(combined_factor, 3), 'season_k_pct': season_k_pct,
            'last5_k': round(df['strikeouts'].head(5).mean(), 2),
            'last10_k': round(df['strikeouts'].head(10).mean(), 2),
            'last10_k_avg': last10_k_avg, 'last10_k_std': last10_k_std,
            'cv': cv, 'confidence_tier': confidence_tier,
            'season_avg_ip': season_avg_ip, 'pitches_per_inning': pitches_per_inning,
            'last3_pitches': last3_pitches, 'season_avg_pitches': season_avg_pitches,
            'pitch_count_factor': round(pitch_based_ip, 2),
            'lineup_factor': round(lineup_k_pct, 3) if lineup_k_pct else None,
            'ip_cv': ip_cv, 'workload_tier': workload_tier,
            'recent_5ip_starts_count': recent_5ip_starts_count,
            'last10_avg_ip': last10_avg_ip,
            'season_ip_looks_stale': season_ip_looks_stale,
            'ip_season_w': ip_season_w, 'ip_last10_w': ip_last10_w, 'ip_last5_w': ip_last5_w,
            '_model_version': MLB_PROJECTION_MODEL_VERSION,
        }
    except Exception as e:
        import traceback
        log_failure_reason('RUN_PROJECTION_EXCEPTION', f"{pitcher_name}: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return None

NBA_API_TIMEOUT = 20  # seconds — fail fast instead of hanging indefinitely on a stalled request

# ---- BALLDONTLIE.IO DATA LAYER ----
# Third NBA data source this project has used. stats.nba.com blocked every IP
# type we tested at the request-fingerprint level (not fixable with proxies).
# Basketball-Reference (web scraping) worked but hit real, hard rate limits
# under any real testing volume, since it's not a real API — just parsing web
# pages. balldontlie.io is an actual documented API with an API key and a
# real rate-limit contract (much more predictable than scraping). Built
# against the ALL-STAR tier ($9.99/mo) — game player stats, active players,
# injuries, and raw box scores. Pace/usage/efficiency are computed ourselves
# from box-score components rather than paying for the GOAT tier's
# precalculated advanced-stats endpoint.
BDL_API_KEY = st.secrets.get("BDL_API_KEY")
BDL_BASE_URL = "https://api.balldontlie.io/v1"

def bdl_get(endpoint, params=None, max_pages=20):
    """Paginated GET against balldontlie — follows meta.next_cursor until it's
    missing, per their docs (pagination is cursor-based despite some docs
    calling it a page number). Retries on transient failures."""
    all_rows = []
    params = dict(params or {})
    cursor = None
    for _ in range(max_pages):
        if cursor is not None:
            params["cursor"] = cursor
        last_error = None
        for attempt in range(3):
            try:
                response = requests.get(
                    f"{BDL_BASE_URL}/{endpoint}",
                    headers={"Authorization": BDL_API_KEY},
                    params=params,
                    timeout=NBA_API_TIMEOUT,
                )
                response.raise_for_status()
                payload = response.json()
                break
            except Exception as e:
                last_error = e
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
        else:
            raise last_error
        all_rows.extend(payload.get("data", []))
        cursor = payload.get("meta", {}).get("next_cursor")
        if cursor is None:
            break
    return all_rows

def strip_accents(text):
    """'Jokić' -> 'Jokic'. balldontlie's search doesn't appear to match
    accented characters against its index."""
    return ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))

@st.cache_data(ttl=86400)
def get_bdl_player_id(player_name):
    """Resolve a player's full name to their balldontlie player ID — free-tier
    endpoint, cached for a day since IDs never change. Searches by last name
    only (a full 'First Last' search came back empty in testing) and with
    accents stripped (e.g. 'Jokić' -> 'Jokic'), since names with accented
    characters didn't match balldontlie's search index directly. Also strips
    common suffixes (Jr., Sr., II, III, IV) before taking 'the last word' as
    the last name — otherwise 'Ronald Holland II' searches for 'II', which
    obviously finds nothing.

    Deliberately does NOT catch every exception here — a transient failure
    (rate-limiting, a network hiccup) needs to raise and NOT get cached,
    otherwise a single bad-timing search failure during a big batch run gets
    permanently remembered as 'this player doesn't exist' for 24 hours. A
    real 'no player found' (search succeeded, zero matches) is the only case
    that's safe to cache as None."""
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
    name_parts = [p for p in player_name.strip().split(" ") if p.lower().rstrip(".") not in suffixes]
    last_name = strip_accents(name_parts[-1] if name_parts else player_name.strip())
    rows = bdl_get("players", {"search": last_name, "per_page": 25})
    name_lower = strip_accents(player_name.strip().lower())
    for p in rows:
        full_name = strip_accents(f"{p.get('first_name', '')} {p.get('last_name', '')}".strip().lower())
        if full_name == name_lower:
            return p.get("id")
    # No exact full-name match — since this is a last-name search, most
    # returned rows should genuinely share the target last name; a few can
    # be unrelated near-matches from balldontlie's own search algorithm.
    # Narrow to rows whose LAST NAME actually matches (handles first-name
    # formatting quirks — nicknames, extra whitespace — without the risk of
    # matching a genuinely different surname). Only auto-accept if that
    # narrows to exactly one candidate; real ambiguity (multiple different
    # people sharing the surname) still correctly returns None rather than
    # guessing (July 2026 fix, refined after it over-corrected and started
    # rejecting real players like Isaiah Stewart and Bennedict Mathurin).
    last_name_matches = [p for p in rows if strip_accents(p.get('last_name', '').strip().lower()) == last_name.lower()]
    if len(last_name_matches) == 1:
        return last_name_matches[0].get("id")
    return None

def get_bdl_player_game_log(player_name, season):
    """A player's full-season game log — the core input for rolling averages.
    ALL-STAR tier's 'stats' endpoint, filtered by player + season."""
    try:
        player_id = get_bdl_player_id(player_name)
    except Exception:
        return pd.DataFrame(), None
    if not player_id:
        return pd.DataFrame(), None
    try:
        rows = _cached_bdl_player_stats(player_id, season)
        return pd.DataFrame(rows), player_id
    except Exception:
        return pd.DataFrame(), player_id

@st.cache_data(ttl=3600)
def _cached_bdl_player_stats(player_id, season):
    return bdl_get("stats", {"player_ids[]": player_id, "seasons[]": season, "per_page": 100})

@st.cache_data(ttl=3600)
def get_bdl_games_for_date(date_str):
    """All player stats league-wide for one specific date — two-step process
    since ALL-STAR tier doesn't include a single-call box-score-by-date
    endpoint (that's GOAT-tier): first get the game IDs for that date (free
    'games' endpoint), then pull all player stats for those specific games."""
    games = bdl_get("games", {"dates[]": date_str, "per_page": 100})
    if not games:
        return pd.DataFrame()
    game_ids = [g["id"] for g in games]
    rows = []
    for gid in game_ids:
        rows.extend(bdl_get("stats", {"game_ids[]": gid, "per_page": 100}))
        time.sleep(1)
    return pd.DataFrame(rows)

@st.cache_data(ttl=86400)
def get_bdl_team_ids():
    """Team name -> balldontlie team ID, free endpoint, cached — teams never
    change mid-season."""
    try:
        rows = bdl_get("teams", {"per_page": 100})
        return {t.get("full_name"): t.get("id") for t in rows}
    except Exception:
        return {}

@st.cache_data(ttl=300, show_spinner=False)
def get_bdl_team_injuries(team_id):
    """Current injury report for one NBA team — confirmed real endpoint
    (GET /v1/player_injuries, ALL-STAR tier, filter verified working via
    live diagnostic) via balldontlie's docs. This is a LIVE snapshot only —
    no date parameter exists, so there's no way to ask 'who was hurt as of
    December 1st.' Only meaningful for live props, never for backtesting a
    historical date, unless daily snapshots are separately archived."""
    if not team_id:
        return []
    try:
        return bdl_get("player_injuries", {"team_ids[]": team_id, "per_page": 100})
    except Exception:
        return []

def normalize_injury_status(status):
    status = str(status or "").strip().lower()
    if status in {"out", "inactive", "suspended"}:
        return "out"
    if status in {"doubtful"}:
        return "doubtful"
    if status in {"questionable", "game time decision", "game-time decision", "gtd"}:
        return "questionable"
    if status in {"probable", "available"}:
        return "probable"
    return "unknown"

# Starting assumptions, not proven-optimal values — worth tracking real
# outcomes and tuning these once there's enough data to backtest against.
INJURY_PLAY_PROBABILITY = {
    "out": 0.00, "doubtful": 0.15, "questionable": 0.50,
    "probable": 0.90, "unknown": 0.75,
}

def build_team_injury_lookup(team_id):
    """player_id -> full injury info for every currently-injured player on
    one team, keyed for fast lookup by both the projected player's own
    status check and the teammate-absence redistribution below."""
    rows = get_bdl_team_injuries(team_id)
    lookup = {}
    for row in rows:
        player = row.get("player") or {}
        player_id = player.get("id")
        if player_id is None:
            continue
        normalized_status = normalize_injury_status(row.get("status"))
        lookup[player_id] = {
            "player_id": player_id,
            "player_name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
            "status": row.get("status"),
            "normalized_status": normalized_status,
            "play_probability": INJURY_PLAY_PROBABILITY.get(normalized_status, 0.75),
            "description": row.get("description"),
            "return_date": row.get("return_date"),
        }
    return lookup

@st.cache_data(ttl=3600)
def get_player_role_profile(player_id, season, as_of_date_str=None):
    """A player's recent role — minutes, FGA, FTA, points per game over
    their last 10 real games — used to estimate how much offensive
    opportunity disappears from a team when this specific player is out.
    Respects as_of_date_str so this stays leak-free if ever reused for
    something date-sensitive, though the injury feature itself is
    live-only regardless."""
    try:
        rows = _cached_bdl_player_stats(player_id, season)
        df = pd.DataFrame(rows)
        if df.empty:
            return None
        df["minutes_played"] = df["min"].apply(bdl_parse_minutes)
        df["game_date"] = pd.to_datetime(df["game"].apply(lambda g: (g or {}).get("date")))
        if as_of_date_str:
            cutoff = pd.Timestamp(as_of_date_str)
            df = df[df["game_date"] < cutoff]
        df = df[df["minutes_played"] > 0].copy()
        for col in ["fga", "fta", "pts"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            else:
                df[col] = 0
        if len(df) < 5:
            return None
        recent = df.tail(10)
        return {
            "minutes": recent["minutes_played"].mean(),
            "fga": recent["fga"].mean(),
            "fta": recent["fta"].mean(),
            "points": recent["pts"].mean(),
        }
    except Exception:
        return None

def calculate_team_absence_load(injury_lookup, season, as_of_date_str=None, projected_player_id=None):
    """Total estimated minutes/FGA/FTA missing from a team right now,
    weighted by how likely each injured player actually is to miss the
    game. Two fixes from initial version (caught in review):

    1. Excludes the projected player themselves — without this, a player
       who is themselves Doubtful/Questionable would have their own
       missing minutes/FGA counted into the team's "missing opportunity,"
       then partially redistributed back to... themselves. Mathematically
       inconsistent, even though injury_pass_recommended already flags
       this player as unresolved separately.

    2. Only redistributes from Out and Doubtful, not Questionable.
       Questionable is close to a coin flip and frequently resolves to
       playing normally — redistributing shots away from a 50/50 case
       risks inflating every teammate's projection, then reversing
       entirely once that player is confirmed active shortly before tip.
       Out and Doubtful are meaningfully more likely to actually be
       missing, so redistributing from those specifically has a much
       better hit rate."""
    absent_minutes = absent_fga = absent_fta = 0.0
    unavailable_players = []
    for injury in injury_lookup.values():
        if projected_player_id is not None and injury["player_id"] == projected_player_id:
            continue
        status = injury["normalized_status"]
        if status not in {"out", "doubtful"}:
            continue
        profile = get_player_role_profile(injury["player_id"], season, as_of_date_str)
        if not profile:
            continue
        absence_probability = 1.0 - injury["play_probability"]
        absent_minutes += profile["minutes"] * absence_probability
        absent_fga += profile["fga"] * absence_probability
        absent_fta += profile["fta"] * absence_probability
        unavailable_players.append({
            "name": injury["player_name"], "status": status,
            "minutes_removed": round(profile["minutes"] * absence_probability, 1),
            "fga_removed": round(profile["fga"] * absence_probability, 1),
        })
    return {
        "absent_minutes": absent_minutes, "absent_fga": absent_fga, "absent_fta": absent_fta,
        "players": unavailable_players,
    }

def calculate_injury_opportunity_adjustment(player_minutes, absence_load):
    """How much of the missing opportunity a specific player picks up,
    scaled by their own role — starters absorb more redistributed workload
    than bench players, since they're the ones a coach actually trusts
    with a bigger role on short notice. Capped so one absence can't
    unrealistically inflate a single player's line."""
    absent_minutes = absence_load["absent_minutes"]
    absent_fga = absence_load["absent_fga"]
    if player_minutes >= 32:
        minutes_share, fga_share = 0.10, 0.16
    elif player_minutes >= 24:
        minutes_share, fga_share = 0.07, 0.10
    elif player_minutes >= 15:
        minutes_share, fga_share = 0.05, 0.06
    else:
        minutes_share, fga_share = 0.03, 0.03
    added_minutes = min(absent_minutes * minutes_share, 4.0)
    added_fga = min(absent_fga * fga_share, 3.5)
    return {"added_minutes": added_minutes, "added_fga": added_fga}

def bdl_parse_minutes(m):
    """balldontlie's 'min' field is a string, sometimes 'MM:SS', sometimes
    just 'MM', sometimes empty for a DNP."""
    if m is None:
        return 0.0
    m = str(m).strip()
    if not m:
        return 0.0
    if ':' in m:
        parts = m.split(':')
        try:
            return float(parts[0]) + float(parts[1]) / 60.0
        except (ValueError, IndexError):
            return 0.0
    try:
        return float(m)
    except ValueError:
        return 0.0

@st.cache_data(ttl=3600)
def get_bdl_season_schedule(season):
    """Full season schedule — every game, every team, one shared cached
    fetch reused by every team's pace lookup. Deliberately doesn't use
    team_ids[] (confirmed broken on /stats — no reason to trust it on
    /games either without testing) — just seasons[] alone, which is a
    plain, already-proven filter. Confirmed schema (July 2026 diagnostic):
    top-level 'id', 'date' ('YYYY-MM-DD'), 'status' ('Final' when complete),
    nested 'home_team'/'visitor_team' objects each with their own 'id'."""
    return bdl_get("games", {"seasons[]": season, "per_page": 100})

@st.cache_data(ttl=86400)
def get_bdl_team_pace_before_date(team_id, season, as_of_date_str, num_recent_games=10):
    """Real, LEAK-FREE team pace estimate — built only from games that
    happened strictly before as_of_date, using their actual completed box
    scores. This replaces an earlier version that accidentally computed a
    team's pace using the very game being predicted (its completed box
    score), which is textbook look-ahead leakage — caught in a July 2026
    code review. Uses only confirmed-working filters: seasons[] alone on
    /games to get the schedule, then game_ids[] on /stats for the actual
    box scores of specific past games. Cached for a day per (team, season,
    date, num_recent_games) combo — without this, 10 players facing the
    same opponent in one Backtest run triggered ~10x redundant fetches of
    the same 10 games (July 2026 review). Also normalizes for overtime:
    an OT game has more true possessions just from being longer, which
    would otherwise inflate the pace average without accounting for it."""
    try:
        schedule = get_bdl_season_schedule(season)
        cutoff = pd.Timestamp(as_of_date_str).normalize()
        team_games = []
        for g in schedule:
            if g.get('status') != 'Final':
                continue
            game_date = g.get('date')
            if not game_date or pd.Timestamp(game_date).normalize() >= cutoff:
                continue
            home_id = (g.get('home_team') or {}).get('id')
            away_id = (g.get('visitor_team') or {}).get('id')
            if team_id not in (home_id, away_id):
                continue
            team_games.append(g)
        if not team_games:
            return None
        team_games.sort(key=lambda g: g['date'], reverse=True)
        recent_game_ids = [g['id'] for g in team_games[:num_recent_games]]
        rows = []
        for gid in recent_game_ids:
            rows.extend(bdl_get("stats", {"game_ids[]": gid, "per_page": 100}))
            time.sleep(0.3)
        team_rows = [r for r in rows if (r.get('team') or {}).get('id') == team_id]
        if not team_rows:
            return None
        game_totals = {}
        for r in team_rows:
            gid = (r.get('game') or {}).get('id')
            if gid is None:
                continue
            gt = game_totals.setdefault(gid, {"fga": 0, "fta": 0, "oreb": 0, "tov": 0, "minutes": 0.0})
            gt["fga"] += r.get("fga") or 0
            gt["fta"] += r.get("fta") or 0
            gt["oreb"] += r.get("oreb") or 0
            gt["tov"] += r.get("turnover") or 0
            gt["minutes"] += bdl_parse_minutes(r.get("min"))
        if not game_totals:
            return None
        normalized_poss = []
        for gt in game_totals.values():
            raw_poss = gt["fga"] + 0.44 * gt["fta"] - gt["oreb"] + gt["tov"]
            game_length_factor = (gt["minutes"] / 240.0) if gt["minutes"] > 0 else 1.0
            normalized_poss.append(raw_poss / game_length_factor)
        return round(sum(normalized_poss) / len(normalized_poss), 1)
    except Exception:
        return None

@st.cache_data(ttl=86400)
def get_bdl_season_baselines(season, as_of_date_str=None):
    """Real, season-specific league averages (2P%, 3P%, FT%, team score),
    computed from a sample of that season's actual completed games, rather
    than fixed constants that assume every NBA season shoots and scores the
    same way (July 2026 review). Sampled rather than exhaustive to keep
    this affordable — ~40 games spread evenly across the available season
    is a large enough sample for a stable league-wide average, and this is
    cached for a day per (season, date) combo. Falls back to sensible fixed
    constants if the dynamic computation fails or the season has too few
    completed games yet (e.g. very early in a new season)."""
    fallback = {'two_pct': 0.52, 'three_pct': 0.36, 'ft_pct': 0.75, 'team_score': 112.0}
    try:
        schedule = get_bdl_season_schedule(season)
        completed = [g for g in schedule if g.get('status') == 'Final']
        if as_of_date_str:
            cutoff = pd.Timestamp(as_of_date_str).normalize()
            completed = [g for g in completed if g.get('date') and pd.Timestamp(g['date']).normalize() < cutoff]
        if len(completed) < 20:  # too early in a season for a stable sample
            return fallback
        sample_size = min(40, len(completed))
        step = max(1, len(completed) // sample_size)
        sample_games = completed[::step][:sample_size]
        rows = []
        for g in sample_games:
            rows.extend(bdl_get("stats", {"game_ids[]": g['id'], "per_page": 100}))
            time.sleep(0.3)
        if not rows:
            return fallback
        total_fgm = sum(r.get('fgm') or 0 for r in rows)
        total_fga = sum(r.get('fga') or 0 for r in rows)
        total_fg3m = sum(r.get('fg3m') or 0 for r in rows)
        total_fg3a = sum(r.get('fg3a') or 0 for r in rows)
        total_ftm = sum(r.get('ftm') or 0 for r in rows)
        total_fta = sum(r.get('fta') or 0 for r in rows)
        two_pct = (total_fgm - total_fg3m) / (total_fga - total_fg3a) if (total_fga - total_fg3a) > 0 else fallback['two_pct']
        three_pct = total_fg3m / total_fg3a if total_fg3a > 0 else fallback['three_pct']
        ft_pct = total_ftm / total_fta if total_fta > 0 else fallback['ft_pct']
        scores = []
        for g in sample_games:
            if g.get('home_team_score') is not None:
                scores.append(g['home_team_score'])
            if g.get('visitor_team_score') is not None:
                scores.append(g['visitor_team_score'])
        team_score = sum(scores) / len(scores) if scores else fallback['team_score']
        return {
            'two_pct': round(two_pct, 3), 'three_pct': round(three_pct, 3),
            'ft_pct': round(ft_pct, 3), 'team_score': round(team_score, 1),
        }
    except Exception:
        return fallback


def get_bdl_matchup_pace(team_full_name, opp_full_name, season, as_of_date):
    """Expected game pace — blends BOTH teams' recent pace, not just the
    opponent's. A fast team facing a very slow one won't necessarily play a
    fully fast-paced game (July 2026 review). Uses a geometric mean rather
    than a simple average, since pace ratios (not raw differences) are what
    actually compound between two teams. Falls back gracefully to whichever
    side resolves if the other doesn't."""
    team_ids = get_bdl_team_ids()
    date_str = pd.Timestamp(as_of_date).strftime("%Y-%m-%d")

    team_id = team_ids.get(team_full_name)
    team_pace = get_bdl_team_pace_before_date(team_id, season, date_str) if team_id else None

    opp_id = team_ids.get(opp_full_name)
    opp_pace = get_bdl_team_pace_before_date(opp_id, season, date_str) if opp_id else None

    if team_pace and opp_pace:
        return round(league_avg_pace * ((team_pace / league_avg_pace) * (opp_pace / league_avg_pace)) ** 0.5, 1)
    return team_pace or opp_pace or league_avg_pace



# ---- NBA POINTS PROJECTION ENGINE ----
@st.cache_data(ttl=300, show_spinner=False)
def get_live_nba_odds():
    """Current NBA odds — cached for 5 minutes so 15 players from the same
    game share one fetch instead of each triggering their own redundant call.
    Deliberately has no as_of_date parameter: this is ONLY for live, current
    props. Historical backtests must never call this (see the July 2026 code
    review that caught this endpoint being hit unconditionally even during
    backtesting, silently returning irrelevant present-day odds instead of
    historical ones)."""
    return get_json("https://api.the-odds-api.com/v4/sports/basketball_nba/odds",
        params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals,spreads', 'oddsFormat': 'american'})

@st.cache_data(ttl=2592000)  # 30 days — historical odds never change, so a re-run never re-costs quota
def get_historical_nba_events_for_date(date_str):
    """Historical NBA events (games) for one specific date — the first step
    needed before pulling historical player-prop odds, since those require
    a specific event_id. Uses The Odds API's historical events endpoint,
    which costs real quota (opt-in feature, only ever called when the user
    explicitly asks for it in Backtest — never automatically)."""
    try:
        snapshot = f"{date_str}T12:00:00Z"
        resp = get_json(
            "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/events",
            params={'apiKey': ODDS_API_KEY, 'date': snapshot}
        )
        return resp.get('data', [])
    except Exception:
        return []

@st.cache_data(ttl=2592000)  # 30 days — same reasoning as above
def get_historical_prop_lines_for_game(event_id, market_key, date_str):
    """Historical sportsbook line for every player in one specific game and
    market (e.g. 'player_assists') — one query returns ALL players' lines
    at once, so cost scales with GAMES tested, not players. Real quota
    cost: 10 units per region per market per event (The Odds API pricing).
    Returns {player_name: line}."""
    try:
        snapshot = f"{date_str}T23:00:00Z"  # late enough in the day to catch a closing-ish line before tipoff
        resp = get_json(
            f"https://api.the-odds-api.com/v4/historical/sports/basketball_nba/events/{event_id}/odds",
            params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': market_key, 'oddsFormat': 'american', 'date': snapshot}
        )
        lines = {}
        game_data = resp.get('data', {})
        for bookmaker in game_data.get('bookmakers', []):
            for market in bookmaker.get('markets', []):
                if market.get('key') == market_key:
                    for outcome in market.get('outcomes', []):
                        pname = outcome.get('description')
                        point = outcome.get('point')
                        if pname and point is not None and pname not in lines:
                            lines[pname] = point
        return lines
    except Exception:
        return {}

def find_game_odds(games_data, home_team, away_team):
    """Matches on BOTH teams as an exact set, not a fragile 'is home_team a
    substring of this field' check — the old version could false-match on
    partial name overlaps (e.g. 'LA Clippers' inside a longer string). Uses
    the MEDIAN across every available bookmaker rather than stopping at the
    first one — protects against one stale or unusual number skewing the
    projection (July 2026 review)."""
    requested = {home_team, away_team}
    for game in games_data:
        if {game.get('home_team'), game.get('away_team')} == requested:
            totals, home_spreads = [], []
            for bookmaker in game.get('bookmakers', []):
                for market in bookmaker.get('markets', []):
                    if market.get('key') == 'totals':
                        for outcome in market.get('outcomes', []):
                            point = outcome.get('point')
                            if point is not None:
                                totals.append(float(point))
                                break
                    elif market.get('key') == 'spreads':
                        for outcome in market.get('outcomes', []):
                            if outcome.get('name') == home_team:
                                point = outcome.get('point')
                                if point is not None:
                                    home_spreads.append(float(point))
            game_total = statistics.median(totals) if totals else None
            spread = statistics.median(home_spreads) if home_spreads else None
            return game_total, spread
    return None, None

def run_nba_points_projection(player_name, opponent_abbrev, home_team, away_team, home_or_away, season='2025-26', as_of_date=None, opp_pace_override=None, game_total_override=None, spread_override=None):
    try:
        bdl_season = int(season.split("-")[0])  # balldontlie uses the season's start year

        df, player_id = get_bdl_player_game_log(player_name, bdl_season)
        if df.empty or not player_id:
            return None

        # Injury status — LIVE USE ONLY. balldontlie's injury endpoint has
        # no date parameter (confirmed via their docs), so there's no way
        # to check historical status for a backtest date — only "right
        # now." Out means no meaningful projection is possible. Doubtful/
        # Questionable don't naively multiply the projection by a play
        # probability (a "50% questionable" player doesn't play half a
        # normal game — they either play close to normally or not at all),
        # so instead this flags injury_pass_recommended for the caller to
        # act on, while still returning a real "if active" number.
        team_ids_for_injury = get_bdl_team_ids()
        player_team_full_name = home_team if home_or_away == 'home' else away_team
        player_team_id = team_ids_for_injury.get(player_team_full_name)
        injury_lookup = build_team_injury_lookup(player_team_id) if (as_of_date is None and player_team_id) else {}
        player_injury = injury_lookup.get(player_id)

        injury_status, injury_description = None, None
        injury_pass_recommended = False
        if player_injury:
            injury_status = player_injury['normalized_status']
            injury_description = player_injury['description']
            if injury_status == 'out':
                return None
            if injury_status in ('doubtful', 'questionable'):
                injury_pass_recommended = True

        df['minutes_played'] = df['min'].apply(bdl_parse_minutes)
        df = df[df['minutes_played'] > 0]  # drop DNPs before any averaging
        if len(df) < 5:
            return None

        df['pts'] = pd.to_numeric(df['pts'], errors='coerce')
        df['fga'] = pd.to_numeric(df['fga'], errors='coerce')
        for col in ['fta', 'turnover', 'fgm', 'fg3m', 'fg3a', 'ftm']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df['game_date'] = pd.to_datetime(df['game'].apply(lambda g: (g or {}).get('date')))
        df['home_team_id'] = df['game'].apply(lambda g: (g or {}).get('home_team_id'))
        df['team_id'] = df['team'].apply(lambda t: (t or {}).get('id'))
        df = df.sort_values('game_date').reset_index(drop=True)
        if as_of_date:
            df = df[df['game_date'] < pd.Timestamp(as_of_date)].reset_index(drop=True)
            if len(df) < 5:
                return None

        # Defensive data cleaning (July 2026 review) — a single malformed
        # value could otherwise silently propagate through the whole
        # projection. Essential columns must be real; optional box-score
        # fields default to 0 rather than leaving NaN; and a few logical
        # consistency checks (can't make more 3s than 3PA, etc.) guard
        # against any raw data weirdness from the API.
        df = df.dropna(subset=['pts', 'fga', 'minutes_played', 'game_date']).copy()
        if len(df) < 5:
            return None
        for col in ['fta', 'ftm', 'fgm', 'fg3m', 'fg3a', 'turnover']:
            if col in df.columns:
                df[col] = df[col].fillna(0)
        if 'fg3a' in df.columns:
            df['fg3a'] = df['fg3a'].clip(lower=0)
            df['fg3a'] = df[['fg3a', 'fga']].min(axis=1)
        if 'fg3m' in df.columns and 'fg3a' in df.columns:
            df['fg3m'] = df['fg3m'].clip(lower=0)
            df['fg3m'] = df[['fg3m', 'fg3a']].min(axis=1)
        if 'ftm' in df.columns and 'fta' in df.columns:
            df['ftm'] = df['ftm'].clip(lower=0)
            df['ftm'] = df[['ftm', 'fta']].min(axis=1)

        season_ppg = round(df['pts'].mean(), 1)  # kept for display/diagnostics only — no longer feeds the projection directly
        season_mpg = round(df['minutes_played'].mean(), 1)
        season_fga = round(df['fga'].mean(), 1)
        last5_avg = round(df['pts'].tail(5).mean(), 1)
        last10_avg = round(df['pts'].tail(10).mean(), 1)
        last5_fga = round(df['fga'].tail(5).mean(), 1)
        last10_fga = round(df['fga'].tail(10).mean(), 1)
        last5_min = round(df['minutes_played'].tail(5).mean(), 1)
        last10_min = round(df['minutes_played'].tail(10).mean(), 1)

        # === Scoring engine rebuild (July 2026) ===
        # Old approach: blend recent PPG averages, then apply a projected-FGA
        # "factor" capped at +-5% — capped so tightly it barely moved the
        # final number regardless of how extreme the shot-volume signal was.
        # It also double-counted recent shot volume: once implicitly through
        # recent PPG, again (barely) through the FGA multiplier. New
        # approach: build points bottom-up from Minutes x shots-per-minute x
        # shooting conversion, so FGA/FTA volume actually drives the number,
        # not just decorates it.
        has_3pt = 'fg3a' in df.columns and 'fg3m' in df.columns
        has_ft = 'fta' in df.columns and 'ftm' in df.columns

        # Separate dataset for RATE calculations (FGA/min, 3PA/min, FTA/min,
        # shooting efficiency) that excludes likely injury-exit games — a
        # player who leaves after 2 minutes hurt shouldn't distort his
        # per-minute shot rate the same way a real, full game does. Keep
        # using the FULL played-games dataset (df) for availability,
        # workload volatility, and confidence signals, since an early exit
        # is still real, relevant information for those (July 2026 review).
        df_rate_games = df[df['minutes_played'] >= 8].copy()
        if len(df_rate_games) < 5:
            df_rate_games = df.copy()  # not enough full games yet — fall back rather than break

        df_rate_games['fga_per_min'] = df_rate_games['fga'] / df_rate_games['minutes_played']
        if has_3pt:
            df_rate_games['fg3a_per_min'] = df_rate_games['fg3a'] / df_rate_games['minutes_played']
        if has_ft:
            df_rate_games['fta_per_min'] = df_rate_games['fta'] / df_rate_games['minutes_played']

        def _blend(col, w_season, w_l10, w_l5, source_df=None):
            source_df = source_df if source_df is not None else df_rate_games
            return (source_df[col].mean() * w_season) + (source_df[col].tail(10).mean() * w_l10) + (source_df[col].tail(5).mean() * w_l5)

        proj_fga_per_min = _blend('fga_per_min', 0.40, 0.35, 0.25)
        proj_3pa_per_min = _blend('fg3a_per_min', 0.50, 0.30, 0.20) if has_3pt else 0.0
        proj_fta_per_min = _blend('fta_per_min', 0.50, 0.30, 0.20) if has_ft else 0.0
        # Safety bounds — not intended prediction caps, just guards against
        # an unusual short-sample blend producing a nonsensical rate
        # (July 2026 review).
        proj_fga_per_min = max(0.0, min(proj_fga_per_min, 1.0))
        proj_3pa_per_min = max(0.0, min(proj_3pa_per_min, proj_fga_per_min))
        proj_fta_per_min = max(0.0, min(proj_fta_per_min, 0.7))

        # Minutes volatility computed early so it can drive role-sensitive
        # weighting below, instead of always using the same fixed 30/30/40
        # split regardless of whether a player has a rock-stable role or a
        # recently-changing one (July 2026 review).
        last10_min_series = df['minutes_played'].tail(10)
        last10_min_std = round(last10_min_series.std(), 2) if len(last10_min_series) > 1 else 0.0
        min_cv = round(last10_min_std / last10_min, 3) if last10_min > 0 else 1.0

        if min_cv < 0.12:
            # Very stable role — trust the longer, less noisy sample more.
            expected_minutes_raw = (season_mpg * 0.45) + (last10_min * 0.35) + (last5_min * 0.20)
        elif min_cv < 0.25:
            # Normal rotation variation — close to the original fixed split.
            expected_minutes_raw = (season_mpg * 0.30) + (last10_min * 0.35) + (last5_min * 0.35)
        else:
            # Role may genuinely be changing — trust recent games more.
            expected_minutes_raw = (season_mpg * 0.15) + (last10_min * 0.30) + (last5_min * 0.55)

        # Explicit role-change flag — the NBA equivalent of a pitcher who
        # just moved from the bullpen to the rotation. Informational only
        # right now, not yet fed into the projection math.
        role_change_ratio = (last5_min / season_mpg) if season_mpg > 0 else 1.0
        if role_change_ratio >= 1.25:
            role_status = "📈 Recently Expanded"
        elif role_change_ratio <= 0.75:
            role_status = "📉 Recently Reduced"
        else:
            role_status = "➡️ Stable"

        # Shooting percentages — Bayesian shrinkage toward a league baseline
        # using pseudo-attempts, replacing a previous fixed-weight blend
        # (70% season / 20% last-10 / 10% league) that treated a 12-attempt
        # season identically to a 300-attempt one. Shrinkage naturally
        # regresses small samples harder without needing a separate,
        # arbitrarily-tuned recency blend (July 2026 review).
        #
        # League baselines are now season-specific (July 2026 review round
        # 4) — computed from a real sample of that season's actual games,
        # rather than one fixed constant assumed to apply to every season.
        baseline_date_str = pd.Timestamp(as_of_date if as_of_date else datetime.today()).strftime("%Y-%m-%d")
        season_baselines = get_bdl_season_baselines(bdl_season, baseline_date_str)
        league_avg_2p_pct = season_baselines['two_pct']
        league_avg_3p_pct = season_baselines['three_pct']
        league_avg_ft_pct = season_baselines['ft_pct']

        def _shrunk_pct(makes, attempts, league_pct, prior_attempts):
            return (makes + league_pct * prior_attempts) / (attempts + prior_attempts) if (attempts + prior_attempts) > 0 else league_pct

        if has_3pt:
            season_2pm = (df_rate_games['fgm'] - df_rate_games['fg3m']).sum()
            season_2pa_sum = (df_rate_games['fga'] - df_rate_games['fg3a']).sum()
            season_3pm = df_rate_games['fg3m'].sum()
            season_3pa_sum = df_rate_games['fg3a'].sum()
        else:
            season_2pm = season_2pa_sum = season_3pm = season_3pa_sum = 0

        projected_2p_pct = _shrunk_pct(season_2pm, season_2pa_sum, league_avg_2p_pct, prior_attempts=75)
        projected_3p_pct = _shrunk_pct(season_3pm, season_3pa_sum, league_avg_3p_pct, prior_attempts=100)

        if has_ft:
            season_ftm = df_rate_games['ftm'].sum()
            season_fta_sum = df_rate_games['fta'].sum()
        else:
            season_ftm = season_fta_sum = 0
        projected_ft_pct = _shrunk_pct(season_ftm, season_fta_sum, league_avg_ft_pct, prior_attempts=50)

        if 'fgm' in df_rate_games.columns:
            season_fgm = round(df_rate_games['fgm'].mean(), 2)
            rate_season_fga = round(df_rate_games['fga'].mean(), 2)
            season_fg_pct = round(season_fgm / rate_season_fga * 100, 1) if rate_season_fga > 0 else None
        else:
            season_fg_pct = None

        last10_fta_val = round(df['fta'].tail(10).mean(), 2) if 'fta' in df.columns else 0
        last10_tov_val = round(df['turnover'].tail(10).mean(), 2) if 'turnover' in df.columns else 0
        recent_touches_per_min = round((last10_fga + 0.44 * last10_fta_val + last10_tov_val) / last10_min, 3) if last10_min > 0 else None

        # Scoring volatility — floor of 10 in the denominator prevents tiny-
        # average bench players from getting an automatically-inflated CV
        # just because their mean is small (a real, confirmed bias: a 4 PPG
        # player with a 4-point std gets CV=1.0 "Uncertain," while a 28 PPG
        # player with an 8-point std gets CV=0.29 "Reliable," even though
        # the star's absolute swings are much larger — July 2026 review).
        last10_pts = df['pts'].tail(10)
        last10_pts_mean = round(last10_pts.mean(), 2)
        last10_pts_std = round(last10_pts.std(), 2) if len(last10_pts) > 1 else 0.0
        cv = round(last10_pts_std / max(last10_pts_mean, 10), 3)

        if cv < 0.35: confidence_tier = "🟢 Reliable"
        elif cv < 0.50: confidence_tier = "🟠 Volatile"
        else: confidence_tier = "🔴 Uncertain Workload"

        # scoring_volatility_tier / workload_reliability_tier / confidence_score:
        # NEW, additive fields (July 2026 review round 3) — confidence_tier's
        # existing string values are left completely untouched, since
        # calculate_mm_stake and get_risk_level_label substring-match on
        # them app-wide and renaming risks silently breaking real stake
        # sizing. These new fields give a more precise, separated view
        # (scoring volatility vs. workload reliability) without that risk.
        if cv < 0.35: scoring_volatility_tier = "🟢 Low Scoring Variance"
        elif cv < 0.50: scoring_volatility_tier = "🟠 Moderate Scoring Variance"
        else: scoring_volatility_tier = "🔴 High Scoring Variance"

        # min_cv already computed earlier (drives role-sensitive minutes
        # weighting above) — reused here for the workload tier label.
        if min_cv < 0.20:
            workload_tier = "🟢 Stable Rotation Player"
        elif min_cv < 0.35:
            workload_tier = "🟡 Changing Role"
        else:
            workload_tier = "🔴 Highly Volatile Minutes"
        workload_reliability_tier = workload_tier

        # Usage rate / defensive rating: known limitations, not real
        # per-player estimates right now — both stay at a neutral fallback.
        # Explicit status fields so the output doesn't imply the model
        # incorporated usage or matchup defense when it actually didn't
        # (July 2026 review).
        usage_rate = 0.20
        opp_def_rating = league_avg_def_rating
        usage_data_status = "Unavailable — neutral fallback"
        defense_data_status = "Unavailable — neutral fallback"

        team_full_name = home_team if home_or_away == 'home' else away_team
        opp_full_name = nba_abbrev_to_name.get(opponent_abbrev, '')
        pace_reference_date = as_of_date if as_of_date else datetime.today()
        opp_pace = opp_pace_override if opp_pace_override else (
            get_bdl_matchup_pace(team_full_name, opp_full_name, bdl_season, pace_reference_date) if opp_full_name else league_avg_pace
        )

        df['was_home'] = df['home_team_id'] == df['team_id']
        home_games = df[df['was_home'] == True]
        away_games = df[df['was_home'] == False]
        home_ppg = round(home_games['pts'].mean(), 1) if not home_games.empty else season_ppg
        away_ppg = round(away_games['pts'].mean(), 1) if not away_games.empty else season_ppg
        raw_location_adj = (home_ppg - season_ppg) if home_or_away == 'home' else (away_ppg - season_ppg)
        # Shrink toward zero when the home/away split is based on a small
        # sample — early in a season, a 2-point swing from 3-4 games is
        # mostly noise, not a real home/away effect (July 2026 fix).
        location_games = len(home_games) if home_or_away == 'home' else len(away_games)
        location_shrinkage = min(1.0, location_games / 20)
        location_adj = max(-1.0, min(1.0, round(raw_location_adj * location_shrinkage, 2)))

        # Rest days — fixed boundary bug (July 2026 review): a genuine
        # back-to-back has a CALENDAR gap of 1 (e.g. played Nov 30, playing
        # Dec 1), not 0 — the old "== 0" check could never actually fire for
        # a real back-to-back. Also reduced the penalty now that it actually
        # triggers for real games instead of being silently dead code.
        reference_date = as_of_date if as_of_date else datetime.today()
        last_game_date = df['game_date'].iloc[-1].to_pydatetime() if not df.empty else None
        date_gap = (pd.Timestamp(reference_date).normalize() - pd.Timestamp(last_game_date).normalize()).days if last_game_date else 2
        days_rest = max(0, date_gap - 1)
        if date_gap == 1:
            rest_adj = -0.5  # true back-to-back
        elif date_gap >= 4:
            rest_adj = 0.25
        else:
            rest_adj = 0.0

        game_total = spread = None
        if game_total_override is not None or spread_override is not None:
            game_total, spread = game_total_override, spread_override
        elif as_of_date is None:  # live use only — a July 2026 review caught this
            try:                # endpoint being hit unconditionally even during
                games_data = get_live_nba_odds()  # backtests, silently pulling
                game_total, spread = find_game_odds(games_data, home_team, away_team)  # today's real odds instead of historical ones
            except Exception as e:
                log_failure_reason('UNAVAILABLE_ODDS', f"NBA points live odds ({home_team} vs {away_team}): {e}")

        implied_team_total = None
        # Blowout minutes impact scales with role, rather than a flat -4 for
        # everyone regardless of whether they're a starter or a fringe bench
        # player — bench players often GAIN garbage-time minutes in a
        # blowout while starters lose 4th-quarter run (July 2026 fix).
        # Deliberately not further tuned/optimized from one slate — would
        # need a proper backtest across many blowout games first.
        blowout_minutes_adj = 0
        # Fixed: "if game_total and spread" is falsy for a real, common
        # pick'em game (spread == 0), silently skipping this whole block —
        # July 2026 review.
        if game_total is not None and spread is not None:
            if home_or_away == 'home':
                implied_team_total = round((game_total / 2) + (abs(spread) / 2 * (1 if spread < 0 else -1)), 1)
            else:
                implied_team_total = round((game_total / 2) - (abs(spread) / 2 * (1 if spread < 0 else -1)), 1)
            if abs(spread) >= 9:
                if expected_minutes_raw >= 32:
                    blowout_multiplier = 1.0
                elif expected_minutes_raw >= 24:
                    blowout_multiplier = 0.5
                else:
                    blowout_multiplier = -0.25  # some bench players gain time
                base_blowout_adj = -4 if abs(spread) >= 12 else -2
                blowout_minutes_adj = round(base_blowout_adj * blowout_multiplier, 1)

        # Teammate absence redistribution — live only, same constraint as
        # the player's own injury status above. Estimates how much
        # opportunity (minutes, shots) is missing from the team due to
        # OTHER injured players, and redistributes a share of it to this
        # player based on their own role (starters absorb more than bench
        # players). A simple first version — a real teammate-out empirical
        # split (this player's actual FGA/min specifically when a given
        # teammate has missed games) would be more precise but costs a lot
        # more API calls; worth building later for a short list of
        # genuinely important absences.
        injury_minutes_adj = injury_fga_adj = 0.0
        team_absence_load = None
        if as_of_date is None and player_team_id and injury_lookup:
            team_absence_load = calculate_team_absence_load(injury_lookup, bdl_season, None, projected_player_id=player_id)
            injury_adjustment = calculate_injury_opportunity_adjustment(expected_minutes_raw, team_absence_load)
            injury_minutes_adj = injury_adjustment['added_minutes']
            injury_fga_adj = injury_adjustment['added_fga']

        # Final minutes -> final attempts -> final scoring base (July 2026
        # review, round 3). Previously, projected FGA/3PA/FTA were computed
        # from PRE-blowout minutes, then only a secondary points-per-minute
        # patch (minutes_pts_adj) tried to correct for the blowout change —
        # meaning the returned "projected FGA" never actually reflected the
        # blowout-adjusted minutes shown alongside it. Now minutes are
        # finalized FIRST, and every downstream number is built from that
        # single, coherent number — including any teammate-injury bump.
        final_expected_minutes_raw = max(0.0, expected_minutes_raw + blowout_minutes_adj + injury_minutes_adj)
        final_expected_minutes = round(final_expected_minutes_raw, 1)

        # Extra shots from teammate absences preserve this player's normal
        # shot mix (3PA share, FT rate) rather than assuming every added
        # shot is a two.
        three_share = (proj_3pa_per_min / proj_fga_per_min) if proj_fga_per_min > 0 else 0.0
        fta_per_fga = (proj_fta_per_min / proj_fga_per_min) if proj_fga_per_min > 0 else 0.0

        projected_fga = round(final_expected_minutes_raw * proj_fga_per_min + injury_fga_adj, 1)
        projected_3pa = round(final_expected_minutes_raw * proj_3pa_per_min + injury_fga_adj * three_share, 1) if has_3pt else 0.0
        projected_3pa = min(projected_3pa, projected_fga)
        projected_fta = round(final_expected_minutes_raw * proj_fta_per_min + injury_fga_adj * fta_per_fga * 0.50, 1) if has_ft else 0.0
        projected_2pa = max(0.0, projected_fga - projected_3pa)

        points_from_twos = projected_2pa * projected_2p_pct * 2
        points_from_threes = projected_3pa * projected_3p_pct * 3
        points_from_free_throws = projected_fta * projected_ft_pct
        base = points_from_twos + points_from_threes + points_from_free_throws

        usage_adj = round((usage_rate - 0.20) * 10, 2)
        def_adj = round((opp_def_rating - league_avg_def_rating) * 0.2, 2)

        # Pace and implied team total are now BOTH multiplicative scales on
        # the base projection, not flat additive point values — a flat +/-
        # gave a 5-point bench player and a 30-point star the exact same
        # adjustment, which doesn't make sense (July 2026 review). Both
        # dampened rather than a full 1:1 scale. pace_adj/team_total_adj are
        # kept as display-only values showing how many points each was
        # worth, for backward compatibility with existing Backtest columns.
        pace_factor = 1 + ((opp_pace / league_avg_pace) - 1) * 0.70
        base_before_pace = base
        base = base * pace_factor
        pace_adj = round(base - base_before_pace, 2)

        team_total_factor = 1.0
        if implied_team_total is not None:
            team_total_factor = 1 + ((implied_team_total / season_baselines['team_score']) - 1) * 0.60
        base_before_team_total = base
        base = base * team_total_factor
        team_total_adj = round(base - base_before_team_total, 2)

        raw_adjustment = max(-6.0, min(6.0, usage_adj + def_adj + location_adj + rest_adj))
        final_projection = round(base + raw_adjustment, 1)

        # Confidence score (July 2026 review, round 3) — combines scoring
        # volatility AND workload reliability into one number, rather than
        # letting points CV alone drive real bankroll sizing through
        # confidence_tier. Additive/informational only right now — does
        # NOT replace confidence_tier's existing thresholds or strings.
        confidence_score = 100.0
        confidence_score -= min(30, cv * 45)
        confidence_score -= min(35, min_cv * 100)
        if len(df) < 10:
            confidence_score -= 10
        if final_expected_minutes < 18:
            confidence_score -= 10
        confidence_score = round(max(0, min(100, confidence_score)), 1)

        return {
            'projection': final_projection, 'base': round(base, 2),
            'season_ppg': season_ppg, 'last5_avg': last5_avg, 'last10_avg': last10_avg,
            'last10_pts_std': last10_pts_std, 'season_mpg': season_mpg,
            'expected_minutes': final_expected_minutes, 'usage_rate': usage_rate,
            'usage_data_status': usage_data_status, 'defense_data_status': defense_data_status,
            'projected_fga': projected_fga, 'season_fg_pct': season_fg_pct,
            'recent_touches_per_min': recent_touches_per_min,
            'projected_2p_pct': round(projected_2p_pct * 100, 1), 'projected_3p_pct': round(projected_3p_pct * 100, 1),
            'projected_ft_pct': round(projected_ft_pct * 100, 1), 'projected_2pa': projected_2pa,
            'projected_3pa': projected_3pa, 'projected_fta': projected_fta,
            'points_from_twos': round(points_from_twos, 2), 'points_from_threes': round(points_from_threes, 2),
            'points_from_free_throws': round(points_from_free_throws, 2),
            'opp_def_rating': opp_def_rating, 'opp_pace': opp_pace,
            'pace_factor': round(pace_factor, 3), 'team_total_factor': round(team_total_factor, 3),
            'location_adj': location_adj, 'rest_adj': rest_adj, 'team_total_adj': team_total_adj,
            'usage_adj': usage_adj, 'def_adj': def_adj,
            'pace_adj': pace_adj, 'implied_team_total': implied_team_total, 'game_total': game_total,
            'cv': cv, 'confidence_tier': confidence_tier, 'days_rest': days_rest,
            'min_cv': min_cv, 'workload_tier': workload_tier, 'role_status': role_status,
            'scoring_volatility_tier': scoring_volatility_tier, 'workload_reliability_tier': workload_reliability_tier,
            'confidence_score': confidence_score,
            'injury_status': injury_status, 'injury_description': injury_description,
            'injury_pass_recommended': injury_pass_recommended,
            'injury_minutes_adj': round(injury_minutes_adj, 1), 'injury_fga_adj': round(injury_fga_adj, 1),
            'unavailable_teammates': team_absence_load['players'] if team_absence_load else [],
        }
    except Exception as e:
        if st.session_state.get("_nba_debug_mode"): raise
        return None


# ---- NBA ASSISTS PROJECTION ENGINE ----
def run_nba_assists_projection(player_name, opponent_abbrev, home_team, away_team, home_or_away, season='2025-26', as_of_date=None, opp_pace_override=None, game_total_override=None, spread_override=None):
    try:
        bdl_season = int(season.split("-")[0])

        df, player_id = get_bdl_player_game_log(player_name, bdl_season)
        if df.empty or not player_id:
            return None

        # Injury status — LIVE USE ONLY, same reasoning as the Points
        # engine (see its comment for the full explanation). Uses the same
        # normalized team-wide lookup, but doesn't attempt teammate-
        # opportunity redistribution here — that logic is built around
        # FGA/shot-volume, which doesn't map cleanly onto assists.
        team_ids_for_injury = get_bdl_team_ids()
        player_team_full_name = home_team if home_or_away == 'home' else away_team
        player_team_id = team_ids_for_injury.get(player_team_full_name)
        injury_lookup = build_team_injury_lookup(player_team_id) if (as_of_date is None and player_team_id) else {}
        player_injury = injury_lookup.get(player_id)

        injury_status, injury_description = None, None
        injury_pass_recommended = False
        if player_injury:
            injury_status = player_injury['normalized_status']
            injury_description = player_injury['description']
            if injury_status == 'out':
                return None
            if injury_status in ('doubtful', 'questionable'):
                injury_pass_recommended = True

        df['minutes_played'] = df['min'].apply(bdl_parse_minutes)
        df = df[df['minutes_played'] > 0]
        if len(df) < 5:
            return None

        df['assists'] = pd.to_numeric(df['ast'], errors='coerce')
        df['turnovers'] = pd.to_numeric(df['turnover'], errors='coerce') if 'turnover' in df.columns else 0
        if 'fga' in df.columns:
            df['fga'] = pd.to_numeric(df['fga'], errors='coerce')
        if 'fta' in df.columns:
            df['fta'] = pd.to_numeric(df['fta'], errors='coerce')
        df['game_date'] = pd.to_datetime(df['game'].apply(lambda g: (g or {}).get('date')))
        df['home_team_id'] = df['game'].apply(lambda g: (g or {}).get('home_team_id'))
        df['team_id'] = df['team'].apply(lambda t: (t or {}).get('id'))
        df = df.sort_values('game_date').reset_index(drop=True)
        if as_of_date:
            df = df[df['game_date'] < pd.Timestamp(as_of_date)].reset_index(drop=True)
            if len(df) < 5:
                return None

        # Defensive data cleaning (July 2026 review) — same reasoning as the
        # Points engine: a single malformed value shouldn't silently
        # propagate through the whole projection.
        df = df.dropna(subset=['assists', 'minutes_played', 'game_date']).copy()
        if len(df) < 5:
            return None
        if 'turnover' in df.columns:
            df['turnovers'] = df['turnovers'].fillna(0)

        season_apg = round(df['assists'].mean(), 1)  # kept for display/diagnostics only — no longer feeds the projection directly
        season_mpg = round(df['minutes_played'].mean(), 1)
        season_tov = round(df['turnovers'].mean(), 1)
        last5_avg = round(df['assists'].tail(5).mean(), 1)
        last10_avg = round(df['assists'].tail(10).mean(), 1)
        last5_min = round(df['minutes_played'].tail(5).mean(), 1)
        last10_min = round(df['minutes_played'].tail(10).mean(), 1)
        last5_tov = round(df['turnovers'].tail(5).mean(), 1)

        last10_ast = df['assists'].tail(10)
        last10_ast_avg = round(last10_ast.mean(), 2)
        last10_ast_std = round(last10_ast.std(), 2) if len(last10_ast) > 1 else 0.0
        # Floor of 4 in the denominator — same reasoning as the Points
        # engine's floor of 10, scaled down since assist totals are
        # naturally smaller numbers than points. This fix was applied to
        # the Points engine earlier but never carried over to Assists,
        # which still had the same bias against low-assist bench players
        # (caught reviewing this engine for the July 2026 round 3 fixes).
        cv = round(last10_ast_std / max(last10_ast_avg, 4), 3)

        if cv < 0.35: confidence_tier = "🟢 Reliable"
        elif cv < 0.50: confidence_tier = "🟠 Volatile"
        else: confidence_tier = "🔴 Uncertain Workload"

        if cv < 0.35: scoring_volatility_tier = "🟢 Low Scoring Variance"
        elif cv < 0.50: scoring_volatility_tier = "🟠 Moderate Scoring Variance"
        else: scoring_volatility_tier = "🔴 High Scoring Variance"

        last10_min_series = df['minutes_played'].tail(10)
        last10_min_std = round(last10_min_series.std(), 2) if len(last10_min_series) > 1 else 0.0
        min_cv = round(last10_min_std / last10_min, 3) if last10_min > 0 else 1.0

        if min_cv < 0.20:
            workload_tier = "🟢 Stable Rotation Player"
        elif min_cv < 0.35:
            workload_tier = "🟡 Changing Role"
        else:
            workload_tier = "🔴 Highly Volatile Minutes"
        workload_reliability_tier = workload_tier

        # === Core rebuild (July 2026, round 4) ===
        # Old approach: blend recent APG averages directly — the exact same
        # double-counting problem Points used to have, since recent APG
        # already reflects recent minutes, then a separate minutes_ast_adj
        # tried to patch for any minutes change on top of that. New
        # approach, matching Points: assists per minute (which separates
        # playmaking rate from playing time) x final expected minutes.
        # balldontlie doesn't expose potential assists at this tier, so
        # this isn't the ideal tracking-data model, but it's structurally
        # better than a blended APG average regardless.
        df_rate_games = df[df['minutes_played'] >= 8].copy()
        if len(df_rate_games) < 5:
            df_rate_games = df.copy()

        # Rate weighted by actual minutes played, not an equal average of
        # per-game rates (July 2026 review — a legitimate model correction,
        # not just a nice-to-have). Averaging individual game rates treats
        # an 8-minute game and a 36-minute game as equally strong evidence,
        # e.g. 1 assist in 8 minutes (0.125/min) counted the same as 6
        # assists in 36 minutes (0.167/min) despite the second game
        # representing 4.5x more actual playing-time evidence. Summing
        # makes and minutes separately, then dividing, correctly weights
        # by real exposure.
        def _weighted_ast_rate(sub_df):
            total_min = sub_df['minutes_played'].sum()
            return sub_df['assists'].sum() / total_min if total_min > 0 else 0.0

        season_ast_per_min = _weighted_ast_rate(df_rate_games)
        last10_ast_per_min = _weighted_ast_rate(df_rate_games.tail(10))
        last5_ast_per_min = _weighted_ast_rate(df_rate_games.tail(5))

        projected_ast_per_min = (season_ast_per_min * 0.45) + (last10_ast_per_min * 0.35) + (last5_ast_per_min * 0.20)
        projected_ast_per_min = max(0.0, min(projected_ast_per_min, 0.6))  # safety bound, not an intended cap

        # tov_factor kept as an informational diagnostic only — never
        # multiplied into the projection. A high-turnover primary
        # ballhandler often ALSO generates a lot of assists (they're
        # correlated, not inversely related), so there's no good evidence
        # base to justify discounting assists by recent turnover rate
        # (July 2026 review).
        tov_factor = max(0.95, min(1.05, round(last5_tov / season_tov, 3) if season_tov > 0 else 1.0))

        # Usage rate: known limitation, not a real per-player estimate right
        # now. It was built on get_bdl_team_game_averages(), which relies on
        # balldontlie's team_ids[] filter — confirmed (July 2026 diagnostic)
        # to silently return ALL teams' stats instead of filtering, making
        # that function's output unreliable. Falls back to neutral defaults
        # until there's a genuinely confirmed-working way to get a team's
        # aggregate box-score totals from this API tier. Assist % has no
        # clean box-score-only formula either way (needs on-court team FG
        # data), so it stays neutral regardless.
        usage_rate, ast_pct = 0.20, 0.15
        usage_data_status = "Unavailable — neutral fallback"

        # Known limitations: no "potential assists" (tracking-only stat) or
        # opponent-assists-allowed equivalent at this data tier — both stay
        # neutral. Pace now blends both teams (see Points engine's comment).
        potential_assists = None
        potential_ast_adj = 0
        team_full_name = home_team if home_or_away == 'home' else away_team
        opp_full_name = nba_abbrev_to_name.get(opponent_abbrev, '')
        pace_reference_date = as_of_date if as_of_date else datetime.today()
        opp_pace = opp_pace_override if opp_pace_override else (
            get_bdl_matchup_pace(team_full_name, opp_full_name, bdl_season, pace_reference_date) if opp_full_name else league_avg_pace
        )
        opp_ast_allowed = 25.0
        opp_ast_adj = 0

        df['was_home'] = df['home_team_id'] == df['team_id']
        home_games = df[df['was_home'] == True]
        away_games = df[df['was_home'] == False]
        # Location now uses assist RATE difference, not raw APG (July 2026
        # review) — raw home/away APG reflects both assist rate AND
        # minutes played at home/away, and since expected minutes are
        # already modeled separately in the core formula, using raw APG
        # here would reintroduce the exact minutes double-counting that
        # was just removed from the base calculation. Actual point value
        # is computed later once final_expected_minutes_raw exists.
        relevant_games = home_games if home_or_away == 'home' else away_games
        relevant_min_sum = relevant_games['minutes_played'].sum()
        location_ast_rate = (relevant_games['assists'].sum() / relevant_min_sum) if relevant_min_sum > 0 else projected_ast_per_min
        location_rate_difference = location_ast_rate - season_ast_per_min
        location_games = len(relevant_games)
        location_shrinkage = min(1.0, location_games / 20)

        # Role-sensitive minutes weighting — same reasoning as the Points
        # engine: a rock-stable role should trust the longer season sample
        # more, while a recently-changing role should trust recent games
        # more, instead of always using a fixed 30/30/40 split regardless
        # (July 2026 review).
        if min_cv < 0.12:
            expected_minutes_raw = (season_mpg * 0.45) + (last10_min * 0.35) + (last5_min * 0.20)
        elif min_cv < 0.25:
            expected_minutes_raw = (season_mpg * 0.30) + (last10_min * 0.35) + (last5_min * 0.35)
        else:
            expected_minutes_raw = (season_mpg * 0.15) + (last10_min * 0.30) + (last5_min * 0.55)

        role_change_ratio = (last5_min / season_mpg) if season_mpg > 0 else 1.0
        if role_change_ratio >= 1.25:
            role_status = "📈 Recently Expanded"
        elif role_change_ratio <= 0.75:
            role_status = "📉 Recently Reduced"
        else:
            role_status = "➡️ Stable"

        # Rest days — same boundary-bug fix as the Points engine (see its
        # comment for the full explanation).
        reference_date = as_of_date if as_of_date else datetime.today()
        last_game_date = df['game_date'].iloc[-1].to_pydatetime() if not df.empty else None
        date_gap = (pd.Timestamp(reference_date).normalize() - pd.Timestamp(last_game_date).normalize()).days if last_game_date else 2
        days_rest = max(0, date_gap - 1)
        if date_gap == 1:
            rest_adj = -0.5  # true back-to-back
        elif date_gap >= 4:
            rest_adj = 0.3
        else:
            rest_adj = 0.0

        game_total = spread = None
        if game_total_override is not None or spread_override is not None:
            game_total, spread = game_total_override, spread_override
        elif as_of_date is None:  # live use only — see Points engine's comment
            try:
                games_data = get_live_nba_odds()
                game_total, spread = find_game_odds(games_data, home_team, away_team)
            except Exception as e:
                log_failure_reason('UNAVAILABLE_ODDS', f"NBA assists live odds ({home_team} vs {away_team}): {e}")

        # Blowout minutes impact now scales with role, matching the Points
        # engine — a flat -4 for everyone regardless of role didn't account
        # for bench players often GAINING garbage-time minutes in a
        # blowout while starters lose 4th-quarter run (July 2026 review).
        blowout_minutes_adj = 0
        if spread is not None and abs(spread) >= 9:
            if expected_minutes_raw >= 32:
                blowout_multiplier = 1.0
            elif expected_minutes_raw >= 24:
                blowout_multiplier = 0.5
            else:
                blowout_multiplier = -0.25  # some bench players gain time
            base_blowout_adj = -4 if abs(spread) >= 12 else -2
            blowout_minutes_adj = round(base_blowout_adj * blowout_multiplier, 1)

        # Final minutes -> final base, same order-of-operations fix as the
        # Points engine: minutes are finalized FIRST (including blowout),
        # then the assists projection is built from that single, coherent
        # number — instead of building from pre-blowout minutes and
        # patching with a separate minutes_ast_adj afterward.
        final_expected_minutes_raw = max(0.0, expected_minutes_raw + blowout_minutes_adj)
        final_expected_minutes = round(final_expected_minutes_raw, 1)
        base = final_expected_minutes_raw * projected_ast_per_min

        # Location adjustment finalized here now that final minutes exist —
        # shrunk toward zero for a small home/away sample (July 2026
        # review), same reasoning as the Points engine's location
        # shrinkage. Capped tighter than before (+-0.5 vs the old +-1.5),
        # since a home/away split this large was never realistic for an
        # assist prop specifically.
        raw_location_adj = final_expected_minutes_raw * location_rate_difference
        location_adj = max(-0.5, min(0.5, round(raw_location_adj * location_shrinkage, 2)))

        # Pace is multiplicative on the base, not flat additive — see
        # Points engine's comment for the full explanation. Dampened at a
        # smaller percentage here to roughly preserve pace's original,
        # smaller relative weight on assists vs. points.
        pace_factor = 1 + ((opp_pace / league_avg_pace) - 1) * 0.35
        base_before_pace = base
        base = base * pace_factor
        pace_adj = round(base - base_before_pace, 2)

        # Game total is now multiplicative too, not flat additive (July
        # 2026 review) — the old version added the same absolute value to
        # a 2.5-assist bench player and a 10-assist primary creator, which
        # doesn't reflect how possessions actually scale. A higher-total
        # game means more possessions for everyone, proportionally, not
        # the same flat assist bump regardless of role.
        total_factor = 1.0
        if game_total is not None:
            total_factor = 1 + ((game_total / 225) - 1) * 0.25
        base_before_total = base
        base = base * total_factor
        total_adj = round(base - base_before_total, 2)

        # Fixed a real bug (July 2026 review): ast_pct was a static 0.15
        # placeholder, so ast_pct_adj = (0.15 - 0.25) * 6 = -0.60 for
        # EVERY single projection, always, regardless of the player — not
        # a limitation, a straightforward bug quietly subtracting 0.6
        # assists from every projection. Zeroed out until real assist
        # percentage data exists.
        ast_pct_adj = 0.0

        raw_adjustment = max(-3.0, min(3.0, location_adj + rest_adj + ast_pct_adj + opp_ast_adj + potential_ast_adj))
        final_projection = max(0, round(base + raw_adjustment, 1))

        confidence_score = 100.0
        confidence_score -= min(30, cv * 45)
        confidence_score -= min(35, min_cv * 100)
        if len(df) < 10:
            confidence_score -= 10
        if final_expected_minutes < 18:
            confidence_score -= 10
        confidence_score = round(max(0, min(100, confidence_score)), 1)

        return {
            'projection': final_projection, 'base': round(base, 2),
            'season_apg': season_apg, 'last5_avg': last5_avg, 'last10_avg': last10_avg,
            'last10_ast_std': last10_ast_std, 'season_mpg': season_mpg,
            'expected_minutes': final_expected_minutes, 'blowout_minutes_adj': blowout_minutes_adj,
            'projected_ast_per_min': round(projected_ast_per_min, 3),
            'usage_rate': usage_rate, 'usage_data_status': usage_data_status,
            'ast_pct': ast_pct, 'ast_pct_adj': ast_pct_adj,
            'tov_factor': tov_factor, 'potential_assists': potential_assists,
            'potential_ast_adj': potential_ast_adj, 'opp_pace': opp_pace,
            'location_adj': location_adj, 'rest_adj': rest_adj,
            'pace_adj': pace_adj, 'opp_ast_adj': opp_ast_adj, 'opp_ast_allowed': opp_ast_allowed,
            'total_adj': total_adj, 'raw_adjustment': round(raw_adjustment, 2),
            'game_total': game_total, 'spread': spread, 'cv': cv,
            'confidence_tier': confidence_tier, 'days_rest': days_rest,
            'min_cv': min_cv, 'workload_tier': workload_tier, 'role_status': role_status,
            'scoring_volatility_tier': scoring_volatility_tier, 'workload_reliability_tier': workload_reliability_tier,
            'confidence_score': confidence_score,
            'injury_status': injury_status, 'injury_description': injury_description,
            'injury_pass_recommended': injury_pass_recommended,
        }
    except Exception as e:
        if st.session_state.get("_nba_debug_mode"): raise
        return None

def nba_bet_sport_label(sport_key):
    """Maps the internal NBA projection sport_key ('nba_points'/'nba_assists')
    to the sport label used consistently across bets/predictions ('NBA'/'NBA_AST')."""
    return 'NBA' if sport_key == 'nba_points' else 'NBA_AST'

# ============================================================
# NFL DATA LAYER — built on nflreadpy (nflverse), confirmed working
# (July 2026). nfl_data_py, an older similarly-named package, is
# officially deprecated by nflverse — its hardcoded data URLs are
# permanently stale. All 4 core functions confirmed live in the
# deployed app: load_player_stats, load_pbp, load_schedules,
# load_injuries.
# ============================================================

@st.cache_data(ttl=86400)
def get_nfl_player_stats(seasons):
    """Weekly player stats — confirmed columns include attempts,
    completions, receptions, targets, target_share, passing_cpoe,
    wopr, air_yards_share, sacks_suffered, and more. This is the core
    box-score input for all three NFL models.

    Real fix (August 2026): if the current season's data isn't
    available yet (nflverse hasn't published it — common in preseason
    before regular-season games are played), falls back to the
    previous season so the pipeline doesn't crash."""
    import nflreadpy as nfl
    try:
        return nfl.load_player_stats(seasons).to_pandas()
    except (ConnectionError, Exception) as e:
        # If we're requesting a single season and it fails, try
        # the previous season as a fallback
        if len(seasons) == 1 and seasons[0] > 2020:
            fallback_seasons = [seasons[0] - 1]
            try:
                return nfl.load_player_stats(fallback_seasons).to_pandas()
            except Exception:
                raise e  # re-raise original if fallback also fails
        raise

@st.cache_data(ttl=86400)
def get_nfl_pbp(seasons):
    """Play-by-play data — confirmed 396 total columns available, but we
    only ever need ~10 of them (pass_attempt, rush_attempt, xpass,
    pass_oe, posteam, defteam, game_id, season, week, play_type). Slimming
    down to just those BEFORE caching (instead of caching the full
    396-column dataframe) is the fix for a real Railway out-of-memory
    crash — the full dataframe for a season is genuinely large enough to
    exceed a standard instance's memory limit, especially once cached
    (July 2026)."""
    import nflreadpy as nfl
    needed_cols = ['pass_attempt', 'rush_attempt', 'xpass', 'pass_oe', 'posteam', 'defteam',
                   'game_id', 'season', 'week', 'play_type', 'pass', 'down',
                   'complete_pass', 'incomplete_pass', 'passer_player_name', 'passer_player_id',
                   'wp', 'score_differential']
    try:
        full_df = nfl.load_pbp(seasons).to_pandas()
    except (ConnectionError, Exception) as e:
        if len(seasons) == 1 and seasons[0] > 2020:
            try:
                full_df = nfl.load_pbp([seasons[0] - 1]).to_pandas()
            except Exception:
                raise e
        else:
            raise
    available_cols = [c for c in needed_cols if c in full_df.columns]
    return full_df[available_cols].copy()

@st.cache_data(ttl=86400)
def get_nfl_schedules(seasons):
    """Game schedules — confirmed columns include spread_line,
    total_line, moneylines, over/under odds, home_qb_id/away_qb_id
    (confirmed starters per game), home_rest/away_rest, roof, surface,
    temp, wind. A genuinely rich single source covering most of the
    Game Environment category and real historical odds."""
    import nflreadpy as nfl
    try:
        return nfl.load_schedules(seasons).to_pandas()
    except (ConnectionError, Exception) as e:
        if len(seasons) == 1 and seasons[0] > 2020:
            try:
                return nfl.load_schedules([seasons[0] - 1]).to_pandas()
            except Exception:
                raise e
        raise

@st.cache_data(ttl=3600)
def get_nfl_injuries(seasons):
    """Weekly injury reports — confirmed columns include report_status
    (Out/Doubtful/Questionable) and practice_status (a leading
    indicator of how a questionable tag is likely to resolve).
    Shorter cache than the others since injury status changes
    frequently during the week."""
    import nflreadpy as nfl
    return nfl.load_injuries(seasons).to_pandas()

@st.cache_data(ttl=86400)
def get_nfl_team_game_pace_proe(seasons):
    """Team-level pace (plays/game) and PROE (Pass Rate Over Expected),
    derived from play-by-play data since neither is available as a
    single ready-made stat anywhere else. Computed once per team-game
    (identified by posteam + game_id) and cached — this is genuinely
    the most expensive computation in the NFL pipeline, since it
    requires the full play-by-play download.

    PROE = actual team pass rate - average xpass for that team-game,
    restricted to real offensive plays (pass_attempt or rush_attempt),
    matching the standard, published definition of PROE.

    Uses 'pass' (every called pass play, including ones that end in a
    sack) rather than 'pass_attempt' (official attempts only) for the
    tendency/PROE calculation specifically (July 2026 review) — a called
    pass that ends in a sack is still real evidence of play-calling
    intent, and excluding it can make a high-sack team look artificially
    run-heavy when it isn't. Official pass_attempts stays separately
    available (as pass_attempts_official) for anything that needs the
    real attempts count specifically, like the opponent's attempts-faced
    signal."""
    pbp = get_nfl_pbp(seasons)
    if 'posteam' not in pbp.columns or 'game_id' not in pbp.columns:
        return pd.DataFrame()
    # Fixed the real, incomplete version of the sack fix (July 2026
    # review): pass_plays correctly summed the 'pass' column already, but
    # the FILTER building offensive_plays still only kept rows where
    # pass_attempt==1 or rush_attempt==1 — and a sack has pass_attempt=0,
    # rush_attempt=0, pass=1. That meant every sack was excluded from the
    # sample before the groupby ever ran, regardless of which column got
    # summed afterward. Now filters on 'pass' OR rush_attempt instead.
    pass_col = 'pass' if 'pass' in pbp.columns else 'pass_attempt'
    offensive_plays = pbp[(pbp.get(pass_col, 0) == 1) | (pbp.get('rush_attempt', 0) == 1)].copy()
    if offensive_plays.empty:
        return pd.DataFrame()
    grouped = offensive_plays.groupby(['posteam', 'game_id', 'season', 'week'], as_index=False).agg(
        total_plays=(pass_col, 'size'),
        pass_plays=(pass_col, 'sum'),
        pass_attempts_official=('pass_attempt', 'sum'),
        avg_xpass=('xpass', 'mean') if 'xpass' in offensive_plays.columns else (pass_col, 'mean'),
    )
    grouped['actual_pass_rate'] = grouped['pass_plays'] / grouped['total_plays']
    grouped['proe'] = grouped['actual_pass_rate'] - grouped['avg_xpass']
    return grouped.rename(columns={'posteam': 'team'})

@st.cache_data(ttl=86400)
def get_nfl_defense_game_stats(seasons):
    """Defense-side equivalent of get_nfl_team_game_pace_proe() — plays
    allowed, pass plays allowed, and PROE allowed, aggregated once per
    team-game (by defteam + game_id) and cached (July 2026 review, round
    7). Built to fix a real memory crash: get_opponent_pass_funnel_factor
    used to call get_nfl_pbp() directly and filter the FULL raw play-by-
    play every time it needed an opponent's profile — and once the
    prior-season fallback was added, that meant potentially holding TWO
    full seasons of raw play-by-play in memory simultaneously during a
    full-season, many-QB backtest (the exact same failure mode as the
    original Railway out-of-memory incident, just triggered by the new
    fallback code instead of the original live-card build). This
    aggregate is computed ONCE per season and is a small fraction of the
    raw data's size, matching the same pattern already proven to work
    well for the offensive side."""
    pbp = get_nfl_pbp(seasons)
    if 'defteam' not in pbp.columns or 'game_id' not in pbp.columns:
        return pd.DataFrame()
    pass_col = 'pass' if 'pass' in pbp.columns else 'pass_attempt'
    defensive_plays = pbp[(pbp.get(pass_col, 0) == 1) | (pbp.get('rush_attempt', 0) == 1)].copy()
    if defensive_plays.empty:
        return pd.DataFrame()
    grouped = defensive_plays.groupby(['defteam', 'game_id', 'season', 'week'], as_index=False).agg(
        total_plays_faced=(pass_col, 'size'),
        pass_plays_faced=(pass_col, 'sum'),
        pass_attempts_faced=('pass_attempt', 'sum'),
        avg_xpass_faced=('xpass', 'mean') if 'xpass' in defensive_plays.columns else (pass_col, 'mean'),
    )
    grouped['proe_allowed'] = (grouped['pass_plays_faced'] / grouped['total_plays_faced']) - grouped['avg_xpass_faced']
    return grouped.rename(columns={'defteam': 'team'})

@st.cache_data(ttl=86400)
def get_nfl_defense_completion_stats(seasons):
    """Defense-side completion stats — attempts faced and completions
    allowed, aggregated once per team-game (by defteam + game_id) and
    cached. Built for the Pass Completions model (July 2026), matching
    the exact same caching pattern as get_nfl_defense_game_stats (built
    for Pass Attempts) — applying that memory lesson from the start this
    time instead of discovering it via a real crash again."""
    pbp = get_nfl_pbp(seasons)
    if 'defteam' not in pbp.columns or 'game_id' not in pbp.columns or 'pass_attempt' not in pbp.columns:
        return pd.DataFrame()
    pass_plays = pbp[pbp['pass_attempt'] == 1].copy()
    if pass_plays.empty:
        return pd.DataFrame()
    agg_dict = {'attempts_faced': ('pass_attempt', 'sum')}
    if 'complete_pass' in pass_plays.columns:
        agg_dict['completions_allowed'] = ('complete_pass', 'sum')
    grouped = pass_plays.groupby(['defteam', 'game_id', 'season', 'week'], as_index=False).agg(**agg_dict)
    if 'completions_allowed' in grouped.columns:
        grouped['completion_pct_allowed'] = grouped['completions_allowed'] / grouped['attempts_faced']
    else:
        grouped['completion_pct_allowed'] = None
    return grouped.rename(columns={'defteam': 'team'})

@st.cache_data(ttl=86400)
def get_nfl_schedule_adjusted_defense(seasons):
    """For each team-game, links the offense's actual pass rate that game
    to who they played (the defense) — the building block for a
    schedule-adjusted defensive signal (July 2026, round 12). The raw
    opponent pass-funnel signal (pass attempts faced) can mislead: a
    defense that happened to face several pass-heavy offenses by
    schedule luck looks like a real pass funnel even if their true
    defensive tendency is neutral. This isolates the real effect instead:
    how much did each offense DEVIATE from their own normal pass rate
    specifically when facing this defense."""
    team_games = get_nfl_team_game_pace_proe(seasons)
    if team_games.empty:
        return pd.DataFrame()
    game_teams = team_games.groupby('game_id')['team'].apply(list).to_dict()
    rows = []
    for _, row in team_games.iterrows():
        teams_in_game = game_teams.get(row['game_id'], [])
        opponent = [t for t in teams_in_game if t != row['team']]
        if not opponent:
            continue
        rows.append({
            'offense_team': row['team'], 'defense_team': opponent[0],
            'game_id': row['game_id'], 'week': row['week'], 'season': row['season'],
            'actual_pass_rate': row['actual_pass_rate'],
        })
    return pd.DataFrame(rows)

def get_schedule_adjusted_opponent_factor(season, opponent, as_of_week=None):
    """Schedule-adjusted opponent pass-funnel signal (July 2026, round
    12) — instead of raw pass attempts faced, measures how much each
    offense deviated from their OWN normal season pass rate specifically
    against this defense, averaged across the defense's real games. A
    genuinely different signal from the existing opponent blend, not
    just a re-weighting of the same inputs. Falls back to the prior
    season if the current season's sample is too thin, same pattern as
    the other opponent/pace functions. Returns a percentage-point
    deviation (positive = this defense forces more passing than normal,
    negative = less), or None if there's not enough data."""
    def _compute(stats_season, week_filter):
        try:
            adj_data = get_nfl_schedule_adjusted_defense([int(stats_season)])
            if adj_data.empty:
                return None
            filtered = adj_data[adj_data['week'] < week_filter] if week_filter is not None else adj_data
            if filtered.empty:
                return None
            offense_normals = filtered.groupby('offense_team')['actual_pass_rate'].mean().to_dict()
            defense_games = filtered[filtered['defense_team'] == opponent]
            if len(defense_games) < 3:
                return None
            deviations = []
            for _, g in defense_games.iterrows():
                offense_normal = offense_normals.get(g['offense_team'])
                if offense_normal is not None:
                    deviations.append(g['actual_pass_rate'] - offense_normal)
            if not deviations:
                return None
            return (sum(deviations) / len(deviations)) * 100
        except Exception:
            return None

    if as_of_week is not None and as_of_week <= 6:
        return _compute(int(season) - 1, None)
    current = _compute(season, as_of_week)
    if current is not None:
        return current
    return _compute(int(season) - 1, None)

# ---- CLOSING LINE / CLV TRACKING ----
def get_odds_api_sport_and_market(sport):
    # Real bug fix (July 2026, per external review) — this function had
    # NO branches at all for any NFL sport label, meaning the Closing
    # Line Tracker silently failed for every NFL bet (Attempts,
    # Completions, Receptions) — always falling through to (None, None)
    # with no error, no warning, nothing. Exactly the kind of silent
    # miss the reviewer's point about centralizing sport labels was
    # warning against, just found here as a genuinely missing branch
    # rather than a typo in an existing one.
    if sport == 'MLB':
        return 'baseball_mlb', 'pitcher_strikeouts'
    elif sport == 'NBA':
        return 'basketball_nba', 'player_points'
    elif sport == 'NBA_AST':
        return 'basketball_nba', 'player_assists'
    elif sport == 'NFL':
        return 'americanfootball_nfl', 'player_pass_attempts'
    elif sport == 'NFL_COMPLETIONS':
        return 'americanfootball_nfl', 'player_pass_completions'
    elif sport == 'NFL_RECEPTIONS':
        return 'americanfootball_nfl', 'player_receptions'
    return None, None

@st.cache_data(ttl=604800)
def get_historical_events_cached(api_sport, snapshot_time):
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/historical/sports/{api_sport}/events",
            params={'apiKey': ODDS_API_KEY, 'date': snapshot_time}, timeout=20
        )
        r.raise_for_status()
        resp = r.json()
        return resp.get('data', [])
    except Exception as e:
        # Real error surfacing (July 2026) — this was a bare `except:`
        # silently swallowing EVERYTHING (auth failures, network errors,
        # rate limits, malformed responses) and just returning an empty
        # list, with no way to tell WHY. That's exactly what was hiding
        # a real, diagnosable problem behind a confusing "0 events, 0
        # credits used" symptom. Now captures the real status
        # code/message for inspection.
        status_code = getattr(getattr(e, 'response', None), 'status_code', None)
        st.session_state.setdefault('_historical_odds_errors', []).append(
            {'call': 'events', 'sport': api_sport, 'snapshot': snapshot_time, 'status_code': status_code, 'error': str(e)}
        )
        return []

@st.cache_data(ttl=604800)
def get_historical_event_odds_cached(api_sport, event_id, market, commence_time):
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/historical/sports/{api_sport}/events/{event_id}/odds",
            params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': market, 'oddsFormat': 'american', 'date': commence_time}, timeout=20
        )
        r.raise_for_status()
        resp = r.json()
        return resp.get('data', {}) or {}
    except Exception as e:
        status_code = getattr(getattr(e, 'response', None), 'status_code', None)
        st.session_state.setdefault('_historical_odds_errors', []).append(
            {'call': 'event_odds', 'sport': api_sport, 'event_id': event_id, 'market': market, 'status_code': status_code, 'error': str(e)}
        )
        return {}

def fetch_closing_line(sport, player_name, direction, game_date_str):
    """Finds the closing (last available pre-game) line AND odds for a player prop,
    filtered to the specific Over/Under side the bet was placed on (line CLV and
    odds CLV are different things — a book can move the number, the price, or both).
    Caches events-per-day and odds-per-event so multiple bets on the same
    date/sport reuse the same API calls instead of re-fetching.
    Returns (closing_line, closing_odds), either of which may be None if not found."""
    api_sport, market = get_odds_api_sport_and_market(sport)
    if not api_sport:
        return None, None
    try:
        snapshot_time = f"{game_date_str}T12:00:00Z"
        events = get_historical_events_cached(api_sport, snapshot_time)
        for event in events:
            commence_time = event['commence_time']
            event_id = event['id']
            data = get_historical_event_odds_cached(api_sport, event_id, market, commence_time)
            points = []
            for bookmaker in data.get('bookmakers', []):
                for mkt in bookmaker.get('markets', []):
                    if mkt['key'] == market:
                        for outcome in mkt['outcomes']:
                            if (outcome.get('description', '').lower() == player_name.lower()
                                    and outcome.get('name', '').lower() == direction.lower()):
                                points.append({'line': outcome['point'], 'odds': outcome['price']})
            if points:
                line_counts = Counter(p['line'] for p in points)
                consensus_line = line_counts.most_common(1)[0][0]
                matching_points = [p for p in points if p['line'] == consensus_line]
                avg_prob = sum(odds_to_implied_prob(p['odds']) for p in matching_points) / len(matching_points)
                avg_odds = prob_to_american_odds(avg_prob)
                return consensus_line, avg_odds
        return None, None
    except Exception as e:
        log_failure_reason('MALFORMED_RESPONSE', f"closing line for {player_name}: {e}")
        return None, None

# Real fix (August 2026) — was completely uncached: every single
# visitor's session hit the live Odds API fresh, every time, even
# though "today's MLB props" genuinely don't change second-to-second.
# Real precedent already established elsewhere in this exact app —
# load_nfl_props_data() already uses this same 5-minute TTL despite
# having the same real "filter out already-started games" logic
# inside it (computed fresh at cache-write time) — 5 minutes is short
# enough that a game starting mid-cache-window is a real, small,
# already-accepted staleness window, not a new risk.
@st.cache_data(ttl=300, show_spinner=False)
def load_mlb_props_data():
    """Fetches today's MLB pitcher-strikeout props from FanDuel/DraftKings.
    Returns an all_pitchers dict (empty on failure) — same shape used throughout the app.
    Skips any game whose commence_time has already passed — a game already
    in progress would otherwise keep showing the same pre-game projection
    all day, paired against odds that DO shift with the live game state,
    creating genuinely inconsistent-looking props (caught in review, July
    2026)."""
    try:
        events_data = get_json("https://api.the-odds-api.com/v4/sports/baseball_mlb/events",
            params={'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'})
        all_pitchers = {}
        now_utc = datetime.now(ZoneInfo("UTC"))

        for event in events_data:
            commence_time_str = event.get('commence_time')
            if commence_time_str:
                try:
                    commence_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    if commence_time <= now_utc:
                        continue  # game has already started — a pre-game projection is stale, not just less accurate
                except (ValueError, TypeError):
                    pass  # if the timestamp can't be parsed, don't block the whole event over it

            home = event['home_team']
            away = event['away_team']
            event_id = event['id']
            # Real addition (August 2026, per direct user request — "a
            # spot to choose which book line im taking... sometimes I
            # like to bet both"). Real, separate market key from The
            # Odds API — 'pitcher_strikeouts_alternate' carries every
            # additional real line a book offers beyond just the one
            # main line, completely distinct data from
            # 'pitcher_strikeouts' itself. Requesting both in the SAME
            # real API call (comma-separated) costs no extra real
            # request against the real API quota.
            props_data = get_json(
                f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds",
                params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'pitcher_strikeouts,pitcher_strikeouts_alternate', 'oddsFormat': 'american'}
            )

            for bookmaker in props_data.get('bookmakers', []):
                book_title = bookmaker.get('title', bookmaker.get('key', ''))
                is_primary = bookmaker['key'] in ['fanduel', 'draftkings']
                book_key = None
                if 'FanDuel' in book_title or bookmaker['key'] == 'fanduel':
                    book_key = 'FanDuel'
                elif 'DraftKings' in book_title or bookmaker['key'] == 'draftkings':
                    book_key = 'DraftKings'

                for market in bookmaker.get('markets', []):
                    if market['key'] == 'pitcher_strikeouts':
                        for outcome in market['outcomes']:
                            pitcher = outcome['description']
                            if pitcher not in all_pitchers:
                                all_pitchers[pitcher] = {
                                    'home': home, 'away': away, 'commence_time': commence_time_str,
                                    'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                    'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                    'Alt Lines': {'FanDuel': {}, 'DraftKings': {}},
                                    'Projection': None, 'Edge': None, 'Play': None,
                                    'Tier': None,
                                    'EV%': None, 'MM Tier': None,
                                    'Model Prob': None, 'No Vig Prob': None,
                                    'Model Edge': None, 'Odds': None, 'Direction': None,
                                    'Fair Odds': None, 'Edge Cents': None, 'Low Confidence': None,
                                    '_book_odds_raw': {},
                                    'odds_api_event_id': event_id,
                                    'odds_api_sport': 'baseball_mlb',
                                    'odds_api_market': 'pitcher_strikeouts',
                                }
                            # Primary FD/DK extraction (unchanged)
                            if is_primary and book_key:
                                if book_key == 'FanDuel':
                                    all_pitchers[pitcher]['FanDuel Line'] = outcome['point']
                                    if outcome['name'] == 'Over':
                                        all_pitchers[pitcher]['FanDuel Over'] = outcome['price']
                                    else:
                                        all_pitchers[pitcher]['FanDuel Under'] = outcome['price']
                                else:
                                    all_pitchers[pitcher]['DraftKings Line'] = outcome['point']
                                    if outcome['name'] == 'Over':
                                        all_pitchers[pitcher]['DraftKings Over'] = outcome['price']
                                    else:
                                        all_pitchers[pitcher]['DraftKings Under'] = outcome['price']
                            # Capture ALL books into _book_odds_raw
                            bor = all_pitchers[pitcher].setdefault('_book_odds_raw', {})
                            if book_title not in bor:
                                bor[book_title] = {'book': book_title, 'line': outcome.get('point'), 'over': None, 'under': None}
                            if outcome['name'] == 'Over':
                                bor[book_title]['over'] = outcome['price']
                            else:
                                bor[book_title]['under'] = outcome['price']
                            bor[book_title]['line'] = outcome.get('point')
                    if market['key'] == 'pitcher_strikeouts_alternate' and book_key:
                            # Real, separate handling — every real
                            # alternate line gets its own real dict
                            # entry keyed by its own real point value,
                            # never overwriting another real line the
                            # way the main-line loop above correctly
                            # does for the single main line.
                            # Guard: book_key is only set for FanDuel/
                            # DraftKings — Alt Lines only has those two
                            # keys, so a non-FD/DK bookmaker here would
                            # KeyError on Alt Lines[None] and silently
                            # kill the entire MLB pipeline (caught
                            # August 2026).
                            for outcome in market['outcomes']:
                                pitcher = outcome['description']
                                if pitcher not in all_pitchers:
                                    all_pitchers[pitcher] = {
                                        'home': home, 'away': away, 'commence_time': commence_time_str,
                                        'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                        'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                        'Alt Lines': {'FanDuel': {}, 'DraftKings': {}},
                                        'Projection': None, 'Edge': None, 'Play': None,
                                        'Tier': None,
                                        'EV%': None, 'MM Tier': None,
                                        'Model Prob': None, 'No Vig Prob': None,
                                        'Model Edge': None, 'Odds': None, 'Direction': None,
                                        'Fair Odds': None, 'Edge Cents': None, 'Low Confidence': None,
                                        '_book_odds_raw': {},
                                        'odds_api_event_id': event_id,
                                        'odds_api_sport': 'baseball_mlb',
                                        'odds_api_market': 'pitcher_strikeouts',
                                    }
                                point = outcome['point']
                                alt_lines = all_pitchers[pitcher]['Alt Lines'][book_key]
                                if point not in alt_lines:
                                    alt_lines[point] = {'over': None, 'under': None}
                                if outcome['name'] == 'Over':
                                    alt_lines[point]['over'] = outcome['price']
                                else:
                                    alt_lines[point]['under'] = outcome['price']
        # Convert _book_odds_raw dicts to clean book_odds lists
        for pitcher in all_pitchers.values():
            raw = pitcher.pop('_book_odds_raw', {})
            pitcher['book_odds'] = sorted(raw.values(), key=lambda b: b.get('book', ''))
        return all_pitchers
    except Exception:
        return {}

def run_all_mlb_projections(all_pitchers, season, progress_callback=None):
    """Runs the projection + EV pipeline for every pitcher in all_pitchers (mutated in place),
    saves each as a prediction, and returns the pitcher_results dict.
    progress_callback(i, total, name), if given, is called before each pitcher runs —
    lets callers render their own progress bar (MLB page) or run silently (Today's Card).

    August 2026 — LINE SHOPPING: analyzes every book's line/odds separately
    and picks the one with the highest EV%. Falls back to FanDuel/DraftKings
    if book_odds is empty (shouldn't happen, but safe fallback)."""
    pitcher_results = {}
    total = len(all_pitchers)
    for i, (pitcher, info) in enumerate(all_pitchers.items()):
        if progress_callback:
            progress_callback(i, total, pitcher)

        _, opp, h = get_pitcher_game_info(pitcher)
        if not opp:
            opp = info['away']
            h = info['home']

        result = cached_run_projection(pitcher, opp, h, season, mm_today_str())

        if result:
            proj = result['projection']

            # ── LINE SHOPPING: analyze every book's line ──
            book_odds_list = info.get('book_odds', [])
            best_play = find_best_book_line(
                book_odds_list, proj,
                std_dev=result['last10_k_std'], cv=result['cv'],
                sport='mlb_strikeouts',
                workload_tier=result.get('workload_tier'),
                confidence_tier=result.get('confidence_tier')
            )

            # Fallback to old FD/DK logic if line shopping found nothing
            if best_play:
                best_line = best_play['best_line']
                direction = best_play['best_direction']
                over_odds = best_play['best_over_odds']
                under_odds = best_play['best_under_odds']
                ev_result = best_play['best_ev_result']
                best_book = best_play['best_book']
                all_book_results = best_play['all_book_results']
            else:
                best_line = info['FanDuel Line'] or info['DraftKings Line']
                if not best_line:
                    continue
                edge_val = round(proj - best_line, 1)
                direction = 'over' if edge_val > 0 else 'under'
                over_odds = info['FanDuel Over'] or info['DraftKings Over']
                under_odds = info['FanDuel Under'] or info['DraftKings Under']
                ev_result = analyze_prop(
                    projection=proj, line=best_line,
                    std_dev=result['last10_k_std'], cv=result['cv'],
                    over_odds=over_odds or -110, under_odds=under_odds or -110,
                    direction=direction, sport='mlb_strikeouts',
                    workload_tier=result.get('workload_tier'),
                    confidence_tier=result.get('confidence_tier')
                )
                best_book = None
                all_book_results = []

            if best_line and ev_result:
                edge = round(proj - best_line, 1)
                play = "⬆️ OVER" if direction == 'over' else "⬇️ UNDER"

                all_pitchers[pitcher].update({
                    'Projection': proj, 'Edge': edge, 'Play': play,
                    'Tier': result['confidence_tier'],
                    'EV%': ev_result['ev_pct'] if ev_result else None,
                    'Raw EV%': ev_result['raw_ev_pct'] if ev_result else None,
                    'MM Tier': ev_result['tier'] if ev_result else None,
                    'Pass Reason': ev_result['pass_reason'] if ev_result else None,
                    'Confidence Level': ev_result['confidence_level'] if ev_result else None,
                    'Model Prob': ev_result['model_prob'] if ev_result else None,
                    'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
                    'Model Edge': ev_result['model_edge'] if ev_result else None,
                    'Odds': over_odds if direction == 'over' else under_odds,
                    'Direction': direction,
                    'Fair Odds': ev_result['fair_odds'] if ev_result else None,
                    'Effective Std': ev_result['effective_std'] if ev_result else None,
                    'Adjusted Projection': ev_result['adjusted_projection'] if ev_result else None,
                    'Opposite Odds': ev_result['opposite_odds'] if ev_result else None,
                    'Edge Cents': ev_result['edge_cents'] if ev_result else None,
                    'Low Confidence': ev_result['low_confidence'] if ev_result else None,
                    # LINE SHOPPING fields
                    'Best Book': best_book,
                    'Best Line': best_line,
                    'Alt Book Lines': [
                        {'book': r['book'], 'line': r['line'], 'direction': r['direction'],
                         'odds': r['odds'], 'ev_pct': r['ev_result']['ev_pct'],
                         'tier': r['ev_result']['tier']}
                        for r in all_book_results
                    ] if all_book_results else [],
                })
                pitcher_results[pitcher] = result

                # Alternate lines analysis (unchanged — still analyzes FD/DK alt lines)
                for book_key, lines in info['Alt Lines'].items():
                    for point, odds_pair in lines.items():
                        alt_over = odds_pair.get('over')
                        alt_under = odds_pair.get('under')
                        if alt_over is None and alt_under is None:
                            continue
                        alt_edge = round(proj - point, 1)
                        alt_direction = 'over' if alt_edge > 0 else 'under'
                        alt_ev_result = analyze_prop(
                            projection=proj, line=point,
                            std_dev=result['last10_k_std'], cv=result['cv'],
                            over_odds=alt_over or -110, under_odds=alt_under or -110,
                            direction=alt_direction, sport='mlb_strikeouts',
                            workload_tier=result.get('workload_tier'), confidence_tier=result.get('confidence_tier')
                        )
                        odds_pair['edge'] = alt_edge
                        odds_pair['direction'] = alt_direction
                        odds_pair['play'] = "⬆️ OVER" if alt_edge > 0 else "⬇️ UNDER"
                        odds_pair['ev_pct'] = alt_ev_result['ev_pct'] if alt_ev_result else None
                        odds_pair['mm_tier'] = alt_ev_result['tier'] if alt_ev_result else None
                        odds_pair['model_prob'] = alt_ev_result['model_prob'] if alt_ev_result else None
                        odds_pair['no_vig_prob'] = alt_ev_result['no_vig_prob'] if alt_ev_result else None

                save_prediction({
                    'date': mm_today_str(),
                    'pitcher': pitcher, 'opponent': opp, 'home_team': h,
                    'projection': proj, 'base': result['base'], 'book_line': best_line,
                    'edge': edge, 'opp_factor': result['opp_factor'],
                    'park_factor': result['park_factor'], 'umpire_factor': result['umpire_factor'],
                    'velo_factor': result['velo_factor'], 'total_factor': result['total_factor'],
                    'pitch_count_factor': result['pitch_count_factor'],
                    'lineup_factor': result['lineup_factor'],
                    'cv': result['cv'], 'confidence_tier': result['confidence_tier'],
                    'actual': None, 'sport': 'MLB',
                    'ev_pct': ev_result['ev_pct'] if ev_result else None,
                    'mm_tier': ev_result['tier'] if ev_result else None,
                    'model_prob': ev_result['model_prob'] if ev_result else None,
                    'no_vig_prob': ev_result['no_vig_prob'] if ev_result else None,
                    'model_edge': ev_result['model_edge'] if ev_result else None,
                    # NOTE: 'best_book' removed (Aug 2026) — the Supabase
                    # 'predictions' table doesn't have this column, which
                    # was throwing a PGRST204 error on every single save
                    # and flooding the page with st.error() banners. Best
                    # Book info already flows through card_entries/info
                    # dict fine without needing to persist here too.
                })
    return pitcher_results


def load_mlb_batter_hits_props_data():
    """Real, direct port of load_mlb_props_data()'s structure —
    fetches today's LIVE batter_hits props from the Odds API, same
    skip-already-started-games logic, same book_odds capture for line
    shopping. Returns an all_batters dict (empty on failure)."""
    try:
        events_data = get_json("https://api.the-odds-api.com/v4/sports/baseball_mlb/events",
            params={'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'})
        all_batters = {}
        now_utc = datetime.now(ZoneInfo("UTC"))

        for event in events_data:
            commence_time_str = event.get('commence_time')
            if commence_time_str:
                try:
                    commence_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    if commence_time <= now_utc:
                        continue
                except (ValueError, TypeError):
                    pass

            home = event['home_team']
            away = event['away_team']
            event_id = event['id']
            props_data = get_json(
                f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds",
                params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'batter_hits', 'oddsFormat': 'american'}
            )

            for bookmaker in props_data.get('bookmakers', []):
                book_title = bookmaker.get('title', bookmaker.get('key', ''))
                for market in bookmaker.get('markets', []):
                    if market['key'] != 'batter_hits':
                        continue
                    for outcome in market['outcomes']:
                        batter = outcome['description']
                        if batter not in all_batters:
                            all_batters[batter] = {
                                'home': home, 'away': away, 'commence_time': commence_time_str,
                                'Projection': None, 'Edge': None, 'Play': None,
                                'EV%': None, 'MM Tier': None,
                                'Model Prob': None, 'No Vig Prob': None,
                                'Model Edge': None, 'Odds': None, 'Direction': None,
                                '_book_odds_raw': {},
                                'odds_api_event_id': event_id,
                                'odds_api_sport': 'baseball_mlb',
                                'odds_api_market': 'batter_hits',
                            }
                        bor = all_batters[batter].setdefault('_book_odds_raw', {})
                        if book_title not in bor:
                            bor[book_title] = {'book': book_title, 'line': outcome.get('point'), 'over': None, 'under': None}
                        if outcome['name'] == 'Over':
                            bor[book_title]['over'] = outcome['price']
                        else:
                            bor[book_title]['under'] = outcome['price']
                        bor[book_title]['line'] = outcome.get('point')

        for batter in all_batters.values():
            raw = batter.pop('_book_odds_raw', {})
            batter['book_odds'] = sorted(raw.values(), key=lambda b: b.get('book', ''))
        return all_batters
    except Exception:
        return {}


def run_all_mlb_batter_hits_projections(all_batters, season, progress_callback=None):
    """Live pipeline for MLB Batter Hits — real matchup resolution
    (confirmed lineup or current-team fallback) + real leak-free
    projection + real line shopping across every book, same overall
    shape as run_all_mlb_projections for strikeouts. Tier thresholds
    (mlb_batter_hits branch in get_tier) reflect the validated,
    INVERTED profitable zone: 0-12% EV, not high EV."""
    batter_results = {}
    total = len(all_batters)
    today_str = mm_today_str()
    for i, (batter, info) in enumerate(all_batters.items()):
        if progress_callback:
            progress_callback(i, total, batter)

        team, opponent, home_team, away_team, is_home, opposing_pitcher = resolve_batter_matchup(batter, today_str)
        if not team or not opposing_pitcher:
            continue  # can't resolve today's real matchup yet (lineup not posted, no probable pitcher) — try again next cycle

        result = run_batter_hits_projection(batter, opposing_pitcher, home_team or info['home'], away_team or info['away'], season, before_date=today_str)
        if result is None:
            continue
        proj = result['projection']

        book_odds_list = info.get('book_odds', [])
        best_play = find_best_book_line(
            book_odds_list, proj, std_dev=result['std_dev'], cv=result['cv'],
            sport='mlb_batter_hits', workload_tier=None, confidence_tier=None
        )
        if not best_play:
            continue

        best_line = best_play['best_line']
        direction = best_play['best_direction']
        over_odds = best_play['best_over_odds']
        under_odds = best_play['best_under_odds']
        ev_result = best_play['best_ev_result']
        best_book = best_play['best_book']
        all_book_results = best_play['all_book_results']

        edge = round(proj - best_line, 2)
        play = "⬆️ OVER" if direction == 'over' else "⬇️ UNDER"

        all_batters[batter].update({
            'Projection': proj, 'Edge': edge, 'Play': play,
            'EV%': ev_result['ev_pct'] if ev_result else None,
            'MM Tier': ev_result['tier'] if ev_result else None,
            'Model Prob': ev_result['model_prob'] if ev_result else None,
            'Odds': over_odds if direction == 'over' else under_odds,
            'Direction': direction,
            'Best Book': best_book, 'Best Line': best_line,
            'Alt Book Lines': [
                {'book': r['book'], 'line': r['line'], 'direction': r['direction'],
                 'odds': r['odds'], 'ev_pct': r['ev_result']['ev_pct'], 'tier': r['ev_result']['tier']}
                for r in all_book_results
            ] if all_book_results else [],
            'Opposing Pitcher': opposing_pitcher, 'Team': team, 'Opponent': opponent,
        })
        batter_results[batter] = result

        save_prediction({
            'date': today_str, 'pitcher': batter, 'opponent': opponent, 'home_team': home_team or info['home'],
            'projection': proj, 'base': None, 'book_line': best_line,
            'edge': edge, 'opp_factor': result['opp_factor'],
            'park_factor': result['park_factor'], 'umpire_factor': None,
            'velo_factor': None, 'total_factor': None,
            'pitch_count_factor': None, 'lineup_factor': None,
            'cv': result['cv'], 'confidence_tier': None,
            'actual': None, 'sport': 'MLB_BATTER_HITS',
            'ev_pct': ev_result['ev_pct'] if ev_result else None,
            'mm_tier': ev_result['tier'] if ev_result else None,
            'model_prob': ev_result['model_prob'] if ev_result else None,
            'no_vig_prob': None, 'model_edge': edge,
        })
    return batter_results


# Real fix (August 2026) — same real reasoning as load_mlb_props_data()
# above: was completely uncached, now matches the same, already-proven
# 5-minute TTL. st.cache_data automatically keys this separately per
# real prop_market argument ('player_points' vs 'player_assists'), so
# NBA Points and NBA Assists each get their own real, independent
# cache entry — no special handling needed for that.
@st.cache_data(ttl=300, show_spinner=False)
def load_nba_props_data(prop_market):
    """Fetches today's NBA player props for the given market
    ('player_points' or 'player_assists'). Returns an all_players dict.

    Real fix (July 2026) — found via a direct audit after a live-game
    issue was caught in the new LoL model: NBA was the one sport
    missing the same real, already-proven live-game filter MLB and all
    three NFL models already had. Skips any event whose commence_time
    has already passed — a game already in progress would otherwise
    keep showing the same pre-game projection, paired against odds
    that DO shift with the live game state, creating genuinely
    inconsistent-looking props."""
    try:
        events_data = get_json("https://api.the-odds-api.com/v4/sports/basketball_nba/events",
            params={'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'})
        all_players = {}
        now_utc = datetime.now(ZoneInfo("UTC"))

        for event in events_data:
            commence_time_str = event.get('commence_time')
            if commence_time_str:
                try:
                    commence_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    if commence_time <= now_utc:
                        continue  # game has already started — a pre-game projection is stale, not just less accurate
                except (ValueError, TypeError):
                    pass  # if the timestamp can't be parsed, don't block the whole event over it

            home = event['home_team']
            away = event['away_team']
            event_id = event['id']
            props_data = get_json(
                f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds",
                params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': prop_market, 'oddsFormat': 'american'}
            )

            for bookmaker in props_data.get('bookmakers', []):
                book_title = bookmaker.get('title', bookmaker.get('key', ''))
                is_primary = bookmaker['key'] in ['fanduel', 'draftkings']

                for market in bookmaker.get('markets', []):
                    if market['key'] == prop_market:
                        for outcome in market['outcomes']:
                            player = outcome['description']
                            if player not in all_players:
                                all_players[player] = {
                                    'home': home, 'away': away, 'commence_time': commence_time_str,
                                    'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                    'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                    'Projection': None, 'Edge': None, 'Play': None,
                                    'Tier': None, 'EV%': None, 'MM Tier': None, 'Low Confidence': None,
                                    'Fair Odds': None, 'Edge Cents': None, 'Direction': None, 'Odds': None,
                                    'Model Prob': None, 'No Vig Prob': None,
                                    '_book_odds_raw': {},
                                    'odds_api_event_id': event_id,
                                    'odds_api_sport': 'basketball_nba',
                                    'odds_api_market': prop_market,
                                }
                            # Primary FD/DK extraction
                            if is_primary:
                                if 'FanDuel' in book_title or bookmaker['key'] == 'fanduel':
                                    all_players[player]['FanDuel Line'] = outcome['point']
                                    if outcome['name'] == 'Over':
                                        all_players[player]['FanDuel Over'] = outcome['price']
                                    else:
                                        all_players[player]['FanDuel Under'] = outcome['price']
                                elif 'DraftKings' in book_title or bookmaker['key'] == 'draftkings':
                                    all_players[player]['DraftKings Line'] = outcome['point']
                                    if outcome['name'] == 'Over':
                                        all_players[player]['DraftKings Over'] = outcome['price']
                                    else:
                                        all_players[player]['DraftKings Under'] = outcome['price']
                            # Capture ALL books
                            bor = all_players[player].setdefault('_book_odds_raw', {})
                            if book_title not in bor:
                                bor[book_title] = {'book': book_title, 'line': outcome.get('point'), 'over': None, 'under': None}
                            if outcome['name'] == 'Over':
                                bor[book_title]['over'] = outcome['price']
                            else:
                                bor[book_title]['under'] = outcome['price']
                            bor[book_title]['line'] = outcome.get('point')
        # Convert _book_odds_raw to clean book_odds lists
        for player in all_players.values():
            raw = player.pop('_book_odds_raw', {})
            player['book_odds'] = sorted(raw.values(), key=lambda b: b.get('book', ''))
        return all_players
    except Exception:
        return {}

def run_all_nba_projections(all_players, run_fn, sport_key, season, progress_callback=None):
    """Runs the projection + EV pipeline for every player in all_players (mutated in place),
    saves each as a prediction, and returns the results dict.
    progress_callback(i, total, name), if given, is called before each player runs.

    August 2026 — LINE SHOPPING: analyzes every book's line/odds separately
    and picks the one with the highest EV%. Falls back to FanDuel/DraftKings
    if book_odds is empty."""
    results = {}
    total = len(all_players)
    for i, (player, info) in enumerate(all_players.items()):
        if progress_callback:
            progress_callback(i, total, player)

        home_team = info['home']
        away_team = info['away']
        home_abbrev = nba_name_to_abbrev.get(home_team, '')
        away_abbrev = nba_name_to_abbrev.get(away_team, '')

        try:
            bdl_season = int(season.split("-")[0])
            check_df, _ = get_bdl_player_game_log(player, bdl_season)
            if check_df.empty:
                continue
            check_df['_game_date'] = pd.to_datetime(check_df['game'].apply(lambda g: (g or {}).get('date')))
            check_df = check_df.sort_values('_game_date')
            last_row = check_df.iloc[-1]
            game_info = last_row.get('game') or {}
            team_info = last_row.get('team') or {}
            home_or_away = 'home' if game_info.get('home_team_id') == team_info.get('id') else 'away'
            opp_abbrev = away_abbrev if home_or_away == 'home' else home_abbrev
        except Exception as e:
            log_failure_reason('MISSING_TEAM_MERGE', f"home/away detection for {player}: {e}")
            home_or_away = 'home'
            opp_abbrev = away_abbrev

        result = cached_run_nba_projection(
            run_fn, nba_bet_sport_label(sport_key), player, opp_abbrev, home_team, away_team,
            home_or_away, season, mm_today_str()
        )

        if result:
            proj = result['projection']
            std_dev = result.get('last10_pts_std', result.get('last10_ast_std', 0))

            # ── LINE SHOPPING: analyze every book's line ──
            book_odds_list = info.get('book_odds', [])
            best_play = find_best_book_line(
                book_odds_list, proj,
                std_dev=std_dev, cv=result['cv'],
                sport=sport_key,
                workload_tier=result.get('workload_tier'),
                confidence_tier=result.get('confidence_tier')
            )

            # Fallback to old FD/DK logic
            if best_play:
                best_line = best_play['best_line']
                direction = best_play['best_direction']
                over_odds = best_play['best_over_odds']
                under_odds = best_play['best_under_odds']
                ev_result = best_play['best_ev_result']
                best_book = best_play['best_book']
                all_book_results = best_play['all_book_results']
            else:
                best_line = info['FanDuel Line'] or info['DraftKings Line']
                if not best_line:
                    continue
                edge_val = round(proj - best_line, 1)
                direction = 'over' if edge_val > 0 else 'under'
                over_odds = info['FanDuel Over'] or info['DraftKings Over']
                under_odds = info['FanDuel Under'] or info['DraftKings Under']
                ev_result = analyze_prop(
                    projection=proj, line=best_line, std_dev=std_dev, cv=result['cv'],
                    over_odds=over_odds or -110, under_odds=under_odds or -110,
                    direction=direction, sport=sport_key,
                    workload_tier=result.get('workload_tier'),
                    confidence_tier=result.get('confidence_tier')
                )
                best_book = None
                all_book_results = []

            if best_line and ev_result:
                edge = round(proj - best_line, 1)
                play = "⬆️ OVER" if direction == 'over' else "⬇️ UNDER"

                all_players[player].update({
                    'Projection': proj, 'Edge': edge, 'Play': play,
                    'Tier': result['confidence_tier'],
                    'EV%': ev_result['ev_pct'] if ev_result else None,
                    'Raw EV%': ev_result['raw_ev_pct'] if ev_result else None,
                    'MM Tier': ev_result['tier'] if ev_result else None,
                    'Pass Reason': ev_result['pass_reason'] if ev_result else None,
                    'Confidence Level': ev_result['confidence_level'] if ev_result else None,
                    'Low Confidence': ev_result['low_confidence'] if ev_result else None,
                    'Fair Odds': ev_result['fair_odds'] if ev_result else None,
                    'Effective Std': ev_result['effective_std'] if ev_result else None,
                    'Adjusted Projection': ev_result['adjusted_projection'] if ev_result else None,
                    'Opposite Odds': ev_result['opposite_odds'] if ev_result else None,
                    'Edge Cents': ev_result['edge_cents'] if ev_result else None,
                    'Direction': direction,
                    'Odds': over_odds if direction == 'over' else under_odds,
                    'Model Prob': ev_result['model_prob'] if ev_result else None,
                    'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
                    # LINE SHOPPING fields
                    'Best Book': best_book,
                    'Best Line': best_line,
                    'Alt Book Lines': [
                        {'book': r['book'], 'line': r['line'], 'direction': r['direction'],
                         'odds': r['odds'], 'ev_pct': r['ev_result']['ev_pct'],
                         'tier': r['ev_result']['tier']}
                        for r in all_book_results
                    ] if all_book_results else [],
                })
                results[player] = result
                bet_sport_label = nba_bet_sport_label(sport_key)
                save_prediction({
                    'date': mm_today_str(),
                    'pitcher': player, 'opponent': opp_abbrev, 'home_team': home_team,
                    'projection': proj, 'base': result['base'], 'book_line': best_line,
                    'edge': edge,
                    'opp_factor': result.get('def_adj', result.get('opp_ast_adj', 0)),
                    'park_factor': 1.0, 'umpire_factor': 1.0,
                    'velo_factor': result.get('fga_factor', result.get('ast_pct_adj', 0)),
                    'total_factor': result.get('team_total_adj', result.get('total_adj', 0)),
                    'pitch_count_factor': result['expected_minutes'],
                    'lineup_factor': result.get('usage_rate', result.get('potential_ast_adj', 0)),
                    'cv': result['cv'], 'confidence_tier': result['confidence_tier'],
                    'actual': None, 'sport': bet_sport_label,
                    'ev_pct': ev_result['ev_pct'] if ev_result else None,
                    'mm_tier': ev_result['tier'] if ev_result else None,
                    'model_prob': ev_result['model_prob'] if ev_result else None,
                    'no_vig_prob': ev_result['no_vig_prob'] if ev_result else None,
                    'model_edge': ev_result['model_edge'] if ev_result else None,
                    # NOTE: 'best_book' removed (Aug 2026) — see MLB comment above.
                })
    return results

def run_todays_card_auto_run(minimal_ui=False, priority_sport=None):
    """Loads and runs every model in the app if not already done this
    session — MLB, both NBA prop types, all three NFL prop types, and
    LoL. minimal_ui=False (Today's Card): shows the detailed technical
    checklist. minimal_ui=True (Home): shows polished, on-brand copy
    instead — a first-time visitor landing on the homepage shouldn't
    see raw step names like "Loading NBA assists props," that reads
    like an unfinished dev tool, not a product.

    Real fix (July 2026) — originally only auto-ran MLB + NBA, even
    though NFL and LoL were both real, working models elsewhere in the
    app. Today's Card silently never showed them unless the user
    happened to separately visit those pages and run them manually
    first. Now covers every model, using the same real functions/
    session-state keys each model's own page already uses.

    Real fix (August 2026, per direct user report — landing directly
    on the Esports page during a real, genuinely cold run still had to
    wait through MLB/NBA/NFL's real cost first, since this always ran
    in a fixed MLB→NBA→NFL→LoL order regardless of which real page the
    visitor actually opened). priority_sport ('mlb'/'nba'/'nfl'/'lol'),
    if given, moves that one real sport's block to the FRONT of the
    real execution order — the caller passes in whichever sport
    matches the current real nav page, so a cold visit to any specific
    sport's page gets that one done first, with the others (which the
    visitor isn't even looking at yet) following after. A real, minor,
    accepted cosmetic side effect: the detailed checklist mode
    (minimal_ui=False, Today's Card) still displays steps in the
    original MLB→NBA→NFL→LoL declared order regardless of real
    execution order, so checkmarks can appear slightly out of visual
    sequence during a reordered run — not worth the real, added
    complexity of reordering the display too, for a rarely-seen mode."""
    if st.session_state.get('today_card_auto_ran'):
        return

    steps = [
        "Loading MLB props", "Running MLB projections",
        "Loading NBA points props", "Running NBA points projections",
        "Loading NBA assists props", "Running NBA assists projections",
        "Loading NFL attempts props", "Running NFL attempts projections",
        "Loading NFL completions props", "Running NFL completions projections",
        "Loading NFL receptions props", "Running NFL receptions projections",
        "Loading LoL matchups", "Running LoL projections",
    ]
    status_box = st.empty()
    completed = []

    minimal_messages = [
        "🔍 Scanning today's matchups...",
        "📊 Comparing every line to the market...",
        "🧮 Running the numbers...",
        "🎯 Finding today's sharpest edge...",
    ]

    def render(current=None):
        if minimal_ui:
            msg = minimal_messages[len(completed) % len(minimal_messages)]
            status_box.markdown(f"""
                <div style='text-align: center; padding: 24px 0; color: var(--mm-text-dim); font-family: var(--mm-mono); font-size: 0.95rem;'>
                    {msg}
                </div>
            """, unsafe_allow_html=True)
            return
        lines = []
        for s in steps:
            if s in completed:
                lines.append(f"✅ {s}")
            elif s == current:
                lines.append(f"⏳ {s}...")
            else:
                lines.append(f"◻️ {s}")
        status_box.markdown("  \n".join(lines))

    render()

    def _run_mlb():
        # Real addition (August 2026, per direct user report — "we
        # gotta figure out why the model is so slow too"). Same real
        # reasoning, same real pattern as NFL's own granular phase
        # timing above: the real, top-level auto-run panel only ever
        # showed MLB as ONE combined number, never separating the real,
        # live props fetch (an external API call, now also fetching
        # the real alternate-lines market too) from the real, per-
        # pitcher model computation (now also computing EV for every
        # real alternate line). Real, granular timing settles which
        # real half actually grew, instead of guessing.
        if 'all_pitchers' not in st.session_state:
            render("Loading MLB props")
            _load_start = time.time()
            mlb_props = load_mlb_props_data()
            _mlb_load_time = round(time.time() - _load_start, 2)
            completed.append("Loading MLB props")
            if mlb_props:
                render("Running MLB projections")
                _run_start = time.time()
                mlb_results = run_all_mlb_projections(mlb_props, '2026')
                _mlb_run_time = round(time.time() - _run_start, 2)
                completed.append("Running MLB projections")
                st.session_state['all_pitchers'] = mlb_props
                st.session_state['pitcher_results'] = mlb_results
                st.session_state['season'] = '2026'
                st.session_state.setdefault('manual_run_order', {})
                st.session_state.setdefault('manual_run_counter', 0)
            else:
                _mlb_run_time = 0.0
                completed.append("Running MLB projections")
            st.session_state['_last_mlb_phase_timing'] = {'mlb_load': _mlb_load_time, 'mlb_run': _mlb_run_time}
        else:
            completed.extend(["Loading MLB props", "Running MLB projections"])

        # MLB Batter Hits (Sep 2026) — backtested and split-half
        # validated (12,658 bets, +4.65%/+5.50% ROI in the profitable
        # 0-12% EV zone). Runs alongside strikeouts in the same MLB
        # block since it shares the same season/date context.
        if 'all_mlb_batters' not in st.session_state:
            render("Loading MLB batter hits props")
            batter_props = load_mlb_batter_hits_props_data()
            completed.append("Loading MLB batter hits props")
            if batter_props:
                render("Running MLB batter hits projections")
                batter_results = run_all_mlb_batter_hits_projections(batter_props, '2026')
                completed.append("Running MLB batter hits projections")
                st.session_state['all_mlb_batters'] = batter_props
                st.session_state['batter_hits_results'] = batter_results
            else:
                completed.append("Running MLB batter hits projections")
        else:
            completed.extend(["Loading MLB batter hits props", "Running MLB batter hits projections"])

    def _run_nba():
        if 'all_nba_players' not in st.session_state:
            render("Loading NBA points props")
            nba_pts_props = load_nba_props_data('player_points')
            completed.append("Loading NBA points props")
            if nba_pts_props:
                render("Running NBA points projections")
                nba_pts_results = run_all_nba_projections(nba_pts_props, run_nba_points_projection, 'nba_points', '2025-26')
                completed.append("Running NBA points projections")
                st.session_state['all_nba_players'] = nba_pts_props
                st.session_state['nba_pts_results'] = nba_pts_results
                st.session_state['nba_season'] = '2025-26'
            else:
                completed.append("Running NBA points projections")
        else:
            completed.extend(["Loading NBA points props", "Running NBA points projections"])

        if 'all_nba_assist_players' not in st.session_state:
            render("Loading NBA assists props")
            nba_ast_props = load_nba_props_data('player_assists')
            completed.append("Loading NBA assists props")
            if nba_ast_props:
                render("Running NBA assists projections")
                nba_ast_results = run_all_nba_projections(nba_ast_props, run_nba_assists_projection, 'nba_assists', '2025-26')
                completed.append("Running NBA assists projections")
                st.session_state['all_nba_assist_players'] = nba_ast_props
                st.session_state['nba_ast_results'] = nba_ast_results
            else:
                completed.append("Running NBA assists projections")
        else:
            completed.extend(["Loading NBA assists props", "Running NBA assists projections"])

    def _run_nfl():
        # Real addition (July 2026) — all three NFL models, same real
        # load_fn/run_all_fn functions and session-state keys each
        # model's own page (run_nfl_display) already uses, just
        # triggered here too.
        nfl_season = datetime.now().year if datetime.now().month >= 3 else datetime.now().year - 1
        nfl_models = [
            ('all_td_scorers', 'nfl_td', load_nfl_td_props_data, run_all_nfl_td_projections,
             "Loading NFL TD props", "Running NFL TD projections"),
        ]
        # Real addition (August 2026, per direct user report — the
        # real, top-level timing panel showed NFL alone eating 105 of
        # ~120 real total seconds, but that alone doesn't say WHERE
        # inside NFL's own real three-model loop the time actually
        # goes: the real, live props fetch (an external API call) or
        # the real, per-player model computation. Real, granular
        # per-phase timing below settles that with direct evidence
        # instead of another guess.
        _nfl_phase_timing = {}
        for all_players_key, session_key, load_fn, run_all_fn, load_step, run_step in nfl_models:
            if all_players_key not in st.session_state:
                render(load_step)
                _load_start = time.time()
                nfl_props = load_fn()
                _nfl_phase_timing[f"{session_key}_load"] = round(time.time() - _load_start, 2)
                completed.append(load_step)
                if nfl_props:
                    render(run_step)
                    _run_start = time.time()
                    nfl_results = run_all_fn(nfl_props, nfl_season)
                    _nfl_phase_timing[f"{session_key}_run"] = round(time.time() - _run_start, 2)
                    completed.append(run_step)
                    st.session_state[all_players_key] = nfl_props
                    st.session_state[f'{session_key}_results'] = nfl_results
                    st.session_state[f'{session_key}_season'] = nfl_season
                    st.session_state.setdefault(f'manual_run_order_{session_key}', {})
                    st.session_state.setdefault(f'manual_run_counter_{session_key}', 0)
                else:
                    completed.append(run_step)
            else:
                completed.extend([load_step, run_step])
        st.session_state['_last_nfl_phase_timing'] = _nfl_phase_timing

    def _run_lol():
        # Real addition (July 2026) — LoL, structured differently from
        # the other models (one real, all-in-one call rather than a
        # separate load-then-run step), same real function/session-
        # state key its own page already uses.
        if 'lol_pipeline_output' not in st.session_state:
            if "CITO_API_KEY" in st.secrets:
                render("Loading LoL matchups")
                completed.append("Loading LoL matchups")
                render("Running LoL projections")
                # Real fix (August 2026) — uses the real, shared,
                # 30-minute cache instead of always recomputing the
                # whole real LoL slate fresh for every visitor's
                # session.
                lol_output = _cached_lol_full_pipeline(st.secrets["CITO_API_KEY"])
                st.session_state['lol_pipeline_output'] = lol_output
                completed.append("Running LoL projections")
            else:
                completed.extend(["Loading LoL matchups", "Running LoL projections"])
        else:
            completed.extend(["Loading LoL matchups", "Running LoL projections"])

    blocks = {'mlb': _run_mlb, 'nfl': _run_nfl}
    order = ['mlb', 'nfl']
    # NBA REMOVED from auto-run (Sep 2026) — both NBA Points and NBA
    # Assists (the only two NBA models on this platform) confirmed
    # unprofitable across two independent backtests each. Not just
    # hidden from display — fully excluded from the pipeline itself,
    # so it stops spending real API calls on every cron cycle for
    # models nobody sees. _run_nba() is left defined above (unused)
    # rather than deleted, matching the same precedent as NFL O/U and
    # LoL, in case a future rebuild brings NBA back.
    # LoL REMOVED from auto-run (Aug 2026) — same treatment as NFL's
    # pass attempts/completions/receptions above: not just hidden from
    # display, fully excluded from the pipeline itself, so it stops
    # spending real Cito API calls on every cron cycle for a model
    # that's no longer shown to anyone. _run_lol() is left defined
    # above (unused) rather than deleted, matching the same
    # keep-the-code-just-stop-calling-it precedent, in case a future
    # rebuild brings LoL back.
    if priority_sport in order:
        order.remove(priority_sport)
        order.insert(0, priority_sport)
    # Real fix (August 2026, per direct user report — a real, confirmed-
    # successful cache-warmer run, checked only 11 real minutes later,
    # STILL took ~2 real minutes) — rather than keep guessing at why,
    # this records the REAL, actual wall-clock time each sport's block
    # takes, every real run, so the next time this happens we have
    # real, direct evidence of exactly where the time goes (e.g. is
    # LoL's own cache genuinely missing, or is a "cache hit" itself
    # still doing real, unexpectedly slow work — like many real,
    # sequential Supabase round-trips even when nothing needs real
    # recomputation) instead of continuing to guess blind.
    _timing_log = {}
    for key in order:
        _block_start = time.time()
        try:
            blocks[key]()
        except Exception as _sport_err:
            # One sport crashing (e.g. NFL's nflreadpy failing to
            # download external data) must NOT kill the entire pipeline
            # — MLB and LoL should still run and cache their picks.
            st.session_state[f'_auto_run_error_{key}'] = str(_sport_err)
        _timing_log[key] = round(time.time() - _block_start, 2)
    st.session_state['_last_auto_run_timing'] = _timing_log

    # Real addition (August 2026, per direct user request — extending
    # the real API bridge to cover every sport, not just LoL). Reuses
    # build_todays_card_entries() — the SAME real, already-finished
    # data Today's Card itself displays (live odds, EV%, tier, all
    # already attached) — grouped by real sport_key and persisted
    # separately per sport, so the real API bridge can read one clean,
    # ready list per sport without ever recomputing or re-deriving
    # anything itself.
    try:
        _all_card_entries = build_todays_card_entries()
        _entries_by_sport = {}
        for _entry in _all_card_entries:
            _entries_by_sport.setdefault(_entry['sport_key'], []).append(_entry)
        for _sport_key, _entries in _entries_by_sport.items():
            set_persistent_all_picks_cache(_sport_key, _entries)
        st.session_state['_last_all_picks_persist_error'] = None
        st.session_state['_last_all_picks_persist_counts'] = {k: len(v) for k, v in _entries_by_sport.items()}

        # Real, new addition (August 2026) — records today's real,
        # actionable picks for the real model track record, then
        # grades any real, past pending picks. Both are real,
        # best-effort and silently no-op on any real failure, so a
        # problem here can never break the real auto-run itself.
        try:
            record_picks_for_grading(_all_card_entries)
            grade_pending_picks()
            grade_pending_bets()
        except Exception:
            pass
    except Exception as _e:
        # Real fix (August 2026, per direct user report — the API
        # bridge showing "0 total picks" even right after a real,
        # successful Streamlit auto-run) — this used to silently
        # swallow any real error here, giving no way to tell WHY the
        # persist step failed versus it genuinely having nothing to
        # persist. Now captures the real exception so it can be
        # surfaced in the admin panel instead of guessed at blind.
        st.session_state['_last_all_picks_persist_error'] = str(_e)

    status_box.empty()

    st.session_state['today_card_auto_ran'] = True
    st.session_state['today_card_updated_at'] = datetime.now(ZoneInfo("America/New_York")).strftime('%I:%M %p ET').lstrip('0')

pitchers_list = get_all_pitchers()

# ---- SIDEBAR ----
with st.sidebar:
    st.markdown("""
        <div style='text-align: center; padding: 20px 0 10px 0;'>
            <img src='https://raw.githubusercontent.com/austinwinkler6-ux/mlb_strikeout_model/main/ModelMetricsLogo.png' width='140'/>
        </div>
    """, unsafe_allow_html=True)

    _sidebar_bankroll, _ = get_bankroll_context()
    if _sidebar_bankroll:
        st.markdown(f"""
            <div style='text-align: center; padding-bottom: 10px;'>
                <span style='font-family: var(--mm-mono); font-size: 0.9rem; color: var(--mm-accent); font-weight: 600;'>💰 ${_sidebar_bankroll:,.2f}</span>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    admin_nav = ["🔬 Model Lab", "🧪 Backtest"] if is_admin else []
    full_nav_options = ["🏠 Home", "🎯 Today's Card", "⚾ MLB Models", "🏈 NFL Models", "🏀 NBA Models", "🎮 Esports (LoL)", "📒 Bet Tracker", "📊 Model Performance"] + admin_nav + ["⚙️ Settings"]
    # Real fix (July 2026) — a real, expired-trial user with no active
    # subscription only ever sees "🏠 Home" as a real, selectable nav
    # option, per the real, deliberate product decision behind this
    # paywall: Home still shows real value (today's highest-rated pick)
    # and carries the real Subscribe CTA, everything else is locked.
    if subscription_status["status"] == "expired":
        nav_options = ["🏠 Home"]
    else:
        nav_options = full_nav_options
    if st.session_state.get('nav_redirect') in nav_options:
        st.session_state['main_nav_radio'] = st.session_state['nav_redirect']
        del st.session_state['nav_redirect']
    nav = st.radio(
        "Navigation",
        nav_options,
        key="main_nav_radio",
        label_visibility="collapsed"
    )
    st.markdown("---")
    st.caption(f"Logged in as {user.email}")
    if st.button("Logout", use_container_width=True):
        sign_out()
        st.rerun()

# Real, deliberate hard block — defense-in-depth on top of nav_options
# itself only ever including locked pages when the status genuinely
# allows it. Even if `nav` somehow ends up set to a locked page (a stale
# session_state value from before the trial expired, a leftover
# nav_redirect, etc.), this forces it back to Home before ANY page
# content below gets a chance to render.
if subscription_status["status"] == "expired" and nav != "🏠 Home":
    nav = "🏠 Home"

# ---- NFL DATA LAYER ----
league_avg_plays_per_game = 64.0  # rough NFL-wide baseline, refined by real data at runtime where possible

# nflverse uses abbreviations (KC, DEN); The Odds API uses full names
# (Kansas City Chiefs, Denver Broncos) — confirmed real mismatch via a
# live diagnostic check, July 2026, same category of issue as the NBA
# team-name matching work done earlier.
nfl_abbrev_to_name = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers",
    "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}

def get_team_pace_and_proe(season, team, as_of_week=None):
    """A team's plays/game and Pass Rate Over Expected, leveraging the
    more rigorous get_nfl_team_game_pace_proe() (proper groupby, standard
    published PROE definition: actual pass rate - average xpass,
    restricted to real offensive plays) instead of reimplementing this
    from scratch. Leak-free — only games strictly before as_of_week when
    backtesting.

    Falls back to the prior season's full-season profile if the current
    season's sample is too thin (July 2026 review, round 7 — same fix as
    get_opponent_pass_funnel_factor, applied here too for consistency,
    even though this one is informational-only and its failure was never
    the critical bug)."""
    def _compute(pace_season, week_filter):
        try:
            team_games = get_nfl_team_game_pace_proe([int(pace_season)])
            if team_games.empty:
                return None, None
            team_rows = team_games[team_games['team'] == team]
            if week_filter is not None:
                team_rows = team_rows[team_rows['week'] < week_filter]
            if team_rows.empty or len(team_rows) < 2:
                return None, None
            plays_per_game = team_rows['total_plays'].mean()
            proe = team_rows['proe'].mean() * 100
            return plays_per_game, proe
        except Exception:
            return None, None

    # Skip the current-season attempt entirely through week 6 (July 2026
    # review, round 9 — a real fix to a real regression). The threshold
    # was originally set at <=3, but the QB-level prior-season bridge
    # (see run_nfl_pass_attempts_projection's prior_weight_table) stays
    # active through 4 STARTS, which a QB with a bye week or two might
    # not reach until week 5-6 — meaning weeks 4-5 were hitting the WORST
    # case: attempting the current-season load (thin, borderline data),
    # discovering it's insufficient, THEN also loading the prior season —
    # doubling the exact memory problem this was supposed to prevent,
    # rather than avoiding it. Raised with real margin to cover the whole
    # range the QB-level bridge can actually be active for.
    if as_of_week is not None and as_of_week <= 6:
        return _compute(int(season) - 1, None)

    plays, proe = _compute(season, as_of_week)
    if plays is not None:
        return plays, proe
    return _compute(int(season) - 1, None)

@st.cache_data(ttl=86400)
def get_nfl_league_baselines(season, as_of_week=None):
    """Real, computed league-wide averages, replacing the hardcoded
    placeholder constants (league_avg_plays_per_game=64.0,
    league_avg_pass_attempts_faced=33.0, league_avg_total=45.0,
    league_avg_qb_carries=3.0, league_baseline_pass_rate=0.58) that were
    flagged repeatedly as known, unresolved gaps (July 2026 review).
    Leak-free — when as_of_week is set, only uses games strictly before
    that week, same principle as every other engine built today. Falls
    back to the old hardcoded values if the real computation fails for
    any reason (e.g. too early in a season for a stable sample), so a
    data hiccup never crashes a live projection."""
    fallback = {
        'plays_per_team_game': 64.0, 'pass_attempts_per_team_game': 33.0,
        'pass_rate': 0.58, 'qb_carries_per_game': 3.0, 'game_total_average': 45.0,
        'pass_plays_per_team_game': 35.0, 'completion_pct_baseline': 0.64,
    }
    # Skip the expensive PBP-dependent load ENTIRELY for very early weeks
    # (July 2026 review, round 8 — real crash fix) — the old version
    # always called get_nfl_team_game_pace_proe() (which loads full raw
    # play-by-play) FIRST, then only checked afterward whether there was
    # enough data. For week 1-3, that check ALWAYS fails and falls back
    # anyway, meaning the full-season PBP load was pure wasted memory
    # pressure — very likely the actual cause of a crash occurring on
    # literally the first QB processed in an early-week backtest, before
    # any accumulation across multiple QBs could even happen.
    if as_of_week is not None and as_of_week <= 6:
        return fallback
    try:
        team_games = get_nfl_team_game_pace_proe([int(season)])
        if as_of_week is not None:
            team_games = team_games[team_games['week'] < as_of_week]
        if team_games.empty or len(team_games) < 20:  # too early in a season for a stable league-wide sample
            return fallback

        plays_per_team_game = team_games['total_plays'].mean()
        pass_attempts_per_team_game = team_games['pass_attempts_official'].mean()
        pass_rate = team_games['actual_pass_rate'].mean()
        # pass_plays (item 8) — ALL called pass plays including sacks,
        # distinct from pass_attempts_official. Needed to convert the
        # Expected Plays x Expected Pass Rate structural view (built on
        # the 'pass' field, so it estimates called pass plays) into
        # official-attempt terms before comparing it against the
        # QB-history-based projection, which targets official attempts
        # specifically.
        pass_plays_per_team_game = team_games['pass_plays'].mean() if 'pass_plays' in team_games.columns else fallback['pass_plays_per_team_game']

        weekly = get_nfl_player_stats([int(season)])
        qb_rows = weekly[weekly['position'] == 'QB']
        if as_of_week is not None:
            qb_rows = qb_rows[qb_rows['week'] < as_of_week]
        qb_carries_per_game = qb_rows['carries'].mean() if not qb_rows.empty and 'carries' in qb_rows.columns else fallback['qb_carries_per_game']
        completion_pct_baseline = (qb_rows['completions'].sum() / qb_rows['attempts'].sum()) if not qb_rows.empty and 'completions' in qb_rows.columns and qb_rows['attempts'].sum() > 0 else fallback['completion_pct_baseline']

        schedules = get_nfl_schedules([int(season)])
        if as_of_week is not None:
            schedules = schedules[schedules['week'] < as_of_week]
        game_total_average = schedules['total_line'].mean() if 'total_line' in schedules.columns and schedules['total_line'].notna().any() else fallback['game_total_average']

        return {
            'plays_per_team_game': round(plays_per_team_game, 1) if pd.notna(plays_per_team_game) else fallback['plays_per_team_game'],
            'pass_attempts_per_team_game': round(pass_attempts_per_team_game, 1) if pd.notna(pass_attempts_per_team_game) else fallback['pass_attempts_per_team_game'],
            'pass_rate': round(pass_rate, 3) if pd.notna(pass_rate) else fallback['pass_rate'],
            'qb_carries_per_game': round(qb_carries_per_game, 1) if pd.notna(qb_carries_per_game) else fallback['qb_carries_per_game'],
            'game_total_average': round(game_total_average, 1) if pd.notna(game_total_average) else fallback['game_total_average'],
            'pass_plays_per_team_game': round(pass_plays_per_team_game, 1) if pd.notna(pass_plays_per_team_game) else fallback['pass_plays_per_team_game'],
            'completion_pct_baseline': round(completion_pct_baseline, 3) if pd.notna(completion_pct_baseline) else fallback['completion_pct_baseline'],
        }
    except Exception:
        return fallback

def get_opponent_pass_funnel_factor(season, opponent, as_of_week=None):
    """How much an opponent's defense tends to face more or fewer pass
    attempts than league average — a real 'pass funnel' signal (e.g. a
    defense that stops the run well but is vulnerable through the air
    tends to face more passing volume, regardless of the opposing team's
    own natural tendencies). Leak-free — only games strictly before
    as_of_week when backtesting.

    Returns a dict with THREE components (July 2026 review) rather than
    pass attempts faced alone — that single number can mislead if an
    opponent's schedule happened to include several pass-heavy teams by
    chance, rather than reflecting a real defensive tendency:
      - pass_attempts_faced_per_game
      - proe_allowed (opponent's defense tends to face more/fewer passes
        than expected, independent of pace)
      - plays_allowed_per_game (opponent's own defensive pace)

    Falls back to the PRIOR season's full profile if the current
    season's sample is too thin (July 2026 review, round 7) — this
    function only ever looked at current-season data, which is
    genuinely empty for week 1 and thin through week 3. Without a
    fallback, this returned all-None for the entire first month of every
    season, silently triggering the critical 'Opponent profile fully
    unavailable' warning for EVERY QB — cascading straight to a Data
    Incomplete tier for the whole slate.

    Now built on the cached, aggregated get_nfl_defense_game_stats()
    instead of filtering raw play-by-play directly (a second July 2026
    review round 7 fix) — the original version called get_nfl_pbp()
    directly here, which meant a full-season backtest with the prior-
    season fallback active could end up holding TWO full seasons of raw
    play-by-play in memory at once, the likely cause of a real reported
    crash. The aggregate is a small fraction of the raw data's size."""
    def _compute_profile(stats_season, week_filter):
        try:
            defense_stats = get_nfl_defense_game_stats([int(stats_season)])
            if defense_stats.empty:
                return None
            opp_rows = defense_stats[defense_stats['team'] == opponent].copy()
            if week_filter is not None:
                opp_rows = opp_rows[opp_rows['week'] < week_filter]
            games_faced = len(opp_rows)
            if games_faced < 3:
                return None  # too thin to trust, even if non-empty
            return {
                'pass_attempts_faced_per_game': opp_rows['pass_attempts_faced'].mean(),
                'proe_allowed': opp_rows['proe_allowed'].mean() * 100,
                'plays_allowed_per_game': opp_rows['total_plays_faced'].mean(),
            }
        except Exception:
            return None

    # Skip the current-season attempt entirely for very early weeks
    # (July 2026 review, round 8 — same crash-prevention reasoning as
    # get_nfl_league_baselines and get_team_pace_and_proe).
    if as_of_week is not None and as_of_week <= 6:
        prior = _compute_profile(int(season) - 1, None)
        return prior if prior is not None else {'pass_attempts_faced_per_game': None, 'proe_allowed': None, 'plays_allowed_per_game': None}

    current = _compute_profile(season, as_of_week)
    if current is not None:
        return current
    prior = _compute_profile(int(season) - 1, None)  # full prior season, no week filter
    if prior is not None:
        return prior
    return {'pass_attempts_faced_per_game': None, 'proe_allowed': None, 'plays_allowed_per_game': None}

def get_nfl_opponent_completion_pct_allowed(season, opponent, as_of_week=None):
    """How much completion percentage an opponent's defense tends to
    allow — built for the Pass Completions model (July 2026), using the
    cached get_nfl_defense_completion_stats aggregate (not raw play-by-
    play directly) and applying the SAME lessons already learned the
    hard way building Pass Attempts: skip the expensive attempt entirely
    for very early weeks (as_of_week <= 6, matching the QB-level prior-
    season bridge window), and fall back to the prior season's full
    profile if the current season's sample is too thin. Requires at
    least 3 real defensive games to trust the number."""
    def _compute(stats_season, week_filter):
        try:
            defense_stats = get_nfl_defense_completion_stats([int(stats_season)])
            if defense_stats.empty:
                return None
            opp_rows = defense_stats[defense_stats['team'] == opponent].copy()
            if week_filter is not None:
                opp_rows = opp_rows[opp_rows['week'] < week_filter]
            if len(opp_rows) < 3:
                return None
            return opp_rows['completion_pct_allowed'].mean()
        except Exception:
            return None

    if as_of_week is not None and as_of_week <= 6:
        return _compute(int(season) - 1, None)
    current = _compute(season, as_of_week)
    if current is not None:
        return current
    return _compute(int(season) - 1, None)

@st.cache_data(ttl=86400)
def get_nfl_team_game_completions(seasons):
    """Team-level completions per game (July 2026) — built for Receptions
    Model B (completion-share challenger), aggregating QB weekly stats
    by team+game rather than building a new PBP-based aggregate, since
    this data is already cached and available. Used to compute a
    receiver's real 'share of team completions' per game, the input
    Model B needs that Model A (target share) doesn't."""
    weekly = get_nfl_player_stats(seasons)
    qb_rows = weekly[weekly['position'] == 'QB'].copy()
    if qb_rows.empty:
        return pd.DataFrame()
    if 'season_type' in qb_rows.columns:
        qb_rows = qb_rows[qb_rows['season_type'] == 'REG']
    if 'completions' in qb_rows.columns:
        qb_rows['completions'] = pd.to_numeric(qb_rows['completions'], errors='coerce').fillna(0)
    grouped = qb_rows.groupby(['team', 'season', 'week'], as_index=False).agg(team_completions=('completions', 'sum'))
    return grouped

@st.cache_data(ttl=86400)
def get_nfl_team_game_targets(seasons):
    """Team-level total targets per game (July 2026, round 2 — real bug
    fix per external review) — needed to properly weight a receiver's
    target_share across games. The bug being fixed: weighting by the
    player's OWN targets (the NUMERATOR of target_share) systematically
    biases the weighted average upward, since it disproportionately
    emphasizes the exact games where the player happened to earn a large
    share. The correct weight is the DENOMINATOR — team total targets —
    computed here by summing targets across every real pass-catcher
    (RECEPTION_POSITIONS) per team-game, giving aggregate_target_share =
    sum(player_targets) / sum(team_targets), the mathematically correct
    way to combine a rate across games of different volume."""
    weekly = get_nfl_player_stats(seasons)
    catcher_rows = weekly[weekly['position'].isin(RECEPTION_POSITIONS)].copy()
    if catcher_rows.empty:
        return pd.DataFrame()
    if 'season_type' in catcher_rows.columns:
        catcher_rows = catcher_rows[catcher_rows['season_type'] == 'REG']
    if 'targets' in catcher_rows.columns:
        catcher_rows['targets'] = pd.to_numeric(catcher_rows['targets'], errors='coerce').fillna(0)
    grouped = catcher_rows.groupby(['team', 'season', 'week'], as_index=False).agg(team_targets=('targets', 'sum'))
    return grouped

@st.cache_data(ttl=86400)
def get_team_targets_vs_attempts_diagnostic(seasons):
    """Real validation diagnostic (July 2026) — team_targets (the
    denominator used for Model A's derived_target_share, built by
    summing every real pass-catcher's targets per team-game) is a
    genuinely different aggregate than official team pass attempts
    (from get_nfl_team_game_pace_proe's pass_attempts_official, built
    from play-by-play). They should generally track closely — every
    real target should correspond to a real attempt — but throwaways,
    spikes, penalties, or provider definitional differences could cause
    them to diverge. Per external review, this doesn't need to block
    the first A-vs-B backtest (a validation tool, not a modeling bug),
    but should exist before drawing strong conclusions from Model A
    specifically. Returns a DataFrame with target_attempt_gap (targets
    minus attempts) and target_attempt_ratio (targets / attempts) per
    team-game, for direct inspection — a consistently small gap means
    the denominator is trustworthy; a large or inconsistent one means
    something about the aggregation needs a closer look."""
    targets_data = get_nfl_team_game_targets(seasons)
    attempts_data = get_nfl_team_game_pace_proe(seasons)
    if targets_data.empty or attempts_data.empty:
        return pd.DataFrame()
    merged = targets_data.merge(
        attempts_data[['team', 'season', 'week', 'pass_attempts_official']],
        on=['team', 'season', 'week'], how='inner',
    )
    if merged.empty:
        return merged
    merged['target_attempt_gap'] = merged['team_targets'] - merged['pass_attempts_official']
    merged['target_attempt_ratio'] = merged['team_targets'] / merged['pass_attempts_official'].replace(0, pd.NA)
    return merged

@st.cache_data(ttl=86400)
def get_nfl_defense_reception_stats(seasons):
    """Defense-side reception stats for Receptions (July 2026) — built
    from weekly WR/TE box scores (NOT play-by-play, avoiding a position
    join PBP doesn't directly support), aggregating targets and
    receptions ALLOWED by grouping WR/TE rows by their real opponent
    each game. Defensive check: does NOT assume 'opponent_team' exists
    as a column — verifies it first and returns an empty DataFrame
    gracefully if it's missing, rather than crashing or silently
    returning wrong data. If missing, the opponent factor for Receptions
    just won't be available (informational gap, not a hard failure) —
    an honest, known limitation rather than building on an unverified
    assumption."""
    weekly = get_nfl_player_stats(seasons)
    wr_te_rows = weekly[weekly['position'].isin(RECEPTION_POSITIONS)].copy()
    if 'opponent_team' not in wr_te_rows.columns or wr_te_rows.empty:
        return pd.DataFrame()
    if 'season_type' in wr_te_rows.columns:
        wr_te_rows = wr_te_rows[wr_te_rows['season_type'] == 'REG']
    for col in ['targets', 'receptions']:
        if col in wr_te_rows.columns:
            wr_te_rows[col] = pd.to_numeric(wr_te_rows[col], errors='coerce').fillna(0)
    grouped = wr_te_rows.groupby(['opponent_team', 'season', 'week'], as_index=False).agg(
        targets_allowed=('targets', 'sum'), receptions_allowed=('receptions', 'sum'),
    )
    grouped['catch_rate_allowed'] = grouped['receptions_allowed'] / grouped['targets_allowed'].replace(0, pd.NA)
    return grouped.rename(columns={'opponent_team': 'team'})

def get_nfl_opponent_reception_factor(season, opponent, as_of_week=None):
    """Opponent factor for Receptions — how many targets a defense tends
    to allow WR/TEs per game, and what catch rate they tend to allow.
    Same early-week-skip and prior-season-fallback pattern proven for
    Completions. Returns (targets_allowed_per_game, catch_rate_allowed)
    or (None, None) if the data isn't available (e.g., if
    opponent_team turned out not to exist as a column)."""
    def _compute(stats_season, week_filter):
        try:
            defense_stats = get_nfl_defense_reception_stats([int(stats_season)])
            if defense_stats.empty:
                return None, None
            opp_rows = defense_stats[defense_stats['team'] == opponent].copy()
            if week_filter is not None:
                opp_rows = opp_rows[opp_rows['week'] < week_filter]
            if len(opp_rows) < 3:
                return None, None
            return opp_rows['targets_allowed'].mean(), opp_rows['catch_rate_allowed'].mean()
        except Exception:
            return None, None

    if as_of_week is not None and as_of_week <= 6:
        return _compute(int(season) - 1, None)
    current_targets, current_catch = _compute(season, as_of_week)
    if current_targets is not None:
        return current_targets, current_catch
    return _compute(int(season) - 1, None)

def get_qb_rush_tendency(season, qb_name, as_of_week=None):
    """A QB's own rushing volume relative to league-average QB rushing —
    computed from real carries data rather than a hardcoded list of known
    'running QBs' (a hardcoded list would need constant manual upkeep as
    rosters and player tendencies change; a computed signal doesn't).
    Running QBs often finish games with fewer pass attempts than a
    similar-volume pocket passer, since some passing situations turn into
    scrambles instead of pass attempts (July 2026 review). Returns
    carries/game for this QB, or None if unavailable."""
    try:
        weekly = get_nfl_player_stats([int(season)])
        qb_rows = weekly[(weekly['player_display_name'] == qb_name) & (weekly['position'] == 'QB')].copy()
        if as_of_week is not None:
            qb_rows = qb_rows[qb_rows['week'] < as_of_week]
        if qb_rows.empty or 'carries' not in qb_rows.columns:
            return None
        return qb_rows['carries'].mean()
    except Exception:
        return None

def find_upcoming_nfl_week(season, home_abbrev, away_abbrev, commence_time_str=None):
    """Finds which real week a game belongs to, by matching team
    abbreviations against the schedule. This is the missing piece that
    lets the LIVE pipeline pass a real as_of_week into the projection
    instead of None — without it, game_context always returns None (see
    get_nfl_game_context's `if as_of_week is not None else None`), which
    meant every live projection was silently skipping Vegas, weather, and
    rest entirely, even though all three were correctly coded and already
    working in Backtest mode.

    Fixed a real bug (July 2026 review, round 4): the original version
    sorted every matchup between these two teams by date and always took
    the EARLIEST one — meaning for a divisional rematch (two teams
    playing twice in a season), this would always return the FIRST
    meeting's week even when the live odds actually belong to the SECOND
    meeting later in the season, and could even match a completed game
    instead of the upcoming one. Now matches using the live event's own
    commence_time when available (closest scheduled gameday to that
    timestamp), falling back to 'first game today-or-later' only if no
    commence_time was given. Also now preserves home/away orientation
    (matches home_abbrev to home_team specifically) rather than checking
    both orderings, since The Odds API already tells us which team is
    truly home."""
    try:
        schedules = get_nfl_schedules([int(season)]).copy()
        matchup = schedules[(schedules['home_team'] == home_abbrev) & (schedules['away_team'] == away_abbrev)].copy()
        if matchup.empty:
            return None
        matchup['gameday_dt'] = pd.to_datetime(matchup['gameday'], utc=True, errors='coerce')

        if commence_time_str:
            event_time = pd.to_datetime(commence_time_str, utc=True, errors='coerce')
            if pd.notna(event_time):
                matchup['time_difference'] = (matchup['gameday_dt'] - event_time).abs()
                matchup = matchup.sort_values('time_difference')
                return int(matchup.iloc[0]['week'])

        now_utc = pd.Timestamp.now(tz='UTC')
        upcoming = matchup[matchup['gameday_dt'] >= now_utc.normalize()]
        if upcoming.empty:
            return None
        return int(upcoming.sort_values('gameday_dt').iloc[0]['week'])
    except Exception:
        return None

@st.cache_data(ttl=21600)
def get_nfl_starter_game_ids(season):
    """Real (game_id, qb_player_id) pairs for confirmed STARTERS, derived
    from schedules' home_qb_id/away_qb_id — replaces the attempts>=15
    interim safeguard (July 2026 review, round 5, item 1 — flagged
    repeatedly across rounds 3-4 as the real fix, and the reviewer's own
    top roadmap priority). An attempts threshold is a noisy proxy: a real
    injury-shortened START with 14 attempts gets wrongly excluded, while
    a backup's 18-attempt mop-up relief appearance in a blowout gets
    wrongly included. A genuine starter-ID join has neither problem.

    Important honest caveat: this assumes weekly stats' player_id and
    schedules' home_qb_id/away_qb_id share the same ID space (both are
    expected to be gsis_id, nflverse's standard cross-table player ID,
    but this couldn't be verified live from the development sandbox — no
    internet access there). If they turn out to use different ID
    systems, this join will silently produce zero matches rather than
    wrong ones, and the caller falls back to the attempts>=15 safeguard
    in that case — see the 'Verify Starter-ID Join' debug button on the
    NFL admin page to confirm which case is actually true once deployed."""
    try:
        schedules = get_nfl_schedules([int(season)])
        starter_ids = set()
        for _, row in schedules.iterrows():
            game_id = row.get('game_id')
            if pd.notna(row.get('home_qb_id')) and pd.notna(game_id):
                starter_ids.add((game_id, row['home_qb_id']))
            if pd.notna(row.get('away_qb_id')) and pd.notna(game_id):
                starter_ids.add((game_id, row['away_qb_id']))
        return starter_ids
    except Exception:
        return set()

def get_nfl_game_context(season, team, opponent, as_of_week):
    """Real Vegas lines (spread, total) and situational context (rest days,
    weather, dome/outdoor) for one specific team's game in a specific
    week — pulled from schedules, which has all of this confirmed
    available. Returns None if the game can't be found (e.g. testing a
    future/hypothetical matchup with no real scheduled game)."""
    try:
        schedules = get_nfl_schedules([int(season)])
        game_row = schedules[
            (schedules['week'] == as_of_week) &
            (((schedules['home_team'] == team) & (schedules['away_team'] == opponent)) |
             ((schedules['away_team'] == team) & (schedules['home_team'] == opponent)))
        ]
        if game_row.empty:
            return None
        row = game_row.iloc[0]
        is_home = row['home_team'] == team
        # spread_line convention: negative means the HOME team is favored.
        # Translate to "this team's own spread" regardless of home/away.
        team_spread = row.get('spread_line') if is_home else (-row.get('spread_line') if pd.notna(row.get('spread_line')) else None)
        team_rest = row.get('home_rest') if is_home else row.get('away_rest')
        return {
            'spread': team_spread, 'total': row.get('total_line'),
            'rest_days': team_rest, 'weekday': row.get('weekday'),
            'roof': row.get('roof'), 'wind': row.get('wind'), 'temp': row.get('temp'),
            'is_home': is_home,
        }
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
@st.cache_data(ttl=300, show_spinner=False)
def _fetch_nfl_events_and_props_combined():
    """Real fix (August 2026, per direct user report — NFL alone eating
    ~99 of ~120 real total auto-run seconds). Shared, cached real fetch
    used by all three NFL load_*_props_data() functions below — fetches
    the real events list ONCE (not three separate times), and for each
    real event, ONE real combined API call requesting all three real
    markets together (player_pass_attempts, player_pass_completions,
    player_receptions) instead of three separate real per-event calls.
    Cuts real NFL auto-run network calls roughly 3x.

    Returns {event_id: {'home', 'away', 'commence_time', 'props_data'}}
    — each caller then runs its OWN, UNCHANGED, market-specific parsing
    loop over this shared real data, exactly as if it had fetched that
    one market alone (the parsing loop already filters by market key,
    so it safely, correctly ignores the other two real markets present
    in this now-shared, combined response)."""
    try:
        events_resp = requests.get("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events",
            params={'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'}, timeout=15)
        events_resp.raise_for_status()
        events_data = events_resp.json()
        if isinstance(events_data, dict) and events_data.get('message'):
            raise RuntimeError(f"Odds API error: {events_data['message']}")

        now_utc = datetime.now(ZoneInfo("UTC"))
        combined = {}

        for event in events_data:
            commence_time_str = event.get('commence_time')
            if commence_time_str:
                try:
                    commence_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    if commence_time <= now_utc:
                        continue  # game already started — a pre-game projection would be stale
                except (ValueError, TypeError):
                    pass

            home = event['home_team']
            away = event['away_team']
            event_id = event['id']
            try:
                props_resp = requests.get(
                    f"https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/{event_id}/odds",
                    params={'apiKey': ODDS_API_KEY, 'regions': 'us',
                             'markets': 'player_pass_attempts,player_pass_completions,player_receptions,player_anytime_td',
                             'oddsFormat': 'american'},
                    timeout=15
                )
                props_resp.raise_for_status()
                props_data = props_resp.json()
                if isinstance(props_data, dict) and props_data.get('message') and 'bookmakers' not in props_data:
                    continue  # this specific event errored — skip it, don't lose every other event over it
            except Exception:
                continue  # one malformed/failed event shouldn't wipe out the whole batch

            combined[event_id] = {'home': home, 'away': away, 'commence_time': commence_time_str, 'props_data': props_data}
        return combined
    except Exception as e:
        st.session_state['_nfl_events_fetch_error'] = str(e)
        return {}


def load_nfl_props_data():
    """Fetches today's live NFL player_pass_attempts props from FanDuel/
    DraftKings — same shape as load_mlb_props_data()/load_nba_props_data()
    so the main NFL page can use the identical card UI. Skips any game
    whose commence_time has already passed — the same fix built for MLB
    after a real incident; applied here from the start this time instead
    of needing a second one to catch it.

    HTTP validation added (July 2026 review, item 9): explicit timeouts,
    raise_for_status(), and a check for The Odds API's own error-object
    responses (e.g. a bad/expired key returns a JSON dict with a
    'message' field, not a list — which would otherwise silently iterate
    as zero events with no explanation). The per-event fetch is wrapped
    in its OWN try/except so one malformed event can't wipe out every
    other successfully-fetched event by tripping the outer handler.

    Real fix (August 2026, per direct user report — NFL alone eating
    ~99 of ~120 real total auto-run seconds, split almost evenly across
    three real, separate ~32s load times). This function, load_nfl_
    completions_props_data(), and load_nfl_receptions_props_data() each
    used to independently re-fetch the SAME real events list, then make
    their OWN separate real per-event API call — three real, redundant
    full passes over the same real games. Now shares the real,
    expensive network calls via _fetch_nfl_events_and_props_combined()
    below, requesting all three real markets together in ONE real per-
    event call instead of three. The parsing loop below is completely
    UNCHANGED — it already filters by market key
    ('player_pass_attempts' only), so it safely, correctly ignores the
    other two real markets present in this now-shared, combined
    response, exactly as if this function had fetched attempts alone."""
    try:
        combined = _fetch_nfl_events_and_props_combined()
        all_qbs = {}

        for event_id, event_info in combined.items():
            home = event_info['home']
            away = event_info['away']
            commence_time_str = event_info['commence_time']
            props_data = event_info['props_data']

            for bookmaker in props_data.get('bookmakers', []):
                book_title = bookmaker.get('title', bookmaker.get('key', ''))
                is_primary = bookmaker['key'] in ['fanduel', 'draftkings']

                for market in bookmaker.get('markets', []):
                    if market.get('key') == 'player_pass_attempts':
                        for outcome in market.get('outcomes', []):
                            qb_name = outcome.get('description')
                            if not qb_name:
                                continue
                            if qb_name not in all_qbs:
                                all_qbs[qb_name] = {
                                    'home': home, 'away': away, 'commence_time': commence_time_str,
                                    'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                    'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                    'Projection': None, 'Edge': None, 'Play': None,
                                    'Tier': None, 'EV%': None, 'MM Tier': None, 'Low Confidence': None,
                                    'Fair Odds': None, 'Edge Cents': None, 'Direction': None, 'Odds': None,
                                    'Model Prob': None, 'No Vig Prob': None,
                                    '_book_odds_raw': {},
                                    'odds_api_event_id': event_id,
                                    'odds_api_sport': 'americanfootball_nfl',
                                    'odds_api_market': 'player_pass_attempts',
                                }
                            if is_primary:
                                if 'FanDuel' in book_title or bookmaker['key'] == 'fanduel':
                                    all_qbs[qb_name]['FanDuel Line'] = outcome.get('point')
                                    if outcome.get('name') == 'Over':
                                        all_qbs[qb_name]['FanDuel Over'] = outcome.get('price')
                                    else:
                                        all_qbs[qb_name]['FanDuel Under'] = outcome.get('price')
                                elif 'DraftKings' in book_title or bookmaker['key'] == 'draftkings':
                                    all_qbs[qb_name]['DraftKings Line'] = outcome.get('point')
                                    if outcome.get('name') == 'Over':
                                        all_qbs[qb_name]['DraftKings Over'] = outcome.get('price')
                                    else:
                                        all_qbs[qb_name]['DraftKings Under'] = outcome.get('price')
                            bor = all_qbs[qb_name].setdefault('_book_odds_raw', {})
                            if book_title not in bor:
                                bor[book_title] = {'book': book_title, 'line': outcome.get('point'), 'over': None, 'under': None}
                            if outcome.get('name') == 'Over':
                                bor[book_title]['over'] = outcome.get('price')
                            else:
                                bor[book_title]['under'] = outcome.get('price')
                            bor[book_title]['line'] = outcome.get('point')
        for qb in all_qbs.values():
            raw = qb.pop('_book_odds_raw', {})
            qb['book_odds'] = sorted(raw.values(), key=lambda b: b.get('book', ''))
        return all_qbs
    except Exception as e:
        st.session_state['_nfl_props_load_error'] = str(e)
        return {}

def evaluate_nfl_quotes(info, proj, cv, confidence_tier):
    """Evaluates every real sportsbook quote SEPARATELY (line + odds kept
    together, never mixed across books) and returns the best valid EV
    result — the old version picked FanDuel's line (or DraftKings' as a
    fallback) and FanDuel's odds (or DraftKings' as a fallback)
    INDEPENDENTLY, which could silently evaluate an invalid combination
    (e.g. FanDuel's line paired with DraftKings' price).

    Fixed a real bug (July 2026 review, round 4, item 3): a missing
    sportsbook price used to get silently filled with a fake -110 —
    meaning the function could report EV on a bet that isn't actually
    available at that price, or at all. Now REQUIRES both real over and
    under prices to exist for a quote to be evaluated at all, and skips
    any quote where the projection is essentially tied with the line
    (abs(proj - line) < 0.05) rather than letting a coin-flip case
    silently default to 'under' just because it's not strictly greater.

    Returns a dict — {'ev_result', 'book', 'line', 'direction', 'odds'}
    — or None if no valid, complete quote exists. Returning the full
    selection (not just book/line) means the caller doesn't have to
    reconstruct which side/odds were actually used."""
    quotes = []
    if info.get('FanDuel Line') is not None:
        quotes.append({'book': 'FanDuel', 'line': info['FanDuel Line'], 'over_odds': info.get('FanDuel Over'), 'under_odds': info.get('FanDuel Under')})
    if info.get('DraftKings Line') is not None:
        quotes.append({'book': 'DraftKings', 'line': info['DraftKings Line'], 'over_odds': info.get('DraftKings Over'), 'under_odds': info.get('DraftKings Under')})

    best = None
    for quote in quotes:
        line = quote['line']
        if line is None or abs(proj - line) < 0.05:
            continue  # essentially tied — don't let this silently default to "under"
        if quote['over_odds'] is None or quote['under_odds'] is None:
            continue  # need BOTH real sides for a valid no-vig probability — never fabricate a missing price
        direction = 'over' if proj > line else 'under'
        selected_odds = quote['over_odds'] if direction == 'over' else quote['under_odds']
        std_dev = get_min_std_dev(cv, proj, sport='nfl_pass_attempts')
        ev_result = analyze_prop(
            projection=proj, line=line, std_dev=std_dev, cv=cv,
            over_odds=quote['over_odds'], under_odds=quote['under_odds'],
            direction=direction, sport='nfl_pass_attempts',
            workload_tier=None, confidence_tier=confidence_tier,
        )
        if ev_result and (best is None or (ev_result.get('ev_pct') or -999) > (best['ev_result'].get('ev_pct') or -999)):
            best = {'ev_result': ev_result, 'book': quote['book'], 'line': line, 'direction': direction, 'odds': selected_odds}
    return best

def run_single_nfl_attempts(qb_name, info, season):
    """Single-player run for the manual ▶️ Run button (July 2026) — a
    genuinely separate function from run_all_nfl_projections' internal
    loop logic, built for the new generic run_nfl_display(), rather than
    refactoring the already-working batch function to share code (same
    safe-copy reasoning used throughout this session — the batch
    version is real, working, and already earning trust). Returns
    (update_fields_dict, result_dict, opp_abbrev, game_week) or
    (None, None, None, None) on failure, so the caller can save its own
    prediction record with the right context."""
    name_to_abbrev = {v: k for k, v in nfl_abbrev_to_name.items()}
    home_abbrev = name_to_abbrev.get(info['home'])
    away_abbrev = name_to_abbrev.get(info['away'])
    weekly_all = get_nfl_player_stats([int(season)])
    qb_recent = weekly_all[(weekly_all['player_display_name'] == qb_name) & (weekly_all['position'] == 'QB')].sort_values('week')
    if qb_recent.empty:
        return None, None, None, None
    qb_team_abbrev = qb_recent.iloc[-1]['team']
    opp_abbrev = away_abbrev if qb_team_abbrev == home_abbrev else (home_abbrev if qb_team_abbrev == away_abbrev else None)
    if opp_abbrev is None:
        return None, None, None, None
    game_week = find_upcoming_nfl_week(season, home_abbrev, away_abbrev, commence_time_str=info.get('commence_time'))
    if game_week is None:
        return None, None, None, None
    result = run_nfl_pass_attempts_projection(qb_name, qb_team_abbrev, opp_abbrev, int(season), as_of_week=game_week)
    if result:
        # Real fix (August 2026) — a manual "▶️ Run" click always
        # force-computes fresh (that's the whole point of the button),
        # but still writes the real result into the shared, persistent
        # cache afterward — same pattern already proven for MLB/NBA's
        # own force-refresh buttons — so every OTHER real visitor
        # benefits from this fresh computation too, not just this one
        # session.
        upsert_cached_projection(mm_today_str(), 'NFL', qb_name, result, has_lineup_data=True)
    if not result:
        return None, None, opp_abbrev, game_week
    proj = result['projection']
    quote = evaluate_nfl_quotes(info, proj, result['attempts_cv'], result.get('confidence_tier'))
    if not quote:
        return None, None, opp_abbrev, game_week
    ev_result, best_book, best_line, direction, selected_odds = quote['ev_result'], quote['book'], quote['line'], quote['direction'], quote['odds']
    edge = round(proj - best_line, 1)
    play = "⬆️ OVER" if direction == 'over' else "⬇️ UNDER"
    update_fields = {
        'Projection': proj, 'Edge': edge, 'Play': play,
        'Tier': result['confidence_tier'],
        'EV%': ev_result['ev_pct'] if ev_result else None,
        'Raw EV%': ev_result['raw_ev_pct'] if ev_result else None,
        'MM Tier': ev_result['tier'] if ev_result else None,
        'Pass Reason': ev_result['pass_reason'] if ev_result else None,
        'Confidence Level': ev_result['confidence_level'] if ev_result else None,
        'Low Confidence': ev_result['low_confidence'] if ev_result else None,
        'Fair Odds': ev_result['fair_odds'] if ev_result else None,
        'Effective Std': ev_result['effective_std'] if ev_result else None,
        'Adjusted Projection': ev_result['adjusted_projection'] if ev_result else None,
        'Opposite Odds': ev_result['opposite_odds'] if ev_result else None,
        'Edge Cents': ev_result['edge_cents'] if ev_result else None,
        'Direction': direction, 'Odds': selected_odds,
        'Model Prob': ev_result['model_prob'] if ev_result else None,
        'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
        'Book': best_book,
    }
    save_fields = {
        'base': result.get('base_attempts'), 'book_line': best_line, 'edge': edge,
        'cv': result['attempts_cv'], 'ev_pct': ev_result['ev_pct'] if ev_result else None,
        'mm_tier': ev_result['tier'] if ev_result else None, 'model_prob': ev_result['model_prob'] if ev_result else None,
        'no_vig_prob': ev_result['no_vig_prob'] if ev_result else None, 'book': best_book,
        'odds': selected_odds, 'direction': direction,
    }
    return update_fields, {'result': result, 'save_fields': save_fields}, opp_abbrev, game_week

def run_single_nfl_completions(qb_name, info, season):
    """Completions version of run_single_nfl_attempts — same structure,
    genuinely separate function."""
    name_to_abbrev = {v: k for k, v in nfl_abbrev_to_name.items()}
    home_abbrev = name_to_abbrev.get(info['home'])
    away_abbrev = name_to_abbrev.get(info['away'])
    weekly_all = get_nfl_player_stats([int(season)])
    qb_recent = weekly_all[(weekly_all['player_display_name'] == qb_name) & (weekly_all['position'] == 'QB')].sort_values('week')
    if qb_recent.empty:
        return None, None, None, None
    qb_team_abbrev = qb_recent.iloc[-1]['team']
    opp_abbrev = away_abbrev if qb_team_abbrev == home_abbrev else (home_abbrev if qb_team_abbrev == away_abbrev else None)
    if opp_abbrev is None:
        return None, None, None, None
    game_week = find_upcoming_nfl_week(season, home_abbrev, away_abbrev, commence_time_str=info.get('commence_time'))
    if game_week is None:
        return None, None, None, None
    result = run_nfl_pass_completions_projection(qb_name, qb_team_abbrev, opp_abbrev, int(season), as_of_week=game_week)
    if result:
        upsert_cached_projection(mm_today_str(), 'NFL_COMPLETIONS', qb_name, result, has_lineup_data=True)
    if not result:
        return None, None, opp_abbrev, game_week
    proj = result['projection']
    quote = evaluate_nfl_completions_quotes(info, proj, result['completion_pct_cv'], result.get('confidence_tier'))
    if not quote:
        return None, None, opp_abbrev, game_week
    ev_result, best_book, best_line, direction, selected_odds = quote['ev_result'], quote['book'], quote['line'], quote['direction'], quote['odds']
    edge = round(proj - best_line, 1)
    play = "⬆️ OVER" if direction == 'over' else "⬇️ UNDER"
    update_fields = {
        'Projection': proj, 'Edge': edge, 'Play': play,
        'Tier': result['confidence_tier'],
        'EV%': ev_result['ev_pct'] if ev_result else None,
        'Raw EV%': ev_result['raw_ev_pct'] if ev_result else None,
        'MM Tier': ev_result['tier'] if ev_result else None,
        'Pass Reason': ev_result['pass_reason'] if ev_result else None,
        'Confidence Level': ev_result['confidence_level'] if ev_result else None,
        'Low Confidence': ev_result['low_confidence'] if ev_result else None,
        'Fair Odds': ev_result['fair_odds'] if ev_result else None,
        'Effective Std': ev_result['effective_std'] if ev_result else None,
        'Adjusted Projection': ev_result['adjusted_projection'] if ev_result else None,
        'Opposite Odds': ev_result['opposite_odds'] if ev_result else None,
        'Edge Cents': ev_result['edge_cents'] if ev_result else None,
        'Direction': direction, 'Odds': selected_odds,
        'Model Prob': ev_result['model_prob'] if ev_result else None,
        'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
        'Book': best_book,
    }
    save_fields = {
        'base': round(result.get('projected_attempts', 0) * result.get('base_completion_pct', 0), 1), 'book_line': best_line, 'edge': edge,
        'cv': result['completion_pct_cv'], 'ev_pct': ev_result['ev_pct'] if ev_result else None,
        'mm_tier': ev_result['tier'] if ev_result else None, 'model_prob': ev_result['model_prob'] if ev_result else None,
        'no_vig_prob': ev_result['no_vig_prob'] if ev_result else None, 'book': best_book,
        'odds': selected_odds, 'direction': direction,
    }
    return update_fields, {'result': result, 'save_fields': save_fields}, opp_abbrev, game_week

def run_single_nfl_receptions(receiver_name, info, season):
    """Receptions version — the one genuinely different piece is the
    real starting-QB lookup, same logic as run_all_nfl_receptions_
    projections but for a single player: tries live Attempts props
    first, falls back to the team's most recent QB from weekly stats."""
    name_to_abbrev = {v: k for k, v in nfl_abbrev_to_name.items()}
    home_abbrev = name_to_abbrev.get(info['home'])
    away_abbrev = name_to_abbrev.get(info['away'])
    weekly_all = get_nfl_player_stats([int(season)])
    receiver_recent = weekly_all[(weekly_all['player_display_name'] == receiver_name) & (weekly_all['position'].isin(RECEPTION_POSITIONS))].sort_values('week')
    if receiver_recent.empty:
        return None, None, None, None
    receiver_team_abbrev = receiver_recent.iloc[-1]['team']
    opp_abbrev = away_abbrev if receiver_team_abbrev == home_abbrev else (home_abbrev if receiver_team_abbrev == away_abbrev else None)
    if opp_abbrev is None:
        return None, None, None, None

    starting_qb = None
    try:
        live_qb_props = load_nfl_props_data()
        for qb_name in live_qb_props.keys():
            qb_recent_check = weekly_all[(weekly_all['player_display_name'] == qb_name) & (weekly_all['position'] == 'QB')].sort_values('week')
            if not qb_recent_check.empty and qb_recent_check.iloc[-1]['team'] == receiver_team_abbrev:
                starting_qb = qb_name
                break
    except Exception:
        pass
    if not starting_qb:
        team_qb_recent = weekly_all[(weekly_all['team'] == receiver_team_abbrev) & (weekly_all['position'] == 'QB')].sort_values('week')
        if not team_qb_recent.empty:
            starting_qb = team_qb_recent.iloc[-1]['player_display_name']
    if not starting_qb:
        return None, None, opp_abbrev, None

    game_week = find_upcoming_nfl_week(season, home_abbrev, away_abbrev, commence_time_str=info.get('commence_time'))
    if game_week is None:
        return None, None, opp_abbrev, None
    result = run_nfl_receptions_projection(receiver_name, receiver_team_abbrev, opp_abbrev, starting_qb, int(season), as_of_week=game_week)
    if result:
        upsert_cached_projection(mm_today_str(), 'NFL_RECEPTIONS', receiver_name, result, has_lineup_data=True)
    if not result:
        return None, None, opp_abbrev, game_week
    proj = result['projection']
    quote = evaluate_nfl_receptions_quotes(info, proj, result['target_share_cv'], result.get('confidence_tier'))
    if not quote:
        return None, None, opp_abbrev, game_week
    ev_result, best_book, best_line, direction, selected_odds = quote['ev_result'], quote['book'], quote['line'], quote['direction'], quote['odds']
    edge = round(proj - best_line, 1)
    play = "⬆️ OVER" if direction == 'over' else "⬇️ UNDER"
    update_fields = {
        'Projection': proj, 'Edge': edge, 'Play': play,
        'Tier': result['confidence_tier'],
        'EV%': ev_result['ev_pct'] if ev_result else None,
        'Raw EV%': ev_result['raw_ev_pct'] if ev_result else None,
        'MM Tier': ev_result['tier'] if ev_result else None,
        'Pass Reason': ev_result['pass_reason'] if ev_result else None,
        'Confidence Level': ev_result['confidence_level'] if ev_result else None,
        'Low Confidence': ev_result['low_confidence'] if ev_result else None,
        'Fair Odds': ev_result['fair_odds'] if ev_result else None,
        'Effective Std': ev_result['effective_std'] if ev_result else None,
        'Adjusted Projection': ev_result['adjusted_projection'] if ev_result else None,
        'Opposite Odds': ev_result['opposite_odds'] if ev_result else None,
        'Edge Cents': ev_result['edge_cents'] if ev_result else None,
        'Direction': direction, 'Odds': selected_odds,
        'Model Prob': ev_result['model_prob'] if ev_result else None,
        'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
        'Book': best_book,
    }
    save_fields = {
        'base': result.get('base_target_share'), 'book_line': best_line, 'edge': edge,
        'cv': result['target_share_cv'], 'ev_pct': ev_result['ev_pct'] if ev_result else None,
        'mm_tier': ev_result['tier'] if ev_result else None, 'model_prob': ev_result['model_prob'] if ev_result else None,
        'no_vig_prob': ev_result['no_vig_prob'] if ev_result else None, 'book': best_book,
        'odds': selected_odds, 'direction': direction,
    }
    return update_fields, {'result': result, 'save_fields': save_fields}, opp_abbrev, game_week

def run_all_nfl_projections(all_qbs, season, progress_callback=None):
    """Runs the projection + EV pipeline for every QB in all_qbs (mutated
    in place), saves each as a prediction, and returns the results dict.
    Matches run_all_nba_projections()'s exact pattern — reuses
    analyze_prop() for the same EV/tier computation used everywhere else,
    rather than a separate NFL-specific version.
    progress_callback(i, total, name), if given, is called before each
    QB runs."""
    results = {}
    total = len(all_qbs)
    name_to_abbrev = {v: k for k, v in nfl_abbrev_to_name.items()}
    weekly_all = get_nfl_player_stats([int(season)])  # loaded once, not once per QB (July 2026 review, item 8) — cached anyway, but this avoids the repeated call + full-frame filter on every iteration
    for i, (qb_name, info) in enumerate(all_qbs.items()):
        if progress_callback:
            progress_callback(i, total, qb_name)

        home_team, away_team = info['home'], info['away']
        home_abbrev = name_to_abbrev.get(home_team)
        away_abbrev = name_to_abbrev.get(away_team)

        try:
            qb_recent = weekly_all[(weekly_all['player_display_name'] == qb_name) & (weekly_all['position'] == 'QB')].sort_values('week')
            if qb_recent.empty:
                continue
            qb_team_abbrev = qb_recent.iloc[-1]['team']
            opp_abbrev = away_abbrev if qb_team_abbrev == home_abbrev else (home_abbrev if qb_team_abbrev == away_abbrev else None)
            if opp_abbrev is None:
                continue  # QB's recent team doesn't match either side of this game — likely a recent trade
        except Exception:
            continue

        # Real fix (July 2026 review, item 1 — the most important one):
        # find_upcoming_nfl_week() determines the actual week this game
        # belongs to, so Vegas/rest/weather (all gated behind
        # `as_of_week is not None` inside get_nfl_game_context) actually
        # populate for live projections. Before this fix, EVERY live
        # projection silently passed as_of_week=None, meaning the entire
        # live pipeline was missing spread, total, rest, and weather —
        # even though all of them were correctly coded and already
        # working in Backtest mode. Now passes the event's own
        # commence_time for accurate matching (fixes a divisional-
        # rematch bug — see the function's own docstring).
        game_week = find_upcoming_nfl_week(season, home_abbrev, away_abbrev, commence_time_str=info.get('commence_time'))
        if game_week is None:
            # Hard block instead of silently falling through with
            # as_of_week=None (July 2026 review, item 2) — a failed week
            # match used to re-disable Vegas/rest/weather with no
            # confidence downgrade at all, exactly the same silent
            # failure item 1 was built to fix in the first place.
            all_qbs[qb_name].update({'Tier': "🔴 Data Incomplete — Pass", 'Pass Reason': "Could not match the live event to an NFL week"})
            continue
        # Real fix (August 2026) — was a real, direct, uncached call to
        # run_nfl_pass_attempts_projection() every single time, for
        # every real visitor's session — meaning NFL had ZERO real
        # computation caching at all, unlike MLB/NBA which already
        # reuse a real, shared, persistent result for the rest of the
        # day once ANY visitor computes it. Now checks/writes the same
        # real daily_cache table those sports already use.
        result = cached_run_nfl_projection(
            run_nfl_pass_attempts_projection, 'NFL', qb_name, mm_today_str(),
            qb_name, qb_team_abbrev, opp_abbrev, int(season), as_of_week=game_week,
        )

        if result:
            proj = result['projection']
            # Fixed a real bug (July 2026 review): the old code picked
            # FanDuel's line (or DraftKings' as fallback) and FanDuel's
            # odds (or DraftKings' as fallback) INDEPENDENTLY — which
            # could silently evaluate an invalid combination.
            # evaluate_nfl_quotes keeps each book's own line and odds
            # together, requires both real sides to exist (no fabricated
            # -110), and returns the complete selection.
            quote = evaluate_nfl_quotes(info, proj, result['attempts_cv'], result.get('confidence_tier'))
            if quote:
                ev_result, best_book, best_line, direction, selected_odds = quote['ev_result'], quote['book'], quote['line'], quote['direction'], quote['odds']
                edge = round(proj - best_line, 1)
                play = "⬆️ OVER" if direction == 'over' else "⬇️ UNDER"
                all_qbs[qb_name].update({
                    'Projection': proj, 'Edge': edge, 'Play': play,
                    'Tier': result['confidence_tier'],
                    'EV%': ev_result['ev_pct'] if ev_result else None,
                    'Raw EV%': ev_result['raw_ev_pct'] if ev_result else None,
                    'MM Tier': ev_result['tier'] if ev_result else None,
                    'Pass Reason': ev_result['pass_reason'] if ev_result else None,
                    'Confidence Level': ev_result['confidence_level'] if ev_result else None,
                    'Low Confidence': ev_result['low_confidence'] if ev_result else None,
                    'Fair Odds': ev_result['fair_odds'] if ev_result else None,
                    'Effective Std': ev_result['effective_std'] if ev_result else None,
                    'Adjusted Projection': ev_result['adjusted_projection'] if ev_result else None,
                    'Opposite Odds': ev_result['opposite_odds'] if ev_result else None,
                    'Edge Cents': ev_result['edge_cents'] if ev_result else None,
                    'Direction': direction,
                    'Odds': selected_odds,
                    'Model Prob': ev_result['model_prob'] if ev_result else None,
                    'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
                    'Book': best_book,
                })
                results[qb_name] = result
                save_prediction({
                    'date': mm_today_str(),
                    'pitcher': qb_name, 'opponent': opp_abbrev, 'home_team': home_team,
                    'projection': proj, 'base': result['base_attempts'], 'book_line': best_line,
                    'edge': edge, 'cv': result['attempts_cv'], 'confidence_tier': result['confidence_tier'],
                    'actual': None, 'sport': 'NFL',
                    'ev_pct': ev_result['ev_pct'] if ev_result else None,
                    'mm_tier': ev_result['tier'] if ev_result else None,
                    'model_prob': ev_result['model_prob'] if ev_result else None,
                    'no_vig_prob': ev_result['no_vig_prob'] if ev_result else None,
                    # Added (July 2026 review, item 6) — without these, later
                    # EV/CLV analysis has no way to know which book/price/
                    # direction was actually recommended, or which real
                    # week/kickoff time the projection was made for.
                    'book': best_book, 'odds': selected_odds, 'direction': direction,
                    'game_week': game_week, 'commence_time': info.get('commence_time'),
                })
    return results

# Real fix (August 2026) — matches the same real 5-minute TTL already
# used by load_nfl_props_data() (Pass Attempts) — this loader didn't
# have it, a real, small inconsistency.
@st.cache_data(ttl=300, show_spinner=False)
def load_nfl_completions_props_data():
    """Fetches today's live NFL player_pass_completions props (July
    2026) — a faithful parallel to load_nfl_props_data(), just built for
    the Completions market instead of Attempts. Same shape, same
    per-event error isolation, same stale-game skip. Deliberately a
    genuinely separate copy rather than a refactor, matching the safe-
    copy pattern used throughout the Completions/Receptions build —
    Attempts' live pipeline is real, working, and already earning
    trust; no reason to risk it for the sake of avoiding a second,
    small function.

    Real fix (August 2026, per direct user report — NFL alone eating
    ~99 of ~120 real total auto-run seconds). Now shares the real,
    expensive network calls via _fetch_nfl_events_and_props_combined()
    instead of independently re-fetching the same real events list and
    making its own separate real per-event API call. This function's
    OWN parsing loop below is completely UNCHANGED."""
    try:
        combined = _fetch_nfl_events_and_props_combined()
        all_qbs = {}

        for event_id, event_info in combined.items():
            home = event_info['home']
            away = event_info['away']
            commence_time_str = event_info['commence_time']
            props_data = event_info['props_data']

            for bookmaker in props_data.get('bookmakers', []):
                book_title = bookmaker.get('title', bookmaker.get('key', ''))
                is_primary = bookmaker['key'] in ['fanduel', 'draftkings']

                for market in bookmaker.get('markets', []):
                    if market.get('key') == 'player_pass_completions':
                        for outcome in market.get('outcomes', []):
                            qb_name = outcome.get('description')
                            if not qb_name:
                                continue
                            if qb_name not in all_qbs:
                                all_qbs[qb_name] = {
                                    'home': home, 'away': away, 'commence_time': commence_time_str,
                                    'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                    'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                    'Projection': None, 'Edge': None, 'Play': None,
                                    'Tier': None, 'EV%': None, 'MM Tier': None, 'Low Confidence': None,
                                    'Fair Odds': None, 'Edge Cents': None, 'Direction': None, 'Odds': None,
                                    'Model Prob': None, 'No Vig Prob': None,
                                    '_book_odds_raw': {},
                                    'odds_api_event_id': event_id,
                                    'odds_api_sport': 'americanfootball_nfl',
                                    'odds_api_market': 'player_pass_completions',
                                }
                            if is_primary:
                                if 'FanDuel' in book_title or bookmaker['key'] == 'fanduel':
                                    all_qbs[qb_name]['FanDuel Line'] = outcome.get('point')
                                    if outcome.get('name') == 'Over':
                                        all_qbs[qb_name]['FanDuel Over'] = outcome.get('price')
                                    else:
                                        all_qbs[qb_name]['FanDuel Under'] = outcome.get('price')
                                elif 'DraftKings' in book_title or bookmaker['key'] == 'draftkings':
                                    all_qbs[qb_name]['DraftKings Line'] = outcome.get('point')
                                    if outcome.get('name') == 'Over':
                                        all_qbs[qb_name]['DraftKings Over'] = outcome.get('price')
                                    else:
                                        all_qbs[qb_name]['DraftKings Under'] = outcome.get('price')
                            bor = all_qbs[qb_name].setdefault('_book_odds_raw', {})
                            if book_title not in bor:
                                bor[book_title] = {'book': book_title, 'line': outcome.get('point'), 'over': None, 'under': None}
                            if outcome.get('name') == 'Over':
                                bor[book_title]['over'] = outcome.get('price')
                            else:
                                bor[book_title]['under'] = outcome.get('price')
                            bor[book_title]['line'] = outcome.get('point')
        for qb in all_qbs.values():
            raw = qb.pop('_book_odds_raw', {})
            qb['book_odds'] = sorted(raw.values(), key=lambda b: b.get('book', ''))
        return all_qbs
    except Exception as e:
        st.session_state['_nfl_completions_props_load_error'] = str(e)
        return {}

def evaluate_nfl_completions_quotes(info, proj, cv, confidence_tier):
    """Completions version of evaluate_nfl_quotes — same real, validated
    fixes already carried over (requires BOTH real over/under prices,
    skips near-tied projections rather than defaulting to 'under',
    never fabricates a missing price). Uses the real
    'nfl_pass_completions' sport key, which now has its own calibrated
    get_min_std_dev branch (built alongside this pipeline — previously
    would have silently fallen through to the generic fallback)."""
    quotes = []
    if info.get('FanDuel Line') is not None:
        quotes.append({'book': 'FanDuel', 'line': info['FanDuel Line'], 'over_odds': info.get('FanDuel Over'), 'under_odds': info.get('FanDuel Under')})
    if info.get('DraftKings Line') is not None:
        quotes.append({'book': 'DraftKings', 'line': info['DraftKings Line'], 'over_odds': info.get('DraftKings Over'), 'under_odds': info.get('DraftKings Under')})

    best = None
    for quote in quotes:
        line = quote['line']
        if line is None or abs(proj - line) < 0.05:
            continue
        if quote['over_odds'] is None or quote['under_odds'] is None:
            continue
        direction = 'over' if proj > line else 'under'
        selected_odds = quote['over_odds'] if direction == 'over' else quote['under_odds']
        std_dev = get_min_std_dev(cv, proj, sport='nfl_pass_completions')
        ev_result = analyze_prop(
            projection=proj, line=line, std_dev=std_dev, cv=cv,
            over_odds=quote['over_odds'], under_odds=quote['under_odds'],
            direction=direction, sport='nfl_pass_completions',
            workload_tier=None, confidence_tier=confidence_tier,
        )
        if ev_result and (best is None or (ev_result.get('ev_pct') or -999) > (best['ev_result'].get('ev_pct') or -999)):
            best = {'ev_result': ev_result, 'book': quote['book'], 'line': line, 'direction': direction, 'odds': selected_odds}
    return best

def run_all_nfl_completions_projections(all_qbs, season, progress_callback=None):
    """Completions version of run_all_nfl_projections — same real week-
    matching fix (find_upcoming_nfl_week, hard block instead of a
    silent as_of_week=None fallthrough), calls
    run_nfl_pass_completions_projection with its validated defaults
    (attempt_weighted completion weighting, moderate/volatile tier
    corrections, team_change_prior_retention=0.0, all five real,
    confirmed Completions corrections)."""
    results = {}
    total = len(all_qbs)
    name_to_abbrev = {v: k for k, v in nfl_abbrev_to_name.items()}
    weekly_all = get_nfl_player_stats([int(season)])
    for i, (qb_name, info) in enumerate(all_qbs.items()):
        if progress_callback:
            progress_callback(i, total, qb_name)

        home_team, away_team = info['home'], info['away']
        home_abbrev = name_to_abbrev.get(home_team)
        away_abbrev = name_to_abbrev.get(away_team)

        try:
            qb_recent = weekly_all[(weekly_all['player_display_name'] == qb_name) & (weekly_all['position'] == 'QB')].sort_values('week')
            if qb_recent.empty:
                continue
            qb_team_abbrev = qb_recent.iloc[-1]['team']
            opp_abbrev = away_abbrev if qb_team_abbrev == home_abbrev else (home_abbrev if qb_team_abbrev == away_abbrev else None)
            if opp_abbrev is None:
                continue
        except Exception:
            continue

        game_week = find_upcoming_nfl_week(season, home_abbrev, away_abbrev, commence_time_str=info.get('commence_time'))
        if game_week is None:
            all_qbs[qb_name].update({'Tier': "🔴 Data Incomplete — Pass", 'Pass Reason': "Could not match the live event to an NFL week"})
            continue
        result = cached_run_nfl_projection(
            run_nfl_pass_completions_projection, 'NFL_COMPLETIONS', qb_name, mm_today_str(),
            qb_name, qb_team_abbrev, opp_abbrev, int(season), as_of_week=game_week,
        )

        if result:
            proj = result['projection']
            quote = evaluate_nfl_completions_quotes(info, proj, result['completion_pct_cv'], result.get('confidence_tier'))
            if quote:
                ev_result, best_book, best_line, direction, selected_odds = quote['ev_result'], quote['book'], quote['line'], quote['direction'], quote['odds']
                edge = round(proj - best_line, 1)
                play = "⬆️ OVER" if direction == 'over' else "⬇️ UNDER"
                all_qbs[qb_name].update({
                    'Projection': proj, 'Edge': edge, 'Play': play,
                    'Tier': result['confidence_tier'],
                    'EV%': ev_result['ev_pct'] if ev_result else None,
                    'Raw EV%': ev_result['raw_ev_pct'] if ev_result else None,
                    'MM Tier': ev_result['tier'] if ev_result else None,
                    'Pass Reason': ev_result['pass_reason'] if ev_result else None,
                    'Confidence Level': ev_result['confidence_level'] if ev_result else None,
                    'Low Confidence': ev_result['low_confidence'] if ev_result else None,
                    'Fair Odds': ev_result['fair_odds'] if ev_result else None,
                    'Effective Std': ev_result['effective_std'] if ev_result else None,
                    'Adjusted Projection': ev_result['adjusted_projection'] if ev_result else None,
                    'Opposite Odds': ev_result['opposite_odds'] if ev_result else None,
                    'Edge Cents': ev_result['edge_cents'] if ev_result else None,
                    'Direction': direction,
                    'Odds': selected_odds,
                    'Model Prob': ev_result['model_prob'] if ev_result else None,
                    'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
                    'Book': best_book,
                })
                results[qb_name] = result
                save_prediction({
                    'date': mm_today_str(),
                    'pitcher': qb_name, 'opponent': opp_abbrev, 'home_team': home_team,
                    'projection': proj, 'base': round(result.get('projected_attempts', 0) * result.get('base_completion_pct', 0), 1), 'book_line': best_line,
                    'edge': edge, 'cv': result['completion_pct_cv'], 'confidence_tier': result['confidence_tier'],
                    'actual': None, 'sport': 'NFL_COMPLETIONS',
                    'ev_pct': ev_result['ev_pct'] if ev_result else None,
                    'mm_tier': ev_result['tier'] if ev_result else None,
                    'model_prob': ev_result['model_prob'] if ev_result else None,
                    'no_vig_prob': ev_result['no_vig_prob'] if ev_result else None,
                    'book': best_book, 'odds': selected_odds, 'direction': direction,
                    'game_week': game_week, 'commence_time': info.get('commence_time'),
                })
    return results

def get_qb_starter_rows(qb_name, season, as_of_week=None):
    """Fetches one season's weekly stats for a QB and filters down to real
    starts, using the starter-ID join with a fallback to the attempts>=15
    threshold. Returns (qb_rows, starter_filter_used) — qb_rows is empty
    (not None) if nothing is found.

    Hardened (July 2026 review, round 7 — debugging a real reported bug
    where every QB, including established veterans, showed 'Games Used:
    1' during Week 1 backtesting): filters to season_type == 'REG'
    explicitly, since nflverse's weekly stats include preseason and
    playoff rows too, and those can have OVERLAPPING or unexpected week
    numbers relative to the regular season — a real, plausible source of
    contamination that was never guarded against before. Also coerces
    'attempts' to numeric explicitly before any threshold comparison
    (defensive — a stray non-numeric value could silently break a >=15
    comparison). The starter-ID join's fallback trigger is now
    proportional (falls back if the join found fewer than half the
    available games), not just an absolute floor of 3 — a join that's
    subtly broken but still produces 1-2 'lucky' matches out of 17 real
    games should also be caught, not just a total failure."""
    try:
        weekly = get_nfl_player_stats([int(season)])
        qb_rows_all = weekly[(weekly['player_display_name'] == qb_name) & (weekly['position'] == 'QB')].copy()
        if 'season_type' in qb_rows_all.columns:
            qb_rows_all = qb_rows_all[qb_rows_all['season_type'] == 'REG']
        if 'attempts' in qb_rows_all.columns:
            qb_rows_all['attempts'] = pd.to_numeric(qb_rows_all['attempts'], errors='coerce').fillna(0)
        if as_of_week is not None:
            qb_rows_all = qb_rows_all[qb_rows_all['week'] < as_of_week]
        qb_rows_all = qb_rows_all.sort_values('week')

        starter_filter_used = "starter_id_join"
        if qb_rows_all.empty:
            # Real bug fix (July 2026) — calling .apply(axis=1) on an
            # EMPTY DataFrame can throw in pandas (it tries to probe a
            # dummy row for type inference), which was silently caught by
            # the outer except below, returning a fully empty, COLUMNLESS
            # DataFrame — breaking any downstream code that checks for
            # specific columns (like Completions' prior-season bridge,
            # which needs qb_rows_all to have real columns even when it
            # has zero rows, e.g. testing week 1 of a season). An empty
            # DataFrame with 0 rows this season is a completely normal,
            # expected case (especially week 1) — return it AS-IS,
            # columns intact, rather than let it become a real crash.
            qb_rows = qb_rows_all.copy()
        elif 'game_id' in qb_rows_all.columns and 'player_id' in qb_rows_all.columns:
            starter_ids = get_nfl_starter_game_ids(season)
            qb_rows = qb_rows_all[qb_rows_all.apply(lambda r: (r['game_id'], r['player_id']) in starter_ids, axis=1)].copy()
            if len(qb_rows_all) >= 3 and len(qb_rows) < max(3, len(qb_rows_all) * 0.5):
                qb_rows = qb_rows_all[qb_rows_all['attempts'] >= 15].copy()
                starter_filter_used = "attempts_threshold_fallback"
        else:
            qb_rows = qb_rows_all[qb_rows_all['attempts'] >= 15].copy()
            starter_filter_used = "attempts_threshold_fallback"
        return qb_rows, starter_filter_used
    except Exception:
        return pd.DataFrame(), "error"

RECEPTION_POSITIONS = ['WR', 'TE', 'RB', 'FB']  # widened per external review (July 2026) — RBs are a major, previously-excluded part of the real reception props market

def get_wr_te_rows(player_name, season, as_of_week=None, min_targets=0):
    """Fetches one season's weekly stats for a receiving-eligible player
    (July 2026, built for Receptions; widened July 2026 round 2 to
    include RB/FB per external review, not just WR/TE). Unlike QBs,
    these positions don't have a clean 'starter' concept the same way —
    target shares are often split across 3-4+ real contributors on a
    given team, with no single ID-join equivalent to QB starter IDs.

    min_targets now defaults to 0 (July 2026 round 2, per external
    review — was 2, a real bug). Filtering out low-target games at the
    ROW level creates genuine survivorship bias: a player's 0- and
    1-target games are often IMPORTANT evidence about role instability,
    declining playing time, returning from injury, or disappearing from
    the offense. A history of [7, 1, 8, 0, 6] targets is NOT the same
    as [7, 8, 6] — filtering the former into the latter inflates both
    target share and confidence dishonestly. Returns ALL games the
    player actually participated in by default; pass min_targets > 0
    explicitly only when deliberately testing that as a hypothesis
    (still worth testing at 1, 2, 3 — just not silently defaulted to).

    Returns (rows, filter_used) — rows is empty (not None) if nothing is
    found. Explicitly filters to season_type == 'REG' and guards against
    calling .apply()-style operations on an empty DataFrame — both real
    lessons learned the hard way building Attempts and Completions,
    applied here from day one instead of rediscovering them a third
    time."""
    try:
        weekly = get_nfl_player_stats([int(season)])
        rows_all = weekly[(weekly['player_display_name'] == player_name) & (weekly['position'].isin(RECEPTION_POSITIONS))].copy()
        if 'season_type' in rows_all.columns:
            rows_all = rows_all[rows_all['season_type'] == 'REG']
        if 'targets' in rows_all.columns:
            # Real diagnostic (July 2026, round 6, per external review,
            # "targets missing values") — track how many targets values
            # were genuinely missing BEFORE the fillna(0) below silently
            # converts them. If this count is effectively zero across
            # real usage, fillna(0) was never really doing anything
            # meaningful and there's no issue. If it's a real, non-
            # trivial number, that's a genuine open question — does
            # missing mean the player truly had zero targets, or does it
            # mean the provider simply didn't report a value for that
            # game — and this diagnostic is what would surface it,
            # rather than assuming without checking. Stored via
            # session_state (not a return-signature change) to avoid
            # rippling through every caller.
            targets_missing_before_fill = rows_all['targets'].isna().sum()
            if targets_missing_before_fill > 0:
                st.session_state.setdefault('_receptions_targets_missing_log', []).append(
                    {'player': player_name, 'season': season, 'missing_count': int(targets_missing_before_fill), 'total_rows': len(rows_all)}
                )
            rows_all['targets'] = pd.to_numeric(rows_all['targets'], errors='coerce').fillna(0)
        # Real fix (July 2026, round 5, per external review, item 4) —
        # only 'targets' was being explicitly coerced to numeric, even
        # though both models perform arithmetic on 'receptions' and
        # 'target_share' too. The source likely already returns these
        # numerically, but production code shouldn't depend on that
        # silently. Deliberately NOT auto-filling these two with 0 the
        # way targets is — a true zero and genuinely unavailable data
        # are different, and the reviewer's caution is well-taken;
        # 'targets' keeps its existing fillna(0) behavior unchanged
        # (an established design choice from round 1, not reversed here
        # without more explicit direction, given how much downstream
        # logic already assumes targets is never null).
        for col in ['receptions', 'target_share']:
            if col in rows_all.columns:
                rows_all[col] = pd.to_numeric(rows_all[col], errors='coerce')
        if as_of_week is not None:
            rows_all = rows_all[rows_all['week'] < as_of_week]
        rows_all = rows_all.sort_values('week')

        if rows_all.empty:
            # Same real bug already fixed for get_qb_starter_rows — an
            # empty DataFrame is a completely normal, expected case
            # (week 1 especially), not something to let become a crash.
            return rows_all.copy(), "all_games_played"

        if min_targets > 0:
            # Only filters when EXPLICITLY requested (e.g. testing the
            # hypothesis directly) — no longer the silent default.
            rows = rows_all[rows_all['targets'] >= min_targets].copy()
            return rows, "targets_threshold"
        return rows_all.copy(), "all_games_played"
    except Exception:
        return pd.DataFrame(), "error"

def compute_prior_season_bridge(qb_name, season, team, as_of_week, current_starts_count,
                                  bridge_schedule='attempts', team_change_multiplier=0.5):
    """Shared prior-season bridge logic (July 2026) — extracted for reuse
    by the Completions model (and future Receptions), WITHOUT touching
    Attempts' existing inline version at all, since that logic is
    already validated and backtested — any risk of a mistake there could
    invalidate real, locked-in corrections. This is a genuine, separate
    copy of the same starts-based phase-out table used by Attempts: 0
    starts=100% prior season, 1=80%, 2=60%, 3=40%, 4=20%, 5+=0%. Also
    halves the carryover weight if the QB changed teams since last
    season (a different team's real prior-season volume reflects a
    different offensive context). Returns (prior_qb_rows, prior_weight,
    team_changed, prior_starter_filter_used).

    bridge_schedule and team_change_multiplier are now real, testable
    parameters (July 2026 review) — completion percentage is generally
    more stable than attempt volume (which can change substantially with
    a new offense, coach, or role), so a slower decay schedule and a
    less severe team-change penalty may be more appropriate for
    Completions specifically than the schedule copied from Attempts.
    Defaults match Attempts' exact original values, so nothing changes
    unless a caller deliberately overrides them."""
    bridge_schedules = {
        'attempts': {0: 1.00, 1: 0.90, 2: 0.75, 3: 0.60, 4: 0.45, 5: 0.30, 6: 0.15},
        'slow_fade': {0: 1.00, 1: 0.90, 2: 0.75, 3: 0.60, 4: 0.40},
        'medium_fade': {0: 1.00, 1: 0.85, 2: 0.70, 3: 0.50, 4: 0.30},
    }
    prior_weight_table = bridge_schedules.get(bridge_schedule, bridge_schedules['attempts'])
    prior_weight = prior_weight_table.get(current_starts_count, 0.0)
    team_changed = False
    prior_qb_rows = pd.DataFrame()
    prior_starter_filter_used = None

    if prior_weight > 0:
        prior_qb_rows, prior_starter_filter_used = get_qb_starter_rows(qb_name, int(season) - 1, as_of_week=None)
        if not prior_qb_rows.empty:
            prior_team = prior_qb_rows['team'].iloc[-1] if 'team' in prior_qb_rows.columns else None
            if prior_team and prior_team != team:
                team_changed = True
                prior_weight = prior_weight * team_change_multiplier

    return prior_qb_rows, prior_weight, team_changed, prior_starter_filter_used

def compute_receptions_prior_season_bridge(player_name, season, team, as_of_week, current_games_count,
                                             bridge_schedule='attempts', team_change_prior_retention=0.5, min_targets=0):
    """Prior-season bridge for Receptions (July 2026) — a genuinely
    separate copy of the same starts-based phase-out logic used by
    compute_prior_season_bridge (built for Completions), using
    get_wr_te_rows instead of get_qb_starter_rows. Deliberately NOT a
    shared/refactored version of the existing function — that one is
    validated and has real, locked-in Completions corrections depending
    on its exact current behavior; any risk of a mistake there wasn't
    worth taking just to avoid one more genuinely small, separate copy.
    Same starts-based table as the other two versions: 0 games=100%
    prior season, 1=80%, 2=60%, 3=40%, 4=20%, 5+=0%.

    team_change_prior_retention (renamed from team_change_multiplier per
    external review — the old name was genuinely ambiguous and led to a
    real, incorrect explanation being given about what the Completions
    model's validated 0.0 value meant): the fraction of the scheduled
    prior-season weight that's RETAINED after a team change. 1.0 = keep
    the full scheduled weight regardless of team change. 0.5 = keep half.
    0.0 = discard prior-season data ENTIRELY on a team change (the
    MAXIMUM penalty, not "no penalty" — a real point of confusion in an
    earlier explanation of the analogous Completions parameter, now
    corrected here and flagged for anyone reading that earlier
    explanation).

    min_targets (real fix, July 2026, round 5, per external review) —
    previously NOT passed through to the prior-season fetch, meaning a
    threshold experiment (testing min_targets=0/1/2/3 on the CURRENT
    season) left the PRIOR season completely unfiltered regardless of
    the setting — an inconsistent comparison. Now passed through
    explicitly so both seasons use the same threshold.

    Returns (prior_rows, prior_weight, team_changed, prior_filter_used)."""
    bridge_schedules = {
        'attempts': {0: 1.00, 1: 0.90, 2: 0.75, 3: 0.60, 4: 0.45, 5: 0.30, 6: 0.15},
        'slow_fade': {0: 1.00, 1: 0.90, 2: 0.75, 3: 0.60, 4: 0.40},
        'medium_fade': {0: 1.00, 1: 0.85, 2: 0.70, 3: 0.50, 4: 0.30},
    }
    prior_weight_table = bridge_schedules.get(bridge_schedule, bridge_schedules['attempts'])
    prior_weight = prior_weight_table.get(current_games_count, 0.0)
    team_changed = False
    prior_rows = pd.DataFrame()
    prior_filter_used = None

    if prior_weight > 0:
        prior_rows, prior_filter_used = get_wr_te_rows(player_name, int(season) - 1, as_of_week=None, min_targets=min_targets)
        if not prior_rows.empty:
            prior_team = prior_rows['team'].iloc[-1] if 'team' in prior_rows.columns else None
            if prior_team and prior_team != team:
                team_changed = True
                prior_weight = prior_weight * team_change_prior_retention
                # Real bug fix (July 2026, round 6, per external review)
                # — prior_weight correctly dropped to 0 when
                # team_change_prior_retention=0.0, but prior_rows itself
                # was still being returned and later concatenated into
                # combined_rows by every caller. That meant "discarded"
                # prior-season games still silently influenced recency
                # windows, volatility (share_cv), confidence_tier, and
                # games_used — a real inconsistency between what the
                # weight said and what the data actually did. Fixed at
                # the source, inside the bridge, so every caller
                # automatically receives behavior consistent with the
                # returned weight, rather than each caller needing to
                # remember to check this themselves.
                if prior_weight <= 0:
                    prior_rows = pd.DataFrame()

    return prior_rows, prior_weight, team_changed, prior_filter_used

def run_nfl_pass_attempts_projection(qb_name, team, opponent, season, as_of_week=None,
                                       season_weight=0.45, last5_weight=0.35, last10_weight=0.20,
                                       spread_coef=0.008, total_coef=0.004, structural_blend_weight=0.0,
                                       schedule_adjust_weight=0.0, bias_correction=0.01, underdog_bias_correction=0.01,
                                       moderate_tier_bias_correction=0.03, reliable_tier_bias_correction=0.0):
    """v1 Pass Attempts model, round 2 (July 2026 review) — QB's own
    recency-blended attempts as the base, layered with Vegas game script,
    actually-used PROE, a blended opponent factor, home/away, QB rushing
    tendency, rest, and weather. Deliberately still excludes completion%
    (per the original build plan) — this model answers ONE question: how
    many times will this team throw the ball. Leak-free when as_of_week
    is set: only uses games/lines/context strictly before that week.

    season_weight/last5_weight/last10_weight (base blend) and spread_coef/
    total_coef (Vegas adjustment strength) are now real, overridable
    parameters (July 2026, round 10) instead of hardcoded constants —
    these were always reasonable starting guesses, never actually tuned
    against real data. Now that two full, independent backtest seasons
    exist, an optimizer can call this function repeatedly with different
    combinations and find out what actually minimizes real error, rather
    than continuing to guess. Defaults match the current, previously-
    hardcoded values, so nothing changes unless a caller deliberately
    overrides them.

    Round 1 -> Round 2 changes, all from direct review feedback:
      - Base weighting changed from a noisy 50% season / 50% last-3 to a
        steadier 45% season / 35% last-5 / 20% last-10 — 3 games is very
        noisy in the NFL (weather, injury, unusual game script can all
        swing it hard).
      - Vegas (spread, total) added as a real adjustment — a large
        favorite tends to throw less, a large underdog more; a high total
        (shootout expected) tends to mean more attempts, a low total
        fewer. This was flagged as the single biggest missing variable.
      - PROE was being COMPUTED but never actually used anywhere in the
        projection — a real bug, the same "calculated but dead" pattern
        found in the NBA Assists tov_factor earlier. Now genuinely
        multiplied into the projection.
      - Opponent adjustment is now a blend (40% pass attempts faced / 30%
        PROE allowed / 30% pace allowed) instead of pass-attempts-faced
        alone, which can mislead if an opponent's schedule happened to
        include several pass-heavy teams by chance.
      - Home/away split added, shrunk toward zero for a small sample —
        same shrinkage principle as the NBA location adjustment.
      - QB rushing tendency added as a small (2-4%) reduction — computed
        from real carries/game rather than a hardcoded list of "known
        running QBs," so it doesn't need manual upkeep as tendencies
        change.
      - Rest (days rest, Thursday/Monday context) and weather (wind)
        added as small adjustments, both using schedule data already
        being pulled for the Vegas lines.
      - expected_plays / expected_pass_rate are now ALSO returned as
        transparency fields (Expected Plays x Expected Pass Rate =
        Attempts, per review) — informational alongside the base for now
        rather than fully replacing the tested QB-history-based base,
        since that would be a bigger, untested structural change to make
        all at once.
    """
    try:
        warnings = []

        # Prior-season bridge (July 2026 review, round 6) — without this,
        # the model returns None for EVERY QB during weeks 1-3 of any
        # season, since it requires 3+ current-season starts and there's
        # no way to have that before week 4. Phases out by STARTS, not
        # week number (more robust to bye weeks and missed games than a
        # fixed week cutoff), using the reviewer's own weighting table:
        # 0 starts this season = 100% prior season, 1 = 80%, 2 = 60%,
        # 3 = 40%, 4 = 20%, 5+ = 0% (fully current-season by then).
        qb_rows, starter_filter_used = get_qb_starter_rows(qb_name, season, as_of_week)
        starts_this_season = len(qb_rows)
        if starter_filter_used == "attempts_threshold_fallback":
            warnings.append("Starter-ID join returned too few matches — fell back to the attempts>=15 threshold. Worth checking the 'Verify Starter-ID Join' debug button for an ID-space mismatch.")

        prior_weight_table = {0: 1.0, 1: 0.9, 2: 0.75, 3: 0.6, 4: 0.45, 5: 0.3, 6: 0.15}
        prior_weight = prior_weight_table.get(starts_this_season, 0.0)
        team_changed = False
        prior_qb_rows = pd.DataFrame()
        prior_starter_filter_used = None

        if prior_weight > 0:
            prior_qb_rows, prior_starter_filter_used = get_qb_starter_rows(qb_name, int(season) - 1, as_of_week=None)
            if prior_starter_filter_used == "attempts_threshold_fallback":
                warnings.append("Prior-season starter-ID join fell back to the attempts>=15 threshold — worth checking the 'Verify Starter-ID Join' debug button.")
            if not prior_qb_rows.empty:
                # Team-change check — last year's volume reflects a
                # DIFFERENT offense if the QB switched teams, so carryover
                # gets cut in half rather than trusted at full strength.
                prior_team = prior_qb_rows['team'].iloc[-1] if 'team' in prior_qb_rows.columns else None
                if prior_team and prior_team != team:
                    team_changed = True
                    prior_weight = prior_weight * 0.5
                    warnings.append(f"QB changed teams since last season ({prior_team} -> {team}) — prior-season carryover weight halved to account for a different offensive context.")

        # Rookie / genuinely no-history case — both current and prior
        # season have insufficient real starts. Per review: label clearly
        # and avoid strong recommendations rather than force a number
        # from almost nothing.
        combined_available = starts_this_season + len(prior_qb_rows)
        if combined_available < 3:
            return None  # still genuinely not enough to project responsibly, rookie or otherwise

        is_rookie_limited_sample = starts_this_season < 3 and len(prior_qb_rows) == 0

        current_weight = 1 - prior_weight
        current_season_avg = qb_rows['attempts'].mean() if not qb_rows.empty else None
        prior_season_avg = prior_qb_rows['attempts'].mean() if not prior_qb_rows.empty else None

        if prior_weight > 0 and prior_season_avg is not None:
            season_attempts_avg = (prior_season_avg * prior_weight) + (current_season_avg * current_weight) if current_season_avg is not None else prior_season_avg
        else:
            season_attempts_avg = current_season_avg

        # last5/last10 pull from a combined chronological log (prior
        # season's real starts, then current season's so far) — this
        # naturally phases out prior-season influence as more current-
        # season games accumulate, without needing separate explicit
        # weighting logic the way season_attempts_avg does.
        combined_rows = pd.concat([prior_qb_rows, qb_rows]).reset_index(drop=True) if not prior_qb_rows.empty else qb_rows
        last5_attempts_avg = combined_rows['attempts'].tail(5).mean()
        last10_attempts_avg = combined_rows['attempts'].tail(10).mean()

        games_started_used = starts_this_season
        partial_games_excluded = None  # tracked inside get_qb_starter_rows's internals now, not directly exposed here post-refactor

        # Base weighting — steadier than the old 50/50 season/last-3 split
        # (July 2026 review: 3 games is very noisy in the NFL).
        base_attempts = (season_attempts_avg * season_weight) + (last5_attempts_avg * last5_weight) + (last10_attempts_avg * last10_weight)

        baselines = get_nfl_league_baselines(season, as_of_week)

        team_pace, team_proe = get_team_pace_and_proe(season, team, as_of_week)
        if team_pace is None:
            warnings.append("Team pace unavailable — informational field only, doesn't affect projection")
        if team_proe is None:
            warnings.append("Team PROE unavailable — informational field only, doesn't affect projection")
        opp_profile = get_opponent_pass_funnel_factor(season, opponent, as_of_week)
        opp_pass_funnel = opp_profile.get('pass_attempts_faced_per_game')
        opp_proe_allowed = opp_profile.get('proe_allowed')
        opp_plays_allowed = opp_profile.get('plays_allowed_per_game')
        if opp_pass_funnel is None and opp_proe_allowed is None and opp_plays_allowed is None:
            warnings.append("Opponent profile fully unavailable — neutral opponent factor (1.0) used")
        game_context = get_nfl_game_context(season, team, opponent, as_of_week) if as_of_week is not None else None
        if as_of_week is not None and game_context is None:
            warnings.append("Game context (Vegas lines, rest, weather) unavailable — neutral values used for all of it")

        # Team pace factor — informational only, see the double-counting
        # note below (not applied to the projection).
        pace_factor = 1.0
        if team_pace:
            pace_factor = 1 + ((team_pace / baselines['plays_per_team_game']) - 1) * 0.5

        # Opponent factor — a real blend (40% attempts faced / 30% PROE
        # allowed / 30% plays allowed) instead of pass-attempts-faced
        # alone, which can mislead if an opponent's schedule happened to
        # include several pass-heavy teams by chance. Now uses real
        # computed league baselines instead of hardcoded placeholders
        # (July 2026 review, item 4).
        opp_factor = 1.0
        component_ratios = []
        if opp_pass_funnel:
            component_ratios.append((opp_pass_funnel / baselines['pass_attempts_per_team_game'], 0.40))
        if opp_proe_allowed is not None:
            component_ratios.append((1 + (opp_proe_allowed / 100), 0.30))
        if opp_plays_allowed:
            component_ratios.append((opp_plays_allowed / baselines['plays_per_team_game'], 0.30))
        # Schedule-adjusted defensive effect (July 2026, round 12) — a
        # genuinely different signal from the 3 above, not just a
        # re-weighting of the same inputs. Isolates how much offenses
        # deviate from their OWN normal pass rate specifically against
        # this defense, instead of raw attempts faced (which can mislead
        # if a defense happened to face several pass-heavy teams by
        # schedule luck). Weight defaults to 0 — genuinely untested until
        # deliberately run through the optimizer, same pattern as the
        # structural blend before it.
        schedule_adjusted_effect = None
        if schedule_adjust_weight > 0:
            schedule_adjusted_effect = get_schedule_adjusted_opponent_factor(season, opponent, as_of_week)
            if schedule_adjusted_effect is not None:
                component_ratios.append((1 + (schedule_adjusted_effect / 100), schedule_adjust_weight))
        if component_ratios:
            total_weight = sum(w for _, w in component_ratios)
            blended_ratio = sum(r * w for r, w in component_ratios) / total_weight
            opp_factor = 1 + (blended_ratio - 1) * 0.4

        # PROE — informational only, see the double-counting note below
        # (not applied to the projection).
        proe_factor = 1.0
        if team_proe is not None:
            proe_factor = 1 + (team_proe / 100) * 0.5

        # Vegas — the single biggest missing variable per review. A big
        # favorite tends to lean run-heavy late to protect a lead; a big
        # underdog throws more trying to catch up; a high total implies
        # a shootout (more attempts), a low total implies a grind-it-out
        # game (fewer). Both dampened and capped to avoid overreacting to
        # an extreme single-game line.
        vegas_factor = 1.0
        home_away_adj = 0.0
        rest_adj = 0.0
        weather_adj = 0.0
        if game_context:
            spread = game_context.get('spread')
            total = game_context.get('total')
            if spread is not None:
                # Fixed a real sign error (July 2026 review): team_spread
                # is negative when THIS team is favored. The old code
                # negated it, which raised attempts for favorites and
                # lowered them for underdogs — exactly backward. A
                # favorite should throw LESS (protecting a lead), an
                # underdog MORE (catching up) — spread's own sign already
                # points the right direction with no negation needed.
                spread_component = max(-0.08, min(0.08, spread * spread_coef))
                vegas_factor += spread_component
            if total is not None:
                total_component = max(-0.05, min(0.05, (total - baselines['game_total_average']) * total_coef))
                vegas_factor += total_component

            rest_days = game_context.get('rest_days')
            weekday = game_context.get('weekday')
            if rest_days is not None and rest_days <= 4:
                rest_adj = -0.02  # short week (e.g. Thursday game) — less practice time, often a simpler game plan
            elif rest_days is not None and rest_days >= 10:
                rest_adj = 0.01  # extra rest — more prep time

            wind = game_context.get('wind')
            roof = game_context.get('roof')
            if roof in ('outdoors', 'open') and wind is not None and wind >= 15:
                weather_adj = -0.04  # real wind, real passing-volume impact

        # QB rushing tendency — computed from real carries data, not a
        # hardcoded "known running QBs" list. Cap reduced from 4% to 2%
        # (July 2026 review, item 6) — raw carries include kneel-downs,
        # sneaks, and designed runs alongside scrambles, which don't all
        # relate to pass attempts the same way. Isolating scrambles
        # specifically (the most relevant signal) needs a separate
        # play-by-play pass — flagged as a real next step, not yet built.
        qb_rush_factor = 1.0
        qb_carries_per_game = get_qb_rush_tendency(season, qb_name, as_of_week)
        if qb_carries_per_game is None:
            warnings.append("QB rushing data unavailable — neutral rushing factor (1.0) used")
        elif qb_carries_per_game > baselines['qb_carries_per_game']:
            excess_rushing = qb_carries_per_game - baselines['qb_carries_per_game']
            qb_rush_factor = max(0.98, 1 - (excess_rushing * 0.005))  # capped at -2%, was -4%

        # Home/away removed for now (July 2026 review, item 7) — the flat
        # +/-1.5% direction wasn't established from any real history, and
        # home/away effects likely already flow through spread, total,
        # pace, and opponent, which ARE real signals. Re-adding this
        # would need a genuine shrunk historical split (home attempts avg
        # - overall avg, heavily shrunk for sample size), not a flat
        # assumed direction. Left at 0.0 until that real version exists.
        home_away_adj = 0.0

        # Expected Plays x Expected Pass Rate — transparency layer per
        # review. Additive with caps (July 2026 review) — the old
        # multiplicative version barely moved the number for a real PROE
        # swing.
        expected_plays = team_pace if team_pace else baselines['plays_per_team_game']
        expected_pass_rate = baselines['pass_rate'] + (team_proe / 100 * 0.5 if team_proe is not None else 0)
        expected_pass_rate = max(0.45, min(0.72, expected_pass_rate))
        expected_pass_plays = expected_plays * expected_pass_rate if expected_plays else None

        # Convert pass PLAYS into official attempts (July 2026 review,
        # round 4, item 8) — expected_pass_plays estimates every called
        # pass play (via the 'pass' field, which includes sacks), but the
        # model's actual target is official QB attempts, which exclude
        # sacks. Without this conversion, a team that allows/takes a lot
        # of sacks would show an artificially inflated structural
        # estimate purely from that mismatch — creating a fake
        # "architecture disagreement" that isn't really about volume
        # forecasting at all, just a units mismatch.
        league_attempt_share_of_pass_plays = (
            baselines['pass_attempts_per_team_game'] / baselines['pass_plays_per_team_game']
            if baselines.get('pass_plays_per_team_game') else 1.0
        )
        expected_plays_x_rate = round(expected_pass_plays * league_attempt_share_of_pass_plays, 1) if expected_pass_plays is not None else None

        # Double-counting fix (July 2026 review, Option A): the QB's own
        # historical attempts base already reflects their team's real
        # pace and PROE identity — that's literally what happened in
        # those games. Multiplying by season-long pace_factor and
        # proe_factor on top of that base counts the same team identity
        # twice (e.g. a naturally pass-heavy team's QB already has a high
        # attempts average; applying a positive PROE factor on top
        # double-counts that). pace_factor and proe_factor are kept as
        # informational/display fields only — NOT applied — while
        # opponent, Vegas, weather, and rest remain real adjustments,
        # since those represent how THIS UPCOMING game differs from the
        # QB's normal environment, which is a genuinely different signal
        # than re-stating the QB's own established identity.
        #
        # qb_rush_factor removed from the active chain for the exact same
        # reason (July 2026 review, round 3, item 4) — a mobile QB's
        # season-long attempts average already reflects that some of his
        # dropbacks become scrambles instead of pass attempts. Applying
        # his season-long rushing tendency on top of that same season-
        # long attempts base counts it twice. Kept informational only
        # until there's a genuine MATCHUP-SPECIFIC signal to apply (a
        # recent scramble-rate change, expected pressure from O-line
        # injuries, an opponent that forces unusual scramble rates, or a
        # previously-injured QB running normally again) — none of which
        # are built yet.
        total_adjustment_factor = opp_factor * vegas_factor * (1 + home_away_adj) * (1 + rest_adj) * (1 + weather_adj)
        projected_attempts = base_attempts * total_adjustment_factor

        # Apples-to-apples fix (July 2026 review, round 3, item 5): the
        # old architecture_gap compared a FULLY adjusted number
        # (projected_attempts, which includes opponent/Vegas/rest/
        # weather) against an UNADJUSTED one (expected_plays_x_rate,
        # which only reflects team pace/PROE) — meaning a large gap could
        # simply mean "this week's spread is unusual," not "the two
        # architectures genuinely disagree." structural_projection
        # applies the SAME matchup adjustments to the plays x rate view,
        # so both estimates now describe the same upcoming environment
        # before being compared.
        structural_projection = expected_plays_x_rate * opp_factor * vegas_factor * (1 + rest_adj) * (1 + weather_adj) if expected_plays_x_rate is not None else None

        # Structural blend (July 2026, round 11) — a real, testable
        # question we'd never actually tried: does incorporating the
        # independent structural (Expected Plays x Rate) view directly
        # into the final number improve accuracy, rather than relying
        # purely on the QB-history-based projection with structural_
        # projection kept as informational-only? structural_blend_weight
        # of 0.0 (the default) reproduces the exact prior behavior —
        # nothing changes unless a caller deliberately overrides it, same
        # pattern as the coefficient parameters. Falls back gracefully to
        # pure QB-history if structural_projection couldn't be computed.
        qb_history_projection = projected_attempts
        if structural_projection is not None and structural_blend_weight > 0:
            projected_attempts = ((1 - structural_blend_weight) * qb_history_projection) + (structural_blend_weight * structural_projection)

        # Bias correction (July 2026, round 13) — a real, cross-season-
        # confirmed finding via residual analysis: the model systematically
        # OVER-projects on average (signed bias was negative — Actual minus
        # Projection — in BOTH 2024 and 2025, though the size varied: -0.6
        # in 2025, -0.2 in 2024). A 1% correction was grid-searched and
        # VALIDATED on genuinely held-out data (trained on 2024: 7.003 vs
        # 7.006 at 0% — a tiny, near-noise gap; validated on 2025: 6.994 vs
        # 7.029 — a real improvement, if anything slightly LARGER than what
        # training suggested, a good sign it's real and not overfit). Now
        # the default (0.01), unlike structural_blend_weight which stayed
        # at its own proven-correct default of 0 after failing validation.
        if bias_correction != 0:
            projected_attempts = projected_attempts * (1 - bias_correction)

        # Underdog-specific bias correction (July 2026, round 15) — real
        # residual analysis found 3 of 5 underdog spread buckets (3-6,
        # 6-9, 9-13) showed a consistent negative bias (over-projection)
        # in BOTH 2024 and 2025, even though the exact magnitude gradient
        # didn't hold up cleanly. Applies an ADDITIONAL downward
        # correction specifically when the team is an underdog (spread >
        # 0), on top of the general bias_correction above. A 1% correction
        # was grid-searched and VALIDATED on held-out data (trained on
        # 2024: 7.002 vs 7.003 at 0% — a tiny, near-noise gap; validated
        # on 2025: 6.956 vs 6.994 — a real improvement, again slightly
        # LARGER than what training suggested, same reassuring pattern as
        # the general bias correction). Now the default (0.01) — second
        # real, validated improvement of the session, stacking on top of
        # the first.
        if underdog_bias_correction != 0 and game_context and game_context.get('spread') is not None and game_context['spread'] > 0:
            projected_attempts = projected_attempts * (1 - underdog_bias_correction)

        # Confidence tiers — built in from this round rather than added
        # later, per review (this made real validation easier for MLB and
        # should do the same here). Based on real, checkable signals:
        # sample size, attempts stability (CV across recent games), dome
        # vs outdoor, weather risk, AND (new, July 2026 review item 9) how
        # much the QB-history-based projection disagrees with the
        # independent Expected Plays x Expected Pass Rate view — a large
        # gap means two different ways of estimating volume disagree,
        # which is real evidence of uncertainty the other signals alone
        # wouldn't catch. Deliberately simple otherwise — injury/backup-
        # WR/rookie-QB signals from the review are real, good ideas but
        # need their own verified data source before being trusted in a
        # tier that could affect real bet sizing.
        attempts_history = combined_rows['attempts'].tail(10)
        attempts_cv = (attempts_history.std() / attempts_history.mean()) if len(attempts_history) > 1 and attempts_history.mean() > 0 else 1.0
        is_dome = game_context.get('roof') in ('dome', 'closed') if game_context else None
        high_wind_risk = (game_context.get('wind') or 0) >= 15 if game_context else False
        # Apples-to-apples fix (July 2026 review, round 3, item 5) — see
        # structural_projection's own comment above for the full
        # reasoning. Falls back to the old comparison if structural_projection
        # couldn't be computed for some reason.
        architecture_gap = abs(projected_attempts - structural_projection) if structural_projection is not None else (abs(projected_attempts - expected_plays_x_rate) if expected_plays_x_rate is not None else 0)

        # Missing-data downgrade (July 2026 review, round 3, item 6) — a
        # projection with genuinely missing opponent or game-context data
        # could previously still land on "Reliable" if the QB's own
        # attempts history happened to be stable, since warnings didn't
        # feed into the tier at all. A statistically stable QB shouldn't
        # be labeled reliable when the actual matchup inputs are missing.
        critical_warning_keywords = ["Opponent profile fully unavailable", "Game context"]
        critical_warning_count = sum(any(k in w for k in critical_warning_keywords) for w in warnings)

        # Real fix (July 2026, round 10) — architecture_gap REMOVED from
        # the tier decision entirely. Backtested across two full,
        # independent seasons (2024 and 2025, ~950 combined predictions):
        # it showed ZERO consistent relationship with real error in
        # EITHER season — the "best" and "worst" gap buckets were
        # essentially scrambled differently each year, no climbing trend
        # in either direction. Worse, using it in the tier logic is a
        # very plausible direct cause of a confirmed, serious problem:
        # the whole tier system INVERTED between seasons (Reliable was
        # the best-performing tier in 2025, second-worst in 2024) — which
        # makes sense if part of what's sorting predictions into tiers is
        # essentially random noise. The tier now rests purely on sample
        # size and attempts volatility (attempts_cv), the two signals
        # that were part of the original, simpler design before the gap
        # got layered on top. architecture_gap is still computed and
        # returned as an informational field, in case a genuinely
        # different way of using it (e.g. the SIGN of disagreement rather
        # than magnitude) proves useful later — just not trusted for real
        # tier decisions until it actually earns that with real evidence.
        if is_rookie_limited_sample:
            confidence_tier = "🔴 Limited NFL Sample"
        elif critical_warning_count >= 1:
            confidence_tier = "🔴 Data Incomplete — Pass"
        elif len(combined_rows) < 4 or attempts_cv > 0.30 or high_wind_risk:
            confidence_tier = "🔴 Volatile — Consider Pass"
        elif len(combined_rows) >= 8 and attempts_cv < (0.20 if is_dome else 0.18):
            confidence_tier = "🟢 Reliable"  # dome games get a slightly more lenient bar — no weather variance to worry about indoors
        else:
            confidence_tier = "🟠 Moderate"

        # Moderate-tier-specific bias correction (July 2026, round 16) —
        # real residual analysis found the Moderate tier specifically
        # showed a consistent negative bias (over-projection) in BOTH
        # 2024 (-1.06) and 2025 (-0.97) — larger than the overall bias
        # already corrected for above. Applies an ADDITIONAL downward
        # correction specifically for Moderate-tier predictions, on top
        # of the general and underdog corrections. Grid-searched and
        # VALIDATED on held-out data — this one had a genuinely clean,
        # convincing shape (a real peak at 3%: 0%=7.002 worst, climbing
        # to 3%=6.975 best, then back down to 5%=6.995 — a real
        # inverted-U, not a near-tie with zero like the other two
        # corrections). Validated on held-out data: 6.93 vs 6.956 at 0%
        # — confirmed the training signal generalizes. Now the default
        # (0.03) — third real, validated improvement of the session,
        # and the most convincing of the three.
        if moderate_tier_bias_correction != 0 and confidence_tier == "🟠 Moderate":
            projected_attempts = projected_attempts * (1 - moderate_tier_bias_correction)

        # Reliable-tier-specific bias correction (July 2026, round 17) —
        # real residual analysis found the Reliable tier showed a
        # consistent POSITIVE bias (under-projection, opposite direction
        # from the other three corrections) in BOTH 2024 (+0.29) and
        # 2025 (+0.69) — smaller in magnitude than Moderate's issue, but
        # same-direction in both seasons, the same bar every other real
        # correction this session had to clear. This applies an
        # ADDITIONAL upward correction specifically for Reliable-tier
        # predictions. Defaults to 0.0 — genuinely untested until run
        # through the optimizer with proper train/validate discipline.
        if reliable_tier_bias_correction != 0 and confidence_tier == "🟢 Reliable":
            projected_attempts = projected_attempts * (1 + reliable_tier_bias_correction)

        return {
            'projection': round(projected_attempts, 1),
            'base_attempts': round(base_attempts, 1),
            'season_attempts_avg': round(season_attempts_avg, 1),
            'last5_attempts_avg': round(last5_attempts_avg, 1),
            'last10_attempts_avg': round(last10_attempts_avg, 1),
            'team_pace': round(team_pace, 1) if team_pace else None,
            'team_proe': round(team_proe, 2) if team_proe else None,
            'opp_pass_attempts_faced_per_game': round(opp_pass_funnel, 1) if opp_pass_funnel else None,
            'opp_proe_allowed': round(opp_proe_allowed, 2) if opp_proe_allowed is not None else None,
            'opp_plays_allowed_per_game': round(opp_plays_allowed, 1) if opp_plays_allowed else None,
            'pace_factor': round(pace_factor, 3),
            'opp_factor': round(opp_factor, 3),
            'proe_factor': round(proe_factor, 3),
            'vegas_factor': round(vegas_factor, 3),
            'qb_rush_factor': round(qb_rush_factor, 3),
            'qb_carries_per_game': round(qb_carries_per_game, 1) if qb_carries_per_game is not None else None,
            'home_away_adj': round(home_away_adj, 3),
            'rest_adj': round(rest_adj, 3),
            'weather_adj': round(weather_adj, 3),
            'game_context': game_context,
            'expected_plays': round(expected_plays, 1) if expected_plays else None,
            'expected_pass_rate': round(expected_pass_rate, 3),
            'expected_plays_x_rate': expected_plays_x_rate,
            'games_used': len(combined_rows),
            'games_started_used': games_started_used, 'partial_games_excluded': partial_games_excluded,
            'starter_filter_used': starter_filter_used,
            'starts_this_season': starts_this_season, 'prior_season_weight': round(prior_weight, 2),
            'prior_games_available': len(prior_qb_rows), 'prior_starter_filter_used': prior_starter_filter_used,
            'team_changed': team_changed, 'is_rookie_limited_sample': is_rookie_limited_sample,
            'confidence_tier': confidence_tier, 'attempts_cv': round(attempts_cv, 3),
            'architecture_gap': round(architecture_gap, 1), 'data_quality_warnings': warnings,
            'structural_projection': round(structural_projection, 1) if structural_projection is not None else None,
            'qb_history_projection': round(qb_history_projection, 1), 'structural_blend_weight_used': structural_blend_weight,
            'schedule_adjusted_effect': round(schedule_adjusted_effect, 2) if schedule_adjusted_effect is not None else None,
            'schedule_adjust_weight_used': schedule_adjust_weight,
            'bias_correction_used': bias_correction,
            'underdog_bias_correction_used': underdog_bias_correction,
            'moderate_tier_bias_correction_used': moderate_tier_bias_correction,
            'reliable_tier_bias_correction_used': reliable_tier_bias_correction,
        }
    except Exception as e:
        if st.session_state.get("_nfl_debug_mode"): raise
        return None

def run_nfl_pass_completions_projection(qb_name, team, opponent, season, as_of_week=None,
                                          completion_weighting='attempt_weighted', bridge_schedule='attempts',
                                          team_change_multiplier=0.0, use_cpoe_model=False, cpoe_weight=1.0,
                                          completions_bias_correction=0.0, completions_moderate_tier_correction=0.06,
                                          completions_volatile_tier_correction=0.20, cpoe_blend_weight=0.0):
    """v1 Pass Completions model (July 2026, now with the prior-season
    bridge and 4 testable parameters from external review) — Projected
    Attempts x Expected Completion%, per the original build order.
    Deliberately reuses as much of the Attempts infrastructure as
    possible: run_nfl_pass_attempts_projection directly for the volume
    component, get_qb_starter_rows for the same starter-ID-joined,
    season_type-filtered QB history, get_nfl_league_baselines for a real
    computed completion_pct_baseline, and compute_prior_season_bridge for
    the same starts-based prior-season blending Attempts has.

    Four real, testable parameters added this round, ALL defaulting to
    preserve the exact original v1 behavior — none of these are assumed
    to be improvements, they're hypotheses to backtest, same discipline
    used throughout the Attempts build:
      - completion_weighting: VALIDATED (July 2026) — 'attempt_weighted'
        (sums completions/sums attempts across games, weighting high-
        volume games more heavily) is now the default, confirmed to
        genuinely beat 'equal' (the original — averaging each game's own
        completion%, treating a 5-attempt game the same as a 45-attempt
        game) on held-out data (trained on 2024: 4.808 vs 4.789; held-out
        2025: 4.751 vs 4.723 — the validation gap was actually LARGER
        than training, a good sign of real signal). Fourth real,
        validated Completions improvement of the session.
      - bridge_schedule: TESTED, NO REAL EFFECT — 'attempts' (original),
        'slow_fade', and 'medium_fade' came back essentially tied on
        both training (0.006 spread) and validation (exact tie, 4.756 vs
        4.756). Kept at 'attempts'; genuinely doesn't matter within the
        range tested.
      - team_change_multiplier: VALIDATED (July 2026) — 0.0 is now the
        default, confirmed to beat 0.5 (the original, copied from
        Attempts) on held-out data (trained on 2024: 4.942 at 0.0 vs
        4.949 at 0.5; held-out 2025: 4.716 vs 4.756 — one of the LARGER
        validation gaps of the session). CORRECTED interpretation (a
        real mistake caught by external review): since prior_weight =
        prior_weight * team_change_multiplier, 0.0 means the prior
        season's data is DISCARDED ENTIRELY on a team change — the
        MAXIMUM possible penalty, not "no penalty" as originally
        (incorrectly) explained here. The real finding: when a QB
        changes teams, completely discarding their old team's
        completion% data predicts better than keeping any of it —
        the opposite conclusion from what was first written. The
        validated MAE numbers themselves were never wrong, only this
        explanation of what they meant. Fifth real, validated
        Completions improvement.
      - use_cpoe_model / cpoe_weight: an entirely different, CPOE-based
        challenger. completion_pct_baseline + QB's own CPOE, instead of
        the historical-blend approach — CPOE isolates completion
        performance relative to throw difficulty, which the raw
        historical blend can't separate from scheme/receiver/situation
        effects.

    Honest, explicit scope limits for this v1 (flagged, not hidden):
      - Does NOT yet have any of the bias corrections Attempts has —
        those need Completions' OWN backtest history first.
      - Opponent factor is still the RAW version (completions allowed /
        attempts faced) — a schedule-adjusted version (like the one
        built, tested, and REJECTED for Attempts) is a real possible
        upgrade, but per review: backtest the simple version first,
        don't build the complex one before learning if the basic factor
        even helps — exactly the lesson Attempts' own schedule-adjustment
        experiment already taught us the hard way.
      - Pressure/blitz/sack-rate context still not verified or used.
      - Rookie / limited-sample labeling not yet added here.
    """
    try:
        attempts_result = run_nfl_pass_attempts_projection(qb_name, team, opponent, season, as_of_week=as_of_week)
        if not attempts_result:
            st.session_state.setdefault('_completions_fail_reasons', {})[qb_name] = "attempts_result was None/empty (the underlying Attempts projection itself failed)"
            return None
        projected_attempts = attempts_result['projection']

        def _weighted_pct(rows):
            """Attempt-weighted completion% (July 2026 review, item 1) —
            sums completions/sums attempts across games, instead of
            averaging each game's own ratio equally. A 45-attempt game
            carries more real information about a QB's true rate than a
            5-attempt game; equal-weighting treats them the same."""
            if rows.empty:
                return None
            total_attempts = rows['attempts'].sum()
            if total_attempts <= 0:
                return None
            return rows['completions'].sum() / total_attempts

        qb_rows, starter_filter_used = get_qb_starter_rows(qb_name, season, as_of_week)
        if 'completions' not in qb_rows.columns or 'attempts' not in qb_rows.columns:
            # Defense-in-depth (July 2026) — even if the current-season
            # fetch genuinely came back malformed, don't give up
            # immediately here. Treat it as zero current-season starts
            # and let the prior-season bridge below attempt a rescue,
            # exactly like it correctly does for a real week-1 QB with
            # legitimately zero current-season games. The real root cause
            # (an unguarded .apply(axis=1) call on an empty DataFrame,
            # which could throw and get silently caught, producing a
            # columnless DataFrame) is now fixed directly in
            # get_qb_starter_rows — this is just a second layer of safety
            # on top of that fix, not a replacement for it.
            st.session_state.setdefault('_completions_fail_reasons', {})[qb_name] = f"qb_rows missing completions/attempts columns (columns found: {list(qb_rows.columns)}) — falling back to treating as zero current-season starts"
            qb_rows = pd.DataFrame(columns=['completions', 'attempts', 'week', 'team'])
        qb_rows = qb_rows.sort_values('week')
        qb_rows = qb_rows[qb_rows['attempts'] > 0]  # avoid divide-by-zero on a genuinely attempt-less row
        qb_rows['game_completion_pct'] = qb_rows['completions'] / qb_rows['attempts']
        starts_this_season = len(qb_rows)

        # Prior-season bridge (July 2026) — reused via the shared helper,
        # now with testable bridge_schedule and team_change_multiplier
        # (review items 2), instead of always copying Attempts' exact
        # schedule and penalty.
        prior_qb_rows, prior_weight, team_changed, prior_starter_filter_used = compute_prior_season_bridge(
            qb_name, season, team, as_of_week, starts_this_season,
            bridge_schedule=bridge_schedule, team_change_multiplier=team_change_multiplier,
        )
        if not prior_qb_rows.empty and 'completions' in prior_qb_rows.columns and 'attempts' in prior_qb_rows.columns:
            prior_qb_rows = prior_qb_rows[prior_qb_rows['attempts'] > 0].copy()
            prior_qb_rows['game_completion_pct'] = prior_qb_rows['completions'] / prior_qb_rows['attempts']

        combined_available = starts_this_season + len(prior_qb_rows)
        if combined_available < 3:
            st.session_state.setdefault('_completions_fail_reasons', {})[qb_name] = f"combined_available={combined_available} (starts_this_season={starts_this_season}, prior_qb_rows={len(prior_qb_rows)}, prior_weight={prior_weight}, prior_starter_filter_used={prior_starter_filter_used})"
            return None

        current_weight = 1 - prior_weight
        combined_rows = pd.concat([prior_qb_rows, qb_rows]).reset_index(drop=True) if not prior_qb_rows.empty else qb_rows

        if completion_weighting == 'attempt_weighted':
            current_season_pct = _weighted_pct(qb_rows)
            prior_season_pct = _weighted_pct(prior_qb_rows)
            last5_pct = _weighted_pct(combined_rows.tail(5))
            last10_pct = _weighted_pct(combined_rows.tail(10))
        else:
            current_season_pct = qb_rows['game_completion_pct'].mean() if not qb_rows.empty else None
            prior_season_pct = prior_qb_rows['game_completion_pct'].mean() if not prior_qb_rows.empty else None
            last5_pct = combined_rows['game_completion_pct'].tail(5).mean()
            last10_pct = combined_rows['game_completion_pct'].tail(10).mean()

        if prior_weight > 0 and prior_season_pct is not None:
            season_pct = (prior_season_pct * prior_weight) + (current_season_pct * current_weight) if current_season_pct is not None else prior_season_pct
        else:
            season_pct = current_season_pct

        base_completion_pct = (season_pct * 0.45) + (last5_pct * 0.35) + (last10_pct * 0.20)

        baselines = get_nfl_league_baselines(season, as_of_week)

        # CPOE-based challenger (July 2026 review) — an entirely
        # different approach from the historical-blend one above. Raw
        # completion% mixes accuracy, throw difficulty, depth of target,
        # receiver separation, game situation, and scheme all together;
        # CPOE (completion percentage over expected) attempts to isolate
        # completion PERFORMANCE specifically relative to throw
        # difficulty. cpoe_projection = league baseline + QB's own CPOE,
        # optionally dampened via cpoe_weight. Does NOT replace
        # base_completion_pct by default (use_cpoe_model=False) — this
        # is a genuine challenger to backtest against the historical
        # version, not an assumed improvement.
        #
        # use_cpoe_model (FULL REPLACEMENT) was tested and REJECTED —
        # the historical blend won outright (4.942 vs 4.954 on training,
        # no validation even needed). Per a follow-up review: full
        # replacement losing doesn't mean CPOE has zero signal — it may
        # just mean throwing away the historical model entirely was too
        # aggressive. cpoe_blend_weight tests a genuinely different idea:
        # MIXING a small amount of CPOE into the historical projection
        # instead of swapping it out. Defaults to 0.0 (no blend, same as
        # today) — untested until run through the optimizer.
        qb_cpoe = None
        if (use_cpoe_model or cpoe_blend_weight > 0) and 'passing_cpoe' in combined_rows.columns:
            qb_cpoe = combined_rows['passing_cpoe'].tail(10).mean()
            if pd.notna(qb_cpoe):
                # nflverse stores passing_cpoe as percentage points (e.g.
                # 3.5 means +3.5 percentage points), not a decimal — added
                # directly to the baseline, which IS a decimal (e.g. 0.64).
                cpoe_completion_pct = baselines['completion_pct_baseline'] + ((qb_cpoe / 100) * cpoe_weight)
                if use_cpoe_model:
                    base_completion_pct = cpoe_completion_pct
                elif cpoe_blend_weight > 0:
                    base_completion_pct = ((1 - cpoe_blend_weight) * base_completion_pct) + (cpoe_blend_weight * cpoe_completion_pct)

        opp_completion_pct_allowed = get_nfl_opponent_completion_pct_allowed(season, opponent, as_of_week)

        # Opponent factor — dampened, same multiplicative-deviation
        # pattern as every other opponent adjustment built this session.
        opp_factor = 1.0
        if opp_completion_pct_allowed is not None:
            opp_factor = 1 + ((opp_completion_pct_allowed / baselines['completion_pct_baseline']) - 1) * 0.4

        # Weather — wind hurts completion rate too, not just volume.
        # Reuses the same game_context already fetched inside the
        # Attempts call (available via attempts_result), not a second
        # separate fetch.
        weather_factor = 1.0
        game_context = attempts_result.get('game_context')
        if game_context:
            wind = game_context.get('wind')
            roof = game_context.get('roof')
            if roof in ('outdoors', 'open') and wind is not None and wind >= 15:
                weather_factor = 0.96  # a real, if modest, completion-rate hit in genuine wind

        projected_completion_pct = base_completion_pct * opp_factor * weather_factor
        projected_completion_pct = max(0.40, min(0.80, projected_completion_pct))  # sanity bounds — a real NFL completion% is never outside this range
        projected_completions = projected_attempts * projected_completion_pct

        # Confidence tier — sample size and completion-pct volatility
        # only (NOT architecture-gap-style disagreement — that signal was
        # PROVEN non-predictive for Attempts across two full seasons, so
        # it's not being reused here even informationally until Completions
        # has its own real backtest evidence one way or the other).
        #
        # Limited-sample check (per a follow-up external review) — added
        # to match Attempts' own "🔴 Limited NFL Sample" tier, which takes
        # priority over every other check. A rookie or a QB with
        # essentially no real career starts behaves genuinely differently
        # than a stable veteran with a temporarily volatile CV, even if
        # the raw numbers happen to look similar — worth a distinct
        # label rather than folding into the generic Volatile tier.
        is_limited_sample = starts_this_season < 3 and len(prior_qb_rows) == 0

        pct_history = combined_rows['game_completion_pct'].tail(10)
        pct_cv = (pct_history.std() / pct_history.mean()) if len(pct_history) > 1 and pct_history.mean() > 0 else 1.0
        if is_limited_sample:
            confidence_tier = "🔴 Limited NFL Sample"
        elif len(combined_rows) < 4 or pct_cv > 0.20:
            confidence_tier = "🔴 Volatile — Consider Pass"
        elif len(combined_rows) >= 8 and pct_cv < 0.12:
            confidence_tier = "🟢 Reliable"
        else:
            confidence_tier = "🟠 Moderate"

        # Bias corrections (July 2026) — real, cross-season-confirmed via
        # residual analysis: this model systematically UNDER-projects
        # (Actual - Projection was positive in BOTH 2024 and 2025), with
        # a real, replicated gradient that gets progressively worse in
        # less-reliable tiers (Reliable: -0.08/+0.65, Moderate:
        # +0.66/+1.03, Volatile: +2.36/+3.42 across the two seasons).
        # Opposite direction from Attempts' corrections (which were all
        # downward) — these are all upward.
        #
        # completions_bias_correction (flat, all tiers) was tested and
        # REJECTED — overfit (clean peak on training, worse than 0% on
        # held-out validation), likely because it got pulled around by
        # Reliable tier's small, direction-unstable bias. Left at 0.0.
        #
        # completions_moderate_tier_correction was grid-searched and
        # VALIDATED on held-out data (trained on 2024: 4.998 at 0% vs
        # 4.901 at 6% — a real, decisive gap; validated on 2025: 4.783
        # vs 4.765 — confirmed the training signal generalizes). Now the
        # default (0.06) — the first real, validated Completions
        # correction of the session.
        #
        # completions_volatile_tier_correction was grid-searched and
        # VALIDATED on held-out data (trained on 2024: 4.901 at 0% vs
        # 4.808 at 20% — a real, decisive gap; validated on 2025: 4.765
        # vs 4.751 — confirmed the training signal generalizes). Now the
        # default (0.20) — the third real, validated Completions
        # correction of the session, and the largest single adjustment
        # of the three, matching the fact it addressed the largest bias.
        if completions_bias_correction != 0:
            projected_completions = projected_completions * (1 + completions_bias_correction)
        if completions_moderate_tier_correction != 0 and confidence_tier == "🟠 Moderate":
            projected_completions = projected_completions * (1 + completions_moderate_tier_correction)
        if completions_volatile_tier_correction != 0 and confidence_tier == "🔴 Volatile — Consider Pass":
            projected_completions = projected_completions * (1 + completions_volatile_tier_correction)

        return {
            'projection': round(projected_completions, 1),
            'projected_attempts': round(projected_attempts, 1),
            'projected_completion_pct': round(projected_completion_pct, 3),
            'base_completion_pct': round(base_completion_pct, 3),
            'season_completion_pct': round(season_pct, 3) if season_pct is not None else None,
            'last5_completion_pct': round(last5_pct, 3),
            'last10_completion_pct': round(last10_pct, 3),
            'opp_completion_pct_allowed': round(opp_completion_pct_allowed, 3) if opp_completion_pct_allowed is not None else None,
            'opp_factor': round(opp_factor, 3),
            'weather_factor': round(weather_factor, 3),
            'confidence_tier': confidence_tier,
            'completion_pct_cv': round(pct_cv, 3),
            'games_used': len(combined_rows),
            'starts_this_season': starts_this_season, 'prior_season_weight': round(prior_weight, 2),
            'team_changed': team_changed, 'is_limited_sample': is_limited_sample,
            'starter_filter_used': starter_filter_used, 'prior_starter_filter_used': prior_starter_filter_used,
            'completion_weighting_used': completion_weighting, 'bridge_schedule_used': bridge_schedule,
            'team_change_multiplier_used': team_change_multiplier,
            'use_cpoe_model_used': use_cpoe_model, 'qb_cpoe': round(qb_cpoe, 2) if qb_cpoe is not None and pd.notna(qb_cpoe) else None,
            'cpoe_blend_weight_used': cpoe_blend_weight,
            'completions_bias_correction_used': completions_bias_correction,
            'completions_moderate_tier_correction_used': completions_moderate_tier_correction,
            'completions_volatile_tier_correction_used': completions_volatile_tier_correction,
        }
    except Exception as e:
        if st.session_state.get("_nfl_debug_mode"): raise
        return None

def run_nfl_receptions_projection(player_name, team, opponent, qb_name, season, as_of_week=None,
                                    target_share_weighting='target_weighted', bridge_schedule='attempts',
                                    team_change_prior_retention=0.0, min_targets=0, use_opponent_factor=False):
    """v1 Receptions model (July 2026) — genuinely different structure
    from Attempts/Completions: this is a WR/TE stat, not a QB stat.

    projected_receptions = projected_team_attempts x player_target_share x player_catch_rate

    Requires qb_name explicitly (the team's real starting QB for this
    game) — reuses run_nfl_pass_attempts_projection DIRECTLY for the
    team volume component, same "reuse what's already validated"
    pattern as Completions reusing Attempts. For backtesting, qb_name
    comes straight from the schedule (home_qb_name/away_qb_name); for
    live use, the caller needs to know the real starter, same
    requirement Attempts and Completions already have.

    Uses get_wr_te_rows and compute_receptions_prior_season_bridge (both
    genuinely separate from the QB-specific versions, not shared/
    refactored — same safe-copy pattern used building Completions,
    protecting the already-validated code those other two models depend
    on). Target share is computed DIRECTLY as sum(player_targets) /
    sum(team_targets) via a real team_targets aggregate
    (get_nfl_team_game_targets) and a derived_target_share column built
    right after that merge — NOT read from nflverse's precomputed
    target_share column (an earlier version of this docstring said the
    opposite; that was stale from round 1 and left uncorrected through
    rounds 3 and 5, which is when the actual behavior changed — fixed
    here in round 6). The provider's target_share, if present, is no
    longer used anywhere in the production path.

    target_share_weighting defaults to 'target_weighted' (not 'equal')
    from day one — applying the attempt-weighting lesson validated for
    Completions immediately, instead of rediscovering it a third time:
    a game where a player saw 10 targets carries more real information
    about their true target share than a game where they saw 2.

    Honest, explicit scope limits for this v1 (flagged, not hidden):
      - min_targets now correctly defaults to 0 (fixed round 3) —
        filtering only happens if explicitly requested for testing.
        Note this counts real STAT ROWS, not necessarily every game
        actually played — some weekly player-stat datasets omit
        players with no recorded stats entirely, so a "0 targets"
        history may only capture games that produced a stat row, not a
        true active/game-played denominator. Labeled honestly rather
        than assumed equivalent (a real, still-open gap per external
        review).
      - NO bias corrections of any kind — zero backtest history exists
        for this model. Any correction would be a guess, not evidence.
      - Opponent factor requires 'opponent_team' to exist as a real
        column in the underlying data — verified defensively in
        get_nfl_defense_reception_stats, but if it's missing, this
        degrades gracefully to no opponent signal rather than crashing.
        use_opponent_factor now defaults to False (changed round 3) so
        the fair A-vs-B architectural comparison is the default
        behavior, not something a tester has to remember to set.
      - No live pipeline, no odds/props fetching yet (a real backtest
        UI DOES exist, with position/model/tier tracking — this line
        was itself stale until this round's docstring cleanup).
      - No rookie/limited-sample tier yet.
      - TE, WR, RB, and FB are treated identically here — no position-
        specific adjustment for the fact that they're typically covered
        and used differently. A real, plausible future refinement.
    """
    try:
        attempts_result = run_nfl_pass_attempts_projection(qb_name, team, opponent, season, as_of_week=as_of_week)
        if not attempts_result:
            return None
        projected_team_attempts = attempts_result['projection']

        rows, filter_used = get_wr_te_rows(player_name, season, as_of_week, min_targets=min_targets)
        # Real fix (July 2026, round 5, per external review, item 1) —
        # previously required 'target_share' to be present here, even
        # though the production calculation no longer depends on it. A
        # row with perfectly valid targets/receptions could be discarded
        # solely because the provider's precomputed share was missing.
        # Only genuinely required columns now.
        if 'targets' not in rows.columns or 'receptions' not in rows.columns:
            return None
        rows = rows.sort_values('week')

        # Real bug fix (July 2026, round 2, per external review): merge
        # in team_targets (the TRUE denominator of target_share) so
        # _weighted_share below can weight correctly. Weighting by the
        # player's own targets (the NUMERATOR) systematically biased the
        # weighted average upward — it disproportionately emphasized
        # exactly the games where the player happened to earn a large
        # share.
        team_targets_data = get_nfl_team_game_targets([int(season)])
        if not team_targets_data.empty and not rows.empty:
            rows = rows.merge(team_targets_data[['team', 'season', 'week', 'team_targets']], on=['team', 'season', 'week'], how='left')
        else:
            rows['team_targets'] = pd.NA

        # Real fix (July 2026, round 5, per external review, item 1) —
        # compute target share DIRECTLY from targets/team_targets rather
        # than depending on nflverse's precomputed target_share column
        # for validity/coverage purposes. The production math already
        # stopped depending on this column in round 3 (_weighted_share
        # computes the aggregate directly); this closes the remaining
        # gap where coverage, bridge decay, and confidence still quietly
        # depended on it. The provider's target_share (if present) stays
        # available separately for diagnostics only.
        rows['derived_target_share'] = rows['targets'] / rows['team_targets'].replace(0, pd.NA)

        # Real fix (July 2026, round 3, per external review, item 7) —
        # games_this_season previously counted ALL rows fetched, even
        # ones where the team_targets merge above would later fail
        # (missing denominator). That could distort the prior-season
        # bridge, phasing out prior data based on games that never
        # actually produced a usable target-share observation. Use the
        # count of rows with a VALID merge instead.
        valid_current_rows = rows.dropna(subset=['targets', 'team_targets', 'derived_target_share'])
        games_this_season = len(valid_current_rows)

        # Real fix (July 2026, round 5, per external review, item 2) —
        # the bridge previously fetched prior-season rows WITHOUT
        # passing min_targets through, meaning a threshold experiment
        # (testing 0/1/2/3) would filter the current season but leave
        # the prior season fully unfiltered — an inconsistent
        # comparison. Now passed through explicitly.
        prior_rows, prior_weight, team_changed, prior_filter_used = compute_receptions_prior_season_bridge(
            player_name, season, team, as_of_week, games_this_season,
            bridge_schedule=bridge_schedule, team_change_prior_retention=team_change_prior_retention,
            min_targets=min_targets,
        )
        if not prior_rows.empty and 'targets' not in prior_rows.columns:
            prior_rows = pd.DataFrame()  # defensive — shouldn't happen given get_wr_te_rows' own guards, but don't trust blindly
        if not prior_rows.empty:
            prior_team_targets_data = get_nfl_team_game_targets([int(season) - 1])
            if not prior_team_targets_data.empty:
                prior_rows = prior_rows.merge(prior_team_targets_data[['team', 'season', 'week', 'team_targets']], on=['team', 'season', 'week'], how='left')
            else:
                prior_rows['team_targets'] = pd.NA
            prior_rows['derived_target_share'] = prior_rows['targets'] / prior_rows['team_targets'].replace(0, pd.NA)

        # Real fix (July 2026, round 4, per external review) — explicit
        # sort by season+week after concatenation. Prior rows were
        # already being concatenated before current rows, so the order
        # was PROBABLY correct, but relying on that implicitly (rather
        # than sorting explicitly) is a real, avoidable dependency on
        # upstream ordering that a future change could silently break.
        combined_rows = pd.concat([prior_rows, rows]).reset_index(drop=True) if not prior_rows.empty else rows
        if not combined_rows.empty and 'season' in combined_rows.columns and 'week' in combined_rows.columns:
            combined_rows = combined_rows.sort_values(['season', 'week']).reset_index(drop=True)

        # Real fix (July 2026, round 3, per external review, item 2;
        # updated round 5, item 1) — sample-size checks, last5/last10,
        # confidence tier, and games_used now use derived_target_share
        # (computed directly from targets/team_targets), not the
        # provider's target_share column — closing the gap where a row
        # with genuinely valid targets/team_targets could be discarded
        # solely because the provider's precomputed share was missing.
        valid_combined_rows = combined_rows.dropna(subset=['targets', 'team_targets', 'derived_target_share']) if not combined_rows.empty else combined_rows
        merge_match_rate = combined_rows['team_targets'].notna().mean() if not combined_rows.empty and 'team_targets' in combined_rows.columns else 0.0

        # Real fix (July 2026, round 4, per external review) — catch
        # rate's recency windows previously used combined_rows.tail(n)
        # directly, which could include rows where the team_targets
        # merge failed. Catch rate itself doesn't need team_targets (it
        # only needs targets and receptions, both present without a
        # merge), so this wasn't mathematically WRONG — but it meant
        # target-share's "last 5" and catch-rate's "last 5" could
        # silently refer to different sets of games, an inconsistency
        # that should be intentional, not accidental. catch_rows is now
        # its own explicitly-named, independently-valid history.
        catch_rows = combined_rows.dropna(subset=['targets', 'receptions']) if not combined_rows.empty else combined_rows

        # Real fix (July 2026, round 6, per external review) — even
        # after the round-6 fix above (clearing prior_rows entirely when
        # retention is 0.0), a PARTIAL retention (e.g. 0.5) still had an
        # issue: base_share correctly respected the 50% weighting, but
        # last5/last10 recency windows still pulled in prior-team games
        # at their full, unreduced influence whenever the combined
        # window happened to include them — meaning the retention
        # parameter only ever controlled the base_share component, not
        # recency, volatility, or confidence. Per the reviewer: for a
        # genuine team change, "recent role" should reflect the
        # player's CURRENT team situation specifically, regardless of
        # how much prior-team weight the base rate retains — target
        # share in particular is heavily dependent on scheme, QB,
        # depth chart, and teammate competition, all of which reset on
        # a team change. The bridged base_share can still blend
        # 0.0/0.5/1.0 of prior information; recency now does not, once
        # a team change has actually happened.
        recent_share_rows = valid_current_rows if team_changed else valid_combined_rows
        recent_catch_rows = rows.dropna(subset=['targets', 'receptions']) if team_changed else catch_rows

        if len(valid_combined_rows) < 3:
            return None

        def _weighted_share(df):
            """Target-share weighted average — computes the aggregate
            DIRECTLY as sum(player_targets) / sum(team_targets) (fixed
            round 3), not dependent on the provider's target_share
            column at all (closed round 5) — no fallback to it either,
            since if team_targets is missing there's genuinely nothing
            reliable to compute a share from."""
            if df.empty or 'targets' not in df.columns or 'team_targets' not in df.columns:
                return None
            valid = df.dropna(subset=['targets', 'team_targets'])
            if valid.empty:
                return None
            total_team_targets = valid['team_targets'].sum()
            if total_team_targets <= 0:
                return None
            return valid['targets'].sum() / total_team_targets

        def _weighted_catch_rate(df):
            # Deliberately does NOT require team_targets — catch rate
            # only needs the player's own targets and receptions, both
            # already present directly on these rows without a merge.
            if df.empty:
                return None
            total_targets = df['targets'].sum()
            if total_targets <= 0:
                return None
            return df['receptions'].sum() / total_targets

        if target_share_weighting == 'target_weighted':
            season_share = _weighted_share(rows)
            prior_share = _weighted_share(prior_rows) if not prior_rows.empty else None
            last5_share = _weighted_share(recent_share_rows.tail(5))
            last10_share = _weighted_share(recent_share_rows.tail(10))
        else:
            # Real fix (July 2026, round 5, per external review, item 1)
            # — the 'equal' weighting branch also previously depended on
            # the provider's target_share column. Now uses
            # derived_target_share here too, for full consistency.
            season_share = rows['derived_target_share'].mean() if not rows.empty else None
            prior_share = prior_rows['derived_target_share'].mean() if not prior_rows.empty else None
            last5_share = recent_share_rows['derived_target_share'].tail(5).mean()
            last10_share = recent_share_rows['derived_target_share'].tail(10).mean()

        if prior_weight > 0 and prior_share is not None:
            current_weight = 1 - prior_weight
            base_share = (prior_share * prior_weight) + (season_share * current_weight) if season_share is not None else prior_share
        else:
            base_share = season_share

        if base_share is None:
            return None

        # Real fix (July 2026, round 2, per external review) — catch
        # rate previously just used combined_rows.tail(10) regardless of
        # the prior-season bridge weight, meaning early in a season it
        # silently mixed prior and current games together WITHOUT the
        # same explicit weighting logic target_share gets. Now bridged
        # the same way: current and prior catch rates computed
        # separately, blended by the real prior_weight, then combined
        # with last5/last10 — using the reviewer's suggested starting
        # weights (60/25/15, not target_share's 45/35/20), since catch
        # rate is generally noisier at the receiver level than QB
        # completion% (especially for low-target players), so leaning
        # more on the full bridged season average makes sense as a
        # starting hypothesis. These weights are untested and worth
        # comparing directly once real backtest data exists.
        current_catch_rate = _weighted_catch_rate(rows)
        prior_catch_rate = _weighted_catch_rate(prior_rows) if not prior_rows.empty else None
        last5_catch_rate = _weighted_catch_rate(recent_catch_rows.tail(5))
        last10_catch_rate = _weighted_catch_rate(recent_catch_rows.tail(10))

        if prior_weight > 0 and prior_catch_rate is not None:
            current_weight_cr = 1 - prior_weight
            bridged_catch_rate = (prior_catch_rate * prior_weight) + (current_catch_rate * current_weight_cr) if current_catch_rate is not None else prior_catch_rate
        else:
            bridged_catch_rate = current_catch_rate

        if bridged_catch_rate is None:
            bridged_catch_rate = last10_catch_rate  # fallback if the bridged version genuinely has nothing
        if bridged_catch_rate is None:
            return None

        base_catch_rate = (bridged_catch_rate * 0.60) + (last5_catch_rate * 0.25) + (last10_catch_rate * 0.15) if last5_catch_rate is not None and last10_catch_rate is not None else bridged_catch_rate

        blended_share = (base_share * 0.45) + (last5_share * 0.35) + (last10_share * 0.20) if last5_share is not None and last10_share is not None else base_share

        opp_factor = 1.0
        opp_targets_allowed, opp_catch_rate_allowed = None, None
        if use_opponent_factor:
            # Fairness fix (July 2026, round 2, updated round 3) — Model
            # A originally had an opponent factor, Model B doesn't. A
            # comparison with this on would answer "Model A + opponent
            # adjustment vs. Model B without one," not the actual
            # architectural question (attempts x target share x catch
            # rate vs. completions x completion share). Default is now
            # False (changed in round 3, per external review, since
            # defaulting to True and relying on a tester to remember to
            # turn it off was the same class of mistake as an earlier
            # Completions bug where Streamlit widgets silently overrode
            # validated defaults) — the fair comparison is now the
            # default behavior, not something to remember. Once a
            # winning architecture is picked, test the opponent factor
            # as a separate ablation on the winner alone.
            opp_targets_allowed, opp_catch_rate_allowed = get_nfl_opponent_reception_factor(season, opponent, as_of_week)
            baselines = get_nfl_league_baselines(season, as_of_week)
            if opp_catch_rate_allowed is not None and pd.notna(opp_catch_rate_allowed):
                opp_factor = 1 + ((opp_catch_rate_allowed / baselines['completion_pct_baseline']) - 1) * 0.4

        projected_target_share = max(0.02, min(0.45, blended_share))  # sanity bounds — a real WR/TE target share is essentially never outside this range
        projected_targets = projected_team_attempts * projected_target_share
        projected_catch_rate = max(0.35, min(0.90, base_catch_rate * opp_factor))
        projected_receptions = projected_targets * projected_catch_rate

        # Real fix (July 2026, round 6, per external review) — volatility
        # and confidence now also use recent_share_rows (current-team-
        # only after a team change), not valid_combined_rows directly —
        # completing the fix, since the reviewer explicitly flagged
        # share_cv, confidence_tier, and games_used as also affected by
        # this same leak, not just the recency windows above.
        share_history = recent_share_rows['derived_target_share'].tail(10)
        share_cv = (share_history.std() / share_history.mean()) if len(share_history) > 1 and share_history.mean() > 0 else 1.0
        # Real recalibration (July 2026) — these thresholds were
        # originally copied directly from the QB-tuned Attempts/
        # Completions values (0.20/0.35), never validated for receivers.
        # Target share is naturally far more volatile week to week than
        # QB attempt/completion volume, so that threshold was far too
        # strict — only ~0.75% of predictions were landing in Reliable
        # (vs. ~27% for Completions), and the tier ordering was
        # genuinely inverted on raw MAE as a result (though NOT on
        # MAE-as-%-of-volume, which was correctly ordered the whole
        # time — the raw inversion was a volume artifact, not a real
        # modeling problem). Recalibrated using the REAL CV distribution
        # from actual 2024 backtest data: tested splits from 33% down to
        # 10% directly, found a genuine, monotonic accuracy/bias
        # tradeoff (tighter splits kept improving MAE-of-volume but
        # introduced a real, growing over-projection bias) — 20% was
        # the deliberately chosen balance point: real accuracy gain over
        # the original default, bias still genuinely near zero, and a
        # large enough sample (687 real predictions) to trust.
        if len(recent_share_rows) < 4 or share_cv > 0.812:
            confidence_tier = "🔴 Volatile — Consider Pass"
        elif len(recent_share_rows) >= 8 and share_cv < 0.357:
            confidence_tier = "🟢 Reliable"
        else:
            confidence_tier = "🟠 Moderate"

        return {
            'projection': round(projected_receptions, 1),
            'projected_targets': round(projected_targets, 1),
            'projected_target_share': round(projected_target_share, 3),
            'projected_catch_rate': round(projected_catch_rate, 3),
            'projected_team_attempts': round(projected_team_attempts, 1),
            'base_target_share': round(base_share, 3) if base_share is not None else None,
            'base_catch_rate': round(base_catch_rate, 3),
            'opp_targets_allowed': round(opp_targets_allowed, 1) if opp_targets_allowed is not None and pd.notna(opp_targets_allowed) else None,
            'opp_catch_rate_allowed': round(opp_catch_rate_allowed, 3) if opp_catch_rate_allowed is not None and pd.notna(opp_catch_rate_allowed) else None,
            'confidence_tier': confidence_tier,
            'target_share_cv': round(share_cv, 3),
            'merge_match_rate': round(merge_match_rate, 3),
            'games_used': len(recent_share_rows), 'games_this_season': games_this_season,
            'prior_season_weight': round(prior_weight, 2), 'team_changed': team_changed,
            'filter_used': filter_used, 'prior_filter_used': prior_filter_used,
            'target_share_weighting_used': target_share_weighting, 'bridge_schedule_used': bridge_schedule,
        }
    except Exception as e:
        if st.session_state.get("_nfl_debug_mode"): raise
        return None

def run_nfl_receptions_model_b_projection(player_name, team, opponent, qb_name, season, as_of_week=None,
                                            bridge_schedule='attempts', team_change_prior_retention=0.0, min_targets=0):
    """Receptions Model B (July 2026) — a genuine, separate challenger to
    the Model A architecture above (team attempts x target share x catch
    rate), per external review: instead of building on Attempts, build
    on Completions (the more-validated of the two upstream models, with
    5 real, confirmed corrections vs. Attempts' own separate set) and
    use a receiver's share of TEAM COMPLETIONS directly, instead of the
    two-stage target-share x catch-rate structure.

    projected_receptions = projected_team_completions x completion_share

    completion_share = player's receptions / team's total completions,
    for each game — computed via get_nfl_team_game_completions (a real,
    new team-level aggregate, since this wasn't needed for Model A).
    Weighted by team_completions per game (a game where the team
    completed 30 passes carries more real information about the
    player's true share than a 15-completion game) — same attempt-
    weighting lesson applied consistently across every model this
    session, not just the first one it was validated on.

    Deliberately does NOT replace Model A — both exist side by side and
    should be backtested against each other on real data before
    deciding anything, same discipline as every other genuine
    architectural question resolved this session (CPOE, structural
    blend, schedule-adjustment). 'The data will tell you,' not either
    of us guessing which one sounds more elegant.

    Reuses get_wr_te_rows and compute_receptions_prior_season_bridge
    from Model A directly (the row-fetching and bridge logic don't
    actually depend on which volume model sits upstream) — only the
    share calculation and volume source differ between A and B.

    Same honest scope limits as Model A: zero backtest history, no
    corrections attempted, no rookie tier, TE/WR/RB/FB treated
    identically. min_targets now correctly defaults to 0 (fixed round
    3) — filtering only happens if a caller explicitly requests it for
    testing."""
    try:
        completions_result = run_nfl_pass_completions_projection(qb_name, team, opponent, season, as_of_week=as_of_week)
        if not completions_result:
            return None
        projected_team_completions = completions_result['projection']

        rows, filter_used = get_wr_te_rows(player_name, season, as_of_week, min_targets=min_targets)
        if 'receptions' not in rows.columns or 'team' not in rows.columns:
            return None
        rows = rows.sort_values('week')

        team_completions_data = get_nfl_team_game_completions([int(season)])
        if not team_completions_data.empty and not rows.empty:
            rows = rows.merge(team_completions_data[['team', 'season', 'week', 'team_completions']], on=['team', 'season', 'week'], how='left')
            rows['completion_share'] = rows['receptions'] / rows['team_completions'].replace(0, pd.NA)
        else:
            rows['team_completions'] = pd.NA
            rows['completion_share'] = pd.NA

        # Real fix (July 2026, round 3, per external review, item 7) —
        # games_this_season previously counted ALL rows fetched, even
        # ones where the team_completions merge above would later fail
        # (missing denominator). That could distort the prior-season
        # bridge, phasing out prior data based on games that never
        # actually produced a usable completion_share observation. Use
        # the count of rows with a VALID merge instead.
        valid_current_rows = rows.dropna(subset=['completion_share', 'team_completions'])
        games_this_season = len(valid_current_rows)

        prior_rows, prior_weight, team_changed, prior_filter_used = compute_receptions_prior_season_bridge(
            player_name, season, team, as_of_week, games_this_season,
            bridge_schedule=bridge_schedule, team_change_prior_retention=team_change_prior_retention,
            min_targets=min_targets,
        )
        if not prior_rows.empty and 'team' in prior_rows.columns:
            prior_team_completions_data = get_nfl_team_game_completions([int(season) - 1])
            if not prior_team_completions_data.empty:
                prior_rows = prior_rows.merge(prior_team_completions_data[['team', 'season', 'week', 'team_completions']], on=['team', 'season', 'week'], how='left')
                prior_rows['completion_share'] = prior_rows['receptions'] / prior_rows['team_completions'].replace(0, pd.NA)
            else:
                prior_rows = pd.DataFrame()

        # Real fix (July 2026, round 5, per external review, item 3) —
        # Model A got this explicit sort in round 4, Model B was missed.
        # Prior rows were already being concatenated before current
        # rows, so the order was PROBABLY correct, but relying on that
        # implicitly (rather than sorting explicitly) is a real,
        # avoidable dependency on upstream ordering.
        combined_rows = pd.concat([prior_rows, rows]).reset_index(drop=True) if not prior_rows.empty else rows
        if not combined_rows.empty and 'season' in combined_rows.columns and 'week' in combined_rows.columns:
            combined_rows = combined_rows.sort_values(['season', 'week']).reset_index(drop=True)

        # Real fix (July 2026, round 2, per external review) — the
        # minimum-sample check, last5/last10, confidence tier, and
        # games_used were all previously computed against combined_rows
        # BEFORE removing rows where the team_completions merge actually
        # failed (missing completion_share). That could overstate real
        # sample size and confidence — a row that never got a valid
        # completion_share shouldn't count as real evidence. Filter to
        # valid rows FIRST, then use that consistently everywhere below.
        valid_combined_rows = combined_rows.dropna(subset=['completion_share', 'team_completions']) if not combined_rows.empty else combined_rows
        merge_match_rate = combined_rows['team_completions'].notna().mean() if not combined_rows.empty and 'team_completions' in combined_rows.columns else 0.0

        if len(valid_combined_rows) < 3:
            return None

        # Real fix (July 2026, round 6, per external review) — same
        # issue found and fixed in Model A: even with prior_rows cleared
        # when retention drops to 0.0 (fixed at the bridge level this
        # round), a PARTIAL retention (e.g. 0.5) still let prior-team
        # games influence recency at full, unreduced weight — meaning
        # the retention parameter only ever controlled base_share, not
        # recency, volatility, or confidence. For a genuine team change,
        # "recent role" should reflect the player's CURRENT team
        # situation specifically, regardless of how much prior-team
        # weight the base rate retains.
        recent_share_rows = valid_current_rows if team_changed else valid_combined_rows

        def _weighted_comp_share(df):
            if df.empty or 'completion_share' not in df.columns:
                return None
            valid = df.dropna(subset=['completion_share', 'team_completions'])
            if valid.empty:
                return None
            weights = valid['team_completions'].clip(lower=0.1)
            if weights.sum() <= 0:
                return valid['completion_share'].mean()
            return (valid['completion_share'] * weights).sum() / weights.sum()

        season_share = _weighted_comp_share(rows)
        prior_share = _weighted_comp_share(prior_rows) if not prior_rows.empty else None
        last5_share = _weighted_comp_share(recent_share_rows.tail(5))
        last10_share = _weighted_comp_share(recent_share_rows.tail(10))

        if prior_weight > 0 and prior_share is not None:
            current_weight = 1 - prior_weight
            base_share = (prior_share * prior_weight) + (season_share * current_weight) if season_share is not None else prior_share
        else:
            base_share = season_share

        if base_share is None:
            return None

        blended_share = (base_share * 0.45) + (last5_share * 0.35) + (last10_share * 0.20) if last5_share is not None and last10_share is not None else base_share
        projected_completion_share = max(0.02, min(0.45, blended_share))
        projected_receptions = projected_team_completions * projected_completion_share

        share_history = recent_share_rows['completion_share'].tail(10)
        share_cv = (share_history.std() / share_history.mean()) if len(share_history) > 1 and share_history.mean() > 0 else 1.0
        if len(recent_share_rows) < 4 or share_cv > 0.35:
            confidence_tier = "🔴 Volatile — Consider Pass"
        elif len(recent_share_rows) >= 8 and share_cv < 0.20:
            confidence_tier = "🟢 Reliable"
        else:
            confidence_tier = "🟠 Moderate"

        return {
            'projection': round(projected_receptions, 1),
            'projected_team_completions': round(projected_team_completions, 1),
            'projected_completion_share': round(projected_completion_share, 3),
            'base_completion_share': round(base_share, 3) if base_share is not None else None,
            'confidence_tier': confidence_tier,
            'merge_match_rate': round(merge_match_rate, 3),
            'completion_share_cv': round(share_cv, 3),
            'games_used': len(recent_share_rows), 'games_this_season': games_this_season,
            'prior_season_weight': round(prior_weight, 2), 'team_changed': team_changed,
            'filter_used': filter_used, 'prior_filter_used': prior_filter_used,
            'bridge_schedule_used': bridge_schedule, 'model': 'B_completion_share',
        }
    except Exception as e:
        if st.session_state.get("_nfl_debug_mode"): raise
        return None

# Real fix (August 2026) — same real reasoning as the Completions
# loader above.
@st.cache_data(ttl=300, show_spinner=False)
def load_nfl_receptions_props_data():
    """Fetches today's live NFL player_receptions props (July 2026) —
    structurally closer to load_nba_props_data() than to
    load_nfl_props_data(), since receivers (like NBA players) aren't
    tied to a single QB-per-team structure the way Attempts/Completions
    are. Keyed by receiver name; tracks home/away team the same way so
    the display and downstream lookup can match it to a real team side.
    Same per-event error isolation and stale-game skip as every other
    NFL props loader.

    Real fix (August 2026, per direct user report — NFL alone eating
    ~99 of ~120 real total auto-run seconds). Now shares the real,
    expensive network calls via _fetch_nfl_events_and_props_combined()
    instead of independently re-fetching the same real events list and
    making its own separate real per-event API call. This function's
    OWN parsing loop below is completely UNCHANGED."""
    try:
        combined = _fetch_nfl_events_and_props_combined()
        all_receivers = {}

        for event_id, event_info in combined.items():
            home = event_info['home']
            away = event_info['away']
            commence_time_str = event_info['commence_time']
            props_data = event_info['props_data']

            for bookmaker in props_data.get('bookmakers', []):
                book_title = bookmaker.get('title', bookmaker.get('key', ''))
                is_primary = bookmaker['key'] in ['fanduel', 'draftkings']

                for market in bookmaker.get('markets', []):
                    if market.get('key') == 'player_receptions':
                        for outcome in market.get('outcomes', []):
                            receiver_name = outcome.get('description')
                            if not receiver_name:
                                continue
                            if receiver_name not in all_receivers:
                                all_receivers[receiver_name] = {
                                    'home': home, 'away': away, 'commence_time': commence_time_str,
                                    'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                    'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                    'Projection': None, 'Edge': None, 'Play': None,
                                    'Tier': None, 'EV%': None, 'MM Tier': None, 'Low Confidence': None,
                                    'Fair Odds': None, 'Edge Cents': None, 'Direction': None, 'Odds': None,
                                    'Model Prob': None, 'No Vig Prob': None,
                                    '_book_odds_raw': {},
                                    'odds_api_event_id': event_id,
                                    'odds_api_sport': 'americanfootball_nfl',
                                    'odds_api_market': 'player_receptions',
                                }
                            if is_primary:
                                if 'FanDuel' in book_title or bookmaker['key'] == 'fanduel':
                                    all_receivers[receiver_name]['FanDuel Line'] = outcome.get('point')
                                    if outcome.get('name') == 'Over':
                                        all_receivers[receiver_name]['FanDuel Over'] = outcome.get('price')
                                    else:
                                        all_receivers[receiver_name]['FanDuel Under'] = outcome.get('price')
                                elif 'DraftKings' in book_title or bookmaker['key'] == 'draftkings':
                                    all_receivers[receiver_name]['DraftKings Line'] = outcome.get('point')
                                    if outcome.get('name') == 'Over':
                                        all_receivers[receiver_name]['DraftKings Over'] = outcome.get('price')
                                    else:
                                        all_receivers[receiver_name]['DraftKings Under'] = outcome.get('price')
                            bor = all_receivers[receiver_name].setdefault('_book_odds_raw', {})
                            if book_title not in bor:
                                bor[book_title] = {'book': book_title, 'line': outcome.get('point'), 'over': None, 'under': None}
                            if outcome.get('name') == 'Over':
                                bor[book_title]['over'] = outcome.get('price')
                            else:
                                bor[book_title]['under'] = outcome.get('price')
                            bor[book_title]['line'] = outcome.get('point')
        for rec in all_receivers.values():
            raw = rec.pop('_book_odds_raw', {})
            rec['book_odds'] = sorted(raw.values(), key=lambda b: b.get('book', ''))
        return all_receivers
    except Exception as e:
        st.session_state['_nfl_receptions_props_load_error'] = str(e)
        return {}

def evaluate_nfl_receptions_quotes(info, proj, cv, confidence_tier):
    """Receptions version of evaluate_nfl_quotes — same real, validated
    fixes carried over. Uses the real 'nfl_receptions' sport key, which
    now has its own calibrated get_min_std_dev branch built alongside
    this pipeline."""
    quotes = []
    if info.get('FanDuel Line') is not None:
        quotes.append({'book': 'FanDuel', 'line': info['FanDuel Line'], 'over_odds': info.get('FanDuel Over'), 'under_odds': info.get('FanDuel Under')})
    if info.get('DraftKings Line') is not None:
        quotes.append({'book': 'DraftKings', 'line': info['DraftKings Line'], 'over_odds': info.get('DraftKings Over'), 'under_odds': info.get('DraftKings Under')})

    best = None
    for quote in quotes:
        line = quote['line']
        if line is None or abs(proj - line) < 0.05:
            continue
        if quote['over_odds'] is None or quote['under_odds'] is None:
            continue
        direction = 'over' if proj > line else 'under'
        selected_odds = quote['over_odds'] if direction == 'over' else quote['under_odds']
        std_dev = get_min_std_dev(cv, proj, sport='nfl_receptions')
        ev_result = analyze_prop(
            projection=proj, line=line, std_dev=std_dev, cv=cv,
            over_odds=quote['over_odds'], under_odds=quote['under_odds'],
            direction=direction, sport='nfl_receptions',
            workload_tier=None, confidence_tier=confidence_tier,
        )
        if ev_result and (best is None or (ev_result.get('ev_pct') or -999) > (best['ev_result'].get('ev_pct') or -999)):
            best = {'ev_result': ev_result, 'book': quote['book'], 'line': line, 'direction': direction, 'odds': selected_odds}
    return best

def run_all_nfl_receptions_projections(all_receivers, season, progress_callback=None):
    """Receptions version of run_all_nfl_projections — the one genuinely
    different piece versus Attempts/Completions: Model A requires the
    team's real starting QB as an explicit input, which Attempts/
    Completions don't need since they ARE the QB-level stat. Solves
    this by fetching live Attempts props internally (real, current
    sportsbook data — books only post QB attempts props for the actual
    starter) to build a team->QB map for this week's games, falling
    back to each team's most recent QB from weekly stats if a
    particular team's QB props haven't been posted yet. Uses
    Receptions Model A (run_nfl_receptions_projection) with its locked-
    in, recalibrated defaults — target_weighted weighting, min_targets=0,
    team_change_prior_retention=0.0, use_opponent_factor=False (tested
    and found to make things worse), and the real, data-driven
    0.357/0.812 confidence tier thresholds."""
    results = {}
    total = len(all_receivers)
    name_to_abbrev = {v: k for k, v in nfl_abbrev_to_name.items()}
    weekly_all = get_nfl_player_stats([int(season)])

    # Build the team->starting-QB map from live Attempts props first —
    # real, current sportsbook data on who's actually starting.
    team_to_qb = {}
    try:
        live_qb_props = load_nfl_props_data()
        for qb_name, qb_info in live_qb_props.items():
            qb_recent = weekly_all[(weekly_all['player_display_name'] == qb_name) & (weekly_all['position'] == 'QB')].sort_values('week')
            if not qb_recent.empty:
                team_to_qb[qb_recent.iloc[-1]['team']] = qb_name
    except Exception:
        pass  # falls through to the per-receiver weekly-stats fallback below

    for i, (receiver_name, info) in enumerate(all_receivers.items()):
        if progress_callback:
            progress_callback(i, total, receiver_name)

        home_team, away_team = info['home'], info['away']
        home_abbrev = name_to_abbrev.get(home_team)
        away_abbrev = name_to_abbrev.get(away_team)

        try:
            receiver_recent = weekly_all[(weekly_all['player_display_name'] == receiver_name) & (weekly_all['position'].isin(RECEPTION_POSITIONS))].sort_values('week')
            if receiver_recent.empty:
                continue
            receiver_team_abbrev = receiver_recent.iloc[-1]['team']
            opp_abbrev = away_abbrev if receiver_team_abbrev == home_abbrev else (home_abbrev if receiver_team_abbrev == away_abbrev else None)
            if opp_abbrev is None:
                continue
        except Exception:
            continue

        # Real starting-QB lookup — try the live props map first, then
        # fall back to this team's most recent QB from weekly stats
        # (e.g. if that team's QB props haven't posted yet, or the QB
        # market failed to load for any reason).
        starting_qb = team_to_qb.get(receiver_team_abbrev)
        if not starting_qb:
            try:
                team_qb_recent = weekly_all[(weekly_all['team'] == receiver_team_abbrev) & (weekly_all['position'] == 'QB')].sort_values('week')
                if not team_qb_recent.empty:
                    starting_qb = team_qb_recent.iloc[-1]['player_display_name']
            except Exception:
                pass
        if not starting_qb:
            all_receivers[receiver_name].update({'Tier': "🔴 Data Incomplete — Pass", 'Pass Reason': "Could not identify this team's starting QB"})
            continue

        game_week = find_upcoming_nfl_week(season, home_abbrev, away_abbrev, commence_time_str=info.get('commence_time'))
        if game_week is None:
            all_receivers[receiver_name].update({'Tier': "🔴 Data Incomplete — Pass", 'Pass Reason': "Could not match the live event to an NFL week"})
            continue
        result = cached_run_nfl_projection(
            run_nfl_receptions_projection, 'NFL_RECEPTIONS', receiver_name, mm_today_str(),
            receiver_name, receiver_team_abbrev, opp_abbrev, starting_qb, int(season), as_of_week=game_week,
        )

        if result:
            proj = result['projection']
            quote = evaluate_nfl_receptions_quotes(info, proj, result['target_share_cv'], result.get('confidence_tier'))
            if quote:
                ev_result, best_book, best_line, direction, selected_odds = quote['ev_result'], quote['book'], quote['line'], quote['direction'], quote['odds']
                edge = round(proj - best_line, 1)
                play = "⬆️ OVER" if direction == 'over' else "⬇️ UNDER"
                all_receivers[receiver_name].update({
                    'Projection': proj, 'Edge': edge, 'Play': play,
                    'Tier': result['confidence_tier'],
                    'EV%': ev_result['ev_pct'] if ev_result else None,
                    'Raw EV%': ev_result['raw_ev_pct'] if ev_result else None,
                    'MM Tier': ev_result['tier'] if ev_result else None,
                    'Pass Reason': ev_result['pass_reason'] if ev_result else None,
                    'Confidence Level': ev_result['confidence_level'] if ev_result else None,
                    'Low Confidence': ev_result['low_confidence'] if ev_result else None,
                    'Fair Odds': ev_result['fair_odds'] if ev_result else None,
                    'Effective Std': ev_result['effective_std'] if ev_result else None,
                    'Adjusted Projection': ev_result['adjusted_projection'] if ev_result else None,
                    'Opposite Odds': ev_result['opposite_odds'] if ev_result else None,
                    'Edge Cents': ev_result['edge_cents'] if ev_result else None,
                    'Direction': direction,
                    'Odds': selected_odds,
                    'Model Prob': ev_result['model_prob'] if ev_result else None,
                    'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
                    'Book': best_book,
                })
                results[receiver_name] = result
                save_prediction({
                    'date': mm_today_str(),
                    'pitcher': receiver_name, 'opponent': opp_abbrev, 'home_team': home_team,
                    'projection': proj, 'base': result.get('base_target_share'), 'book_line': best_line,
                    'edge': edge, 'cv': result['target_share_cv'], 'confidence_tier': result['confidence_tier'],
                    'actual': None, 'sport': 'NFL_RECEPTIONS',
                    'ev_pct': ev_result['ev_pct'] if ev_result else None,
                    'mm_tier': ev_result['tier'] if ev_result else None,
                    'model_prob': ev_result['model_prob'] if ev_result else None,
                    'no_vig_prob': ev_result['no_vig_prob'] if ev_result else None,
                    'book': best_book, 'odds': selected_odds, 'direction': direction,
                    'game_week': game_week, 'commence_time': info.get('commence_time'),
                })
    return results



# ---- NFL ANYTIME TOUCHDOWN MODEL (August 2026) ----
TD_ELIGIBLE_POSITIONS = ('RB', 'WR', 'TE', 'QB')

def load_nfl_td_props_data():
    try:
        if '_nfl_combined_events_cache' not in st.session_state:
            combined = _fetch_nfl_events_and_props_combined()
            st.session_state['_nfl_combined_events_cache'] = combined
        else:
            combined = st.session_state['_nfl_combined_events_cache']
        all_players = {}
        for event_id, event_info in combined.items():
            home = event_info['home']
            away = event_info['away']
            commence_time_str = event_info['commence_time']
            props_data = event_info['props_data']
            for bookmaker in props_data.get('bookmakers', []):
                book_title = bookmaker.get('title', bookmaker.get('key', ''))
                for market in bookmaker.get('markets', []):
                    if market.get('key') != 'player_anytime_td':
                        continue
                    for outcome in market.get('outcomes', []):
                        if outcome.get('name') != 'Yes':
                            continue
                        player = outcome.get('description')
                        if not player:
                            continue
                        odds = outcome.get('price')
                        if odds is None:
                            continue
                        if player not in all_players:
                            all_players[player] = {
                                'home': home, 'away': away, 'commence_time': commence_time_str,
                                'td_odds': None, 'td_book': None, '_td_book_odds': {},
                                'Projection': None, 'Model Prob': None, 'Implied Prob': None,
                                'EV%': None, 'MM Tier': None, 'Direction': 'td', 'Odds': None,
                                'Fair Odds': None, 'Edge Cents': None, 'Low Confidence': None,
                                'odds_api_event_id': event_id,
                                'odds_api_sport': 'americanfootball_nfl',
                                'odds_api_market': 'player_anytime_td',
                            }
                        all_players[player]['_td_book_odds'][book_title] = {'book': book_title, 'odds': odds}
                        current_best = all_players[player]['td_odds']
                        if current_best is None or odds > current_best:
                            all_players[player]['td_odds'] = odds
                            all_players[player]['td_book'] = book_title
        for player in all_players.values():
            raw = player.pop('_td_book_odds', {})
            player['book_odds'] = sorted(
                [{'book': v['book'], 'line': None, 'over': v['odds'], 'under': None} for v in raw.values()],
                key=lambda b: b.get('book', ''))
        return all_players
    except Exception as e:
        st.session_state['_nfl_td_props_load_error'] = str(e)
        return {}


def american_odds_to_implied_prob(odds):
    if odds is None:
        return None
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def run_all_nfl_td_projections(all_players, season, progress_callback=None):
    """NFL Anytime TD model V1.4 (August 2026).

    Architecture: Opportunity x Efficiency = Expected TDs -> Poisson.

    V1.4 fixes:
    1. Opponent adjustment DISABLED — V1.3 used skill-player TDs only,
       missing passing TDs entirely. Worse than nothing.
    2. Separated opportunity from efficiency — no double-counting.
    3. Removed TD-history blend — purely volume x regressed efficiency.
    """
    from math import exp
    results = {}
    # Load BOTH current and prior season — blend them for early weeks
    # using the same 7-week bridge that won the bridge experiment.
    # This is the key early-season fix: in Week 3, the model has only
    # 2 games of current data. Without prior-season blending, it's
    # working with almost nothing. With blending, it anchors to a
    # full season of prior data and gradually transitions.
    try:
        weekly = get_nfl_player_stats([int(season)])
    except Exception:
        try:
            weekly = get_nfl_player_stats([int(season) - 1])
        except Exception:
            return results

    try:
        prior_weekly = get_nfl_player_stats([int(season) - 1])
    except Exception:
        prior_weekly = pd.DataFrame()

    name_to_abbrev = {v: k for k, v in nfl_abbrev_to_name.items()}
    skill_players = weekly[weekly['position'].isin(TD_ELIGIBLE_POSITIONS)].copy()
    if skill_players.empty:
        return results

    prior_skill = prior_weekly[prior_weekly['position'].isin(TD_ELIGIBLE_POSITIONS)].copy() if not prior_weekly.empty else pd.DataFrame()

    # Add total_tds to both datasets
    for df in [skill_players, prior_skill]:
        if df.empty:
            continue
        if 'rushing_tds' in df.columns and 'receiving_tds' in df.columns:
            df['total_tds'] = df['rushing_tds'].fillna(0) + df['receiving_tds'].fillna(0)
        elif 'rushing_tds' in df.columns:
            df['total_tds'] = df['rushing_tds'].fillna(0)
        if 'carries' not in df.columns:
            df['carries'] = 0
        if 'targets' not in df.columns:
            df['targets'] = 0
        df['carries'] = df['carries'].fillna(0)
        df['targets'] = df['targets'].fillna(0)

    if 'total_tds' not in skill_players.columns:
        return results

    # Position-specific league baselines for efficiency and volume
    pos_efficiency = {}
    pos_opportunity = {}
    for pos in TD_ELIGIBLE_POSITIONS:
        pos_data = skill_players[skill_players['position'] == pos]
        if len(pos_data) == 0:
            continue
        if pos in ('WR', 'TE') and 'targets' in pos_data.columns:
            t_targets = pos_data['targets'].fillna(0).sum()
            t_tds = pos_data['total_tds'].sum()
            pos_efficiency[pos] = t_tds / t_targets if t_targets > 0 else 0.05
            pos_opportunity[pos] = pos_data['targets'].fillna(0).mean()
        elif pos == 'RB':
            t_carries = pos_data['carries'].fillna(0).sum() if 'carries' in pos_data.columns else 0
            t_targets = pos_data['targets'].fillna(0).sum() if 'targets' in pos_data.columns else 0
            t_touches = t_carries + t_targets
            t_tds = pos_data['total_tds'].sum()
            pos_efficiency[pos] = t_tds / t_touches if t_touches > 0 else 0.04
            a_carries = pos_data['carries'].fillna(0).mean() if 'carries' in pos_data.columns else 10
            a_targets = pos_data['targets'].fillna(0).mean() if 'targets' in pos_data.columns else 2
            pos_opportunity[pos] = a_carries + a_targets
        elif pos == 'QB' and 'carries' in pos_data.columns:
            t_rushes = pos_data['carries'].fillna(0).sum()
            t_rush_tds = pos_data['rushing_tds'].fillna(0).sum() if 'rushing_tds' in pos_data.columns else pos_data['total_tds'].sum()
            pos_efficiency[pos] = t_rush_tds / t_rushes if t_rushes > 0 else 0.03
            pos_opportunity[pos] = pos_data['carries'].fillna(0).mean()

    team_col = 'recent_team' if 'recent_team' in skill_players.columns else ('team' if 'team' in skill_players.columns else None)
    # Opponent defense: DISABLED V1.4 — see docstring
    count = 0
    total = len(all_players)

    for player_name, info in all_players.items():
        count += 1
        if progress_callback and count % 5 == 0:
            progress_callback(count, total, f"TD model: {player_name}")
        td_odds = info.get('td_odds')
        if td_odds is None:
            continue
        player_rows = weekly[weekly['player_display_name'] == player_name].sort_values('week')
        if player_rows.empty:
            continue
        player_pos = player_rows.iloc[-1].get('position', '')
        if player_pos not in TD_ELIGIBLE_POSITIONS:
            continue
        player_rows = player_rows.copy()
        if 'rushing_tds' in player_rows.columns and 'receiving_tds' in player_rows.columns:
            player_rows['total_tds'] = player_rows['rushing_tds'].fillna(0) + player_rows['receiving_tds'].fillna(0)
        elif 'rushing_tds' in player_rows.columns:
            player_rows['total_tds'] = player_rows['rushing_tds'].fillna(0)
        else:
            continue
        games_played = len(player_rows)

        # ── Prior-season bridge (7-week, same as other NFL models) ──
        # Blend prior-season opportunity/efficiency with current season.
        # Early weeks lean on prior data; by Week 7+ it's all current.
        _td_bridge = {0: 1.00, 1: 0.90, 2: 0.75, 3: 0.60, 4: 0.45, 5: 0.30, 6: 0.15}
        prior_weight = _td_bridge.get(games_played, 0.0)
        current_weight = 1.0 - prior_weight

        # Get prior-season data for this player
        prior_rows = pd.DataFrame()
        if prior_weight > 0 and not prior_skill.empty:
            prior_rows = prior_skill[prior_skill['player_display_name'] == player_name].sort_values('week')
            # Detect team change — halve prior weight if different team
            if not prior_rows.empty:
                team_col = 'recent_team' if 'recent_team' in player_rows.columns else ('team' if 'team' in player_rows.columns else None)
                if team_col and team_col in prior_rows.columns:
                    prior_team = prior_rows.iloc[-1].get(team_col, '')
                    current_team = player_rows.iloc[-1].get(team_col, '') if games_played > 0 else ''
                    if prior_team and current_team and prior_team != current_team:
                        prior_weight *= 0.5
                        current_weight = 1.0 - prior_weight

        # STEP 1: OPPORTUNITY — expected volume per game
        # Blend current + prior season using the 7-week bridge
        expected_volume = None
        
        # Calculate prior-season volume if available
        prior_volume = None
        if not prior_rows.empty and prior_weight > 0:
            if player_pos in ('WR', 'TE') and 'targets' in prior_rows.columns:
                prior_volume = prior_rows['targets'].fillna(0).mean()
            elif player_pos == 'RB':
                pc = prior_rows['carries'].fillna(0).mean() if 'carries' in prior_rows.columns else 10
                pt = prior_rows['targets'].fillna(0).mean() if 'targets' in prior_rows.columns else 2
                prior_volume = pc + pt
            elif player_pos == 'QB' and 'carries' in prior_rows.columns:
                prior_volume = prior_rows['carries'].fillna(0).mean()

        # Calculate current-season volume
        current_volume = None
        if player_pos in ('WR', 'TE') and 'targets' in player_rows.columns:
            targets = player_rows['targets'].fillna(0)
            if games_played >= 5:
                current_volume = targets.tail(5).mean() * 0.6 + targets.mean() * 0.4
            elif games_played > 0:
                current_volume = targets.mean()
        elif player_pos == 'RB':
            c = player_rows['carries'].fillna(0) if 'carries' in player_rows.columns else None
            t = player_rows['targets'].fillna(0) if 'targets' in player_rows.columns else None
            if games_played > 0:
                cv = (c.tail(5).mean() * 0.6 + c.mean() * 0.4) if c is not None and games_played >= 5 else (c.mean() if c is not None else 10)
                tv = (t.tail(5).mean() * 0.6 + t.mean() * 0.4) if t is not None and games_played >= 5 else (t.mean() if t is not None else 2)
                current_volume = cv + tv
        elif player_pos == 'QB' and 'carries' in player_rows.columns:
            rushes = player_rows['carries'].fillna(0)
            if games_played > 0:
                if games_played >= 5:
                    current_volume = rushes.tail(5).mean() * 0.6 + rushes.mean() * 0.4
                else:
                    current_volume = rushes.mean()

        # Blend current + prior using bridge weights
        if current_volume is not None and prior_volume is not None:
            expected_volume = (current_volume * current_weight) + (prior_volume * prior_weight)
        elif current_volume is not None:
            expected_volume = current_volume
        elif prior_volume is not None:
            expected_volume = prior_volume
        
        # Regress toward position average for very small samples
        if expected_volume is not None:
            league_vol = pos_opportunity.get(player_pos, 5.0)
            total_games = games_played + (len(prior_rows) if not prior_rows.empty else 0)
            vol_reg = min(total_games / 8, 1.0)
            expected_volume = (expected_volume * vol_reg) + (league_vol * (1 - vol_reg))

        if expected_volume is None or expected_volume <= 0:
            continue

        # STEP 2: EFFICIENCY — TD per opportunity, heavily regressed
        # Blend current + prior season efficiency using bridge weights
        league_eff = pos_efficiency.get(player_pos, 0.04)
        
        # Current-season efficiency
        if player_pos in ('WR', 'TE') and 'targets' in player_rows.columns:
            p_opps = player_rows['targets'].fillna(0).sum()
            p_tds = player_rows['total_tds'].sum()
        elif player_pos == 'RB':
            p_opps = (player_rows['carries'].fillna(0).sum() if 'carries' in player_rows.columns else 0) + (player_rows['targets'].fillna(0).sum() if 'targets' in player_rows.columns else 0)
            p_tds = player_rows['total_tds'].sum()
        elif player_pos == 'QB':
            p_opps = player_rows['carries'].fillna(0).sum() if 'carries' in player_rows.columns else 0
            p_tds = player_rows['rushing_tds'].fillna(0).sum() if 'rushing_tds' in player_rows.columns else player_rows['total_tds'].sum()
        else:
            continue

        # Prior-season efficiency
        prior_opps = 0
        prior_tds = 0
        if not prior_rows.empty and prior_weight > 0:
            if player_pos in ('WR', 'TE') and 'targets' in prior_rows.columns:
                prior_opps = prior_rows['targets'].fillna(0).sum()
                prior_tds = prior_rows['total_tds'].sum()
            elif player_pos == 'RB':
                prior_opps = (prior_rows['carries'].fillna(0).sum() if 'carries' in prior_rows.columns else 0) + (prior_rows['targets'].fillna(0).sum() if 'targets' in prior_rows.columns else 0)
                prior_tds = prior_rows['total_tds'].sum()
            elif player_pos == 'QB':
                prior_opps = prior_rows['carries'].fillna(0).sum() if 'carries' in prior_rows.columns else 0
                prior_tds = prior_rows['rushing_tds'].fillna(0).sum() if 'rushing_tds' in prior_rows.columns else prior_rows['total_tds'].sum()

        # Blend opportunities and TDs using bridge weights
        blended_opps = (p_opps * current_weight) + (prior_opps * prior_weight)
        blended_tds = (p_tds * current_weight) + (prior_tds * prior_weight)

        raw_eff = blended_tds / blended_opps if blended_opps > 0 else league_eff
        reg_opps = {'WR': 100, 'TE': 80, 'RB': 150, 'QB': 60}.get(player_pos, 100)
        eff_w = min(blended_opps / reg_opps, 1.0)
        td_per_opp = (raw_eff * eff_w) + (league_eff * (1 - eff_w))

        # STEP 3: EXPECTED TDs = volume x efficiency
        expected_tds = expected_volume * td_per_opp

        # STEP 4: POISSON PROBABILITY
        model_prob = 1 - exp(-expected_tds) if expected_tds > 0 else 0.0
        model_prob = max(0.03, min(0.85, model_prob))

        # STEP 4b: MILD SHRINKAGE (V1.4R, August 2026)
        # Validated across 3 chronological windows + betting sim.
        # α=0.95 compresses the upper tail where the model is
        # overconfident (69%→52%) without disturbing the well-
        # calibrated lower range. Shrinkage beat isotonic in
        # betting ROI despite slightly worse Brier score.
        _TD_SHRINKAGE_ALPHA = 0.95
        _TD_BASE_RATE = 0.197  # 2025 season base TD rate
        model_prob = _TD_SHRINKAGE_ALPHA * model_prob + (1 - _TD_SHRINKAGE_ALPHA) * _TD_BASE_RATE

        # STEP 5: EV CALCULATION
        implied_prob = american_odds_to_implied_prob(td_odds)
        if implied_prob is None or implied_prob <= 0:
            continue
        if td_odds > 0:
            decimal_odds = 1 + (td_odds / 100)
        else:
            decimal_odds = 1 + (100 / abs(td_odds))
        ev_pct = round(((model_prob * decimal_odds) - 1) * 100, 2)

        # STEP 6: CONFIDENCE + TIERING (rebuilt August 2026)
        #
        # Real historical odds backtest (14,188 predictions, 3 seasons,
        # REAL sportsbook prices) — then re-tiered against EV buckets:
        #
        #   3-5% EV:  +33.2% ROI (154 bets) ← Best Bet
        #   5-8% EV:  +1.3% ROI  (233 bets) ← Worth a Look
        #   8%+ EV:   negative ROI — model overestimates, don't show
        #   Longshots (+500+): massively negative — don't show
        #   QB position: +15.8% ROI across actionable tiers
        #
        # Only show picks with real, proven edge. Everything else
        # is suppressed to Pass (hidden from users).

        # No low-confidence suppression — the tight EV range (3-8%)
        # and longshot filter (>+500) already protect against bad picks.
        # Backtested profitably from Week 3 onward, which uses minimal
        # current-season data anyway.
        is_longshot = td_odds > 500
        is_qb = player_pos == 'QB'

        if is_longshot:
            mm_tier = "🔴 Pass"
        elif 3 <= ev_pct < 5:
            # The sweet spot: +33.2% historical ROI
            mm_tier = "🟢 Best Bet"
        elif 5 <= ev_pct < 8:
            # Slight but real edge: +1.3% historical ROI
            if is_qb:
                mm_tier = "🟢 Best Bet"  # QBs +15.8% ROI, promote them
            else:
                mm_tier = "🔵 Worth a Look"
        elif 3 <= ev_pct < 10 and is_qb:
            # QBs have proven edge across a wider EV range
            mm_tier = "🔵 Worth a Look"
        else:
            # Everything else: negative historical ROI, don't show
            mm_tier = "🔴 Pass"

        fair_odds = prob_to_american_odds(model_prob)
        edge_cents = calculate_odds_edge_cents(td_odds, fair_odds) if fair_odds else None
        info.update({
            'Projection': round(expected_tds, 3), 'Model Prob': round(model_prob, 4),
            'Implied Prob': round(implied_prob, 4), 'EV%': ev_pct, 'MM Tier': mm_tier,
            'Odds': td_odds, 'Fair Odds': fair_odds, 'Edge Cents': edge_cents,
            'Low Confidence': False, 'Direction': 'td',
            'Book': info.get('td_book'), 'player_position': player_pos,
            'games_played': games_played,
            'expected_volume': round(expected_volume, 2),
            'td_per_opp': round(td_per_opp, 4),
        })
        results[player_name] = {
            'player': player_name, 'matchup': f"{info['away']} @ {info['home']}",
            'projected_tds': round(expected_tds, 3), 'model_prob': round(model_prob, 4),
            'implied_prob': round(implied_prob, 4), 'ev_pct': ev_pct, 'mm_tier': mm_tier,
            'odds': td_odds, 'book': info.get('td_book'), 'commence_time': info.get('commence_time'),
        }
    return results


def run_nfl_display(all_players_key, load_fn, run_all_fn, run_single_fn, session_key, player_label, sport_save_label, model_sport_key):
    """Generic NFL model display (July 2026) — built to give NFL the
    same dropdown-driven, single-shared-display pattern NBA already has
    via run_nba_display, instead of NFL's three models needing three
    separate, duplicated page sections. Also fixes a real, pre-existing
    bug found while building this: the old NFL page's '📝 Log' button
    set a session_state flag that nothing ever displayed or read —
    clicking it visibly did nothing. Now uses the same working log
    modal pattern MLB already has.

    load_fn() -> dict of {player_name: info}
    run_all_fn(all_players, season, progress_callback) -> results dict
    run_single_fn(player_name, info, season) -> (update_fields, result_wrapper, opp_abbrev, game_week)
    """
    bankroll, risk_style = get_bankroll_context()
    already_bet_today = get_already_bet_players_today(sport_save_label)

    # Real fix (August 2026, per direct user request) — data is now
    # already loaded automatically by the real, global
    # run_todays_card_auto_run() call before page dispatch (backed by
    # today's real caching fixes — this is the same NFL that used to
    # have ZERO computation caching at all, now fully persistent). This
    # button is now an OPTIONAL way to force a genuinely fresh props
    # pull (load_fn.clear() bypasses its 5-minute cache on purpose
    # here) rather than a required first step.
    if st.button(f"🔄 Refresh {player_label} Props & Projections", key=f"refresh_{session_key}"):
        if hasattr(load_fn, "clear"):
            load_fn.clear()
        with st.spinner(f"Pulling fresh {player_label} props and running projections..."):
            all_players = load_fn()
            if all_players:
                season = datetime.now().year if datetime.now().month >= 3 else datetime.now().year - 1
                progress_bar = st.progress(0)
                status_text = st.empty()
                total = len(all_players)

                def _update_progress(i, total, name):
                    status_text.text(f"Running {i+1} of {total}: {name}")
                    progress_bar.progress((i + 1) / total)

                player_results = run_all_fn(all_players, season, progress_callback=_update_progress)
                st.session_state[all_players_key] = all_players
                st.session_state[f'{session_key}_season'] = season
                st.session_state.setdefault(f'{session_key}_results', {})
                st.session_state[f'{session_key}_results'].update(player_results)
                st.session_state[f'manual_run_order_{session_key}'] = {}
                st.session_state[f'manual_run_counter_{session_key}'] = 0
                progress_bar.empty()
                status_text.empty()
                st.rerun()
            else:
                real_error = st.session_state.pop(f'_nfl_{session_key}_props_load_error', None) or st.session_state.pop('_nfl_props_load_error', None) or st.session_state.pop('_nfl_completions_props_load_error', None) or st.session_state.pop('_nfl_receptions_props_load_error', None)
                if real_error:
                    st.error(f"Couldn't load this week's props — real error: {real_error}")
                else:
                    st.error("Couldn't load this week's props — either no games are posted yet or it's off-season.")

    if all_players_key in st.session_state:
        all_players = st.session_state[all_players_key]
        season = st.session_state.get(f'{session_key}_season', datetime.now().year)
        player_results = st.session_state.get(f'{session_key}_results', {})

        now_utc = datetime.now(ZoneInfo("UTC"))
        started_since_load = []
        for pname, pdata in all_players.items():
            ct_str = pdata.get('commence_time')
            if not ct_str:
                continue
            try:
                ct = datetime.fromisoformat(ct_str.replace('Z', '+00:00'))
                if ct <= now_utc:
                    started_since_load.append(pname)
            except (ValueError, TypeError):
                pass
        if started_since_load:
            names_preview = ", ".join(started_since_load[:5])
            more = f" and {len(started_since_load) - 5} more" if len(started_since_load) > 5 else ""
            st.warning(f"⚠️ {len(started_since_load)} loaded game(s) have started since you pulled props ({names_preview}{more}) — their projections are now stale. Click **\"🔄 Refresh\"** above to update.")

        manual_run_order = st.session_state.get(f'manual_run_order_{session_key}', {})

        sorted_players = sorted(
            all_players.items(),
            key=lambda x: (
                x[0] in manual_run_order,
                manual_run_order.get(x[0], 0),
                TIER_RANK.get(x[1].get('MM Tier'), -1),
                x[1]['EV%'] if x[1]['EV%'] is not None else -999,
                abs(x[1]['Edge']) if x[1]['Edge'] is not None else -999
            ),
            reverse=True
        )

        hcol1, hcol2, hcol3, hcol4, hcol5, hcol6, hcol7, hcol8, hcol9, hcol10, hcol11 = st.columns([2.0, 0.8, 0.8, 0.7, 0.7, 1.0, 1.4, 0.9, 1.5, 1.1, 1.1])
        header_style = "color: var(--mm-text-faint); font-size: 0.72rem; font-family: var(--mm-mono); letter-spacing: 0.04em; text-transform: uppercase;"
        for hcol, label in [
            (hcol1, player_label), (hcol2, "FD"), (hcol3, "DK"),
            (hcol4, "Proj"), (hcol5, "Edge"), (hcol6, "Play"),
            (hcol7, "Reliability"), (hcol8, "EV%"), (hcol9, "Tier"),
            (hcol10, ""), (hcol11, ""),
        ]:
            with hcol:
                st.markdown(f"<div style='{header_style}'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='padding-top: 6px;'></div>", unsafe_allow_html=True)

        for player_name, info in sorted_players:
            col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11 = st.columns([2.0, 0.8, 0.8, 0.7, 0.7, 1.0, 1.4, 0.9, 1.5, 1.1, 1.1])
            with col1:
                st.write(f"**{player_name}**")
                st.caption(f"{info['away']} @ {info['home']}")
                if player_name in already_bet_today:
                    st.caption("✅ Already bet today")
            with col2:
                st.write(f"FD: {info['FanDuel Line']}")
                st.caption(f"O:{fmt_odds(info['FanDuel Over'])} U:{fmt_odds(info['FanDuel Under'])}")
            with col3:
                st.write(f"DK: {info['DraftKings Line']}")
                st.caption(f"O:{fmt_odds(info['DraftKings Over'])} U:{fmt_odds(info['DraftKings Under'])}")
            with col4:
                st.write(f"Proj: **{info['Projection']}**" if info['Projection'] else "Proj: —")
            with col5:
                st.write(f"Edge: **{info['Edge']}**" if info['Edge'] is not None else "Edge: —")
            with col6:
                st.markdown(f"<div style='white-space: nowrap;'>{info['Play']}</div>" if info['Play'] else "—", unsafe_allow_html=True)
            with col7:
                st.write(short_tier_label(info.get('Tier')))
            with col8:
                ev = info.get('EV%')
                st.write(f"EV: **{ev}%**" if ev is not None else "EV: —")
            with col9:
                st.markdown(tier_badge(info.get('MM Tier'), compact=True), unsafe_allow_html=True)
                if info.get('MM Tier') == "🔴 Pass" and info.get('Pass Reason'):
                    st.caption(info.get('Pass Reason'))
                elif info.get('Confidence Level') == "🔴 Low":
                    st.caption("🔴 Confidence: Low")
            with col10:
                if st.button("▶️ Run", key=f"{session_key}_run_{player_name}"):
                    with st.spinner(f"Running {player_name}..."):
                        update_fields, result_wrapper, opp_abbrev, game_week = run_single_fn(player_name, info, season)
                        if update_fields and result_wrapper:
                            st.session_state[all_players_key][player_name].update(update_fields)
                            st.session_state.setdefault(f'{session_key}_results', {})
                            st.session_state[f'{session_key}_results'][player_name] = result_wrapper['result']
                            st.session_state.setdefault(f'manual_run_order_{session_key}', {})
                            st.session_state[f'manual_run_counter_{session_key}'] = st.session_state.get(f'manual_run_counter_{session_key}', 0) + 1
                            st.session_state[f'manual_run_order_{session_key}'][player_name] = st.session_state[f'manual_run_counter_{session_key}']
                            save_prediction({
                                'date': mm_today_str(),
                                'pitcher': player_name, 'opponent': opp_abbrev, 'home_team': info['home'],
                                'confidence_tier': result_wrapper['result'].get('confidence_tier'),
                                'actual': None, 'sport': sport_save_label,
                                'game_week': game_week, 'commence_time': info.get('commence_time'),
                                **result_wrapper['save_fields'],
                            })
                            st.rerun()
                        else:
                            st.error("Couldn't run this projection — insufficient history, no valid quote, or a real starter/week couldn't be matched.")
            with col11:
                if info.get('Projection') is not None:
                    if st.button("📝 Log", key=f"{session_key}_log_{player_name}"):
                        st.session_state[f'{session_key}_log_modal_{player_name}'] = True

            if info.get('Projection') is not None and player_name in player_results:
                result = player_results[player_name]
                direction = info.get('Direction', 'over')
                why_lines = generate_why(info, result, direction, model_sport_key)
                if why_lines:
                    with st.expander(f"💡 Why this bet? — {player_name}"):
                        for line in why_lines:
                            st.markdown(line)
                        if ANTHROPIC_API_KEY:
                            if st.button("🧠 Generate Model Insight", key=f"{session_key}_insight_btn_{player_name}"):
                                with st.spinner("🧠 Generating model insight..."):
                                    insight, thesis_label = get_or_generate_ai_insight(
                                        mm_today_str(), sport_save_label, player_name, info, result
                                    )
                                if insight:
                                    render_ai_insight_block(insight, thesis_label, result, model_sport_key)
                                else:
                                    st.caption("Couldn't generate an insight right now.")
                    render_mm_stake_block(info, result, bankroll, risk_style)

            # Real addition (August 2026, per direct user request — "a
            # spot to choose which book line im taking... sometimes I
            # like to bet both"). Only real MLB pitchers carry 'Alt
            # Lines' at all (see load_mlb_props_data) — guarded so this
            # doesn't break for NBA/NFL, which don't have this real
            # field populated.
            alt_lines = info.get('Alt Lines')
            if alt_lines and any(lines for lines in alt_lines.values()):
                with st.expander(f"📊 Alternate Lines — {player_name}"):
                    for book_key in ['FanDuel', 'DraftKings']:
                        lines = alt_lines.get(book_key) or {}
                        if not lines:
                            continue
                        st.markdown(f"**{book_key}**")
                        sorted_points = sorted(
                            lines.items(),
                            key=lambda kv: kv[1].get('ev_pct') if kv[1].get('ev_pct') is not None else -999,
                            reverse=True,
                        )
                        for point, odds_pair in sorted_points:
                            ev_pct = odds_pair.get('ev_pct')
                            mm_tier = odds_pair.get('mm_tier')
                            play = odds_pair.get('play', '—')
                            over_str = fmt_odds(odds_pair.get('over'))
                            under_str = fmt_odds(odds_pair.get('under'))
                            alt_col1, alt_col2, alt_col3, alt_col4 = st.columns([1.2, 1.5, 1.0, 1.2])
                            with alt_col1:
                                st.write(f"**{point}**")
                            with alt_col2:
                                st.caption(f"O:{over_str} U:{under_str}")
                            with alt_col3:
                                st.write(play)
                            with alt_col4:
                                if ev_pct is not None:
                                    st.markdown(tier_badge(mm_tier, compact=True), unsafe_allow_html=True)
                                    st.caption(f"EV: {ev_pct}%")
                                else:
                                    st.caption("—")
                        st.markdown("---")

            if st.session_state.get(f'{session_key}_log_modal_{player_name}'):
                with st.expander(f"📝 Log Bet — {player_name}", expanded=True):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        log_ou = st.selectbox("Over or Under?", ["Over", "Under"], key=f"{session_key}_log_ou_{player_name}")
                        log_bet = st.number_input("Bet Amount ($)", value=None, min_value=0.0, placeholder="e.g. 100.50", step=0.01, format="%.2f", key=f"{session_key}_log_bet_{player_name}")
                        log_odds = st.number_input("Odds (e.g. -140 or +110)", value=None, placeholder="e.g. -140", step=1, key=f"{session_key}_log_odds_{player_name}")
                    with col_b:
                        log_actual = st.number_input(f"Actual {player_label} Result (fill after game)", value=None, placeholder="e.g. 24", key=f"{session_key}_log_actual_{player_name}")
                        log_result = st.selectbox("Result", ["Pending", "Win", "Loss"], key=f"{session_key}_log_result_{player_name}")

                    # Real fix (August 2026, per direct user report —
                    # "it doesn't have the calculation thing at the
                    # bottom of the bet logger telling you if you are a
                    # percent over the recommended stake like MLB does,
                    # we need to add that to all of the models") — NFL's
                    # log form was missing the real MM Stake
                    # recommendation AND the deviation message entirely,
                    # not just the deviation part — MLB/NBA already had
                    # both, this brings NFL in line with that same real
                    # pattern.
                    log_mm_stake_dollars = None
                    _log_result_data = player_results.get(player_name)
                    if bankroll and _log_result_data:
                        _log_stake = calculate_mm_stake(info, _log_result_data, bankroll, risk_style)
                        if _log_stake and not _log_stake.get('pass'):
                            log_mm_stake_dollars = _log_stake['stake_dollars']
                            if log_bet:
                                st.caption(format_stake_deviation_message(log_mm_stake_dollars, log_bet))
                            else:
                                st.caption(f"💰 MM Stake recommendation: ${log_mm_stake_dollars:,.2f}")

                    if st.button(f"✅ Confirm Log Bet", key=f"{session_key}_log_confirm_{player_name}", use_container_width=True):
                        if log_result != "Pending" and log_actual is None:
                            st.error("Enter the actual result before marking the bet settled.")
                        else:
                            odds = int(log_odds) if log_odds else -110
                            bet_val = round(float(log_bet), 2) if log_bet else 0.0
                            profit = calc_profit(bet_val, odds, log_result)
                            save_bet({
                                'date': mm_today_str(), 'pitcher': player_name,
                                'projection': info.get('Projection') or 0,
                                'opening_line': info.get('FanDuel Line') or info.get('DraftKings Line') or 0,
                                'over_under': log_ou, 'odds': odds,
                                'bet_amount': bet_val, 'result': log_result,
                                'actual': log_actual or 0, 'profit': profit,
                                'sport': sport_save_label, 'ev_pct': info.get('EV%'),
                                'mm_tier': info.get('MM Tier'),
                                'no_vig_prob': info.get('No Vig Prob'),
                                'model_prob': info.get('Model Prob'), 'confidence_tier': info.get('Tier'),
                                'sportsbook': info.get('Book'), 'raw_ev_pct': info.get('Raw EV%'),
                                'opposite_odds': info.get('Opposite Odds'),
                                'adjusted_projection': info.get('Adjusted Projection'),
                                'effective_std': info.get('Effective Std'),
                                'model_version': MODEL_VERSION, 'ev_engine_version': EV_ENGINE_VERSION,
                                'logged_at': datetime.now(ZoneInfo("UTC")).isoformat(),
                            })
                            st.session_state[f'{session_key}_log_modal_{player_name}'] = False
                            st.success(f"✅ Bet logged for {player_name}!")
                            st.rerun()

            st.divider()

# ---- LoL LIVE PROJECTION PIPELINE ----
def format_lol_match_date(match_date_str):
    """Real, honest formatter for the match_date shown in results.
    Real history: an earlier version tried direct Polymarket date
    fields for an exact time, which real live data confirmed were
    market-creation timestamps, not game times — removed, falling back
    to a date-only slug parse. Real fix (July 2026): a genuine,
    verified exact-time source was found — Cito's schedule endpoints
    include a real 'startTime' field per match (confirmed via live
    data to show real, varying times, not a placeholder), looked up by
    team pair via cito_api.build_match_time_map() and prioritized
    upstream in _price_and_tier_lol_matchup() before this formatter
    ever sees the value. So this now genuinely may receive either a
    full ISO timestamp (the common case now) or a date-only string (a
    real, honest fallback for the rarer case where no schedule entry
    was found for that team pair — a bye week, a very recent schedule
    change, etc). Returns a clear 'not yet known' message rather than
    a blank or malformed string if genuinely nothing usable was found."""
    if not match_date_str:
        return "Date not available"
    try:
        if "T" in match_date_str:
            dt_utc = datetime.fromisoformat(match_date_str.replace("Z", "+00:00"))
            dt_eastern = dt_utc.astimezone(ZoneInfo("America/New_York"))
            return dt_eastern.strftime("%a %b %-d, %-I:%M %p ET")
        else:
            dt_date = datetime.strptime(match_date_str, "%Y-%m-%d")
            return dt_date.strftime("%a %b %-d") + " (exact time not available)"
    except (ValueError, TypeError):
        return match_date_str  # real, unparseable value — show it raw rather than hide it


# Real fix (July 2026, round 2 — the first fix was correct in principle
# but badly over-cautious in practice). The original version added a
# flat, unconditional 2-second sleep before EVERY real Cito call — that
# genuinely does keep the pipeline under 30 calls/min, but it does so
# by making EVERY run slow, even a small run with only a handful of
# real calls that was never anywhere close to the real limit. A rate
# limit like Cito's is a real ROLLING 60-second window, not "wait 2
# seconds no matter what" — this replaces the flat delay with an
# adaptive limiter that tracks the real timestamps of recent Cito calls
# in this process and only sleeps the minimum real time actually needed
# to stay under the limit. In practice: the first ~27 calls in any real
# 60-second window fire back-to-back with NO added delay at all; only
# once genuinely approaching the real limit does it pause, and only for
# as long as actually necessary. CITO_RATE_LIMIT_MAX_CALLS uses a real,
# deliberate safety margin (27, not the documented 30) since the exact
# limit is documented, not independently verified.
CITO_RATE_LIMIT_MAX_CALLS = 27
CITO_RATE_LIMIT_WINDOW_SECONDS = 60
_cito_call_timestamps = []


def _throttle_cito_call():
    """Real, adaptive rate-limit guard — call this immediately before
    every real Cito network request. Prunes call timestamps older than
    the real rolling window, and if the window is already at capacity,
    sleeps only the real remaining time until the oldest call in the
    window ages out (plus a small margin), then records this call.
    Shared, module-level state is fine here — Streamlit runs one real
    pipeline execution at a time per session, and this is meant to
    protect the whole real run (not just one function), same as the
    single, shared roster/history caches built elsewhere in this fix."""
    now = time.time()
    while _cito_call_timestamps and now - _cito_call_timestamps[0] > CITO_RATE_LIMIT_WINDOW_SECONDS:
        _cito_call_timestamps.pop(0)
    if len(_cito_call_timestamps) >= CITO_RATE_LIMIT_MAX_CALLS:
        sleep_seconds = CITO_RATE_LIMIT_WINDOW_SECONDS - (now - _cito_call_timestamps[0]) + 0.1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    _cito_call_timestamps.append(time.time())


def _call_cito_with_backoff(fn, *args, max_retries=2, base_backoff=5.0, **kwargs):
    """Real, shared wrapper for every Cito API call in the LoL pipeline.
    Applies the real, adaptive rate-limit guard above before every real
    attempt (including retries), then calls fn(*args, **kwargs). If it
    fails with a real 429 (rate limit) specifically, waits and retries
    up to max_retries times with real exponential backoff before giving
    up. A non-429 failure (network error, 500, malformed response, etc.)
    is NOT retried here — it's re-raised immediately so the caller's own
    existing try/except handles it exactly as before, unchanged."""
    last_error = None
    for attempt in range(max_retries + 1):
        _throttle_cito_call()
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            if "429" not in str(e) or attempt >= max_retries:
                raise
            time.sleep(base_backoff * (attempt + 1))
    raise last_error


# Real fix (July 2026, round 3) — even with the flat-delay problem
# fixed, a genuinely busy real LoL slate (many concurrent leagues —
# LCK, LPL, LEC, LCS, CBLOL, etc — all under one "league-of-legends"
# tag) can legitimately need well over 100 real, sequential Cito calls
# in one run (2 unique-team calls each for match history + roster,
# plus 1 head-to-head call per matchup). Against a real 30-calls/min
# limit, that volume alone can genuinely take several real minutes —
# not a bug, just the honest cost of respecting a real rate limit on a
# pipeline that needs that many calls. The single biggest real lever
# available without a bigger concurrency rewrite: a team's real match
# history and roster don't change meaningfully within a few minutes,
# so re-clicking "Load Latest Matchups" again shortly after (very
# common while testing, or just re-checking later) shouldn't force a
# full, real re-fetch of every unique team from scratch every time.
# These three wrappers cache each real call's result for a real,
# bounded TTL, shared across the whole Streamlit session — a second
# real run within the TTL window skips the network entirely for any
# team/matchup already seen, which is where the real, meaningful speed
# win comes from for anyone iterating on this page.
@st.cache_data(ttl=600, show_spinner=False)
def _cached_lol_team_matches(api_key, team_slug):
    from cito_api import get_lol_team_matches
    return _call_cito_with_backoff(get_lol_team_matches, api_key, team_slug)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_lol_team_roster(api_key, team_slug):
    from cito_api import get_lol_team_roster_history
    return _call_cito_with_backoff(get_lol_team_roster_history, api_key, team_slug)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_lol_head_to_head(api_key, team1_slug, team2_slug):
    # Shorter TTL than team history/roster (5 min, not 10) — there are
    # fewer of these real calls to begin with (one per real matchup,
    # not per team), so a slightly fresher real refresh cadence is
    # affordable without meaningfully hurting the real speed win.
    from cito_api import get_lol_head_to_head
    return _call_cito_with_backoff(get_lol_head_to_head, api_key, team1_slug, team2_slug)


def _fetch_lol_match_markets(tag_slug):
    """Real extraction (July 2026, per external review — code split #1
    of several) — fetches live Polymarket events and extracts real
    match-winner markets. Returns (events, match_markets, error_dict).
    error_dict is None on success; when set, the caller should return
    it directly as the pipeline's final result, matching the existing
    honest-failure pattern (no silent empty result)."""
    from polymarket_api import get_all_polymarket_events, extract_match_winner_markets
    try:
        events = get_all_polymarket_events(tag_slug=tag_slug, closed=False)
    except Exception as e:
        return None, None, {"error": f"Polymarket fetch failed: {e}"}

    match_markets = extract_match_winner_markets(events)
    if not match_markets:
        all_fetched_event_titles = [e.get("title") for e in events]
        return events, [], {
            "debug": {
                "note": "No real match-winner markets found in the Polymarket fetch itself — 0 events had a groupItemTitle of 'Match Winner'.",
                "total_events_fetched": len(events), "all_fetched_event_titles": all_fetched_event_titles,
            },
            "results": [],
        }
    return events, match_markets, None


def _resolve_lol_matchup_teams(match_markets, api_key):
    """Real extraction (code split #2) — the full, real three-pass team
    resolution: cheap schedule data first, the expensive full teams
    list only as a targeted fallback, then league-context
    disambiguation for genuinely ambiguous names. Returns
    (resolved_matchups, name_to_slug, candidates_map, unresolved_team_names,
    unresolved_detail, needs_fallback, team_region_map, match_time_map, error_dict).

    Real, honest note on team_region_map: it's only built when the
    full teams list happens to already be fetched (i.e. needs_fallback
    was True for at least one team) — fetching the full, expensive
    teams list JUST for region data on every run would reverse the
    real rate-limit optimization built earlier. When the schedule data
    alone resolves everything, team_region_map comes back empty, and
    the cross-region international K-factor boost simply doesn't apply
    for that run — a real, honest limitation, not a silent bug, since
    the boost logic already treats an empty map as a safe no-op.

    match_time_map is real, confirmed Cito startTime data (genuinely
    varying real times, unlike Polymarket's own date fields, which
    were investigated and confirmed to be market-creation timestamps,
    not game times) — always available from the cheap schedule fetch,
    unlike team_region_map."""
    from cito_api import (
        get_lol_schedule_today, get_lol_schedule_upcoming, get_lol_teams_list,
        build_team_name_to_slug_map, build_team_name_to_slug_map_from_teams_list, merge_name_to_slug_maps,
        build_team_region_map, build_match_time_map,
        match_polymarket_name_to_slug, build_team_candidates_map, resolve_team_with_league_context,
        _find_prefix_candidates, _find_last_word_candidates, _normalize_team_name,
    )

    try:
        # Real, deliberate two-pass approach — schedule data is cheap
        # (2 calls) but genuinely narrower than the full team database;
        # real testing found major teams (T1, Cloud9, Team Liquid)
        # missing simply because they weren't playing in the
        # today/upcoming window, not because of a bug.
        schedule_today = get_lol_schedule_today(api_key)
        schedule_upcoming = get_lol_schedule_upcoming(api_key)
        name_to_slug = build_team_name_to_slug_map(schedule_today, schedule_upcoming)
        match_time_map = build_match_time_map(schedule_today, schedule_upcoming)
    except Exception as e:
        if "429" in str(e):
            return None, None, None, None, None, None, None, None, {"error": f"Cito is rate-limiting this key right now (429 Too Many Requests) — this is almost always temporary. Wait a minute and try again. Raw error: {e}"}
        return None, None, None, None, None, None, None, None, {"error": f"Cito schedule fetch failed (needed for team name matching): {e}"}

    all_market_team_names = set()
    for market in match_markets:
        for name in market.get("outcomes_parsed", []):
            all_market_team_names.add(name)
    needs_fallback = any(match_polymarket_name_to_slug(name, name_to_slug) is None for name in all_market_team_names)

    teams_list = None
    team_region_map = {}
    if needs_fallback:
        try:
            # The full teams list is expensive (18+ paginated calls) —
            # previously avoided entirely due to a free-tier rate
            # limit, now affordable as a targeted fallback on the paid
            # tier. Only fetched when the cheap schedule map actually
            # leaves real teams unresolved.
            teams_list = get_lol_teams_list(api_key)
            teams_list_map = build_team_name_to_slug_map_from_teams_list(teams_list)
            name_to_slug = merge_name_to_slug_maps(name_to_slug, teams_list_map)
            team_region_map = build_team_region_map(teams_list)
        except Exception:
            # Real, deliberate choice: don't fail the whole pipeline if
            # only the fallback errors — proceed with whatever the
            # cheap schedule map alone could resolve.
            pass

    # League-context disambiguation for genuinely ambiguous names —
    # built from data already fetched above, no extra API calls.
    candidates_map = build_team_candidates_map(schedule_today, schedule_upcoming, *([teams_list] if teams_list else []))

    def _resolve(team_name, market_text):
        slug = match_polymarket_name_to_slug(team_name, name_to_slug)
        if slug:
            return slug
        return resolve_team_with_league_context(team_name, candidates_map, market_text)

    def _diagnose_unresolved(team_name):
        """Real diagnostic showing exactly what each resolution stage
        found for a team that failed to resolve — not just the final
        exact-match lookup.

        Real fix (July 2026) — was using a plain .strip().lower() key,
        while name_to_slug/candidates_map are both built (and looked up
        during real resolution) using cito_api._normalize_team_name(),
        which ALSO strips real, confirmed invisible Unicode characters
        (e.g. the real U+2060 WORD JOINER found in "Movistar KOI
        Fénix"). Actual team resolution was never affected by this —
        match_polymarket_name_to_slug() already normalizes correctly
        internally — but this diagnostic could show a misleading "no
        candidates found" for a team whose real difference from a known
        key was only an invisible character, confusing debugging."""
        key = _normalize_team_name(team_name)
        return {
            "exact_match_candidates": name_to_slug.get(key),
            "candidates_map_exact": candidates_map.get(key, {}),
            "prefix_fallback_candidates": _find_prefix_candidates(team_name, candidates_map),
            "last_word_fallback_candidates": _find_last_word_candidates(team_name, candidates_map),
        }

    resolved_matchups = []
    unresolved_team_names = []
    unresolved_detail = {}
    # Real fix (July 2026) — tracks real team-pair combinations already
    # added, so the same real matchup listed under two different
    # Polymarket events/markets (a real, possible occurrence — re-listed
    # or mirrored markets) doesn't get priced and displayed twice. This
    # also matters for API load: a duplicate matchup would otherwise
    # double the real head-to-head/roster-history calls made for that
    # exact team pair later in the pipeline.
    seen_team_pairs = set()
    for market in match_markets:
        outcomes = market.get("outcomes_parsed", [])
        if len(outcomes) != 2:
            continue
        market_text = f"{market.get('event_title', '')} {market.get('question', '')}"
        slug1 = _resolve(outcomes[0], market_text)
        slug2 = _resolve(outcomes[1], market_text)
        if not slug1:
            unresolved_team_names.append(outcomes[0])
            unresolved_detail[outcomes[0]] = {**_diagnose_unresolved(outcomes[0]), "market_text_checked": market_text}
        if not slug2:
            unresolved_team_names.append(outcomes[1])
            unresolved_detail[outcomes[1]] = {**_diagnose_unresolved(outcomes[1]), "market_text_checked": market_text}
        if not slug1 or not slug2:
            continue  # a real, unmatched team — skip rather than guess
        pair_key = frozenset({slug1, slug2})
        if pair_key in seen_team_pairs:
            continue  # a real, already-resolved duplicate of this exact matchup — skip
        seen_team_pairs.add(pair_key)
        resolved_matchups.append({
            "market": market, "team1_name": outcomes[0], "team2_name": outcomes[1],
            "team1_slug": slug1, "team2_slug": slug2,
        })

    return resolved_matchups, name_to_slug, candidates_map, unresolved_team_names, unresolved_detail, needs_fallback, team_region_map, match_time_map, None



def _get_unique_lol_team_slugs(resolved_matchups):
    """Real, shared helper (July 2026) — the same real set of unique
    team slugs across a slate of matchups is needed by BOTH the match-
    history fetch below and the new roster-history cache, so this is
    computed once and reused, rather than each real fetch function
    recomputing (and, previously, re-fetching per-matchup) it
    separately."""
    unique_slugs = set()
    for m in resolved_matchups:
        unique_slugs.add(m["team1_slug"])
        unique_slugs.add(m["team2_slug"])
    return unique_slugs


def _fetch_lol_team_histories(resolved_matchups, api_key, unique_slugs=None, on_step=None):
    """Real extraction (code split #3) — fetches real match history for
    every unique team across all resolved matchups, then combines,
    dedupes, and chronologically sorts it into one dataset ready for
    Elo. Returns (sorted_history, fetch_errors, per_team_fetch_counts).

    Real fix (July 2026) — also applies infer_missing_game_winners()
    to the combined history before returning it. A real, confirmed data
    bug: some completed matches have their overall series score
    correct but individual games missing a winnerSlug (found via live
    investigation of a real G2 2-1 series where only Game 1's winner
    was recorded) — since Elo processes games individually, those
    missing games were previously invisible to the rating system
    entirely, silently under-crediting series winners. Applied here,
    after combining/deduping but before Elo ever sees the data, so
    every downstream caller benefits automatically.

    Real fix (July 2026) — this loop fires one real Cito API call per
    unique team with zero delay between them and no retry on a real,
    transient 429. On a real slate with many unique teams, this alone
    could already meaningfully eat into the real 30-calls/min budget
    before the head-to-head/roster calls later in the pipeline even
    start. Now wrapped with _call_cito_with_backoff, which applies the
    real, adaptive rate-limit guard (_throttle_cito_call) before every
    real attempt, matching the same pattern used everywhere else in
    this fix.

    Real fix (July 2026, round 3) — unique_slugs can now be passed in
    directly (computed once by the caller and shared with
    _fetch_lol_team_rosters, rather than each function recomputing its
    own copy), and on_step(label), if given, is called before each
    real per-team fetch — real, honest progress feedback for a real
    run that can take a while, instead of one static spinner that
    looks frozen the whole time.

    Real fix (July 2026, round 6, per direct user report — a team
    showing a suspicious, unmoved default 1500 Elo rating despite its
    own underlying Cito data being confirmed completely healthy via the
    separate admin coverage tool) — an EXCEPTION during this fetch
    already gets recorded in fetch_errors, but a real, quieter failure
    mode wasn't visible anywhere: a call that returns successfully (no
    exception) but with zero or fewer completed matches than the team
    actually has, for any real reason (a transient, malformed real
    response, a real caching edge case, etc.). per_team_fetch_counts
    records the REAL number of completed matches this specific live
    run actually received for every team, so that can be checked
    directly against the separate coverage tool's own independent
    count — if they disagree, that's real, direct evidence the live
    run itself received bad data, even with zero exceptions raised."""
    from cito_api import extract_completed_matches, sort_matches_chronologically, infer_missing_game_winners, normalize_requested_team_slug, apply_slug_alias_map, slugs_textually_related, resolve_fetchable_slug, is_disambiguated_challengers_slug
    from lol_elo import combine_and_dedupe_matches

    if unique_slugs is None:
        unique_slugs = _get_unique_lol_team_slugs(resolved_matchups)

    all_team_histories = []
    fetch_errors = []
    per_team_fetch_counts = {}
    # Real fix (July 2026, round 2, same real investigation) — tracks
    # every real {old_slug: requested_slug} alias detected while
    # fetching, so it can be applied ONE MORE TIME globally after
    # combining (see apply_slug_alias_map's own docstring) — closing a
    # real, remaining gap where deduping by matchId could keep an
    # un-normalized copy of a shared match depending on real fetch
    # order, even after each team's own per-fetch normalization.
    slug_alias_map = {}

    # Real fix (August 2026, round 6, per direct user report — "dn
    # still doesn't work" after round 5's tier-based fix, which tested
    # correctly in isolation). Found the real, remaining cause:
    # combine_and_dedupe_matches() keeps whichever real copy of a
    # shared matchId it encounters FIRST — if a Challengers team's own
    # fetch (which correctly tier-relabels a shared match, e.g. "dns")
    # gets added to all_team_histories AFTER the corresponding main-
    # roster team's own fetch (which leaves that same real match
    # untouched, e.g. still "kwangdong-freecs", since main-roster's own
    # fetch has no real reason to relabel a match it already sees under
    # its own real slug), the main-roster's un-relabeled copy silently
    # wins the dedup race — discarding the real, correctly-relabeled
    # Challengers copy entirely, even though round 5's fix worked
    # perfectly within that one team's own fetch. Fetching Challengers-
    # tier slugs FIRST guarantees their real, correctly-relabeled copy
    # is the one already in all_team_histories by the time any
    # corresponding main-roster fetch for the same shared match comes
    # along later in this loop.
    from cito_api import MANUAL_CHALLENGERS_SLUGS
    def _is_challengers_slug(s):
        return "challenger" in (s or "").lower() or (s or "").lower() in MANUAL_CHALLENGERS_SLUGS or is_disambiguated_challengers_slug(s)
    unique_slugs = sorted(unique_slugs, key=lambda s: (not _is_challengers_slug(s), s))

    for slug in unique_slugs:
        if on_step:
            on_step(f"Match history: {slug}")
        try:
            # Real fix (August 2026, round 6, per direct user
            # investigation) — slug may now be a real, synthetic,
            # disambiguated identifier (e.g. "bro::cl") that Cito's own
            # real API has no idea about — the actual real fetch must
            # always use the real, underlying Cito slug
            # (resolve_fetchable_slug strips the synthetic suffix,
            # returning it unchanged if there wasn't one).
            fetchable_slug = resolve_fetchable_slug(slug)
            team_matches = _cached_lol_team_matches(api_key, fetchable_slug)
            completed = extract_completed_matches(team_matches)
            # Real fix (July 2026, per direct user report — a real,
            # established team, paiN Gaming, showing zero processed
            # games despite genuinely having 38 real completed matches)
            # — see normalize_requested_team_slug()'s own docstring for
            # the full real reasoning. Cito's own real slug aliasing
            # (a schedule-resolved slug like "pain-gaming" that its
            # own /matches endpoint accepts, but whose returned match
            # objects still label the team as "pain" internally) meant
            # every downstream slug comparison silently failed for any
            # team hit by this. Normalizes at the source, right after
            # fetching, so every function downstream of this point
            # (Elo, in-tournament form, head-to-head) sees one
            # consistent, real slug for this team.
            # Real fix (round 3, August 2026, per direct user
            # investigation) — this detection used to build the alias
            # map unconditionally for ANY isRequested-marked slug
            # mismatch, which is exactly what let a real, serious bug
            # slip through: requesting "dns" (DN SOOPers CHALLENGERS)
            # returned a real match belonging to "kwangdong-freecs"
            # (the MAIN roster, confirmed via the match's own
            # tournamentId being a real main-league split, not
            # Challengers) — two real, unrelated strings, not an alias
            # of the same team. Now uses the same real, shared
            # slugs_textually_related() check normalize_requested_
            # team_slug() itself uses, so a genuinely different real
            # team never gets folded into this map at all.
            # Real fix (round 6, August 2026) — ALSO skips this
            # detection entirely for a real, synthetic disambiguated
            # slug (e.g. "bro::cl"). A global {real_slug: synthetic_
            # slug} entry here would be real, direct danger — applied
            # via apply_slug_alias_map() below across the ENTIRE
            # combined history, it would incorrectly relabel every
            # real occurrence of the underlying slug (e.g. "bro")
            # anywhere in the whole dataset, including real, unrelated
            # main-roster matches from a completely different real
            # matchup this same run. normalize_requested_team_slug()
            # right below already correctly handles the disambiguation
            # within THIS team's own real fetch — that's sufficient and
            # safe; the global map must stay real-slug-to-real-slug
            # only.
            if not is_disambiguated_challengers_slug(slug):
                for _match in completed:
                    for _side_key in ("team1", "team2"):
                        _side = _match.get(_side_key)
                        if isinstance(_side, dict) and _side.get("isRequested") and _side.get("slug") and _side.get("slug") != slug and slugs_textually_related(_side.get("slug"), slug):
                            slug_alias_map[_side["slug"]] = slug
            completed = normalize_requested_team_slug(completed, slug)
            all_team_histories.append(completed)
            per_team_fetch_counts[slug] = len(completed)
        except Exception as e:
            fetch_errors.append(f"{slug}: {e}")
            per_team_fetch_counts[slug] = None  # a real, honest "we don't know" — the fetch itself failed

    combined_history = combine_and_dedupe_matches(all_team_histories)
    combined_history = apply_slug_alias_map(combined_history, slug_alias_map)
    combined_history = infer_missing_game_winners(combined_history)
    sorted_history = sort_matches_chronologically(combined_history)
    return sorted_history, fetch_errors, per_team_fetch_counts


def _fetch_lol_team_rosters(unique_slugs, api_key, on_step=None):
    """Real, new fix (July 2026) — builds a real {team_slug: roster_
    history_response} cache ONCE per pipeline run, fetched a single
    time per unique team. Previously, _price_and_tier_lol_matchup()
    called get_lol_team_roster_history() directly, TWICE PER MATCHUP
    (once per side) with zero caching — meaning a team appearing in
    multiple matchups on the same real slate had its roster history
    re-fetched from scratch every single time, real API calls wasted
    on data that hadn't changed since the last fetch a few seconds
    earlier. Combined with the same lack of throttling, this was a
    real, direct contributor to exceeding Cito's real 30-calls/min
    limit partway through a run. Returns a dict; a team whose real
    fetch fails is simply absent from the dict (caller already treats
    a missing/failed roster fetch as a safe, honest "no discount"
    fallback — see _price_and_tier_lol_matchup).

    Real fix (July 2026, round 3) — on_step(label), if given, is
    called before each real per-team fetch, feeding a real progress
    indicator on the LoL page instead of a single static spinner."""
    roster_cache = {}
    from cito_api import resolve_fetchable_slug
    for slug in unique_slugs:
        if on_step:
            on_step(f"Roster history: {slug}")
        try:
            # Real fix (August 2026, round 6) — slug may be a real,
            # synthetic, disambiguated identifier (e.g. "bro::cl") that
            # Cito's own real roster endpoint has no idea about. Fetches
            # using the real, underlying slug, but still keys the cache
            # by the original (possibly synthetic) slug, so downstream
            # lookups for the disambiguated identity still find an
            # entry — Cito's real roster endpoint has no tier concept
            # of its own anyway, so reusing the same real, current
            # roster snapshot for both identities is the most honest
            # real option available, not a compromise specific to this
            # fix.
            roster_cache[slug] = _cached_lol_team_roster(api_key, resolve_fetchable_slug(slug))
        except Exception:
            pass  # real, honest fallback — this team simply won't have a roster-continuity discount applied
    return roster_cache



def _price_and_tier_lol_matchup(m, ratings, max_days_ahead, cutoff_date, international_counts=None, match_time_map=None, sorted_history=None, api_key=None, roster_cache=None):
    """Real extraction (code split #4) — the real per-matchup pricing
    logic: date-cutoff filtering, price validation, illiquid-market
    filtering, model-vs-market probability, recommended side, real
    EV%, and tier classification. Returns (result_dict, filter_reason)
    — exactly one of the two is None. filter_reason is one of
    'too_far_ahead', 'bad_price_data', 'illiquid', or None (meaning a
    real result was produced)."""
    from polymarket_api import polymarket_price_to_american_odds
    from cito_api import is_disambiguated_challengers_slug

    market = m["market"]
    prices = market.get("outcomePrices_parsed", [])

    # Real fix (July 2026) — prioritize Cito's own confirmed, real
    # startTime (genuinely varying real times, unlike Polymarket's own
    # date fields, which were investigated and confirmed to be market-
    # creation timestamps, not game times) over the date-only slug
    # fallback. Looked up by team pair since match_time_map is built
    # from Cito's schedule data, which doesn't share a common match ID
    # with Polymarket's markets.
    real_match_time = None
    if match_time_map:
        real_match_time = match_time_map.get(frozenset({m["team1_slug"], m["team2_slug"]}))

    # Real fix (July 2026, round 2 — per direct user report, live-
    # verified via the admin Raw Market/Event Field Inspector) — Cito's
    # own schedule doesn't cover every real matchup (a real coverage
    # gap, not a Cito bug — a match simply isn't in schedule/today +
    # schedule/upcoming). Confirmed real case: a Cloud9 vs Dignitas
    # match Cito's schedule was missing had market.eventStartTime =
    # "2026-08-01T20:00:00Z" — directly verified CORRECT, matching the
    # market's own description text ("initially scheduled for August 1
    # at 4:00PM ET") exactly (20:00 UTC = 4PM EDT). This directly
    # contradicts an earlier investigation that rejected this same
    # field for returning wrong, past-dated values on OTHER real
    # markets — real data quality on Polymarket's side appears to be
    # genuinely inconsistent market-to-market, not uniformly bad. Used
    # here as a real, HONEST second-tier fallback specifically for the
    # gap Cito leaves — Cito's own schedule still gets priority
    # whenever it actually has the match, and a genuinely bad value in
    # this field on some other market is a real, accepted risk of
    # showing SOME exact time (even if occasionally wrong) instead of
    # no time at all for a match Cito's schedule doesn't cover.
    if not real_match_time:
        real_match_time = market.get("eventStartTime")

    match_date_display = real_match_time or market.get("match_date")

    # Real fix (July 2026, per direct user feedback) — a live/already-
    # started match shouldn't get a pre-game projection at all, since
    # the real market price would already be reacting to in-game
    # events our model has no idea happened, making the comparison
    # meaningless. Same real pattern already used for MLB/NFL
    # (comparing commence_time against now_utc) — applied here using
    # whichever real, exact source resolved real_match_time above
    # (Cito's schedule first, Polymarket's own eventStartTime as a real
    # fallback for matches Cito's schedule doesn't cover — see round 2
    # fix above). A real, useful side effect of that fallback: this
    # already-started check now also correctly applies to Cito-gap
    # matches, which it silently skipped before (real_match_time was
    # simply None for them). Only checked when we have the PRECISE
    # real timestamp, not the date-only slug fallback, since a bare
    # date can't tell us whether a game already started earlier today.
    if real_match_time and "T" in real_match_time:
        try:
            real_start_dt = datetime.fromisoformat(real_match_time.replace("Z", "+00:00"))
            now_utc = datetime.now(ZoneInfo("UTC"))
            if real_start_dt <= now_utc:
                return None, {"reason": "already_started", "team1": m["team1_name"], "team2": m["team2_name"], "match_date": real_match_time}
        except (ValueError, TypeError):
            pass  # unparseable real timestamp — don't block on it

    # Real date cutoff — real feedback found matchups showing up over
    # a week out, too far ahead to be practically useful for betting
    # right now. A missing/unparseable date is kept, not excluded —
    # that's genuinely unknown, not evidence of being far away.
    if match_date_display:
        try:
            # A real startTime is a full ISO timestamp; the slug
            # fallback is date-only — parse whichever form this is.
            if "T" in match_date_display:
                match_date = datetime.fromisoformat(match_date_display.replace("Z", "+00:00")).date()
            else:
                match_date = datetime.strptime(match_date_display, "%Y-%m-%d").date()
            if match_date > cutoff_date:
                return None, {"reason": "too_far_ahead", "team1": m["team1_name"], "team2": m["team2_name"], "match_date": match_date_display}
        except (ValueError, TypeError):
            pass  # unparseable date — kept, same as a missing one

    if len(prices) != 2:
        return None, {"reason": "bad_price_data", "team1": m["team1_name"], "team2": m["team2_name"], "prices": prices}
    try:
        market_prob_team1 = float(prices[0])
    except (ValueError, TypeError):
        return None, {"reason": "bad_price_data", "team1": m["team1_name"], "team2": m["team2_name"], "prices": prices}

    # Real fix — a price at or extremely near 0%/100% generally means
    # the market has little to no real trading activity yet, not a
    # genuine, liquid consensus price. Computing an "edge" against a
    # stale placeholder like this is misleading, not a real signal.
    if market_prob_team1 <= 0.01 or market_prob_team1 >= 0.99:
        return None, {"reason": "illiquid", "team1": m["team1_name"], "team2": m["team2_name"], "market_prob_team1": market_prob_team1, "question": market.get("question")}

    # Real fix (July 2026) — found via direct comparison of real data:
    # a 187% "EV" matchup had just $739 in real total trading volume,
    # vs a genuine, reasonable 4% EV matchup with $92,869 — roughly a
    # 159x gap. Real market liquidity (capital sitting in the order
    # book) was actually similar between the two ($88K vs $134K),
    # confirming liquidity is NOT the discriminating signal here —
    # volume (actual real trades that happened) is. A market nobody's
    # genuinely traded yet doesn't have a price that means anything,
    # even if it's not sitting at the 0%/100% extreme the filter above
    # already catches.
    #
    # Real design choice, per direct user feedback: rather than
    # hiding a low-volume matchup entirely, it stays visible with a
    # real, proportional EV discount and a visible warning — a $1,900
    # market barely gets touched, a $200 market gets discounted
    # heavily. MIN_MARKET_VOLUME is a real, conservative first
    # threshold set well above the confirmed-bad case and well below
    # the confirmed-good one — not finely tuned, and may need real
    # calibration later once more real examples are seen, same as
    # every other threshold in this project.
    MIN_MARKET_VOLUME = 2000
    try:
        market_volume = float(market.get("volume") or 0)
    except (ValueError, TypeError):
        market_volume = 0
    volume_confidence = min(1.0, market_volume / MIN_MARKET_VOLUME) if MIN_MARKET_VOLUME else 1.0
    is_low_volume = market_volume < MIN_MARKET_VOLUME

    question = (market.get("question") or "").lower()
    # Real fix (July 2026) — found via a real case: a KeSPA Cup match
    # whose own market context text explicitly said "BO1" was still
    # being computed as Bo3, since the old logic only ever checked for
    # "bo5" and silently defaulted everything else to 3. Bo3 math
    # genuinely inflates a clear favorite's series-win probability
    # above their real single-game probability (needing only 1 win
    # instead of 2 gives them fewer chances to close it out, which
    # actually lowers a favorite's true win probability versus Bo3) —
    # likely the real reason this specific match showed an extreme,
    # overconfident 92.9%. Now explicitly checks for "bo1" too, rather
    # than only ever detecting the Bo5 case.
    if "bo1" in question:
        best_of = 1
    elif "bo5" in question:
        best_of = 5
    else:
        best_of = 3  # real, simple default — Bo3 is the common LoL regular-season format

    from lol_elo import predict_series, blend_with_head_to_head, blend_with_head_to_head_from_api, calculate_roster_continuity, apply_roster_continuity_discount
    model_prob_team1 = predict_series(ratings, m["team1_slug"], m["team2_slug"], best_of)
    # Real addition (July 2026, per external review) — captures the
    # real probability at each stage of the blending pipeline, not
    # just the final number. Not shown to regular users by default,
    # but logged so future analysis across many real bets can answer
    # questions like "did the H2H blend actually improve calibration,
    # or is it just adding noise/redundant with in-tournament form?" —
    # answerable only with this real, step-by-step trail, not the
    # final probability alone.
    probability_waterfall = {"base_elo": round(model_prob_team1 * 100, 2)}

    # Real addition (July 2026, per direct user feedback and a real,
    # concrete case — Dignitas/Sentinels had two prior meetings, both
    # real 2-0 sweeps, a pattern our overall-rating-only Elo had no way
    # to see). Blends in real, direct head-to-head history between
    # these two specific teams, conservatively capped so a small
    # sample can matter without ever fully overriding the broader Elo
    # signal. h2h_detail is real, honest transparency about what
    # evidence (if any) went into this, not a hidden adjustment.
    #
    # Real fix (July 2026) — now tries Cito's own dedicated /h2h
    # endpoint first (confirmed via live testing to return more
    # complete real data — 10 real matches back to Jan 2025 for a real
    # pair, vs only 4 found by reconstructing from each team's own
    # /matches history for that same pair). Falls back to the
    # reconstruction approach if the API call fails for this specific
    # pair (rate limit, network issue, etc) — a real, honest fallback,
    # not silently losing the feature entirely over one failed call.
    h2h_detail = {"total_h2h_series": 0}
    # Real fix (August 2026, round 6) — a real, synthetic disambiguated
    # slug (e.g. "bro::cl") has no real meaning to Cito's own live H2H
    # endpoint, and this project doesn't have live access to verify
    # exactly how blend_with_head_to_head_from_api's interpretation of
    # the raw API response would behave if handed a slug value that
    # doesn't match what the API itself actually returned. Rather than
    # risk a real, unverified bug in that path, disambiguated matchups
    # go straight to the reconstruction-based H2H below, which already
    # correctly uses the real, tier-filtered sorted_history — same
    # real, safe fallback this code already uses when the live API
    # call fails for any other reason.
    _either_side_disambiguated = is_disambiguated_challengers_slug(m["team1_slug"]) or is_disambiguated_challengers_slug(m["team2_slug"])
    if api_key and not _either_side_disambiguated:
        try:
            # Real fix (July 2026) — now uses the cached wrapper
            # (_cached_lol_head_to_head), so a repeat run within the
            # cache TTL skips this real network call entirely for any
            # matchup already seen, on top of the existing retry-on-429
            # protection built into _call_cito_with_backoff underneath.
            h2h_api_response = _cached_lol_head_to_head(api_key, m["team1_slug"], m["team2_slug"])
            model_prob_team1, h2h_detail = blend_with_head_to_head_from_api(model_prob_team1, h2h_api_response, m["team1_slug"])
        except Exception:
            if sorted_history:
                model_prob_team1, h2h_detail = blend_with_head_to_head(model_prob_team1, m["team1_slug"], m["team2_slug"], sorted_history)
    elif sorted_history:
        model_prob_team1, h2h_detail = blend_with_head_to_head(model_prob_team1, m["team1_slug"], m["team2_slug"], sorted_history)
    probability_waterfall["after_h2h"] = round(model_prob_team1 * 100, 2)

    # Real addition (July 2026) — found via a real, concrete case: a
    # KeSPA Cup match where Dplus KIA (rated 1684.7, one of the best
    # teams in the world) was genuinely 0-2 in that exact tournament,
    # while HANJIN BRION (rated far lower) was 2-2 in the same event —
    # real, current evidence that a team's overall Elo (built across
    # every tournament/roster configuration they've played under) had
    # no way to reflect. KeSPA Cup specifically is a real, known event
    # where teams often field substitutes/academy players instead of
    # their main roster, but this blend doesn't need to know WHY a
    # team is over/underperforming in a given tournament — it just
    # uses their real, direct record in that specific event, whatever
    # the reason. Extracts the tournament name the same way the
    # display text already does (the part after the last ' - ' in the
    # real event_title).
    in_tournament_detail = {"team1_total": 0, "team2_total": 0}
    tournament_name_for_form = (market.get("event_title") or "").split(" - ")[-1].strip()
    if sorted_history and tournament_name_for_form:
        from lol_elo import blend_with_in_tournament_form
        # Real fix (July 2026, round 8) — passes the real match's own
        # date (already resolved above as real_match_time) as the
        # reference point for the new calendar-based recency cutoff in
        # blend_with_in_tournament_form/get_in_tournament_record — a
        # match happening a few days from now should measure "current
        # split form" relative to ITS OWN real date, not just whatever
        # moment the pipeline happens to run.
        in_tournament_reference_date = None
        if real_match_time:
            try:
                in_tournament_reference_date = datetime.fromisoformat(real_match_time.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass  # real, honest fallback — blend_with_in_tournament_form defaults to real "now" if this stays None
        model_prob_team1, in_tournament_detail = blend_with_in_tournament_form(model_prob_team1, m["team1_slug"], m["team2_slug"], tournament_name_for_form, sorted_history, reference_date=in_tournament_reference_date)
    probability_waterfall["after_tournament_form"] = round(model_prob_team1 * 100, 2)
    probability_waterfall["final"] = probability_waterfall["after_tournament_form"]

    edge = round((model_prob_team1 - market_prob_team1) * 100, 1)

    # A moneyline bet needs a decision about WHICH team to actually
    # back, unlike a prop's single over/under line. Whichever side the
    # model rates more favorably than the market is the real value side.
    if model_prob_team1 >= market_prob_team1:
        rec_side, rec_team_name, rec_model_prob, rec_market_prob = "team1", m["team1_name"], model_prob_team1, market_prob_team1
    else:
        rec_side, rec_team_name, rec_model_prob, rec_market_prob = "team2", m["team2_name"], 1 - model_prob_team1, 1 - market_prob_team1
    rec_odds = polymarket_price_to_american_odds(rec_market_prob)
    raw_ev_pct = calculate_ev_pct(rec_model_prob, rec_odds) if rec_odds else None
    # Real, proportional discount for low real trading volume — a
    # market nobody's traded doesn't deserve the same trust as one
    # that's been genuinely tested by real money. Applied to the tier
    # too (not just displayed alongside it), so a huge raw EV% from an
    # untraded market doesn't get called "Best Bet" on the strength of
    # a number that isn't real yet.
    ev_pct = round(raw_ev_pct * volume_confidence, 2) if raw_ev_pct is not None else None

    # Real, proportional discount for roster continuity (July 2026) —
    # found via a real, concrete case: RED Canids' current roster
    # showed 4 of 5 starters joining just 10 days before a real match,
    # with their Elo rating still built entirely from games played
    # before that change. Uses whichever team's continuity is worse
    # (the weaker link determines how much to trust the whole
    # prediction), and applies the same proportional-discount
    # mechanism already proven for market volume. A real, honest
    # fallback to no discount (1.0) if roster data is unavailable for
    # either team — not silently losing the rest of the pipeline over
    # one missing lookup.
    #
    # Real fix (July 2026) — this used to call get_lol_team_roster_
    # history() directly here, TWICE PER MATCHUP, with no caching —
    # meaning a team appearing in several of today's matchups had its
    # roster re-fetched fresh, from scratch, every single time, purely
    # wasted real API calls (roster data doesn't change second to
    # second) and a real, direct contributor to exceeding Cito's
    # 30-calls/min limit on a busy slate. Now reads from roster_cache,
    # built ONCE per unique team by _fetch_lol_team_rosters() before
    # this per-matchup loop ever starts.
    roster_continuity_detail = {"team1": {"continuity_pct": 1.0}, "team2": {"continuity_pct": 1.0}, "worse_continuity_pct": 1.0}
    if roster_cache:
        try:
            team1_roster = roster_cache.get(m["team1_slug"])
            team2_roster = roster_cache.get(m["team2_slug"])
            team1_continuity = calculate_roster_continuity(team1_roster)
            team2_continuity = calculate_roster_continuity(team2_roster)
            worse_continuity_pct = min(team1_continuity["continuity_pct"], team2_continuity["continuity_pct"])
            roster_continuity_detail = {
                "team1": team1_continuity, "team2": team2_continuity,
                "worse_continuity_pct": worse_continuity_pct,
            }
            ev_pct = apply_roster_continuity_discount(ev_pct, worse_continuity_pct)
        except Exception:
            pass  # real, honest fallback — no roster discount applied, not a pipeline failure

    # EV cap (August 2026) — a +173% EV is never real, it means the
    # model is wildly overconfident (stale ratings, missing roster
    # data, thin market). Cap at 40% so unrealistic numbers don't
    # mislead users into oversizing bets on bad predictions.
    _LOL_MAX_EV_PCT = 40.0
    if ev_pct is not None and ev_pct > _LOL_MAX_EV_PCT:
        ev_pct = _LOL_MAX_EV_PCT

    # Real, honest first-attempt tier thresholds specific to moneyline
    # EV — genuinely different distribution than prop betting EV, not
    # borrowed from another sport's calibration. Needs real calibration
    # once enough real settled LoL bets exist — can't happen until then.
    if ev_pct is None:
        mm_tier = "🔴 Pass"
    elif ev_pct >= 15:
        mm_tier = "🟢 Best Bet"
    elif ev_pct >= 7:
        mm_tier = "🔵 Worth a Look"
    elif ev_pct >= 2:
        mm_tier = "🟡 Lean"
    else:
        mm_tier = "🔴 Pass"

    result = {
        "event_title": market.get("event_title"),
        "question": market.get("question"),
        "market_slug": market.get("slug"),
        "group_item_title": market.get("groupItemTitle"),
        "match_date": match_date_display,
        "context_description": market.get("context_description"),
        "market_liquidity": market.get("liquidity"),
        "market_volume24hr": market.get("volume24hr"),
        "market_volume": market.get("volume"),
        "market_volume_numeric": market_volume,
        "team1_name": m["team1_name"], "team2_name": m["team2_name"],
        "team1_slug": m["team1_slug"], "team2_slug": m["team2_slug"],
        "team1_rating": round(ratings.get(m["team1_slug"], 1500), 1),
        "team2_rating": round(ratings.get(m["team2_slug"], 1500), 1),
        "model_prob_team1": round(model_prob_team1, 3),
        "market_prob_team1": round(market_prob_team1, 3),
        "edge_pct": edge,
        "best_of": best_of,
        "market_odds_team1": polymarket_price_to_american_odds(market_prob_team1),
        # Real fix (July 2026) — was "and", meaning this only warned when
        # BOTH teams were unrated. A matchup where only ONE team is
        # genuinely new (silently defaulting to a neutral 1500 rating)
        # while the other has a real, established Elo is arguably the
        # MORE misleading case — the prediction looks confident but is
        # half built on a made-up number. Now warns if EITHER side lacks
        # real match history.
        "no_real_data": m["team1_slug"] not in ratings or m["team2_slug"] not in ratings,
        "team1_international_matches": (international_counts or {}).get(m["team1_slug"], 0),
        "team2_international_matches": (international_counts or {}).get(m["team2_slug"], 0),
        "recommended_side": rec_side,
        "recommended_team_name": rec_team_name,
        "recommended_model_prob": round(rec_model_prob, 3),
        "recommended_market_prob": round(rec_market_prob, 3),
        "recommended_odds": rec_odds,
        "ev_pct": ev_pct,
        "raw_ev_pct_before_volume_discount": round(raw_ev_pct, 2) if raw_ev_pct is not None else None,
        "is_low_volume": is_low_volume,
        "roster_continuity": roster_continuity_detail,
        "head_to_head": h2h_detail,
        "in_tournament_form": in_tournament_detail,
        "probability_waterfall": probability_waterfall,
        "volume_confidence": round(volume_confidence, 3),
        "mm_tier": mm_tier,
    }
    return result, None


def _prefilter_lol_matchups(resolved_matchups, match_time_map, cutoff_date):
    """Real fix (July 2026, per direct user report — "why does the
    pipeline need 265 steps to show 14 matches?"). The four real,
    hard filters (already_started, too_far_ahead, bad_price_data,
    illiquid) were previously only ever applied AFTER the expensive
    per-unique-team match-history and roster-history fetch phase, even
    though every one of these checks only needs data already sitting
    in each matchup's own market dict (price, volume, event time) —
    none of them need real Elo ratings, head-to-head, or roster
    continuity to evaluate. That meant real API calls were being spent
    fetching history/roster for teams whose ONLY real matchup(s) were
    always going to get filtered out anyway, directly inflating the
    real step count far beyond what the final, surviving match count
    would suggest.

    Applies the EXACT same real checks, in the same order, that
    _price_and_tier_lol_matchup itself still performs — deliberately
    kept there too, as a real, redundant safety net (not removed),
    since a match's real price/volume could in principle shift in the
    short window between this early pass and final pricing, and the
    repeated check costs nothing extra (it's just comparing data
    already in hand, no new real API calls). Returns (surviving_
    matchups, filtered_dict) where filtered_dict uses the same four
    real category names as the final pipeline output, so the two sets
    of filtered results can be merged into one real, honest debug
    total."""
    surviving = []
    filtered_as_illiquid = []
    filtered_bad_price_data = []
    filtered_as_too_far_ahead = []
    filtered_as_already_started = []
    filtered_as_excluded_tournament = []

    # Allowlist of leagues/tournaments — only matches from these
    # competitions will reach the pricing pipeline. Substring-matched
    # (case-insensitive) against event_title, question, and slug fields
    # from Polymarket. Flipped from the old blocklist approach (which
    # only excluded KeSPA) because the user wants to control exactly
    # which leagues are covered rather than playing whack-a-mole with
    # minor tournaments that keep appearing.
    ALLOWED_LEAGUES = (
        # Tier 1 — major regional leagues
        "lck", "lpl", "lec", "lcs", "lta ",
        # International events
        "worlds", "world championship", "msi ",
        # Regional leagues
        "first stand", "tcl", "prime league", "lcp", "les ", "cbl",
    )

    # Exclude developmental/lower-tier divisions WITHIN allowed leagues
    # (e.g. LCK Challengers is tagged "lck" but is NOT main LCK).
    EXCLUDED_SUBLEVEL = ("challengers", "academy", "promotion", "youth", "desafiante", "kespa")

    for m in resolved_matchups:
        market = m["market"]
        prices = market.get("outcomePrices_parsed", [])

        # League allowlist — checked first, before any other filter,
        # so matches from minor/unknown tournaments never reach the
        # expensive pricing pipeline. Checks multiple fields since the
        # tournament name may appear in different places depending on
        # how Polymarket structured the event.
        event_title = (market.get("event_title") or "").lower()
        question = (market.get("question") or "").lower()
        slug = (market.get("slug") or "").lower()
        tournament_text = f" {event_title} {question} {slug} "
        if not any(kw in tournament_text for kw in ALLOWED_LEAGUES):
            filtered_as_excluded_tournament.append({"team1": m["team1_name"], "team2": m["team2_name"], "event_title": market.get("event_title"), "question": market.get("question"), "reason": "not in allowed leagues"})
            continue

        # Sub-level exclusion — catches developmental divisions within
        # allowed leagues (e.g. "LCK Challengers League" matches "lck"
        # but should not be shown as main LCK competition).
        if any(kw in tournament_text for kw in EXCLUDED_SUBLEVEL):
            filtered_as_excluded_tournament.append({"team1": m["team1_name"], "team2": m["team2_name"], "event_title": market.get("event_title"), "question": market.get("question"), "reason": "excluded sub-level tournament"})
            continue

        real_match_time = None
        if match_time_map:
            real_match_time = match_time_map.get(frozenset({m["team1_slug"], m["team2_slug"]}))
        if not real_match_time:
            real_match_time = market.get("eventStartTime")
        match_date_display = real_match_time or market.get("match_date")

        if real_match_time and "T" in real_match_time:
            try:
                real_start_dt = datetime.fromisoformat(real_match_time.replace("Z", "+00:00"))
                now_utc = datetime.now(ZoneInfo("UTC"))
                if real_start_dt <= now_utc:
                    filtered_as_already_started.append({"team1": m["team1_name"], "team2": m["team2_name"], "match_date": real_match_time})
                    continue
            except (ValueError, TypeError):
                pass

        if match_date_display:
            try:
                if "T" in match_date_display:
                    match_date = datetime.fromisoformat(match_date_display.replace("Z", "+00:00")).date()
                else:
                    match_date = datetime.strptime(match_date_display, "%Y-%m-%d").date()
                if match_date > cutoff_date:
                    filtered_as_too_far_ahead.append({"team1": m["team1_name"], "team2": m["team2_name"], "match_date": match_date_display})
                    continue
            except (ValueError, TypeError):
                pass

        if len(prices) != 2:
            filtered_bad_price_data.append({"team1": m["team1_name"], "team2": m["team2_name"], "prices": prices})
            continue
        try:
            market_prob_team1 = float(prices[0])
        except (ValueError, TypeError):
            filtered_bad_price_data.append({"team1": m["team1_name"], "team2": m["team2_name"], "prices": prices})
            continue

        if market_prob_team1 <= 0.01 or market_prob_team1 >= 0.99:
            filtered_as_illiquid.append({"team1": m["team1_name"], "team2": m["team2_name"], "market_prob_team1": market_prob_team1, "question": market.get("question")})
            continue

        surviving.append(m)

    return surviving, {
        "filtered_as_illiquid": filtered_as_illiquid,
        "filtered_bad_price_data": filtered_bad_price_data,
        "filtered_as_too_far_ahead": filtered_as_too_far_ahead,
        "filtered_as_already_started": filtered_as_already_started,
        "filtered_as_excluded_tournament": filtered_as_excluded_tournament,
    }


def run_lol_matchup_projections(api_key, tag_slug="league-of-legends", max_days_ahead=1, progress_callback=None):
    """The real, full pipeline — now a thin orchestrator over the real,
    focused helper functions above (code split, July 2026, per external
    review: the original single ~330-line function was flagged as
    getting large enough to be worth splitting before it doubles again).
    Each helper is a genuine extraction of the original, already-tested
    logic, not a rewrite — verified to produce identical results before
    this split shipped.

    1. Fetch real, live LoL events from Polymarket, extract match-
       winner markets.
    2. Resolve every matchup's two team names to real Cito slugs.
    3. Fetch real match history for every team involved, build one
       real, global Elo ratings table (with recent-form weighting).
    4. Price and tier every real matchup against the real market.
    Returns a list of dicts, one per matchup, with everything needed
    to display and log a bet — or an 'error' key if something failed,
    following the same honest-failure pattern used throughout this
    project rather than silently returning an empty result.

    Real fix (July 2026, round 4, per direct user feedback) —
    max_days_ahead default narrowed from 2 to 1: real matchups more
    than a day out weren't just less useful for betting right now,
    they were also directly inflating the real Cito call count (every
    extra matchup means one more real head-to-head call, plus more
    unique teams needing real match-history/roster fetches) — fewer
    real matchups in scope means fewer real calls needed, which also
    helps the real, honest speed cost described below.

    Real fix (July 2026, round 3) — progress_callback(current, total,
    label), if given, is called before every real Cito call across all
    three real phases (team match history, roster history, per-matchup
    pricing/head-to-head) with a single, real, monotonically
    increasing step count spanning the WHOLE pipeline — not per-phase.
    A genuinely busy real slate (many concurrent leagues) can need
    well over 100 real, sequential Cito calls, which, respecting a
    real 30-calls/min rate limit, can honestly take several real
    minutes — this doesn't make that faster, but it means the caller
    can show real, honest progress instead of one static spinner that
    looks identical whether it's 10 seconds in or frozen entirely."""
    from lol_elo import build_team_ratings_from_history

    events, match_markets, error_result = _fetch_lol_match_markets(tag_slug)
    if error_result is not None:
        return error_result

    resolved_matchups, name_to_slug, candidates_map, unresolved_team_names, unresolved_detail, needs_fallback, team_region_map, match_time_map, error_result = _resolve_lol_matchup_teams(match_markets, api_key)
    if error_result is not None:
        return error_result

    # Real fix (August 2026, per direct user report — "so many of
    # these lol teams just dont work"). Applies real, confirmed wrong-
    # slug redirects found directly via the admin "Auto-Investigate"
    # tool's own real cross-check against Cito's full team database —
    # see KNOWN_WRONG_SLUG_REDIRECTS in cito_api.py for the real,
    # confirmed cases and reasoning. Applied first, before the
    # Challengers disambiguation step below, so every later step
    # (unique_slugs, fetching, Elo) already sees the real, correct slug.
    from cito_api import KNOWN_WRONG_SLUG_REDIRECTS
    for m in resolved_matchups:
        if m["team1_slug"] in KNOWN_WRONG_SLUG_REDIRECTS:
            m["team1_slug"] = KNOWN_WRONG_SLUG_REDIRECTS[m["team1_slug"]]
        if m["team2_slug"] in KNOWN_WRONG_SLUG_REDIRECTS:
            m["team2_slug"] = KNOWN_WRONG_SLUG_REDIRECTS[m["team2_slug"]]

    # Real fix (round 7, August 2026, per direct user report — "all
    # challenger LCK teams are still pulling games from their main LCK
    # teams"). Rounds 3-6 required each real, ambiguous shared-slug
    # team to be manually found and added to AMBIGUOUS_SINGLE_SLUG_
    # TEAMS one at a time (bro, kwangdong-freecs, ...) — but this
    # turned out to be a real, SYSTEMIC pattern across LCK specifically
    # (shared main+Challengers slugs appear to be the real norm for
    # this region on Cito, not the exception), making one-at-a-time
    # whack-a-mole the wrong real approach.
    #
    # Real, key insight: tier-based filtering (see normalize_requested_
    # team_slug's tier_confirmed logic) is SAFE to apply universally —
    # even for a real team that turns out NOT to be ambiguous,
    # filtering a Challengers-context matchup down to only Challengers-
    # tagged real games is always the correct real behavior either way.
    # So disambiguation no longer requires a team to be pre-registered
    # in AMBIGUOUS_SINGLE_SLUG_TEAMS at all — it now applies
    # automatically to ANY real team slug in a real Challengers-context
    # matchup, as long as that slug doesn't already self-identify as
    # Challengers (i.e. doesn't already contain the literal word
    # "challenger" — those teams have their own real, dedicated slug
    # and don't need this). AMBIGUOUS_SINGLE_SLUG_TEAMS itself is kept
    # in cito_api.py purely as real, historical documentation of
    # confirmed cases — it's no longer read here.
    #
    # Real fix (round 8, August 2026, per direct user report — "Vivo
    # Keyd Stars has an academy team and their real team, both under
    # the same API"). "Academy" is a real, DIFFERENT lower-tier naming
    # convention than "Challenger" (used by some real orgs/regions
    # instead of, or alongside, "Challengers") — the same real shared-
    # slug pattern, just a different real keyword. Generalized both
    # keywords together here as LOWER_TIER_KEYWORDS, rather than only
    # ever checking for "challenger" specifically.
    LOWER_TIER_KEYWORDS = ("challenger", "academy")
    from cito_api import build_disambiguated_slug
    for m in resolved_matchups:
        matchup_tournament_text = (m["market"].get("event_title") or "").split(" - ")[-1].strip().lower()
        if any(kw in matchup_tournament_text for kw in LOWER_TIER_KEYWORDS):
            if not any(kw in m["team1_slug"].lower() for kw in LOWER_TIER_KEYWORDS):
                m["team1_slug"] = build_disambiguated_slug(m["team1_slug"])
            if not any(kw in m["team2_slug"].lower() for kw in LOWER_TIER_KEYWORDS):
                m["team2_slug"] = build_disambiguated_slug(m["team2_slug"])

    def _serialize_candidates_dict(candidates_dict):
        return {slug: {"leagues": sorted(info["leagues"]), "regions": sorted(info["regions"])} for slug, info in candidates_dict.items()}

    unresolved_detail_serializable = {
        name: {
            "exact_match_slug_found": detail["exact_match_candidates"],
            "candidates_map_exact": _serialize_candidates_dict(detail["candidates_map_exact"]),
            "prefix_fallback_candidates": _serialize_candidates_dict(detail["prefix_fallback_candidates"]),
            "last_word_fallback_candidates": _serialize_candidates_dict(detail["last_word_fallback_candidates"]),
            "market_text_checked": detail["market_text_checked"],
        }
        for name, detail in unresolved_detail.items()
    }

    all_fetched_event_titles = [e.get("title") for e in events]
    debug_info = {
        "total_events_fetched": len(events),
        "all_fetched_event_titles": all_fetched_event_titles,
        "real_match_winner_markets_found": len(match_markets),
        "used_full_teams_list_fallback": needs_fallback,
        "name_to_slug_map_size": len(name_to_slug),
        "resolved_matchups": len(resolved_matchups),
        "unresolved_team_names": sorted(set(unresolved_team_names)),
        "unresolved_detail": unresolved_detail_serializable,
    }
    if not resolved_matchups:
        return {"debug": debug_info, "results": []}

    # Real fix (July 2026, round 5, per direct user report) — applies
    # the same real hard filters (illiquid, bad price data, too far
    # ahead, already started) EARLY, before any expensive per-team
    # match-history/roster fetch happens — see _prefilter_lol_
    # matchups()'s own docstring for the full real reasoning. Only
    # teams involved in a matchup that actually SURVIVES this early
    # pass get their real history/roster fetched at all, directly
    # shrinking the real step count to match what viewers actually see,
    # instead of paying for teams whose only real matchup was always
    # going to get filtered out anyway.
    cutoff_date = (datetime.now(ZoneInfo("UTC")) + timedelta(days=max_days_ahead)).date()
    surviving_matchups, early_filtered = _prefilter_lol_matchups(resolved_matchups, match_time_map, cutoff_date)
    debug_info["prefiltered_out_count"] = len(resolved_matchups) - len(surviving_matchups)
    resolved_matchups = surviving_matchups
    if not resolved_matchups:
        debug_info["final_result_count"] = 0
        debug_info["filtered_as_illiquid"] = early_filtered["filtered_as_illiquid"]
        debug_info["filtered_bad_price_data"] = early_filtered["filtered_bad_price_data"]
        debug_info["filtered_as_too_far_ahead"] = early_filtered["filtered_as_too_far_ahead"]
        debug_info["filtered_as_already_started"] = early_filtered["filtered_as_already_started"]
        return {"debug": debug_info, "results": []}

    # Real fix (July 2026, round 3) — unique_slugs computed ONCE here
    # and shared with both _fetch_lol_team_histories and _fetch_lol_
    # team_rosters, instead of each function separately recomputing
    # its own copy. Also drives the real, single progress counter
    # spanning all three phases below.
    unique_slugs = _get_unique_lol_team_slugs(resolved_matchups)
    total_steps = (len(unique_slugs) * 2) + len(resolved_matchups)
    step_counter = [0]

    def _tick(label):
        if progress_callback:
            step_counter[0] += 1
            progress_callback(step_counter[0], total_steps, label)

    sorted_history, fetch_errors, per_team_fetch_counts = _fetch_lol_team_histories(resolved_matchups, api_key, unique_slugs=unique_slugs, on_step=_tick)
    ratings = build_team_ratings_from_history(sorted_history, team_region_map=team_region_map)

    # Between-split Elo regression (August 2026) — standard practice
    # in every serious Elo system (FiveThirtyEight does 1/3 for NFL
    # between seasons). Without this, a team that dominated last split
    # keeps an extreme rating even after roster changes, meta shifts,
    # and months of off-time — producing absurdly overconfident
    # predictions (+173% EV) that are clearly wrong. 25% regression
    # pulls every rating 25% of the way back toward 1500, shrinking
    # the gap between model probability and market probability to
    # something realistic.
    _LOL_REGRESSION_FACTOR = 0.25
    _LOL_MEAN_RATING = 1500.0
    for _slug in ratings:
        ratings[_slug] = _LOL_MEAN_RATING + (ratings[_slug] - _LOL_MEAN_RATING) * (1 - _LOL_REGRESSION_FACTOR)
    from lol_elo import count_international_matches
    international_counts = count_international_matches(sorted_history, team_region_map)

    # Real diagnostic (July 2026, round 6, per direct user report) — a
    # real, direct record of exactly what happened to every unique
    # team's real history during THIS live run: how many completed
    # matches this run actually received for them (None if the fetch
    # itself raised an exception — see fetch_errors), and whether they
    # ended up with any real Elo rating movement at all afterward. A
    # team showing real_completed_matches_this_run > 0 but never_moved_
    # from_default=True would be direct, real evidence of a bug further
    # downstream (combine/dedupe, or build_team_ratings_from_history
    # itself) — not a Cito data problem, since the data clearly arrived.
    team_history_diagnostics = {
        slug: {
            "real_completed_matches_this_run": per_team_fetch_counts.get(slug),
            "ended_up_in_ratings": slug in ratings,
            "final_rating": round(ratings[slug], 1) if slug in ratings else None,
        }
        for slug in unique_slugs
    }

    # Real fix (July 2026) — real roster history is now fetched ONCE per
    # unique team (throttled, with retry-on-429, and cached across
    # repeat runs), instead of twice per matchup with no caching at all
    # — see _fetch_lol_team_rosters()'s own docstring for the full real
    # reasoning.
    roster_cache = _fetch_lol_team_rosters(unique_slugs, api_key, on_step=_tick)

    results = []
    # Real fix (July 2026, round 5) — seeded with whatever the early
    # prefilter already caught, so the final debug totals reflect BOTH
    # passes combined — a real matchup filtered early still shows up
    # in the same real category a viewer would expect, just without
    # having paid for a real history/roster fetch first.
    filtered_as_illiquid = list(early_filtered["filtered_as_illiquid"])
    filtered_bad_price_data = list(early_filtered["filtered_bad_price_data"])
    filtered_as_too_far_ahead = list(early_filtered["filtered_as_too_far_ahead"])
    filtered_as_already_started = list(early_filtered["filtered_as_already_started"])
    for m in resolved_matchups:
        # Real fix (July 2026, round 2) — no manual sleep needed here.
        # This loop's one real head-to-head Cito call per matchup
        # (roster history is cached above, no longer called here at
        # all) already goes through the cached wrapper / _call_cito_
        # with_backoff() inside _price_and_tier_lol_matchup(), which
        # applies the real, adaptive rate-limit guard itself.
        _tick(f"Pricing {m['team1_name']} vs {m['team2_name']}")
        result, filter_info = _price_and_tier_lol_matchup(m, ratings, max_days_ahead, cutoff_date, international_counts, match_time_map, sorted_history, api_key, roster_cache)
        if result is not None:
            result["fetch_errors"] = fetch_errors
            results.append(result)
        elif filter_info["reason"] == "too_far_ahead":
            filtered_as_too_far_ahead.append({k: v for k, v in filter_info.items() if k != "reason"})
        elif filter_info["reason"] == "bad_price_data":
            filtered_bad_price_data.append({k: v for k, v in filter_info.items() if k != "reason"})
        elif filter_info["reason"] == "illiquid":
            filtered_as_illiquid.append({k: v for k, v in filter_info.items() if k != "reason"})
        elif filter_info["reason"] == "already_started":
            filtered_as_already_started.append({k: v for k, v in filter_info.items() if k != "reason"})

    # Real fix (July 2026, per direct user feedback) — low-volume
    # matchups are no longer excluded; they stay visible with a real,
    # proportional EV discount and a warning instead. This reports
    # which real results got discounted, for visibility, rather than
    # tracking them as filtered-out (they're not).
    low_volume_results = [
        {"team1": r["team1_name"], "team2": r["team2_name"], "raw_ev_pct": r["raw_ev_pct_before_volume_discount"], "discounted_ev_pct": r["ev_pct"], "volume_confidence": r["volume_confidence"]}
        for r in results if r.get("is_low_volume")
    ]

    # Real diagnostic (July 2026, per direct user report) — real,
    # exact match times only ever come from Cito's own schedule/today +
    # schedule/upcoming data (via match_time_map); a matchup whose real
    # team-pair wasn't found there falls back to a date-only display
    # (see format_lol_match_date's "exact time not available" branch),
    # even when Polymarket's own site happens to show a time elsewhere.
    # A real Cito time is always a full ISO timestamp (contains "T");
    # the date-only fallback never does — this distinguishes the two
    # without needing any new real API calls, purely from data already
    # fetched. Surfaces exactly which real matchups are missing Cito
    # schedule coverage, so a real, evidence-based next fix (rather than
    # a guess) can be built once we see the pattern.
    matchups_missing_exact_time = [
        {"team1": r["team1_name"], "team2": r["team2_name"], "date_only_value": r.get("match_date")}
        for r in results if r.get("match_date") and "T" not in str(r.get("match_date"))
    ]

    debug_info["final_result_count"] = len(results)
    debug_info["filtered_as_illiquid"] = filtered_as_illiquid
    debug_info["filtered_bad_price_data"] = filtered_bad_price_data
    debug_info["filtered_as_too_far_ahead"] = filtered_as_too_far_ahead
    debug_info["filtered_as_already_started"] = filtered_as_already_started
    debug_info["low_volume_results_discounted_not_filtered"] = low_volume_results
    debug_info["matchups_missing_exact_time_no_cito_schedule_match"] = matchups_missing_exact_time
    debug_info["team_history_diagnostics"] = team_history_diagnostics
    # Real addition (July 2026, per direct user report) — persists the
    # real, combined match history this run actually used, so the new
    # admin "In-Tournament Record Diagnostic" tool can inspect exactly
    # which real games get matched to a given tournament WITHOUT
    # needing a fresh, separate fetch (which could return subtly
    # different real data than what THIS run actually priced against).
    return {"debug": debug_info, "results": results, "sorted_history": sorted_history}


@st.cache_data(ttl=7200, show_spinner=False)
def _cached_lol_full_pipeline(api_key, tag_slug="league-of-legends", max_days_ahead=1, force_refresh=False):
    """Real fix (August 2026) — caches the ENTIRE real LoL pipeline
    output (every real matchup, priced and tiered) for 2 real hours,
    shared across every visitor hitting this same running server
    process. Real, deliberate design choice, different from MLB/NBA/
    NFL's once-a-day persistent cache: this pipeline computes a whole
    real slate atomically in one pass, not incrementally per player,
    and real market prices genuinely shift meaningfully within a day —
    treating a morning snapshot as valid for the rest of the day (like
    the once-a-day sports do) would be a real, honest accuracy
    tradeoff this project shouldn't make silently.

    Real fix (round 2, August 2026, per direct user report — "the
    loading has still be so slow even with the cache thing"). This
    originally used a 30-minute TTL, reasoned as "short enough to stay
    fresh, long enough for the second+ real visitor within that window
    to get an instant result." That reasoning quietly assumed frequent,
    steady real traffic — for a real, genuinely low-traffic app (one
    person checking in occasionally, hours apart), a 30-minute cache
    is effectively ALWAYS cold by the time anyone actually visits,
    completely defeating both this cache AND the whole real point of
    the scheduled cache-warmer script, which only ran once a day and
    had long since expired by the time it was actually checked. 2
    hours is a real, deliberate rebalancing toward this project's
    actual real usage pattern — still refreshes often enough within a
    real day to track real, moving market prices and newly-completed
    real matches, while realistically staying warm through most real,
    spaced-out visits instead of expiring long before the next one.

    Real, deliberate limitation: no progress_callback support here — a
    real Python closure/function can't be part of a real Streamlit
    cache key (unhashable), so this always calls the underlying real
    pipeline with progress_callback=None. In practice this means a
    real cache MISS (now rarer still, at a real 2-hour window instead
    of 30 minutes) falls back to a simple real spinner instead of the
    detailed step-by-step progress bar, while a real cache HIT (the
    now-common case) is instant either way.

    Real fix (round 3, August 2026, per direct user report — "I
    literally just ran this 10 minutes ago why do I have to wait all
    over again"). This function's own @st.cache_data decorator only
    caches in the running server process's real memory — genuinely
    wiped on every real deploy/restart, regardless of the real 2-hour
    TTL, since a new process starts with a real, empty cache every
    time. Given how many real deploys happened in quick succession
    tonight, that alone explained a real, repeated "still slow" report
    even minutes after a real, successful run. Now checks a SECOND,
    real, persistent cache (Supabase-backed, survives real restarts)
    before falling through to the real, expensive computation, and
    writes to it after — so even a genuinely fresh server process
    (right after a real deploy) can skip straight to a real, fast DB
    read instead of a full real recompute, as long as SOME real run
    happened within the last real 2 hours, from any real server
    process, not just this one.

    Real fix (round 4, August 2026, per direct user report — a real
    code-level fix that was already deployed still didn't show up,
    because the "🔄 Refresh Matchups" button only cleared THIS
    function's real, in-memory st.cache_data layer, not the real,
    persistent Supabase layer added in round 3 — meaning a refresh
    click immediately fell right back into the SAME stale, persistent
    result instead of a genuinely fresh one. force_refresh=True (a
    real part of the real Streamlit cache key, so it's a guaranteed
    real cache miss whenever True) skips BOTH real cache layers
    entirely and goes straight to a real, fresh computation — still
    writing the real, fresh result back to the persistent cache
    afterward, so the NEXT ordinary, non-forced request benefits from
    it too."""
    if not force_refresh:
        _persistent_hit = get_persistent_lol_pipeline_cache()
        if _persistent_hit is not None:
            return _persistent_hit
    result = run_lol_matchup_projections(api_key, tag_slug=tag_slug, max_days_ahead=max_days_ahead, progress_callback=None)
    set_persistent_lol_pipeline_cache(result)
    return result


# Real, soft banner shown on every page — a hard block (via the sidebar
# nav trim + the nav-override above) already handles the "premium stuff"
# side of this; this is the "everywhere" side.
render_trial_banner(subscription_status, user_id, user.email)

# Real fix (August 2026, per direct user request — "get rid of the
# load player prop and run player projections buttons and just have
# all the data fully there for when anyone loads the site") — this
# used to only fire on the Home page specifically, meaning a real
# visitor who went straight to, say, the NFL page without visiting
# Home first would still hit the old two-button "Load Props" / "Run
# Projections" manual flow. Now fires globally, once per real session,
# regardless of which page someone lands on first — thanks to today's
# earlier caching fixes (persistent daily_cache for MLB/NBA/NFL, a
# real 30-minute shared cache for LoL, plus the scheduled cache-warmer
# script), this is now fast enough in the common case to run silently
# before any page's own content renders, rather than needing a visible
# checklist/progress UI most of the time. The function's own existing
# session-state guard (today_card_auto_ran) means this is a genuinely
# free, instant no-op on every page after the first one in a session.
#
# Real fix (August 2026, round 2, per direct user report — landing
# directly on the Esports page during a real, genuinely cold run still
# showed raw NFL loading text and took a while, since the fixed
# MLB→NBA→NFL→LoL order ran regardless of which real page was actually
# open). Maps the current real nav page to a priority sport, so a cold
# run does that one FIRST — the sport the visitor is actually looking
# at gets done before the others, which they aren't even viewing yet.
_nav_to_priority_sport = {
    "⚾ MLB Models": "mlb", "🏀 NBA Models": "nba",
    "🏈 NFL Models": "nfl", "🎮 Esports (LoL)": "lol",
}

# Real fix (August 2026, per direct user report — "when I first load up
# the home screen it just shows that the projections are loading" with
# nothing above it) — the real hero header used to only render AFTER
# the global auto-run finished, since it lived inside the Home page
# block further below, and the auto-run itself runs earlier, before
# nav dispatch. Now shown immediately, right here, before the auto-run
# call — so a visitor sees the real header right away, with any real
# loading indicator appearing below it, not instead of it. Skipped for
# a brand-new signup still in the bankroll-setup gate (that flow shows
# its own, different "Welcome to Model Metrics" header instead, just
# below) to avoid showing two stacked headers.
_early_bankroll_settings = get_user_settings() if nav == "🏠 Home" else None
_early_has_bankroll = bool(_early_bankroll_settings and _early_bankroll_settings.get('starting_bankroll') is not None)
if nav == "🏠 Home" and not (st.session_state.get('just_signed_up') and not _early_has_bankroll):
    st.markdown("""
        <div style='text-align: center; padding: 8px 0 4px 0;'>
            <div style='color: var(--mm-accent); font-family: var(--mm-mono); font-size: 0.8rem; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 14px;'>
                Player Prop Analytics
            </div>
            <h1 style='font-size: 3rem; margin: 0 0 14px 0; line-height: 1.1;'>Sharp Data. Sharp Bets.</h1>
        </div>
    """, unsafe_allow_html=True)

# Real fix (August 2026, per direct user report — "it won't let me get
# on the bet tracker until all props are run") — making the auto-run
# fire globally, unconditionally, on every page (an earlier fix today)
# had a real, serious side effect: pages with NOTHING to do with sports
# props at all — Bet Tracker, Model Performance, Model Lab, Backtest,
# Settings — were ALSO stuck waiting on the full MLB→NBA→NFL→LoL run
# to finish before rendering, even though none of that data is
# remotely relevant to them. Only real, sport-facing pages actually
# need this data pre-loaded; everything else should render instantly,
# completely independent of it.
_PAGES_NEEDING_AUTO_RUN = {
    "🏠 Home", "🎯 Today's Card", "⚾ MLB Models",
    "🏀 NBA Models", "🏈 NFL Models", "🎮 Esports (LoL)",
}
if nav in _PAGES_NEEDING_AUTO_RUN:
    run_todays_card_auto_run(minimal_ui=True, priority_sport=_nav_to_priority_sport.get(nav))

# ---- HOME PAGE ----
if nav == "🏠 Home":
    _bankroll_settings = _early_bankroll_settings
    _has_bankroll = _early_has_bankroll

    if st.session_state.get('just_signed_up') and not _has_bankroll:
        st.markdown("""
            <div style='text-align: center; padding: 60px 0 24px 0;'>
                <h1 style='font-size: 2.1rem; margin-bottom: 10px;'>Welcome to Model Metrics</h1>
                <p style='color: var(--mm-text-dim); font-size: 1.05rem;'>One last step before today's card...</p>
            </div>
        """, unsafe_allow_html=True)
        gate_col1, gate_col2, gate_col3 = st.columns([1, 1.4, 1])
        with gate_col2:
            st.markdown("""
                <div class='mm-card' style='text-align: center; margin-bottom: 16px;'>
                    <h3 style='margin-bottom: 8px; font-size: 1.15rem;'>What's your starting bankroll?</h3>
                    <p style='color: var(--mm-text-dim); font-size: 0.9rem; margin: 0;'>
                        We'll use it to personalize a suggested stake — MM Stake — on every projection.
                    </p>
                </div>
            """, unsafe_allow_html=True)
            with st.form("welcome_bankroll_form"):
                welcome_bankroll = st.number_input(
                    "Starting Bankroll ($)", value=None, min_value=0.0, step=0.01, format="%.2f", placeholder="e.g. 2500.00"
                )
                if st.form_submit_button("Save & Continue", use_container_width=True):
                    if welcome_bankroll is not None:
                        if save_user_settings(round(float(welcome_bankroll), 2), 'Standard'):
                            st.session_state['just_signed_up'] = False
                            st.rerun()
                    else:
                        st.warning("Enter a starting bankroll to continue.")
            if st.button("Skip for now", use_container_width=True):
                st.session_state['just_signed_up'] = False
                st.rerun()
        st.stop()

    # Real fix (August 2026) — the real header now renders earlier
    # (see above, before the global auto-run call), removed the
    # duplicate that used to live here.
    top_entry = top_ranked_entry(build_todays_card_entries())
    already_bet_by_sport = get_already_bet_players_today_by_sport()

    if top_entry:
        tier_word = "Bet" if "Best Bet" in top_entry['tier'] else "Pick"
        play_short = (top_entry['play'] or '').replace('⬆️ OVER', 'Over').replace('⬇️ UNDER', 'Under')
        line_str = f" {play_short} {top_entry['line']}" if top_entry['line'] is not None else ""
        ev = top_entry['ev_pct']
        ev_str = f"{'+' if ev and ev > 0 else ''}{ev}%" if ev is not None else "—"
        _top_entry_sport_label = sport_key_to_bet_label(top_entry['sport_key'])
        already_bet_banner = "<div style='color: var(--mm-success); font-size: 0.85rem; margin-bottom: 8px;'>✅ You already bet this today</div>" if top_entry['name'] in already_bet_by_sport.get(_top_entry_sport_label, set()) else ""
        st.markdown(f"""
            <div class='mm-card' style='max-width: 640px; margin: 0 auto 16px auto; text-align: center; border-color: var(--mm-accent);'>
                <div style='color: var(--mm-accent); font-family: var(--mm-mono); font-size: 0.78rem; letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 12px;'>
                    🔥 Today's Highest Rated {tier_word} &nbsp;·&nbsp; {top_entry['sport_label']}
                </div>
                <h2 style='margin: 0 0 4px 0; font-size: 1.7rem;'>{top_entry['name']}</h2>{already_bet_banner}
                <div style='color: var(--mm-text-dim); font-size: 1.15rem; margin-bottom: 16px;'>{line_str.strip()}</div>
                <div style='display: flex; justify-content: center; gap: 28px; margin-bottom: 18px;'>
                    <div>
                        <div style='font-family: var(--mm-mono); font-size: 1.4rem; font-weight: 600;'>{top_entry['info'].get('Projection')}</div>
                        <div style='color: var(--mm-text-faint); font-size: 0.75rem; text-transform: uppercase;'>Projection</div>
                    </div>
                    <div>
                        <div style='font-family: var(--mm-mono); font-size: 1.4rem; font-weight: 600; color: var(--mm-success);'>{ev_str}</div>
                        <div style='color: var(--mm-text-faint); font-size: 0.75rem; text-transform: uppercase;'>Expected Value</div>
                    </div>
                </div>
                {tier_badge(top_entry['tier'])}
            </div>
        """, unsafe_allow_html=True)

    else:
        st.markdown("""
            <div class='mm-card' style='max-width: 640px; margin: 0 auto 16px auto; text-align: center;'>
                <div style='font-size: 1.5rem; margin-bottom: 8px;'>🗓️</div>
                <p style='color: var(--mm-text-dim); margin: 0;'>No games on the board right now — check back once today's slate is up.</p>
            </div>
        """, unsafe_allow_html=True)

    # Real, deliberate stop point (July 2026) — per the real product
    # decision behind this paywall, an expired-trial user with no active
    # subscription sees ONLY the hero header and today's single highest-
    # rated pick above (both already rendered by this point), plus a real
    # Subscribe CTA here — nothing else on Home (bankroll teaser, feature
    # grid, AI thesis blurb, About section) renders for them. This is on
    # top of the sidebar already only offering "🏠 Home" as a real,
    # selectable nav option, and the hard-block right after the sidebar
    # that forces nav back to Home regardless of how it got set.
    if subscription_status["status"] == "expired":
        st.markdown("<div style='padding-top: 12px;'></div>", unsafe_allow_html=True)
        expired_cta_col1, expired_cta_col2, expired_cta_col3 = st.columns([1, 1.4, 1])
        with expired_cta_col2:
            st.markdown("""
                <div class='mm-card' style='text-align: center; border-color: var(--mm-accent);'>
                    <div style='font-size: 1.6rem; margin-bottom: 8px;'>🔓</div>
                    <h3 style='margin: 0 0 8px 0; font-size: 1.2rem;'>Unlock Every Model</h3>
                    <p style='color: var(--mm-text-dim); font-size: 0.92rem; margin-bottom: 4px;'>
                        Your free trial has ended. Subscribe to get every pick, every sport, Today's Card, Bet Tracker, and MM Stake — not just today's top play.
                    </p>
                </div>
            """, unsafe_allow_html=True)
            st.markdown("<div style='padding-top: 10px;'></div>", unsafe_allow_html=True)
            _home_checkout_url = create_stripe_checkout_url(user_id, user.email)
            if _home_checkout_url:
                st.link_button("🔓 Subscribe Now", _home_checkout_url, use_container_width=True, type="primary")
            else:
                st.button("🔓 Subscribe Now", use_container_width=True, disabled=True, help="Checkout isn't available right now — try again shortly.")
        st.stop()

    cta_col1, cta_col2, cta_col3 = st.columns([1, 1, 1])
    with cta_col2:
        if st.button("🎯 See Full Today's Card", use_container_width=True, type="primary"):
            st.session_state['nav_redirect'] = "🎯 Today's Card"
            st.rerun()
    st.markdown("<div style='padding-bottom: 4px;'></div>", unsafe_allow_html=True)

    if not _has_bankroll:
        st.markdown("""
            <div class='mm-card' style='border-color: var(--mm-accent);'>
                <div style='font-size: 1.6rem; margin-bottom: 10px;'>💰</div>
                <h2 style='margin: 0 0 8px 0; font-size: 1.3rem;'>Built Around Your Bankroll</h2>
                <p style='color: var(--mm-text-dim); font-size: 1rem; line-height: 1.55; margin-bottom: 16px;'>
                    Unlike generic betting tools, Model Metrics personalizes every recommendation to your bankroll.
                </p>
                <div style='color: var(--mm-text-dim); font-size: 0.95rem; line-height: 2;'>
                    📊 Personalized MM Stake for every bet<br>
                    🎯 Dynamic sizing based on EV and model confidence<br>
                    📈 Automatic bankroll tracking as bets settle<br>
                    🛡️ Helps prevent overbetting during hot and cold streaks
                </div>
            </div>
        """, unsafe_allow_html=True)
        bankroll_cta_col1, bankroll_cta_col2, bankroll_cta_col3 = st.columns([1, 1, 1])
        with bankroll_cta_col2:
            st.markdown("<div style='padding-top: 12px;'></div>", unsafe_allow_html=True)
            if st.button("Set Your Bankroll →", use_container_width=True, type="primary"):
                st.session_state['nav_redirect'] = "⚙️ Settings"
                st.rerun()
    else:
        _profile_bankroll, _profile_risk_style = get_bankroll_context()
        _max_single_bet = _profile_bankroll * RISK_STYLE_CAPS.get(_profile_risk_style, 0.02)
        st.markdown(f"""
            <div class='mm-card' style='border-color: var(--mm-accent);'>
                <div style='color: var(--mm-text-faint); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 14px;'>💰 Your Bankroll Profile</div>
                <div style='display: flex; gap: 40px; flex-wrap: wrap;'>
                    <div>
                        <div style='font-family: var(--mm-mono); font-size: 1.3rem; font-weight: 600;'>${_profile_bankroll:,.2f}</div>
                        <div style='color: var(--mm-text-faint); font-size: 0.75rem; text-transform: uppercase;'>Current Bankroll</div>
                    </div>
                    <div>
                        <div style='font-family: var(--mm-mono); font-size: 1.3rem; font-weight: 600;'>{_profile_risk_style}</div>
                        <div style='color: var(--mm-text-faint); font-size: 0.75rem; text-transform: uppercase;'>Risk Style</div>
                    </div>
                    <div>
                        <div style='font-family: var(--mm-mono); font-size: 1.3rem; font-weight: 600;'>${_max_single_bet:,.2f}</div>
                        <div style='color: var(--mm-text-faint); font-size: 0.75rem; text-transform: uppercase;'>Max Single Bet</div>
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
            <div class='mm-card' style='height: 240px; overflow: hidden;'>
                <div style='font-size: 1.6rem; margin-bottom: 10px;'>📈</div>
                <h3 style='margin: 0 0 8px 0; font-size: 1.1rem;'>Proprietary Projection Models</h3>
                <p style='color: var(--mm-text-dim); font-size: 0.92rem; line-height: 1.55; margin: 0;'>
                    Built from advanced statistics, matchup data, pace, usage, workload, and live betting market information.
                </p>
            </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("""
            <div class='mm-card' style='height: 240px; overflow: hidden;'>
                <div style='font-size: 1.6rem; margin-bottom: 10px;'>💰</div>
                <h3 style='margin: 0 0 8px 0; font-size: 1.1rem;'>Real-Time +EV Analysis</h3>
                <p style='color: var(--mm-text-dim); font-size: 0.92rem; line-height: 1.55; margin: 0;'>
                    We strip sportsbook vig, compare our probabilities to fair market odds, and surface positive expected value.
                </p>
            </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown("""
            <div class='mm-card' style='height: 240px; overflow: hidden;'>
                <div style='font-size: 1.6rem; margin-bottom: 10px;'>🎯</div>
                <h3 style='margin: 0 0 8px 0; font-size: 1.1rem;'>Clear Bet Tiers</h3>
                <p style='color: var(--mm-text-dim); font-size: 0.92rem; line-height: 1.55; margin: 0;'>
                    Every prop sorts into 🟢 Best Bet, 🔵 Worth a Look, 🟡 Lean, or 🔴 Pass — with a specific reason shown whenever the model passes.
                </p>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='padding-top: 36px;'></div>", unsafe_allow_html=True)
    # Real fix (August 2026, per direct user request — "we should make
    # an update to the home screen since we're into esports now") —
    # this grid previously only listed MLB/NBA/NFL, even though LoL has
    # been a real, fully working model in the app for a while now.
    # Today's Card's own caption already correctly said "MLB, NBA, NFL,
    # and LoL" — this grid was the one real, remaining place on Home
    # that didn't reflect that.
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("""
            <div class='mm-card' style='height: 125px; overflow: hidden;'>
                <div style='color: var(--mm-text-faint); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px;'>⚾ MLB</div>
                <div style='font-family: var(--mm-mono); font-size: 1.15rem; font-weight: 600;'>Strikeouts</div>
            </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("""
            <div class='mm-card' style='height: 125px; overflow: hidden;'>
                <div style='color: var(--mm-text-faint); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px;'>🏀 NBA</div>
                <div style='font-family: var(--mm-mono); font-size: 1.15rem; font-weight: 600;'>Points · Assists</div>
            </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown("""
            <div class='mm-card' style='height: 125px; overflow: hidden;'>
                <div style='color: var(--mm-text-faint); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px;'>🏈 NFL</div>
                <div style='font-family: var(--mm-mono); font-size: 0.95rem; font-weight: 600;'>Pass Attempts · Pass Completions · Receptions</div>
            </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown("""
            <div class='mm-card' style='height: 125px; overflow: hidden;'>
                <div style='color: var(--mm-text-faint); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px;'>🎮 Esports</div>
                <div style='font-family: var(--mm-mono); font-size: 1.05rem; font-weight: 600;'>League of Legends · Match Winner</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='padding-top: 44px;'></div>", unsafe_allow_html=True)
    st.markdown(f"""
        <div class='mm-card' style='border-color: var(--mm-accent);'>
            <div style='font-size: 1.6rem; margin-bottom: 10px;'>🧠</div>
            <h2 style='margin: 0 0 8px 0; font-size: 1.3rem;'>AI Model Thesis</h2>
            <p style='color: var(--mm-text-dim); font-size: 1rem; line-height: 1.55; margin-bottom: 18px;'>
                Don't just see the projection. Understand why the model disagrees with the market.
            </p>
            <p style='color: var(--mm-text-faint); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 10px;'>
                Every recommended bet includes an AI-generated explanation built from:
            </p>
            <div style='display: flex; gap: 10px; flex-wrap: wrap;'>
                {tier_badge("Recent Performance")}
                {tier_badge("Workload Trends")}
                {tier_badge("Matchup Data")}
                {tier_badge("Betting Market Movement")}
                {tier_badge("Model Projections")}
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='padding-top: 36px;'></div>", unsafe_allow_html=True)
    st.markdown("""
        <div class='mm-card'>
            <h3 style='margin-bottom: 14px; font-size: 1.15rem;'>About Model Metrics</h3>
            <p style='color: var(--mm-text-dim); line-height: 1.7; margin-bottom: 12px;'>
                Winning long-term isn't about predicting every game correctly — it's about consistently betting when the odds are in your favor.
            </p>
            <p style='color: var(--mm-text-dim); line-height: 1.7; margin-bottom: 18px;'>
                Model Metrics combines proprietary projection models with professional expected value analysis to help bettors identify
                wagers with long-term mathematical value. Every recommendation is backed by data, fair-odds pricing, and transparent confidence metrics.
            </p>
            <p style='color: var(--mm-text-faint); font-size: 0.85rem; font-family: var(--mm-mono); margin: 0;'>
                PROPRIETARY MODELS &nbsp;·&nbsp; NO-VIG PRICING &nbsp;·&nbsp; +EV ANALYTICS &nbsp;·&nbsp; CONFIDENCE RATINGS
            </p>
        </div>
    """, unsafe_allow_html=True)

# ---- TODAY'S CARD (Decision Engine) ----
elif nav == "🎯 Today's Card":
    st.title("🎯 Today's Card")
    st.caption("Ranked, not listed. Loads and runs every model automatically — MLB, NBA, NFL, and LoL.")

    # Real fix (August 2026) — same real global auto-run now covers
    # this page too, removed the redundant duplicate call.
    if st.session_state.get('today_card_updated_at'):
        st.caption(f"🕐 Last updated at {st.session_state['today_card_updated_at']}")

    card_entries = build_todays_card_entries()
    already_bet_by_sport = get_already_bet_players_today_by_sport()

    if not card_entries:
        st.markdown("""
            <div class='mm-card' style='text-align: center; padding: 48px 24px;'>
                <div style='font-size: 2rem; margin-bottom: 12px;'>🗓️</div>
                <h3 style='margin-bottom: 8px;'>Nothing to show right now</h3>
                <p style='color: var(--mm-text-dim); max-width: 480px; margin: 0 auto 20px auto;'>
                    No games found for today, or the odds API didn't return props. Try refreshing,
                    or check a model page directly.
                </p>
            </div>
        """, unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⚾ Go to MLB Models", use_container_width=True):
                st.session_state['nav_redirect'] = "⚾ MLB Models"
                st.rerun()
        with col2:
            if st.button("🏀 Go to NBA Models", use_container_width=True):
                st.session_state['nav_redirect'] = "🏀 NBA Models"
                st.rerun()
    else:
        groups = {"🟢 Best Bet": [], "🔵 Worth a Look": [], "🟡 Lean": [], "🔴 Pass": []}
        for e in card_entries:
            if e['tier'] in groups:
                groups[e['tier']].append(e)

        for tier_name in groups:
            groups[tier_name].sort(
                key=lambda e: (
                    e['ev_pct'] if e['ev_pct'] is not None else -999,
                    abs(e['edge']) if e['edge'] is not None else -999
                ),
                reverse=True
            )

        if st.button("🔄 Refresh Card"):
            for k in ['today_card_auto_ran', 'today_card_updated_at', 'all_pitchers', 'pitcher_results',
                      'all_nba_players', 'nba_pts_results',
                      'all_nba_assist_players', 'nba_ast_results']:
                st.session_state.pop(k, None)
            st.rerun()

        st.markdown(f"""
            <div style='display: flex; gap: 24px; padding: 12px 0 28px 0; flex-wrap: wrap; align-items: center;'>
                <div>{tier_badge("🟢 Best Bet")} <span style='font-family: var(--mm-mono); font-weight: 600;'>{len(groups["🟢 Best Bet"])}</span></div>
                <div>{tier_badge("🔵 Worth a Look")} <span style='font-family: var(--mm-mono); font-weight: 600;'>{len(groups["🔵 Worth a Look"])}</span></div>
                <div>{tier_badge("🟡 Lean")} <span style='font-family: var(--mm-mono); font-weight: 600;'>{len(groups["🟡 Lean"])}</span></div>
                <div>{tier_badge("🔴 Pass")} <span style='font-family: var(--mm-mono); font-weight: 600;'>{len(groups["🔴 Pass"])}</span></div>
            </div>
        """, unsafe_allow_html=True)

        bankroll, risk_style = get_bankroll_context()

        def render_ranked_section(title, entries, show_why_expander=True, auto_insight=False):
            if title:
                st.markdown(f"### {title}")
            if not entries:
                st.caption("Nothing here right now.")
                return
            for i, e in enumerate(entries, 1):
                col1, col2, col3, col4 = st.columns([0.5, 3.2, 1.1, 1.4])
                with col1:
                    st.markdown(f"<div style='font-family: var(--mm-mono); color: var(--mm-accent); font-weight: 600; padding-top: 4px;'>#{i}</div>", unsafe_allow_html=True)
                with col2:
                    play_short = (e['play'] or '').replace('⬆️ OVER', 'O').replace('⬇️ UNDER', 'U')
                    line_str = f" {play_short}{e['line']}" if e['line'] is not None else ""
                    already_bet_note = " &nbsp; <span style='color: var(--mm-success); font-size:0.75rem;'>✅ Already bet</span>" if e['name'] in already_bet_by_sport.get(sport_key_to_bet_label(e['sport_key']), set()) else ""
                    st.markdown(f"**{e['name']}**{line_str} &nbsp; <span style='color: var(--mm-text-faint); font-size:0.78rem;'>{e['sport_label']}</span>{already_bet_note}", unsafe_allow_html=True)
                    if e['tier'] == "🔴 Pass" and e['info'].get('Pass Reason'):
                        st.caption(f"Pass Reason: {e['info'].get('Pass Reason')}")
                with col3:
                    ev = e['ev_pct']
                    if ev is not None:
                        color = "var(--mm-success)" if ev > 0 else "var(--mm-danger)"
                        st.markdown(f"<span style='font-family: var(--mm-mono); color: {color}; font-weight: 600;'>EV: {'+' if ev > 0 else ''}{ev}%</span>", unsafe_allow_html=True)
                    else:
                        st.write("—")
                with col4:
                    st.markdown(tier_badge(e['tier']), unsafe_allow_html=True)
                    if e['tier'] != "🔴 Pass" and e['info'].get('Confidence Level') == "🔴 Low":
                        st.caption("🔴 Confidence: Low")
                # Real fix (August 2026, per direct user report — "on
                # today's card it only gives a why this bet and MM stake
                # for MLB props, we need that for every sport"). Found
                # TWO real, separate bugs causing this:
                #
                # 1. render_mm_stake_block() used to be nested INSIDE
                #    "if why_lines:" — meaning if generate_why() ever
                #    returned nothing for a real entry, BOTH the why
                #    section AND the MM Stake block silently vanished
                #    together, even though MM Stake doesn't actually
                #    depend on why_lines at all. Un-nested below so each
                #    renders independently.
                #
                # 2. generate_why() only ever understood MLB/NBA/NFL's
                #    real, shared info-dict shape (Projection, FanDuel
                #    Line, etc.) — LoL's real result dict uses a
                #    completely different shape (team1_name,
                #    recommended_model_prob, in_tournament_form, etc.),
                #    so generate_why() always returned empty for LoL,
                #    which is exactly what triggered bug #1 above for
                #    every single real LoL entry. Now detects LoL
                #    specifically and reuses the SAME real pill-based
                #    summary already proven on the LoL page itself,
                #    instead of forcing LoL's real data through a
                #    function built for a different sport's shape.
                if show_why_expander and e['result']:
                    is_lol_entry = e['sport_key'] == 'lol_moneyline'
                    if is_lol_entry:
                        r = e['info']
                        rec_is_team1 = r.get('recommended_side') == 'team1'
                        rec_rating = r.get('team1_rating') if rec_is_team1 else r.get('team2_rating')
                        opp_rating = r.get('team2_rating') if rec_is_team1 else r.get('team1_rating')
                        edge_pp = round((r.get('recommended_model_prob', 0) - r.get('recommended_market_prob', 0)) * 100, 1)
                        quick_pills = [_lol_pill(f"📊 +{edge_pp}pp edge vs market", "best")]
                        if rec_rating is not None and opp_rating is not None:
                            quick_pills.append(_lol_pill("📈 Higher rated" if rec_rating >= opp_rating else "📉 Lower rated (other signals outweigh)", "playable" if rec_rating >= opp_rating else "neutral"))
                        h2h = r.get("head_to_head") or {}
                        if h2h.get("total_h2h_series", 0) > 0:
                            rec_h2h = h2h.get("team1_h2h_wins", 0) if rec_is_team1 else h2h.get("team2_h2h_wins", 0)
                            opp_h2h = h2h.get("team2_h2h_wins", 0) if rec_is_team1 else h2h.get("team1_h2h_wins", 0)
                            if rec_h2h > opp_h2h:
                                quick_pills.append(_lol_pill("🤝 H2H favors pick", "playable"))
                            elif rec_h2h < opp_h2h:
                                quick_pills.append(_lol_pill("⚠️ H2H favors opponent", "lean"))
                        with st.expander("💡 Why this bet?"):
                            st.markdown("".join(quick_pills), unsafe_allow_html=True)
                            if r.get("context_description"):
                                st.markdown("---")
                                st.caption("Additional real market context:")
                                st.markdown(r["context_description"])
                        if auto_insight:
                            stake_info = {
                                'MM Tier': r.get('mm_tier'), 'Model Prob': r.get('recommended_model_prob'),
                                'Odds': r.get('recommended_odds'), 'EV%': r.get('ev_pct'),
                                # 'Edge' deliberately omitted — see the LoL page's own identical
                                # stake_info construction for the full real reasoning.
                            }
                            render_mm_stake_block(stake_info, {}, bankroll, risk_style)
                    else:
                        direction = e['info'].get('Direction', 'over')
                        why_lines = generate_why(e['info'], e['result'], direction, e['sport_key'])
                        if why_lines:
                            with st.expander("💡 Why this bet?"):
                                for line in why_lines:
                                    st.markdown(line)
                                if auto_insight and ANTHROPIC_API_KEY:
                                    cache_sport_label = 'MLB' if e['sport_key'] == 'mlb_strikeouts' else nba_bet_sport_label(e['sport_key'])
                                    with st.spinner("🧠 Generating model insight..."):
                                        insight, thesis_label = get_or_generate_ai_insight(
                                            mm_today_str(), cache_sport_label, e['name'], e['info'], e['result']
                                        )
                                    render_ai_insight_block(insight, thesis_label, e['result'], e['sport_key'])
                        if auto_insight:
                            render_mm_stake_block(e['info'], e['result'], bankroll, risk_style)
                st.divider()

        render_ranked_section("🟢 Today's Best Bets", groups["🟢 Best Bet"], auto_insight=True)
        render_ranked_section("🔵 Worth a Look", groups["🔵 Worth a Look"], auto_insight=True)

        with st.expander(f"🟡 Leans ({len(groups['🟡 Lean'])})"):
            render_ranked_section("", groups["🟡 Lean"], show_why_expander=False)

        with st.expander(f"🔴 Passes ({len(groups['🔴 Pass'])})"):
            render_ranked_section("", groups["🔴 Pass"], show_why_expander=False)

# ---- MLB PAGE ----
elif nav == "⚾ MLB Models":
    st.title("⚾ MLB Strikeout Model")
    st.markdown("---")
    bankroll, risk_style = get_bankroll_context()
    already_bet_today = get_already_bet_players_today('MLB')

    # Real fix (August 2026, per direct user request — "get rid of the
    # load player prop and run player projections buttons and just
    # have all the data fully there") — data is now already loaded
    # automatically by the real, global run_todays_card_auto_run()
    # call before page dispatch (backed by today's real caching fixes
    # — persistent daily_cache + the scheduled cache-warmer — so this
    # is genuinely fast now, not a guess that it'll be fine). This
    # button is now an OPTIONAL way to force a genuinely fresh odds
    # pull (load_mlb_props_data.clear() bypasses its 5-minute cache on
    # purpose here, since the whole point of clicking this is "get me
    # current lines right now") rather than a required first step.
    if st.button("🔄 Refresh Props & Projections", key="mlb_refresh"):
        load_mlb_props_data.clear()
        with st.spinner("Pulling fresh props and running projections..."):
            all_pitchers = load_mlb_props_data()
            if all_pitchers:
                progress_bar = st.progress(0)
                status_text = st.empty()
                total = len(all_pitchers)

                def _update_progress(i, total, name):
                    status_text.text(f"Running {i+1} of {total}: {name}")
                    progress_bar.progress((i + 1) / total)

                pitcher_results = run_all_mlb_projections(all_pitchers, '2026', progress_callback=_update_progress)
                st.session_state['all_pitchers'] = all_pitchers
                st.session_state['season'] = '2026'
                st.session_state['pitcher_results'] = pitcher_results
                st.session_state['manual_run_order'] = {}
                st.session_state['manual_run_counter'] = 0
                progress_bar.empty()
                status_text.empty()
                st.rerun()
            else:
                st.error("Couldn't load today's props — no games found or the odds API request failed.")

    if 'all_pitchers' in st.session_state:
        all_pitchers = st.session_state['all_pitchers']
        season = st.session_state.get('season', '2026')
        pitcher_results = st.session_state.get('pitcher_results', {})

        # Warn if any loaded game has since started — the props were pulled
        # at load time, but if enough time has passed, a game that hadn't
        # started yet then may have started since, meaning its projection
        # is now stale relative to the actual live game state (July 2026).
        now_utc = datetime.now(ZoneInfo("UTC"))
        started_since_load = []
        for pname, pdata in all_pitchers.items():
            ct_str = pdata.get('commence_time')
            if not ct_str:
                continue
            try:
                ct = datetime.fromisoformat(ct_str.replace('Z', '+00:00'))
                if ct <= now_utc:
                    started_since_load.append(pname)
            except (ValueError, TypeError):
                pass
        if started_since_load:
            names_preview = ", ".join(started_since_load[:5])
            more = f" and {len(started_since_load) - 5} more" if len(started_since_load) > 5 else ""
            st.warning(f"⚠️ {len(started_since_load)} loaded game(s) have started since you pulled props ({names_preview}{more}) — their projections are now stale. Click **\"🔄 Refresh Props & Projections\"** above to update.")

        manual_run_order = st.session_state.get('manual_run_order', {})

        sorted_pitchers = sorted(
            all_pitchers.items(),
            key=lambda x: (
                x[0] in manual_run_order,
                manual_run_order.get(x[0], 0),
                TIER_RANK.get(x[1].get('MM Tier'), -1),
                x[1]['EV%'] if x[1]['EV%'] is not None else -999,
                abs(x[1]['Edge']) if x[1]['Edge'] is not None else -999
            ),
            reverse=True
        )

        hcol1, hcol2, hcol3, hcol4, hcol5, hcol6, hcol7, hcol8, hcol9, hcol10, hcol11 = st.columns([2.0, 0.8, 0.8, 0.7, 0.7, 1.0, 1.4, 0.9, 1.5, 1.1, 1.1])
        header_style = "color: var(--mm-text-faint); font-size: 0.72rem; font-family: var(--mm-mono); letter-spacing: 0.04em; text-transform: uppercase;"
        for hcol, label in [
            (hcol1, "Pitcher"), (hcol2, "FD"), (hcol3, "DK"),
            (hcol4, "Proj"), (hcol5, "Edge"), (hcol6, "Play"),
            (hcol7, "Reliability"), (hcol8, "EV%"), (hcol9, "Tier"),
            (hcol10, ""), (hcol11, ""),
        ]:
            with hcol:
                st.markdown(f"<div style='{header_style}'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='padding-top: 6px;'></div>", unsafe_allow_html=True)

        for pitcher, info in sorted_pitchers:
            col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11 = st.columns([2.0, 0.8, 0.8, 0.7, 0.7, 1.0, 1.4, 0.9, 1.5, 1.1, 1.1])
            with col1:
                st.write(f"**{pitcher}**")
                st.caption(f"{info['away']} @ {info['home']}")
                if pitcher in already_bet_today:
                    st.caption("✅ Already bet today")
            with col2:
                st.write(f"FD: {info['FanDuel Line']}")
                st.caption(f"O:{fmt_odds(info['FanDuel Over'])} U:{fmt_odds(info['FanDuel Under'])}")
            with col3:
                st.write(f"DK: {info['DraftKings Line']}")
                st.caption(f"O:{fmt_odds(info['DraftKings Over'])} U:{fmt_odds(info['DraftKings Under'])}")
            with col4:
                st.write(f"Proj: **{info['Projection']}**" if info['Projection'] else "Proj: —")
            with col5:
                st.write(f"Edge: **{info['Edge']}**" if info['Edge'] is not None else "Edge: —")
            with col6:
                st.markdown(f"<div style='white-space: nowrap;'>{info['Play']}</div>" if info['Play'] else "—", unsafe_allow_html=True)
            with col7:
                st.write(short_tier_label(info.get('Tier')))
            with col8:
                ev = info.get('EV%')
                st.write(f"EV: **{ev}%**" if ev is not None else "EV: —")
            with col9:
                st.markdown(tier_badge(info.get('MM Tier'), compact=True), unsafe_allow_html=True)
                if info.get('MM Tier') == "🔴 Pass" and info.get('Pass Reason'):
                    st.caption(info.get('Pass Reason'))
                elif info.get('Confidence Level') == "🔴 Low":
                    st.caption("🔴 Confidence: Low")
            with col10:
                if st.button("▶️ Run", key=f"run_{pitcher}"):
                    with st.spinner(f"Running {pitcher}..."):
                        _, opp, h = get_pitcher_game_info(pitcher)
                        if not opp:
                            opp = info['away']
                            h = info['home']
                        result = force_run_and_cache_mlb(pitcher, opp, h, season, mm_today_str())
                        if result:
                            proj = result['projection']
                            best_line = info['FanDuel Line'] or info['DraftKings Line']
                            if best_line:
                                edge = round(proj - best_line, 1)
                                play = "⬆️ OVER" if edge > 0 else "⬇️ UNDER"
                                direction = 'over' if edge > 0 else 'under'
                                over_odds = info['FanDuel Over'] or info['DraftKings Over']
                                under_odds = info['FanDuel Under'] or info['DraftKings Under']
                                ev_result = analyze_prop(
                                    projection=proj, line=best_line,
                                    std_dev=result['last10_k_std'], cv=result['cv'],
                                    over_odds=over_odds or -110, under_odds=under_odds or -110,
                                    direction=direction, sport='mlb_strikeouts',
                                    workload_tier=result.get('workload_tier'), confidence_tier=result.get('confidence_tier')
                                )
                                st.session_state['all_pitchers'][pitcher].update({
                                    'Projection': proj, 'Edge': edge, 'Play': play,
                                    'Tier': result['confidence_tier'],
                                    'EV%': ev_result['ev_pct'] if ev_result else None,
                                    'Raw EV%': ev_result['raw_ev_pct'] if ev_result else None,
                                    'MM Tier': ev_result['tier'] if ev_result else None,
                                    'Pass Reason': ev_result['pass_reason'] if ev_result else None,
                                    'Confidence Level': ev_result['confidence_level'] if ev_result else None,
                                    'Model Prob': ev_result['model_prob'] if ev_result else None,
                                    'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
                                    'Model Edge': ev_result['model_edge'] if ev_result else None,
                                    'Odds': over_odds if direction == 'over' else under_odds,
                                    'Direction': direction,
                                    'Fair Odds': ev_result['fair_odds'] if ev_result else None,
                                    'Effective Std': ev_result['effective_std'] if ev_result else None,
                                    'Adjusted Projection': ev_result['adjusted_projection'] if ev_result else None,
                                    'Opposite Odds': ev_result['opposite_odds'] if ev_result else None,
                                    'Edge Cents': ev_result['edge_cents'] if ev_result else None,
                                    'Low Confidence': ev_result['low_confidence'] if ev_result else None,
                                })
                                st.session_state['pitcher_results'][pitcher] = result
                                st.session_state['last_pitcher'] = pitcher
                                st.session_state.setdefault('manual_run_order', {})
                                st.session_state['manual_run_counter'] = st.session_state.get('manual_run_counter', 0) + 1
                                st.session_state['manual_run_order'][pitcher] = st.session_state['manual_run_counter']
                                save_prediction({
                                    'date': mm_today_str(),
                                    'pitcher': pitcher, 'opponent': opp, 'home_team': h,
                                    'projection': proj, 'base': result['base'], 'book_line': best_line,
                                    'edge': edge, 'opp_factor': result['opp_factor'],
                                    'park_factor': result['park_factor'], 'umpire_factor': result['umpire_factor'],
                                    'velo_factor': result['velo_factor'], 'total_factor': result['total_factor'],
                                    'pitch_count_factor': result['pitch_count_factor'],
                                    'lineup_factor': result['lineup_factor'],
                                    'cv': result['cv'], 'confidence_tier': result['confidence_tier'],
                                    'actual': None, 'sport': 'MLB',
                                    'ev_pct': ev_result['ev_pct'] if ev_result else None,
                                    'mm_tier': ev_result['tier'] if ev_result else None,
                                    'model_prob': ev_result['model_prob'] if ev_result else None,
                                    'no_vig_prob': ev_result['no_vig_prob'] if ev_result else None,
                                    'model_edge': ev_result['model_edge'] if ev_result else None,
                                })
                                st.rerun()
            with col11:
                if info.get('Projection') is not None:
                    if st.button("📝 Log", key=f"log_{pitcher}"):
                        st.session_state[f'log_modal_{pitcher}'] = True

            if info.get('Projection') is not None and pitcher in pitcher_results:
                result = pitcher_results[pitcher]
                direction = info.get('Direction', 'over')
                why_lines = generate_why(info, result, direction, 'mlb_strikeouts')
                if why_lines:
                    with st.expander(f"💡 Why this bet? — {pitcher}"):
                        for line in why_lines:
                            st.markdown(line)
                        if ANTHROPIC_API_KEY:
                            if st.button("🧠 Generate Model Insight", key=f"insight_btn_{pitcher}"):
                                with st.spinner("🧠 Generating model insight..."):
                                    insight, thesis_label = get_or_generate_ai_insight(
                                        mm_today_str(), 'MLB', pitcher, info, result
                                    )
                                if insight:
                                    render_ai_insight_block(insight, thesis_label, result, 'mlb_strikeouts')
                                else:
                                    st.caption("Couldn't generate an insight right now.")
                    render_mm_stake_block(info, result, bankroll, risk_style)

            if st.session_state.get(f'log_modal_{pitcher}'):
                with st.expander(f"📝 Log Bet — {pitcher}", expanded=True):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        log_ou = st.selectbox("Over or Under?", ["Over", "Under"], key=f"log_ou_{pitcher}")
                        log_bet = st.number_input("Bet Amount ($)", value=None, min_value=0.0, placeholder="e.g. 100.50", step=0.01, format="%.2f", key=f"log_bet_{pitcher}")
                        log_odds = st.number_input("Odds (e.g. -140 or +110)", value=None, placeholder="e.g. -140", step=1, key=f"log_odds_{pitcher}")
                    with col_b:
                        log_actual = st.number_input("Actual Strikeouts (fill after game)", value=None, placeholder="e.g. 7", key=f"log_actual_{pitcher}")
                        log_result = st.selectbox("Result", ["Pending", "Win", "Loss"], key=f"log_result_{pitcher}")

                    log_mm_stake_dollars = None
                    _log_result_data = pitcher_results.get(pitcher)
                    if bankroll and _log_result_data:
                        _log_stake = calculate_mm_stake(info, _log_result_data, bankroll, risk_style)
                        if _log_stake and not _log_stake.get('pass'):
                            log_mm_stake_dollars = _log_stake['stake_dollars']
                            if log_bet:
                                st.caption(format_stake_deviation_message(log_mm_stake_dollars, log_bet))
                            else:
                                st.caption(f"💰 MM Stake recommendation: ${log_mm_stake_dollars:,.2f}")

                    if st.button(f"✅ Confirm Log Bet", key=f"log_confirm_{pitcher}", use_container_width=True):
                        if log_result != "Pending" and log_actual is None:
                            st.error("Enter the actual result before marking the bet settled.")
                        else:
                            odds = int(log_odds) if log_odds else -110
                            bet_val = round(float(log_bet), 2) if log_bet else 0.0
                            profit = calc_profit(bet_val, odds, log_result)
                            # Real addition (July 2026, per direct user
                            # request) — looks up the real game_pk for
                            # this pitcher's real game today, so a
                            # later "Refresh Results" action can pull
                            # the actual, final strikeout count
                            # automatically instead of requiring manual
                            # entry. Wrapped safely — if this lookup
                            # fails for any reason, the bet still logs
                            # normally, just without auto-refresh for
                            # this one bet (falls back to manual entry).
                            bet_game_pk = None
                            try:
                                todays_starters = get_starters_for_date(mm_today_str())
                                matching_starter = next((s for s in todays_starters if s['pitcher'].lower() == pitcher.lower()), None)
                                if matching_starter:
                                    bet_game_pk = matching_starter['game_pk']
                            except Exception:
                                pass
                            save_bet({
                                'date': mm_today_str(), 'pitcher': pitcher,
                                'projection': info.get('Projection') or 0,
                                'opening_line': info.get('FanDuel Line') or info.get('DraftKings Line') or 0,
                                'over_under': log_ou, 'odds': odds,
                                'bet_amount': bet_val, 'result': log_result,
                                'actual': log_actual or 0, 'profit': profit,
                                'sport': 'MLB', 'ev_pct': info.get('EV%'),
                                'mm_tier': info.get('MM Tier'),
                                'model_edge': info.get('Model Edge'), 'no_vig_prob': info.get('No Vig Prob'),
                                'model_prob': info.get('Model Prob'), 'confidence_tier': info.get('Tier'),
                                'mm_stake_recommended': log_mm_stake_dollars,
                                'sportsbook': info.get('Book'), 'raw_ev_pct': info.get('Raw EV%'),
                                'opposite_odds': info.get('Opposite Odds'),
                                'adjusted_projection': info.get('Adjusted Projection'),
                                'effective_std': info.get('Effective Std'),
                                'model_version': MODEL_VERSION, 'ev_engine_version': EV_ENGINE_VERSION,
                                'logged_at': datetime.now(ZoneInfo("UTC")).isoformat(),
                                'game_pk': bet_game_pk,
                            })
                            st.session_state[f'log_modal_{pitcher}'] = False
                            st.success(f"✅ Bet logged for {pitcher}!")
                            st.rerun()

            st.divider()

# ---- NFL PAGE ----


elif nav == "🏈 NFL Models":
    st.title("🏈 NFL Models")
    st.markdown("---")

    nfl_model_select = st.selectbox("Select Model", ["NFL Pass Attempts", "NFL Pass Completions", "NFL Receptions"])

    if nfl_model_select == "NFL Pass Attempts":
        run_nfl_display('all_qbs', load_nfl_props_data, run_all_nfl_projections, run_single_nfl_attempts, 'nfl_attempts', 'QB', 'NFL', 'nfl_pass_attempts')
    elif nfl_model_select == "NFL Pass Completions":
        run_nfl_display('all_qbs_completions', load_nfl_completions_props_data, run_all_nfl_completions_projections, run_single_nfl_completions, 'nfl_completions', 'QB', 'NFL_COMPLETIONS', 'nfl_pass_completions')
    else:
        run_nfl_display('all_receivers', load_nfl_receptions_props_data, run_all_nfl_receptions_projections, run_single_nfl_receptions, 'nfl_receptions', 'Player', 'NFL_RECEPTIONS', 'nfl_receptions')

elif nav == "🏀 NBA Models":
    st.title("🏀 NBA Models")
    st.markdown("---")

    nba_model_select = st.selectbox("Select Model", ["NBA Points", "NBA Assists"])

    def run_nba_display(all_players_key, run_fn, sport_key, prop_market, session_key):
        bankroll, risk_style = get_bankroll_context()
        already_bet_today = get_already_bet_players_today(nba_bet_sport_label(sport_key))

        # Real fix (August 2026, per direct user request) — data is
        # now already loaded automatically by the real, global
        # run_todays_card_auto_run() call before page dispatch. This
        # button is now an OPTIONAL way to force a genuinely fresh
        # odds pull (load_nba_props_data.clear() bypasses its 5-minute
        # cache on purpose here) rather than a required first step.
        label = "NBA Points" if prop_market == 'player_points' else "Assist"
        if st.button(f"🔄 Refresh {label} Props & Projections", key=f"refresh_{session_key}"):
            load_nba_props_data.clear()
            with st.spinner(f"Pulling fresh {label} props and running projections..."):
                all_players = load_nba_props_data(prop_market)
                if all_players:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    total = len(all_players)

                    def _update_progress(i, total, name):
                        status_text.text(f"Running {i+1} of {total}: {name}")
                        progress_bar.progress((i + 1) / total)

                    results = run_all_nba_projections(all_players, run_fn, sport_key, '2025-26', progress_callback=_update_progress)
                    st.session_state[all_players_key] = all_players
                    st.session_state['nba_season'] = '2025-26'
                    st.session_state.setdefault(f'{session_key}_results', {})
                    st.session_state[f'{session_key}_results'].update(results)
                    st.session_state[f'manual_run_order_{session_key}'] = {}
                    progress_bar.empty()
                    status_text.empty()
                    st.rerun()
                else:
                    st.error("Couldn't load today's props — no games found or the odds API request failed.")

        if all_players_key in st.session_state:
            all_players = st.session_state[all_players_key]
            season = st.session_state.get('nba_season', '2025-26')
            player_results = st.session_state.get(f'{session_key}_results', {})
            manual_run_order = st.session_state.get(f'manual_run_order_{session_key}', {})

            sorted_players = sorted(
                all_players.items(),
                key=lambda x: (
                    x[0] in manual_run_order,
                    manual_run_order.get(x[0], 0),
                    TIER_RANK.get(x[1].get('MM Tier'), -1),
                    x[1]['EV%'] if x[1]['EV%'] is not None else -999,
                    abs(x[1]['Edge']) if x[1]['Edge'] is not None else -999
                ),
                reverse=True
            )

            hcol1, hcol2, hcol3, hcol4, hcol5, hcol6, hcol7, hcol8, hcol9, hcol10, hcol11 = st.columns([2.0, 0.8, 0.8, 0.7, 0.7, 1.0, 1.4, 0.9, 1.5, 1.1, 1.1])
            header_style = "color: var(--mm-text-faint); font-size: 0.72rem; font-family: var(--mm-mono); letter-spacing: 0.04em; text-transform: uppercase;"
            for hcol, label in [
                (hcol1, "Player"), (hcol2, "FD"), (hcol3, "DK"),
                (hcol4, "Proj"), (hcol5, "Edge"), (hcol6, "Play"),
                (hcol7, "Reliability"), (hcol8, "EV%"), (hcol9, "Tier"),
                (hcol10, ""), (hcol11, ""),
            ]:
                with hcol:
                    st.markdown(f"<div style='{header_style}'>{label}</div>", unsafe_allow_html=True)
            st.markdown("<div style='padding-top: 6px;'></div>", unsafe_allow_html=True)

            for player, info in sorted_players:
                col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11 = st.columns([2.0, 0.8, 0.8, 0.7, 0.7, 1.0, 1.4, 0.9, 1.5, 1.1, 1.1])
                with col1:
                    st.write(f"**{player}**")
                    st.caption(f"{info['away']} @ {info['home']}")
                    if player in already_bet_today:
                        st.caption("✅ Already bet today")
                with col2:
                    st.write(f"FD: {info['FanDuel Line']}")
                    st.caption(f"O:{fmt_odds(info['FanDuel Over'])} U:{fmt_odds(info['FanDuel Under'])}")
                with col3:
                    st.write(f"DK: {info['DraftKings Line']}")
                    st.caption(f"O:{fmt_odds(info['DraftKings Over'])} U:{fmt_odds(info['DraftKings Under'])}")
                with col4:
                    st.write(f"Proj: **{info['Projection']}**" if info['Projection'] else "Proj: —")
                with col5:
                    st.write(f"Edge: **{info['Edge']}**" if info['Edge'] is not None else "Edge: —")
                with col6:
                    st.markdown(f"<div style='white-space: nowrap;'>{info['Play']}</div>" if info['Play'] else "—", unsafe_allow_html=True)
                with col7:
                    st.write(short_tier_label(info.get('Tier')))
                with col8:
                    ev = info.get('EV%')
                    st.write(f"EV: **{ev}%**" if ev is not None else "EV: —")
                with col9:
                    st.markdown(tier_badge(info.get('MM Tier'), compact=True), unsafe_allow_html=True)
                    if info.get('MM Tier') == "🔴 Pass" and info.get('Pass Reason'):
                        st.caption(info.get('Pass Reason'))
                    elif info.get('Confidence Level') == "🔴 Low":
                        st.caption("🔴 Confidence: Low")
                with col10:
                    if st.button("▶️ Run", key=f"{session_key}_run_{player}"):
                        with st.spinner(f"Running {player}..."):
                            home_team = info['home']
                            away_team = info['away']
                            home_abbrev = nba_name_to_abbrev.get(home_team, '')
                            away_abbrev = nba_name_to_abbrev.get(away_team, '')
                            try:
                                bdl_season = int(season.split("-")[0])
                                check_df, _ = get_bdl_player_game_log(player, bdl_season)
                                if not check_df.empty:
                                    check_df['_game_date'] = pd.to_datetime(check_df['game'].apply(lambda g: (g or {}).get('date')))
                                    check_df = check_df.sort_values('_game_date')
                                    last_row = check_df.iloc[-1]
                                    game_info = last_row.get('game') or {}
                                    team_info = last_row.get('team') or {}
                                    home_or_away = 'home' if game_info.get('home_team_id') == team_info.get('id') else 'away'
                                    opp_abbrev = away_abbrev if home_or_away == 'home' else home_abbrev
                                else:
                                    home_or_away = 'home'
                                    opp_abbrev = away_abbrev
                            except Exception as e:
                                log_failure_reason('MISSING_TEAM_MERGE', f"home/away detection for {player}: {e}")
                                home_or_away = 'home'
                                opp_abbrev = away_abbrev
                            result = force_run_and_cache_nba(
                                run_fn, nba_bet_sport_label(sport_key), player, opp_abbrev, home_team, away_team,
                                home_or_away, season, mm_today_str()
                            )
                            if result:
                                proj = result['projection']
                                best_line = info['FanDuel Line'] or info['DraftKings Line']
                                if best_line:
                                    edge = round(proj - best_line, 1)
                                    play = "⬆️ OVER" if edge > 0 else "⬇️ UNDER"
                                    direction = 'over' if edge > 0 else 'under'
                                    over_odds = info['FanDuel Over'] or info['DraftKings Over']
                                    under_odds = info['FanDuel Under'] or info['DraftKings Under']
                                    std_dev = result.get('last10_pts_std', result.get('last10_ast_std', 0))
                                    ev_result = analyze_prop(
                                        projection=proj, line=best_line, std_dev=std_dev, cv=result['cv'],
                                        over_odds=over_odds or -110, under_odds=under_odds or -110,
                                        direction=direction, sport=sport_key,
                                        workload_tier=result.get('workload_tier'), confidence_tier=result.get('confidence_tier')
                                    )
                                    st.session_state[all_players_key][player].update({
                                        'Projection': proj, 'Edge': edge, 'Play': play,
                                        'Tier': result['confidence_tier'],
                                        'EV%': ev_result['ev_pct'] if ev_result else None,
                                        'Raw EV%': ev_result['raw_ev_pct'] if ev_result else None,
                                        'MM Tier': ev_result['tier'] if ev_result else None,
                                        'Pass Reason': ev_result['pass_reason'] if ev_result else None,
                                        'Confidence Level': ev_result['confidence_level'] if ev_result else None,
                                        'Low Confidence': ev_result['low_confidence'] if ev_result else None,
                                        'Fair Odds': ev_result['fair_odds'] if ev_result else None,
                                        'Effective Std': ev_result['effective_std'] if ev_result else None,
                                        'Adjusted Projection': ev_result['adjusted_projection'] if ev_result else None,
                                        'Opposite Odds': ev_result['opposite_odds'] if ev_result else None,
                                        'Edge Cents': ev_result['edge_cents'] if ev_result else None,
                                        'Direction': direction,
                                        'Odds': over_odds if direction == 'over' else under_odds,
                                        'Model Prob': ev_result['model_prob'] if ev_result else None,
                                        'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
                                    })
                                    st.session_state.setdefault(f'{session_key}_results', {})
                                    st.session_state[f'{session_key}_results'][player] = result
                                    st.session_state.setdefault(f'manual_run_order_{session_key}', {})
                                    st.session_state[f'manual_run_counter_{session_key}'] = st.session_state.get(f'manual_run_counter_{session_key}', 0) + 1
                                    st.session_state[f'manual_run_order_{session_key}'][player] = st.session_state[f'manual_run_counter_{session_key}']
                                    st.rerun()
                with col11:
                    if info.get('Projection') is not None:
                        if st.button("📝 Log", key=f"{session_key}_log_{player}"):
                            st.session_state[f'{session_key}_log_modal_{player}'] = True

                if info.get('Projection') is not None and player in player_results:
                    result = player_results[player]
                    direction = info.get('Direction', 'over')
                    why_lines = generate_why(info, result, direction, sport_key)
                    if why_lines:
                        with st.expander(f"💡 Why this bet? — {player}"):
                            for line in why_lines:
                                st.markdown(line)
                            if ANTHROPIC_API_KEY:
                                if st.button("🧠 Generate Model Insight", key=f"{session_key}_insight_btn_{player}"):
                                    with st.spinner("🧠 Generating model insight..."):
                                        insight, thesis_label = get_or_generate_ai_insight(
                                            mm_today_str(), nba_bet_sport_label(sport_key), player, info, result
                                        )
                                    if insight:
                                        render_ai_insight_block(insight, thesis_label, result, sport_key)
                                    else:
                                        st.caption("Couldn't generate an insight right now.")
                        render_mm_stake_block(info, result, bankroll, risk_style)

                if st.session_state.get(f'{session_key}_log_modal_{player}'):
                    bet_sport_label = nba_bet_sport_label(sport_key)
                    with st.expander(f"📝 Log Bet — {player}", expanded=True):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            log_ou = st.selectbox("Over or Under?", ["Over", "Under"], key=f"{session_key}_log_ou_{player}")
                            log_bet = st.number_input("Bet Amount ($)", value=None, min_value=0.0, placeholder="e.g. 100.50", step=0.01, format="%.2f", key=f"{session_key}_log_bet_{player}")
                            log_odds = st.number_input("Odds (e.g. -140 or +110)", value=None, placeholder="e.g. -140", step=1, key=f"{session_key}_log_odds_{player}")
                        with col_b:
                            _nba_actual_label = "Actual Points (fill after game)" if sport_key == 'nba_points' else "Actual Assists (fill after game)"
                            log_actual = st.number_input(_nba_actual_label, value=None, placeholder="e.g. 25", key=f"{session_key}_log_actual_{player}")
                            log_result = st.selectbox("Result", ["Pending", "Win", "Loss"], key=f"{session_key}_log_result_{player}")

                        log_mm_stake_dollars = None
                        _log_result_data = player_results.get(player)
                        if bankroll and _log_result_data:
                            _log_stake = calculate_mm_stake(info, _log_result_data, bankroll, risk_style)
                            if _log_stake and not _log_stake.get('pass'):
                                log_mm_stake_dollars = _log_stake['stake_dollars']
                                if log_bet:
                                    st.caption(format_stake_deviation_message(log_mm_stake_dollars, log_bet))
                                else:
                                    st.caption(f"💰 MM Stake recommendation: ${log_mm_stake_dollars:,.2f}")

                        if st.button("✅ Confirm Log Bet", key=f"{session_key}_log_confirm_{player}", use_container_width=True):
                            if log_result != "Pending" and log_actual is None:
                                st.error("Enter the actual result before marking the bet settled.")
                            else:
                                odds = int(log_odds) if log_odds else -110
                                bet_val = round(float(log_bet), 2) if log_bet else 0.0
                                profit = calc_profit(bet_val, odds, log_result)
                                save_bet({
                                    'date': mm_today_str(), 'pitcher': player,
                                    'projection': info.get('Projection') or 0,
                                    'opening_line': info.get('FanDuel Line') or info.get('DraftKings Line') or 0,
                                    'over_under': log_ou, 'odds': odds,
                                    'bet_amount': bet_val, 'result': log_result,
                                    'actual': log_actual or 0, 'profit': profit,
                                    'sport': bet_sport_label, 'ev_pct': info.get('EV%'),
                                    'mm_tier': info.get('MM Tier'),
                                    'model_edge': info.get('Edge'), 'confidence_tier': info.get('Tier'),
                                    'model_prob': info.get('Model Prob'), 'no_vig_prob': info.get('No Vig Prob'),
                                    'mm_stake_recommended': log_mm_stake_dollars,
                                    'sportsbook': info.get('Book'), 'raw_ev_pct': info.get('Raw EV%'),
                                    'opposite_odds': info.get('Opposite Odds'),
                                    'adjusted_projection': info.get('Adjusted Projection'),
                                    'effective_std': info.get('Effective Std'),
                                    'model_version': MODEL_VERSION, 'ev_engine_version': EV_ENGINE_VERSION,
                                    'logged_at': datetime.now(ZoneInfo("UTC")).isoformat(),
                                })
                                st.session_state[f'{session_key}_log_modal_{player}'] = False
                                st.success(f"✅ Bet logged for {player}!")
                                st.rerun()

                st.divider()

    if nba_model_select == "NBA Points":
        run_nba_display('all_nba_players', run_nba_points_projection, 'nba_points', 'player_points', 'nba_pts')
    else:
        run_nba_display('all_nba_assist_players', run_nba_assists_projection, 'nba_assists', 'player_assists', 'nba_ast')

# ---- MODEL PERFORMANCE (PUBLIC TRUST PAGE) ----
elif nav == "📊 Model Performance":
    st.title("📊 Model Performance")
    st.markdown("""
        <p style='color: var(--mm-text-dim); max-width: 640px; margin-bottom: 24px;'>
            Every number below is a real, tracked record — not a backtest run once and forgotten.
            Updated whenever new results come in.
        </p>
    """, unsafe_allow_html=True)

    perf_sports = [("MLB", "⚾ MLB Strikeout Model"), ("NBA", "🏀 NBA Points Model"), ("NBA_AST", "🏀 NBA Assists Model")]
    any_published = False

    for sport_key, label in perf_sports:
        stats = get_published_model_performance(sport_key)
        if not stats:
            continue
        any_published = True

        st.markdown(f"### {label}")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Projections Tracked", stats.get('total_projections') or "—")
        col2.metric("MAE", stats.get('mae') if stats.get('mae') is not None else "—")
        roi = stats.get('roi')
        col3.metric("ROI", f"{'+' if roi and roi > 0 else ''}{roi}%" if roi is not None else "—")
        beat_close = stats.get('beat_close_pct')
        col4.metric("Beat Closing Line", f"{beat_close}%" if beat_close is not None else "—")

        profit_series = stats.get('profit_series')
        if profit_series:
            profit_df = pd.DataFrame(profit_series)
            if not profit_df.empty and 'date' in profit_df.columns:
                profit_df = profit_df.set_index('date')
                st.line_chart(profit_df['cumulative_profit'])

        updated_at = stats.get('updated_at')
        if updated_at:
            try:
                updated_dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                updated_et = updated_dt.astimezone(ZoneInfo("America/New_York")).strftime('%b %d, %Y at %I:%M %p ET').replace(' 0', ' ')
                st.caption(f"Last updated {updated_et} · Sample size: {stats.get('total_bets') or 0} settled bets")
            except Exception:
                pass
        st.markdown("---")

    if not any_published:
        st.info("Model performance stats haven't been published yet — check back soon.")

# ---- BET TRACKER PAGE ----
elif nav == "📒 Bet Tracker":
    st.title("📒 Bet Tracker")

    # Real fix (August 2026, per direct user report — "no nba points or
    # nfl pass attempts" showing in the filter) — the dropdown used to
    # show the raw, internal sport codes directly ("NBA_AST",
    # "NFL_COMPLETIONS"), which don't read as real, distinct options at
    # a glance — "NBA" alone doesn't say Points specifically, and
    # "NFL" alone doesn't say Pass Attempts specifically. This maps
    # real, friendly labels to the exact same underlying codes already
    # stored in the database — filtering behavior is completely
    # unchanged, just what's actually shown in the dropdown.
    SPORT_FILTER_LABELS = {
        "All": "All", "MLB": "MLB", "NBA": "NBA Points", "NBA_AST": "NBA Assists",
        "NFL": "NFL Pass Attempts", "NFL_COMPLETIONS": "NFL Pass Completions",
        "NFL_RECEPTIONS": "NFL Receptions", "LOL": "Esports (LoL)",
    }
    SPORT_FILTER_CODES = {v: k for k, v in SPORT_FILTER_LABELS.items()}
    sport_filter_label = st.selectbox("Filter by Sport", list(SPORT_FILTER_LABELS.values()), key="bet_sport_filter")
    sport_filter = SPORT_FILTER_CODES[sport_filter_label]
    sport_query = None if sport_filter == "All" else sport_filter

    bets = load_bets(sport_query)

    tab_recent, tab_stats, tab_manage = st.tabs(["📋 Recent Bets", "📊 Stats & Insights", "⚙️ Manage"])

    with tab_recent:
        st.markdown("---")
        with st.expander("➕ Log a Bet Manually", expanded=False):
            st.caption("For bets outside today's model run (backfilling, or a prop not pulled from the models). For anything you ran through the models, use the 📝 Log button on that row instead — it auto-fills everything and includes your MM Stake recommendation.")

            bet_sport_label = st.selectbox("Sport", [v for k, v in SPORT_FILTER_LABELS.items() if k != "All"], key="new_bet_sport")
            bet_sport = SPORT_FILTER_CODES[bet_sport_label]
            # Real fix (July 2026) — LoL is structurally different (a real
            # matchup between two teams with win probabilities, not a
            # single player against an over/under line), so it needs its
            # own real branch rather than being forced into the same
            # fields as every other sport.
            is_lol = bet_sport == "LOL"

            col1, col2, col3 = st.columns(3)
            with col1:
                if is_lol:
                    bt_team1 = st.text_input("Team 1", placeholder="e.g. T1")
                    bt_team2 = st.text_input("Team 2", placeholder="e.g. Gen.G")
                    bt_player = f"{bt_team1} vs {bt_team2}" if bt_team1 or bt_team2 else ""
                    bt_projection = st.number_input("Model Win Probability (%)", value=None, placeholder="e.g. 62.5", min_value=0.0, max_value=100.0)
                elif bet_sport == "MLB":
                    bt_player = st.selectbox("Pitcher", pitchers_list, index=0)
                    bt_projection = st.number_input("Your Projection", value=None, placeholder="e.g. 6.4")
                else:
                    bt_player = st.text_input("Player Name", placeholder="e.g. LeBron James")
                    bt_projection = st.number_input("Your Projection", value=None, placeholder="e.g. 6.4")
                if is_lol:
                    bt_opening_line = st.number_input("Market Implied Probability (%)", value=None, placeholder="e.g. 55.0", min_value=0.0, max_value=100.0)
                else:
                    bt_opening_line = st.number_input("Book Line", value=None, placeholder="e.g. 5.5")
                bt_bet = st.number_input("Bet Amount ($)", value=None, min_value=0.0, placeholder="e.g. 100.50", step=0.01, format="%.2f")
                bt_model_edge = None if is_lol else st.number_input("Model Edge", value=None, placeholder="e.g. 0.9")
            with col2:
                bt_date = st.date_input("Date")
                if is_lol:
                    bt_over_under = st.text_input("Team You Bet On", placeholder="e.g. T1")
                else:
                    bt_over_under = st.selectbox("Over or Under?", ["Over", "Under"])
                bt_odds = st.number_input("Odds (e.g. -140 or +110)", value=None, placeholder="e.g. -140")
                bt_actual = None if is_lol else st.number_input("Actual Statistic", value=None, placeholder="e.g. 7")
                bt_ev_pct = st.number_input("EV% at time of bet", value=None, placeholder="e.g. 6.2")
            with col3:
                bt_result = st.selectbox("Result", ["Pending", "Win", "Loss"])
                if is_lol:
                    bt_tier = st.selectbox("MM Tier", ["", "🟢 Best Bet", "🔵 Worth a Look", "🟡 Lean", "🔴 Pass"])
                else:
                    bt_tier = st.selectbox("Reliability", ["", "🟢 Reliable", "🟠 Volatile", "🔴 Uncertain Workload"])
                bt_no_vig_prob = None if is_lol else st.number_input("No-Vig Prob", value=None, placeholder="e.g. 0.52")
                bt_model_prob = st.number_input("Model Prob", value=None, placeholder="e.g. 0.61")

            if st.button("Log Bet"):
                odds_val = bt_odds or -110
                bet_val = round(float(bt_bet), 2) if bt_bet else 0.0
                profit = calc_profit(bet_val, odds_val, bt_result)
                # Real fix (July 2026, per direct user feedback) — for LoL,
                # rebuild the matchup text here (now that both team names
                # AND the pick are available) to lead with the real,
                # picked team, so it's immediately obvious which side was
                # bet on — same fix already applied to the LoL page's own
                # Log button.
                final_player = bt_player
                final_over_under = bt_over_under
                if is_lol and bt_over_under:
                    lol_other_team = bt_team2 if bt_over_under.strip().lower() == (bt_team1 or '').strip().lower() else bt_team1
                    final_player = f"{bt_over_under} (vs {lol_other_team})" if lol_other_team else bt_over_under
                    final_over_under = '-'  # over/under genuinely doesn't apply to a moneyline bet
                bet_payload = {
                    'date': str(bt_date), 'pitcher': final_player,
                    'projection': (bt_projection / 100 if is_lol and bt_projection else bt_projection) or 0,
                    'opening_line': (bt_opening_line / 100 if is_lol and bt_opening_line else bt_opening_line) or 0,
                    'over_under': final_over_under, 'odds': odds_val,
                    'bet_amount': bet_val, 'result': bt_result,
                    'actual': bt_actual or 0, 'profit': profit,
                    'sport': bet_sport, 'ev_pct': bt_ev_pct,
                    'model_prob': (bt_model_prob / 100 if bt_model_prob else None),
                }
                if is_lol:
                    # Matches the exact real field convention the LoL
                    # page's own Log button already uses — mm_tier instead
                    # of confidence_tier, no no_vig_prob/model_edge at all.
                    bet_payload['mm_tier'] = bt_tier or None
                else:
                    bet_payload['confidence_tier'] = bt_tier or None
                    bet_payload['model_edge'] = bt_model_edge
                    bet_payload['no_vig_prob'] = bt_no_vig_prob
                save_bet(bet_payload)
                st.rerun()


        st.markdown("---")
        st.subheader("📋 Recent Bets")
        if not bets:
            st.info("No bets logged yet — log one above, or check back after running a model and hitting \"📝 Log\" on a pick.")
        else:
            RECENT_BETS_SHOW_LIMIT = 25
            sorted_bets = sorted(bets, key=lambda b: b.get('date') or '', reverse=True)
            show_all_recent = st.session_state.get('bt_show_all_recent', False)
            bets_to_show = sorted_bets if show_all_recent else sorted_bets[:RECENT_BETS_SHOW_LIMIT]
            for _b in bets_to_show:
                _result = _b.get('result', 'Pending')
                _result_kind = 'best' if _result == 'Win' else ('pass' if _result == 'Loss' else 'neutral')
                _result_icon = '✅' if _result == 'Win' else ('❌' if _result == 'Loss' else '⏳')
                _profit = _b.get('profit', 0) or 0
                _profit_color = 'var(--mm-success)' if _profit > 0 else ('var(--mm-danger)' if _profit < 0 else 'var(--mm-text-dim)')
                _profit_str = f"+${_profit:,.2f}" if _profit > 0 else (f"-${abs(_profit):,.2f}" if _profit < 0 else "$0.00")
                st.markdown(f"""
                    <div class='mm-card' style='margin-bottom: 10px; padding: 14px 18px;'>
                        <div style='display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;'>
                            <div>
                                <span style='font-weight: 600; font-size: 1.02rem;'>{_b.get('pitcher', 'Unknown')}</span>
                                <span class='mm-badge mm-badge-neutral' style='margin-left: 8px; font-size: 0.72rem;'>{_b.get('sport', '')}</span>
                            </div>
                            <div style='color: var(--mm-text-faint); font-size: 0.82rem; font-family: var(--mm-mono);'>{_b.get('date', '')}</div>
                        </div>
                        <div style='display: flex; justify-content: space-between; align-items: center; margin-top: 8px;'>
                            <span class='mm-badge mm-badge-{_result_kind}'>{_result_icon} {_result}</span>
                            <span style='font-family: var(--mm-mono); font-weight: 600; color: {_profit_color};'>{_profit_str}</span>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
            if not show_all_recent and len(sorted_bets) > RECENT_BETS_SHOW_LIMIT:
                if st.button(f"Show all {len(sorted_bets)} bets", key='bt_show_all_recent_btn'):
                    st.session_state['bt_show_all_recent'] = True
                    st.rerun()

    with tab_stats:
        if bets:
            st.markdown("---")
            st.subheader("📈 Performance Summary")
            bets_df = pd.DataFrame(bets)
            settled = bets_df[bets_df['result'] != 'Pending']

            if not settled.empty:
                wins = len(settled[settled['result'] == 'Win'])
                losses = len(settled[settled['result'] == 'Loss'])
                total = wins + losses
                win_pct = round(wins / total * 100, 1) if total > 0 else 0
                total_profit = round(settled['profit'].sum(), 2)
                total_wagered = round(settled['bet_amount'].sum(), 2)
                roi = round(total_profit / total_wagered * 100, 1) if total_wagered > 0 else 0

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Record", f"{wins}-{losses}")
                col2.metric("Win %", f"{win_pct}%")
                col3.metric("Total Profit", f"${total_profit}")
                col4.metric("ROI", f"{roi}%")

                if 'ev_pct' in bets_df.columns and bets_df['ev_pct'].notna().any():
                    st.metric("Avg EV%", f"{round(bets_df['ev_pct'].dropna().mean(), 2)}%")

            settings = get_user_settings()
            if settings and settings.get('starting_bankroll') is not None:
                st.markdown("---")
                st.subheader("💰 Bankroll")
                all_bets_unfiltered = bets if sport_filter == "All" else load_bets()
                current_bankroll = get_current_bankroll(settings, all_bets_unfiltered)
                starting_bankroll = settings['starting_bankroll']
                baseline_date = settings.get('bankroll_set_date') or '1900-01-01'
                profit_this_month = calc_profit_this_month(all_bets_unfiltered)
                max_drawdown = calc_max_drawdown_pct(all_bets_unfiltered, starting_bankroll, baseline_date)
                avg_stake_units = calc_avg_stake_units(all_bets_unfiltered, current_bankroll)

                col1, col2 = st.columns(2)
                col1.metric("Current Bankroll", f"${current_bankroll:,.2f}")
                col2.metric(
                    "This Month",
                    f"{'+' if profit_this_month >= 0 else ''}${profit_this_month:,.2f}"
                )

                col3, col4 = st.columns(2)
                if avg_stake_units is not None:
                    col3.metric("Average Stake", f"{avg_stake_units} Units")
                if max_drawdown is not None:
                    col4.metric("Largest Drawdown", f"{max_drawdown}%")

                st.caption(f"Baseline of ${starting_bankroll:,.2f} set on {baseline_date}. Adjustable anytime in Settings.")

                discipline = calc_stake_discipline_stats(all_bets_unfiltered)
                if discipline:
                    st.markdown("---")
                    st.subheader("🎯 MM Stake Performance")
                    st.caption(f"Based on {discipline['total_tracked']} bet(s) logged with an MM Stake recommendation attached. \"Followed\" = actual stake within ±{STAKE_DEVIATION_FOLLOWED_THRESHOLD}% of the recommendation.")

                    if discipline['today_total'] > 0:
                        st.caption(f"**Today's Discipline:** {discipline['today_followed']} of {discipline['today_total']} bets followed MM Stake")

                    dcol1, dcol2 = st.columns(2)
                    dcol1.metric("Bets Following MM Stake", f"{discipline['bets_following']} of {discipline['total_tracked']}")
                    dcol2.metric("Stake Discipline", f"{discipline['discipline_pct']}%")

                    dcol3, dcol4 = st.columns(2)
                    dev = discipline['avg_deviation_pct']
                    dcol3.metric("Avg. Stake Deviation", f"{'+' if dev >= 0 else ''}{dev}%")

                    if discipline['roi_following'] is not None and discipline['roi_exceeding'] is not None:
                        dcol4.metric(
                            "ROI: Following vs. Deviating",
                            f"{discipline['roi_following']}% vs {discipline['roi_exceeding']}%",
                        )
                    elif discipline['roi_following'] is not None:
                        dcol4.metric("ROI When Following MM Stake", f"{discipline['roi_following']}%")
                        st.caption("Not enough settled deviated bets yet for a comparison.")
            else:
                st.caption("💰 Set a bankroll in Settings to unlock your Bankroll dashboard and personalized MM Stake recommendations.")

            st.markdown("---")
            st.subheader("🎯 Closing Line Tracker")
            today_str = mm_today_str()
            # Real fix (July 2026) — NFL (all 3 variants) added: the
            # backend (get_odds_api_sport_and_market) already fully
            # supports NFL closing lines, this filter just never included
            # them, so NFL bets silently never got closing-line data even
            # though the real capability existed. LoL is deliberately left
            # out — fetch_closing_line() is built entirely around an
            # over/under prop structure (a specific player, a direction),
            # which doesn't map to a real moneyline bet (two teams, no
            # line at all) without real, separate work.
            CLOSING_LINE_SUPPORTED_SPORTS = ('MLB', 'NBA', 'NBA_AST', 'NFL', 'NFL_COMPLETIONS', 'NFL_RECEPTIONS')
            all_settled_for_closing = [
                b for b in bets
                if b.get('date') and b['date'] < today_str and b.get('sport') in CLOSING_LINE_SUPPORTED_SPORTS
            ]
            missing_closing = [b for b in all_settled_for_closing if not b.get('closing_line')]

            force_refetch = st.checkbox(
                "Re-fetch all closing lines (use this if old values look wrong)"
            )
            bets_to_update = all_settled_for_closing if force_refetch else missing_closing

            if bets_to_update:
                if force_refetch:
                    st.caption(f"Will re-fetch and overwrite closing data for all {len(bets_to_update)} settled bet(s).")
                else:
                    st.caption(f"{len(bets_to_update)} settled bet(s) missing closing line data.")
                if st.button("🔄 Update Closing Lines", use_container_width=True):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    updated = 0
                    for i, bet in enumerate(bets_to_update):
                        status_text.text(f"Fetching closing line {i+1} of {len(bets_to_update)}: {bet.get('pitcher')}")
                        progress_bar.progress((i + 1) / len(bets_to_update))
                        closing_line, closing_odds = fetch_closing_line(
                            bet.get('sport'), bet.get('pitcher'), bet.get('over_under'), bet.get('date')
                        )
                        if closing_line is not None:
                            placed_line = bet.get('opening_line') or 0
                            if bet.get('over_under') == 'Over':
                                clv = round(closing_line - placed_line, 2)
                            else:
                                clv = round(placed_line - closing_line, 2)

                            odds_clv = None
                            placed_odds = bet.get('odds')
                            if closing_odds is not None and placed_odds and closing_line == placed_line:
                                odds_clv = calculate_odds_clv(placed_odds, closing_odds)

                            update_bet(bet['id'], {
                                'closing_line': closing_line,
                                'closing_odds': closing_odds,
                                'clv': clv,
                                'odds_clv': odds_clv,
                            })
                            updated += 1
                    status_text.text(f"✅ Done! Found closing lines for {updated} of {len(bets_to_update)} bets.")
                    progress_bar.progress(1.0)
                    st.rerun()
            else:
                st.caption("✅ All settled bets have closing line data.")

            if 'clv' in bets_df.columns and bets_df['clv'].notna().any():
                clv_df = bets_df[bets_df['clv'].notna()]
                avg_clv = clv_df['clv'].mean()
                beat_close_pct = round((clv_df['clv'] > 0).mean() * 100, 1)

                has_odds_clv = 'odds_clv' in bets_df.columns and bets_df['odds_clv'].notna().any()
                avg_odds_clv = None
                beat_odds_pct = None
                if has_odds_clv:
                    odds_clv_df = bets_df[bets_df['odds_clv'].notna()]
                    avg_odds_clv = odds_clv_df['odds_clv'].mean()
                    beat_odds_pct = round((odds_clv_df['odds_clv'] > 0).mean() * 100, 1)

                market_result_series = [
                    market_result_label(c, o) for c, o in zip(
                        bets_df.get('clv'),
                        bets_df.get('odds_clv') if has_odds_clv else [None] * len(bets_df)
                    )
                ]
                decided = [x for x in market_result_series if x in ('🟢 Beat by Line', '🟢 Beat by Price', '🔴 Lost to Close')]

                if decided:
                    beat_by_line = sum(1 for x in decided if x == '🟢 Beat by Line')
                    beat_by_price = sum(1 for x in decided if x == '🟢 Beat by Price')
                    missed = sum(1 for x in decided if x == '🔴 Lost to Close')
                    overall_beat_pct = round((beat_by_line + beat_by_price) / len(decided) * 100, 1)
                    st.metric("📈 Beat Market", f"{overall_beat_pct}%")
                    st.caption(f"🟢 {beat_by_line} Beat by Line · 🟢 {beat_by_price} Beat by Price · 🔴 {missed} Lost to Close")

                col1, col2 = st.columns(2)
                col1.metric("🎯 Beat Closing Line", f"{beat_close_pct}%")
                col2.metric("📏 Avg Line CLV", f"{clv_emoji(avg_clv)}{fmt_signed_num(avg_clv, 2)} pts")

                if has_odds_clv:
                    col3, col4 = st.columns(2)
                    col3.metric("Beat Closing Odds", f"{beat_odds_pct}%")
                    col4.metric("💵 Avg Odds CLV", f"{clv_emoji(avg_odds_clv)}{fmt_signed_num(avg_odds_clv, 2)} implied pts")
                    with col4:
                        st.caption("Based on implied probability movement. (Not return on investment.)")

            if 'ev_pct' in bets_df.columns and not settled.empty and settled['ev_pct'].notna().any():
                st.markdown("---")
                st.subheader("💰 Performance by EV%")
                ev_settled = settled[settled['ev_pct'].notna()]
                ev_buckets = [('<0%', -999, 0), ('0–2.5%', 0, 2.5), ('2.5–5%', 2.5, 5), ('5–7.5%', 5, 7.5), ('7.5–10%', 7.5, 10), ('10–15%', 10, 15), ('15%+', 15, 999)]
                ev_data = []
                for label, low, high in ev_buckets:
                    bucket = ev_settled[(ev_settled['ev_pct'] >= low) & (ev_settled['ev_pct'] < high)]
                    if len(bucket) > 0:
                        b_wagered = round(bucket['bet_amount'].sum(), 2)
                        b_roi = round(bucket['profit'].sum() / b_wagered * 100, 1) if b_wagered > 0 else 0
                        ev_data.append({'EV%': label, 'Bets': len(bucket), 'ROI': f"{b_roi}%", 'Profit': f"${round(bucket['profit'].sum(), 2)}"})
                if ev_data:
                    st.dataframe(pd.DataFrame(ev_data), use_container_width=True)

            if 'sport' in bets_df.columns and not settled.empty:
                st.markdown("---")
                st.subheader("📊 Performance by Sport")
                sport_data = []
                for sport in settled['sport'].unique():
                    s_df = settled[settled['sport'] == sport]
                    s_wins = len(s_df[s_df['result'] == 'Win'])
                    s_total = len(s_df)
                    s_wagered = round(s_df['bet_amount'].sum(), 2)
                    s_roi = round(s_df['profit'].sum() / s_wagered * 100, 1) if s_wagered > 0 else 0
                    avg_ev = round(s_df['ev_pct'].dropna().mean(), 2) if 'ev_pct' in s_df.columns and s_df['ev_pct'].notna().any() else 'N/A'
                    sport_data.append({'Sport': sport, 'Bets': s_total, 'Win %': f"{round(s_wins / s_total * 100, 1)}%" if s_total > 0 else '0%', 'ROI': f"{s_roi}%", 'Avg EV%': avg_ev})
                if sport_data:
                    st.dataframe(pd.DataFrame(sport_data), use_container_width=True)

            settled_with_data = bets_df[
                (bets_df['result'] != 'Pending') &
                (bets_df['opening_line'] > 0) &
                (bets_df['projection'] > 0)
            ].copy()

            if not settled_with_data.empty:
                st.markdown("---")
                st.subheader("📊 Edge Tier Win Rate")
                settled_with_data['edge'] = (settled_with_data['projection'] - settled_with_data['opening_line']).abs().round(1)
                settled_with_data['win'] = settled_with_data['result'] == 'Win'
                tiers = [('0.0 to 0.4', 0.0, 0.4), ('0.5 to 0.9', 0.5, 0.9), ('1.0 to 1.4', 1.0, 1.4), ('1.5+', 1.5, 99)]
                tier_data = []
                for label, low, high in tiers:
                    for direction in ['⬆️ OVER', '⬇️ UNDER']:
                        dir_df = settled_with_data[settled_with_data['over_under'].str.lower() == direction.split(' ')[1].lower()]
                        tier_df = dir_df[(dir_df['edge'] >= low) & (dir_df['edge'] <= high)]
                        if len(tier_df) > 0:
                            win_rate = round(tier_df['win'].mean() * 100, 1)
                            tier_data.append({'Direction': direction, 'Edge Tier': label, 'Bets': len(tier_df), 'Wins': int(tier_df['win'].sum()), 'Win Rate': f"{win_rate}%"})
                if tier_data:
                    st.dataframe(pd.DataFrame(tier_data), use_container_width=True)

    with tab_manage:
        if bets:
            st.markdown("---")
            st.subheader("📝 All Bets")
            # Real fix (July 2026) — mm_tier used to be dropped
            # unconditionally, on the assumption that confidence_tier
            # already covers tier/reliability info. That's true for MLB/
            # NBA/NFL, but LoL never sets confidence_tier at all — mm_tier
            # is the only real tier field LoL bets have, so dropping it
            # hid that information completely for every LoL bet.
            # Real fix (July 2026, per direct user feedback) — these four
            # fields are still saved to every bet (probability_waterfall
            # for future calibration analysis across settled bets,
            # model_version/ev_engine_version for internal tracking,
            # sportsbook as real metadata) — just no longer shown as
            # visible columns cluttering the day-to-day tracker view.
            # Real fix (July 2026, per direct user feedback) — 'actual' is
            # now hidden from the visible table too. It's not used in any
            # of the Bet Tracker's own stats (confirmed — only 'result'
            # and 'profit' feed those), but it IS the real input the
            # Refresh MLB Results feature compares against opening_line to
            # auto-determine Win/Loss/Push — so it's still saved and used
            # internally, just no longer a visible column.
            display_df = bets_df.drop(columns=[c for c in ['created_at', 'user_id', 'mm_score', 'probability_waterfall', 'model_version', 'ev_engine_version', 'sportsbook', 'game_pk', 'actual'] if c in bets_df.columns], errors='ignore')
            if 'no_vig_prob' in display_df.columns:
                display_df['no_vig_prob'] = display_df['no_vig_prob'].apply(lambda v: round(v * 100, 1) if pd.notna(v) else v)
            if 'model_prob' in display_df.columns:
                display_df['model_prob'] = display_df['model_prob'].apply(lambda v: round(v * 100, 1) if pd.notna(v) else v)

            # Real fix (July 2026) — found via a real screenshot: LoL bets
            # store real probabilities (0-1) in the SAME projection/
            # opening_line columns MLB/NBA/NFL use for actual stat lines
            # (e.g. 5.0 innings) — the shared 1-decimal numeric formatting
            # crushed a real 62.5% model probability down to a
            # meaningless-looking "0.6". Converts these two columns to a
            # real percentage STRING for LoL rows only (e.g. "62.5%"),
            # leaving every other sport's numeric values untouched. Also
            # fixes 'actual' showing a real, misleading "0" for LoL bets,
            # which genuinely have no actual-statistic concept at all
            # (a moneyline bet just wins or loses) — now shows "—" instead,
            # matching this app's existing convention for real N/A values.
            # Real fix (July 2026) — found via a real, confirmed report:
            # 'actual' (and the same issue applies to 'projection'/
            # 'opening_line') was declared as a TextColumn in column_config
            # below, but the LoL-specific string formatting only ran
            # conditionally (only if the CURRENT FILTERED VIEW happened to
            # contain at least one LoL row). Filtering to just 'MLB', or
            # simply having no LoL bets logged yet, left these columns as
            # pure, numeric float64 dtype underneath — while column_config
            # still declared them as TextColumn regardless. That mismatch
            # between the real, underlying pandas dtype and the declared
            # column type is what broke editability, not a disabled flag.
            # Now unconditionally casts these three columns to real string
            # values (still just the plain number as text for non-LoL
            # rows, e.g. "5.0"), so the actual dtype always matches what
            # column_config declares, regardless of which sports happen to
            # be in the current filtered view.
            for _col in ['projection', 'opening_line', 'actual']:
                if _col in display_df.columns:
                    display_df[_col] = display_df[_col].apply(lambda v: '' if pd.isna(v) else str(v))

            if 'sport' in display_df.columns:
                is_lol_row = display_df['sport'] == 'LOL'
                if is_lol_row.any():
                    if 'projection' in display_df.columns:
                        display_df['projection'] = display_df.apply(
                            lambda row: f"{round(float(row['projection']) * 100, 1)}%" if row['sport'] == 'LOL' and row['projection'] not in (None, '') else row['projection'],
                            axis=1)
                    if 'opening_line' in display_df.columns:
                        display_df['opening_line'] = display_df.apply(
                            lambda row: f"{round(float(row['opening_line']) * 100, 1)}%" if row['sport'] == 'LOL' and row['opening_line'] not in (None, '') else row['opening_line'],
                            axis=1)
                    # Real fix (July 2026) — bets logged before the save-
                    # logic fix have the raw, ugly market_slug stored in
                    # 'pitcher' (e.g. 'lol-tl2-c9-2026-07-26') instead of a
                    # real, readable team matchup. Can't fully recover the
                    # original full team names from an abbreviated slug,
                    # but this real, best-effort cleanup at least strips
                    # the 'lol-' prefix and trailing date, turning it into
                    # something like 'TL2 vs C9' — genuinely cleaner, even
                    # if not a perfect match for the real, full names.
                    # Bets logged going forward already store the real,
                    # full matchup name and pass through unchanged here.
                    if 'pitcher' in display_df.columns:
                        import re

                        def _clean_lol_slug_for_display(value):
                            if not isinstance(value, str) or not value.startswith("lol-"):
                                return value
                            stripped = re.sub(r"^lol-", "", value)
                            stripped = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", stripped)
                            parts = stripped.split("-")
                            if len(parts) == 2:
                                return f"{parts[0].upper()} vs {parts[1].upper()}"
                            return stripped.replace("-", " ").upper()

                        display_df['pitcher'] = display_df.apply(
                            lambda row: _clean_lol_slug_for_display(row['pitcher']) if row['sport'] == 'LOL' else row['pitcher'],
                            axis=1)

            if 'clv' in display_df.columns and 'odds_clv' in display_df.columns:
                display_df['Market Result'] = [
                    market_result_label(c, o) for c, o in zip(bets_df.get('clv'), bets_df.get('odds_clv'))
                ]
                cols = display_df.columns.tolist()
                cols.remove('Market Result')
                insert_at = cols.index('odds_clv') + 1 if 'odds_clv' in cols else len(cols)
                cols.insert(insert_at, 'Market Result')
                display_df = display_df[cols]

            if 'closing_line' in display_df.columns:
                display_df['closing_line'] = bets_df['closing_line'].apply(lambda v: "—" if pd.isna(v) else v)
            if 'clv' in display_df.columns:
                display_df['clv'] = bets_df['clv'].apply(lambda v: "—" if pd.isna(v) else f"{clv_emoji(v)}{fmt_signed_num(v, 1)}")
            if 'closing_odds' in display_df.columns:
                display_df['closing_odds'] = bets_df['closing_odds'].apply(fmt_odds_signed)
            if 'odds_clv' in display_df.columns:
                display_df['odds_clv'] = bets_df['odds_clv'].apply(lambda v: "—" if pd.isna(v) else f"{clv_emoji(v)}{fmt_signed_num(v, 1)}")

            edited_df = st.data_editor(
                display_df, use_container_width=True, num_rows="dynamic",
                column_config={
                    'id': st.column_config.TextColumn('ID', disabled=True, help="Internal row ID — used to match edits to the correct bet, don't need to touch this"),
                    'pitcher': st.column_config.TextColumn('Player / Matchup', help="A player name for MLB/NBA/NFL bets, or the full matchup (e.g. 'Team A vs Team B') for LoL bets"),
                    'result': st.column_config.SelectboxColumn('Result', options=['Pending', 'Win', 'Loss']),
                    'opening_line': st.column_config.TextColumn('Book Line / Market %', help="A number for stat props (e.g. 4.5 innings); a real percentage for LoL (market-implied win probability)", width="small"),
                    'projection': st.column_config.TextColumn('Projection / Model %', help="A number for stat props (e.g. 5.0 innings); a real percentage for LoL (model win probability)", width="small"),
                    'bet_amount': st.column_config.NumberColumn('Bet ($)', min_value=0.0, step=0.01, format="%.2f"),
                    'odds': st.column_config.NumberColumn('Odds', format="%+d"),
                    'profit': st.column_config.NumberColumn('Profit ($)'),
                    'over_under': st.column_config.SelectboxColumn('O/U', options=['Over', 'Under', '-']),
                    'sport': st.column_config.SelectboxColumn('Sport', options=['MLB', 'NBA', 'NBA_AST', 'NFL', 'NFL_COMPLETIONS', 'NFL_RECEPTIONS', 'LOL']),
                    'ev_pct': st.column_config.NumberColumn('EV%'),
                    'no_vig_prob': st.column_config.NumberColumn('No-Vig Prob (%)', min_value=0.0, max_value=100.0, step=0.1),
                    'model_prob': st.column_config.NumberColumn('Model Prob (%)', min_value=0.0, max_value=100.0, step=0.1),
                    'confidence_tier': st.column_config.SelectboxColumn('Reliability', options=['🟢 Reliable', '🟠 Volatile', '🔴 Uncertain Workload']),
                    'mm_tier': st.column_config.SelectboxColumn('MM Tier', options=['🟢 Best Bet', '🔵 Worth a Look', '🟡 Lean', '🔴 Pass']),
                    'closing_line': st.column_config.TextColumn('Closing Line', disabled=True),
                    'clv': st.column_config.TextColumn('Line CLV', disabled=True, help="Positive = line moved in your favor after you bet"),
                    'closing_odds': st.column_config.TextColumn('Closing Odds', disabled=True),
                    'odds_clv': st.column_config.TextColumn('Odds CLV', disabled=True, help="Positive = odds moved in your favor after you bet (implied probability movement, not %ROI)"),
                    'Market Result': st.column_config.TextColumn('Market Result', disabled=True, help="Beat by Line = the number moved in your favor (the bigger win). Beat by Price = same line, better price. Lost to Close = the market beat you."),
                },
                column_order=[c for c in display_df.columns if c != 'id']
            )

            col_save, col_clear = st.columns(2)
            with col_save:
                if st.button("💾 Save Table Changes", use_container_width=True):
                    updated_bets = edited_df.to_dict('records')

                    # Rows removed via the table's own delete UI (trash icon) never
                    # show up in edited_df at all — without this, a "deleted" row
                    # just reappears on the next reload since nothing told the
                    # database to actually delete it.
                    original_ids = {str(b['id']) for b in bets if b.get('id')}
                    remaining_ids = {
                        str(b.get('id')) for b in updated_bets
                        if b.get('id') is not None and not (isinstance(b.get('id'), float) and pd.isna(b.get('id'))) and str(b.get('id')).strip() != ''
                    }
                    removed_ids = original_ids - remaining_ids
                    for removed_id in removed_ids:
                        delete_bet(removed_id)

                    for b in updated_bets:
                        row_id = b.get('id')
                        if row_id is None or (isinstance(row_id, float) and pd.isna(row_id)) or str(row_id).strip() == '':
                            continue  # a newly added row from the dynamic table — no id yet, nothing to update
                        b['profit'] = calc_profit(b.get('bet_amount', 0), b.get('odds', -110), b.get('result', 'Pending'))
                        no_vig_val = b.get('no_vig_prob')
                        model_prob_val = b.get('model_prob')

                        # Real fix (July 2026) — projection/opening_line/
                        # actual can now be real percentage strings ('62.5%')
                        # or the '—' placeholder for LoL rows, per the real
                        # display fix above. Without converting these back
                        # to real numbers here, saving table edits would
                        # try to write a literal string into a numeric
                        # database column, silently corrupting every edited
                        # LoL row.
                        def _parse_display_value_back_to_number(v):
                            if v is None or (isinstance(v, float) and pd.isna(v)):
                                return None
                            if isinstance(v, str):
                                v = v.strip()
                                if v == "—" or v == "":
                                    return None
                                if v.endswith("%"):
                                    try:
                                        return round(float(v[:-1]) / 100, 4)
                                    except ValueError:
                                        return None
                                try:
                                    return float(v)
                                except ValueError:
                                    return None
                            return v

                        # Real fix (July 2026) — found via a real, direct
                        # report: "Out of range float values are not JSON
                        # compliant: nan". Several fields (odds, bet_amount,
                        # ev_pct, model_edge) were being passed straight
                        # through with no NaN-checking at all, unlike the
                        # three fields already fixed above. A real NaN in
                        # ANY of these (a very real possibility — a manually
                        # logged bet that never set ev_pct, an older bet
                        # missing odds, etc.) breaks the ENTIRE save, not
                        # just that one field, since Supabase's API can't
                        # serialize a raw NaN into JSON at all. This applies
                        # real, general NaN-to-None safety to every numeric
                        # field in this payload, not just the ones already
                        # covered.
                        def _nan_to_none(v):
                            if isinstance(v, float) and pd.isna(v):
                                return None
                            return v

                        update_bet(row_id, {
                            'result': b.get('result'),
                            'odds': _nan_to_none(b.get('odds')), 'bet_amount': _nan_to_none(b.get('bet_amount')),
                            'opening_line': _parse_display_value_back_to_number(b.get('opening_line')),
                            'projection': _parse_display_value_back_to_number(b.get('projection')), 'over_under': b.get('over_under'),
                            'profit': _nan_to_none(b.get('profit')) or 0, 'sport': b.get('sport', 'MLB'),
                            'ev_pct': _nan_to_none(b.get('ev_pct')),
                            'model_edge': _nan_to_none(b.get('model_edge')),
                            'no_vig_prob': round(no_vig_val / 100, 3) if no_vig_val is not None and pd.notna(no_vig_val) else None,
                            'model_prob': round(model_prob_val / 100, 3) if model_prob_val is not None and pd.notna(model_prob_val) else None,
                            'confidence_tier': b.get('confidence_tier'),
                            'mm_tier': b.get('mm_tier'),
                        })
                    if removed_ids:
                        st.success(f"✅ Deleted {len(removed_ids)} bet(s).")
                    st.rerun()
            with col_clear:
                if not st.session_state.get('confirm_clear_bets'):
                    if st.button("🗑️ Clear All Bets", use_container_width=True):
                        st.session_state['confirm_clear_bets'] = True
                        st.rerun()
                else:
                    st.warning(f"⚠️ This will permanently delete all {len(bets)} bet(s) in your tracker. This cannot be undone.")
                    confirm_col1, confirm_col2 = st.columns(2)
                    with confirm_col1:
                        if st.button("✅ Yes, delete everything", use_container_width=True):
                            for bet in bets:
                                delete_bet(bet['id'])
                            st.session_state['confirm_clear_bets'] = False
                            st.rerun()
                    with confirm_col2:
                        if st.button("Cancel", use_container_width=True):
                            st.session_state['confirm_clear_bets'] = False
                            st.rerun()

# ---- MODEL LAB (ADMIN ONLY) ----
elif nav == "🔬 Model Lab" and is_admin:
    st.title("🔬 Model Lab")

    with st.expander("🔍 Structured Failure Log (this session)", expanded=False):
        st.caption("Real, categorized failure reasons from optional/fallback signals across the app (per external review, item 9) — a lineup fetch failing, an umpire lookup missing, a player match not found, etc. These are all cases that were ALREADY caught and gracefully handled (no crash), but previously reduced to a silent None/empty result with no record of why. This only covers the current session — it resets on app restart, since it's session_state-based, not a database table.")
        failure_log = st.session_state.get('_failure_log', [])
        if not failure_log:
            st.info("No failures logged yet this session.")
        else:
            failure_df = pd.DataFrame(failure_log)
            st.write(f"**{len(failure_df)} total, by category:**")
            st.dataframe(failure_df['category'].value_counts().reset_index().rename(columns={'index': 'Category', 'category': 'Count'}), use_container_width=True)
            st.write("**Full log (most recent first)**")
            st.dataframe(failure_df.iloc[::-1], use_container_width=True)
            if st.button("Clear failure log"):
                st.session_state['_failure_log'] = []
                st.rerun()

    lab_sport = st.selectbox("Sport", ["MLB", "NBA Points", "NBA Assists"], key="lab_sport")
    sport_key = 'MLB' if lab_sport == 'MLB' else ('NBA' if lab_sport == 'NBA Points' else 'NBA_AST')

    preds = load_predictions(sport_key)
    preds_with_actual = [p for p in preds if p.get('actual') is not None]

    st.subheader("📥 Update Actual Results")
    today_str = mm_today_str()
    preds_today = [p for p in preds if p.get('date') == today_str and p.get('actual') is None]

    if preds_today:
        for i, pred in enumerate(preds_today):
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.write(f"**{pred['pitcher']}** — Proj: {pred['projection']}")
            with col2:
                actual = st.number_input("Actual", value=0, key=f"actual_{i}", min_value=0)
            with col3:
                if st.button("Save", key=f"save_actual_{i}"):
                    update_prediction(pred['id'], {'actual': actual})
                    st.rerun()
    else:
        st.info("No pending predictions for today!")

    st.markdown("---")

    if len(preds_with_actual) < 5:
        st.warning(f"Need at least 5 completed predictions. You have {len(preds_with_actual)} so far.")
    else:
        if lab_sport == "MLB":
            st.subheader("🏆 Model Version Comparison")
            model_versions = {
                'A — Base Only': {'use_park': False, 'use_umpire': False, 'use_pitch_count': False, 'use_total': False, 'desc': 'Pitcher skill × BF only'},
                'B — + Opponent K%': {'use_park': False, 'use_umpire': False, 'use_pitch_count': False, 'use_total': False, 'desc': 'Base + opponent K%'},
                'C — + Park': {'use_park': True, 'use_umpire': False, 'use_pitch_count': False, 'use_total': False, 'desc': 'Base + opp K% + park'},
                'D — + Umpire': {'use_park': True, 'use_umpire': True, 'use_pitch_count': False, 'use_total': False, 'desc': 'Base + opp K% + park + umpire'},
                'E — + Pitch Count': {'use_park': True, 'use_umpire': True, 'use_pitch_count': True, 'use_total': False, 'desc': 'All except total'},
                'F — Full Model': {'use_park': True, 'use_umpire': True, 'use_pitch_count': True, 'use_total': True, 'desc': 'Everything'},
            }
            version_results = []
            for version_name, config in model_versions.items():
                errors = []
                for pred in preds_with_actual:
                    base = pred['base']
                    opp_f = pred['opp_factor']
                    park_f = pred['park_factor'] if config['use_park'] else 1.0
                    ump_f = pred['umpire_factor'] if config['use_umpire'] else 1.0
                    velo_f = pred['velo_factor']
                    total_f = pred['total_factor'] if config['use_total'] else 1.0
                    combined = max(0.90, min(1.10, opp_f * park_f * ump_f * velo_f * total_f))
                    proj = round(base * combined, 1)
                    errors.append(abs(proj - pred['actual']))
                mae = round(sum(errors) / len(errors), 2)
                version_results.append({'Version': version_name, 'Description': config['desc'], 'MAE': mae, 'Predictions': len(errors)})

            version_df = pd.DataFrame(version_results).sort_values('MAE')
            best_mae = version_df['MAE'].min()
            version_df['vs Best'] = version_df['MAE'].apply(lambda x: f"+{round(x - best_mae, 2)}" if x > best_mae else "✅ Best")
            st.dataframe(version_df, use_container_width=True)
            st.bar_chart(version_df.set_index('Version')['MAE'])

        preds_with_tier = [p for p in preds_with_actual if p.get('confidence_tier')]
        if preds_with_tier:
            st.markdown("---")
            st.subheader("🎯 MAE by Confidence Tier")
            tier_df = pd.DataFrame(preds_with_tier)
            tier_df['error'] = (tier_df['projection'] - tier_df['actual']).abs()
            tier_summary = tier_df.groupby('confidence_tier').agg(Predictions=('error', 'count'), MAE=('error', 'mean')).reset_index()
            tier_summary['MAE'] = tier_summary['MAE'].round(2)
            st.dataframe(tier_summary, use_container_width=True)

        st.markdown("---")
        st.subheader("📋 All Predictions")
        full_df = pd.DataFrame(preds_with_actual)
        full_df['error'] = (full_df['projection'] - full_df['actual']).abs().round(2)
        display_cols = ['date', 'pitcher', 'projection', 'actual', 'error', 'book_line', 'edge']
        if 'confidence_tier' in full_df.columns:
            display_cols.append('confidence_tier')
        st.dataframe(full_df[display_cols].sort_values('date', ascending=False), use_container_width=True)

        col1, col2, col3 = st.columns(3)
        col1.metric("Overall MAE", f"{round(full_df['error'].mean(), 2)}")
        col2.metric("Total Predictions", len(full_df))
        col3.metric("Best Prediction", f"{full_df['error'].min()} error")

        st.markdown("---")
        st.subheader("📢 Public Model Performance Page")
        st.caption("Publishes a snapshot of these stats (plus ROI/Beat Close from your Bet Tracker) to the public Model Performance page every user can see.")
        if st.button(f"📢 Publish {lab_sport} Stats"):
            if publish_model_performance(sport_key):
                st.success(f"✅ Published {lab_sport} stats to the public Model Performance page.")

# ---- ESPORTS (LoL) ----
elif nav == "🎮 Esports (LoL)":
    st.title("🎮 Esports — League of Legends")
    st.markdown("---")
    bankroll, risk_style = get_bankroll_context()
    already_bet_today_lol = get_already_bet_players_today('LOL')

    if "CITO_API_KEY" not in st.secrets:
        st.warning("⚠️ This model isn't fully configured yet — check back soon.")
    else:
        # Real fix (August 2026, per direct user request) — data is now
        # already loaded automatically by the real, global
        # run_todays_card_auto_run() call before page dispatch (LoL is
        # included in that same real auto-run). This button is now an
        # OPTIONAL way to force a genuinely fresh pull.
        #
        # Real fix (round 2, August 2026, per direct user report — a
        # real, deployed code fix still wasn't showing up after
        # clicking Refresh) — clearing only THIS process's real, in-
        # memory cache wasn't enough once a real, persistent Supabase
        # cache layer got added underneath it — this button would
        # immediately fall right back into that same real, stale,
        # persistent result. force_refresh=True now bypasses BOTH real
        # cache layers entirely, guaranteeing a genuinely fresh real
        # computation on every real click of this button.
        if st.button("🔄 Refresh Matchups", use_container_width=True, key="run_lol_projections"):
            _cached_lol_full_pipeline.clear()
            with st.spinner("🎮 Loading LoL matchups..."):
                pipeline_output = _cached_lol_full_pipeline(st.secrets["CITO_API_KEY"], force_refresh=True)
            st.session_state['lol_pipeline_output'] = pipeline_output

        pipeline_output = st.session_state.get('lol_pipeline_output')
        if pipeline_output:
            if isinstance(pipeline_output, dict) and pipeline_output.get("error"):
                st.error(f"Couldn't load matchups right now — please try again shortly.")
                if is_admin:
                    st.caption(f"Admin detail: {pipeline_output['error']}")
            else:
                debug = pipeline_output.get("debug")
                lol_results = pipeline_output.get("results", [])

                if not lol_results:
                    st.info("No live matchups available right now — check back closer to game time.")
                else:
                    # Real fix (August 2026, per direct user report —
                    # "can we have this disappear after it pops up
                    # instead of just sitting there?"). st.toast() is
                    # Streamlit's own real, built-in mechanism for
                    # exactly this — a real notification that shows
                    # briefly then fades on its own, instead of a
                    # permanent st.success() banner staying on screen
                    # for the rest of the real session.
                    #
                    # Real fix (round 2, August 2026, per direct user
                    # report — the toast kept popping up randomly,
                    # repeatedly). This ran on EVERY real script rerun,
                    # not just once — and Streamlit reruns the WHOLE
                    # real script on ANY interaction anywhere on the
                    # page, including just opening one of the "last 10
                    # games" dropdowns. Gated now so it only actually
                    # fires once per genuinely NEW pipeline run (tracked
                    # via real object identity), not on every real
                    # rerun triggered by an unrelated click elsewhere.
                    if st.session_state.get('_lol_toast_shown_for_id') != id(pipeline_output):
                        st.toast(f"✅ {len(lol_results)} real matchup(s) with model predictions")
                        st.session_state['_lol_toast_shown_for_id'] = id(pipeline_output)
                    sorted_lol_results = sorted(
                        lol_results,
                        key=lambda r: (TIER_RANK.get(r.get("mm_tier"), -1), r.get("ev_pct") if r.get("ev_pct") is not None else -999),
                        reverse=True,
                    )

                    # Real fix (August 2026, per direct user report —
                    # "the LOL model is taking SOOOOO much longer to
                    # run" after the real "last 10 games" dropdown got
                    # added). That feature originally re-scanned the
                    # ENTIRE real sorted_history list from scratch for
                    # EVERY team, on EVERY real matchup — 2x per
                    # matchup, dozens of real matchups, on every single
                    # real Streamlit rerun (not just once per pipeline
                    # computation). Builds one real index here instead,
                    # in a single real pass over the history, so each
                    # matchup's dropdown is just a real, instant
                    # dict lookup afterward.
                    _team_recent_games_index = {}
                    for _match in (pipeline_output.get("sorted_history") or []):
                        _t1 = _match.get("team1") or {}
                        _t2 = _match.get("team2") or {}
                        for _side, _opponent in ((_t1, _t2), (_t2, _t1)):
                            _side_slug = _side.get("slug")
                            if not _side_slug:
                                continue
                            _result = "W" if _match.get("winner") == _side_slug else "L"
                            _team_recent_games_index.setdefault(_side_slug, []).append({
                                "date": _match.get("startTime"),
                                "opponent": _opponent.get("name") or _opponent.get("slug") or "Unknown",
                                "result": _result,
                                "tournament": _match.get("tournamentName") or "",
                            })
                    for _slug in _team_recent_games_index:
                        _team_recent_games_index[_slug].sort(key=lambda g: g["date"] or "", reverse=True)
                        _team_recent_games_index[_slug] = _team_recent_games_index[_slug][:10]

                    with st.expander("ℹ️ What's this rating?"):
                        st.markdown("""
Every team starts at a neutral **1500**. From there, real match results move it up or down — win, and it goes up; lose, and it goes down. How much depends on who you played: beating a stronger team moves your rating more than beating a weaker one, since that's a bigger, more meaningful result.

A few things make this smarter than a simple win/loss count:
- **Recent games matter more than old ones.** A win from last week counts more than one from six months ago.
- **Rare cross-region matchups (like MSI or Worlds) count extra**, since those are the only times we get to see how different regions actually compare to each other.
- **It's built entirely from real, completed match results** — not estimates, not manual input.

The gap between two teams' ratings is what turns into the win probability you see next to each pick.
""")

                    hcol1, hcol2, hcol3, hcol4, hcol5, hcol6, hcol7, hcol8, hcol9 = st.columns([2.4, 1.2, 1.3, 0.9, 0.9, 0.8, 0.8, 1.3, 1.0])
                    header_style = "color: var(--mm-text-faint); font-size: 0.72rem; font-family: var(--mm-mono); letter-spacing: 0.04em; text-transform: uppercase;"
                    for hcol, label in [
                        (hcol1, "Matchup"), (hcol2, "Ratings"), (hcol3, "Pick"),
                        (hcol4, "Model %"), (hcol5, "Market %"), (hcol6, "EV%"), (hcol7, "Odds"),
                        (hcol8, "Tier"), (hcol9, ""),
                    ]:
                        with hcol:
                            st.markdown(f"<div style='{header_style}'>{label}</div>", unsafe_allow_html=True)
                    st.markdown("<div style='padding-top: 6px;'></div>", unsafe_allow_html=True)

                    for r in sorted_lol_results:
                        matchup_key = r.get("market_slug") or f"{r['team1_name']}_{r['team2_name']}"
                        # Real fix (July 2026) — bets are actually saved with
                        # pitcher = "{TEAM_ABBREV} (vs {OPPONENT_ABBREV})" using
                        # real Cito team slugs (see the Log Bet confirm button
                        # below), NOT matchup_key (a market slug or full team-
                        # name string). Comparing matchup_key against
                        # already_bet_today_lol could never match, so "Already
                        # bet today" silently never appeared on this page.
                        # Builds both possible real save-format strings
                        # (whichever side was actually picked) and checks
                        # against either.
                        _t1_abbrev = r['team1_slug'].upper()
                        _t2_abbrev = r['team2_slug'].upper()
                        already_bet_this_matchup = (
                            f"{_t1_abbrev} (vs {_t2_abbrev})" in already_bet_today_lol
                            or f"{_t2_abbrev} (vs {_t1_abbrev})" in already_bet_today_lol
                        )
                        if r.get("no_real_data"):
                            st.caption("⚠️ Limited real match history for these teams yet — treat this one as lower-confidence.")
                        if r.get("is_low_volume"):
                            st.caption(f"⚠️ Low real trading volume on this market (${r.get('market_volume_numeric', 0):,.0f}) — this price hasn't been genuinely tested by much real money yet. EV% shown is already discounted for this (raw, undiscounted EV was {r.get('raw_ev_pct_before_volume_discount')}%).")
                        roster_cont = r.get("roster_continuity") or {}
                        worse_continuity = roster_cont.get("worse_continuity_pct", 1.0)
                        if worse_continuity < 0.8:
                            t1_cont = roster_cont.get("team1", {})
                            t2_cont = roster_cont.get("team2", {})
                            new_team_notes = []
                            if t1_cont.get("continuity_pct", 1.0) < 0.8:
                                new_team_notes.append(f"{r['team1_name']} ({t1_cont.get('new_since_lookback', '?')}/{t1_cont.get('current_roster_size', '?')} new)")
                            if t2_cont.get("continuity_pct", 1.0) < 0.8:
                                new_team_notes.append(f"{r['team2_name']} ({t2_cont.get('new_since_lookback', '?')}/{t2_cont.get('current_roster_size', '?')} new)")
                            st.caption(f"⚠️ Recent roster change(s): {', '.join(new_team_notes)} — the existing rating was built before these changes, so it may not reflect current strength. EV% is already discounted for this.")

                        col1, col2, col3, col4, col5, col6, col7, col8, col9 = st.columns([2.4, 1.2, 1.3, 0.9, 0.9, 0.8, 0.8, 1.3, 1.0])
                        with col1:
                            st.write(f"**{r['team1_name']}** vs **{r['team2_name']}**")
                            st.caption(f"{(r.get('event_title') or '').split(' - ')[-1]} — Bo{r['best_of']}")
                            st.caption(f"🕐 {format_lol_match_date(r.get('match_date'))}")
                            if already_bet_this_matchup:
                                st.caption("✅ Already bet today")
                        with col2:
                            rec_rating = r['team1_rating'] if r['recommended_side'] == 'team1' else r['team2_rating']
                            opp_rating = r['team2_rating'] if r['recommended_side'] == 'team1' else r['team1_rating']
                            st.write(f"{rec_rating}")
                            st.caption(f"vs {opp_rating}")
                        with col3:
                            st.write(f"**{r['recommended_team_name']}**")
                        with col4:
                            st.write(f"{r['recommended_model_prob']*100:.1f}%")
                        with col5:
                            st.write(f"{r['recommended_market_prob']*100:.1f}%")
                        with col6:
                            ev = r.get("ev_pct")
                            st.write(f"**{ev}%**" if ev is not None else "—")
                        with col7:
                            st.write(f"{fmt_odds_signed(r.get('recommended_odds'))}")
                        with col8:
                            st.markdown(tier_badge(r.get("mm_tier"), compact=True), unsafe_allow_html=True)
                        with col9:
                            if st.button("📝 Log", key=f"lol_log_btn_{matchup_key}"):
                                st.session_state[f'lol_log_modal_{matchup_key}'] = True

                        # Real fix (July 2026, per direct user report —
                        # "this is all just so complicated to look at")
                        # — replaces a wall of 5-7 full, verbose sentences
                        # (always shown inside one expander) with a
                        # compact, scannable row of short tags plus a
                        # single headline sentence, always visible with no
                        # click needed. The FULL detailed breakdown isn't
                        # removed — it's still available on demand in a
                        # separate "📋 Full Breakdown" expander right below
                        # (Streamlit can't nest an expander inside another
                        # one, so this uses two separate, sibling
                        # expanders rather than one nested inside another).

                        rec_is_team1 = r['recommended_side'] == 'team1'
                        rec_rating = r['team1_rating'] if rec_is_team1 else r['team2_rating']
                        opp_rating = r['team2_rating'] if rec_is_team1 else r['team1_rating']
                        edge_pp = round((r['recommended_model_prob'] - r['recommended_market_prob']) * 100, 1)

                        quick_pills = [_lol_pill(f"📊 +{edge_pp}pp edge vs market", "best")]
                        quick_pills.append(_lol_pill("📈 Higher rated" if rec_rating >= opp_rating else "📉 Lower rated (other signals outweigh)", "playable" if rec_rating >= opp_rating else "neutral"))

                        h2h = r.get("head_to_head") or {}
                        if h2h.get("total_h2h_series", 0) > 0:
                            rec_h2h = h2h.get("team1_h2h_wins", 0) if rec_is_team1 else h2h.get("team2_h2h_wins", 0)
                            opp_h2h = h2h.get("team2_h2h_wins", 0) if rec_is_team1 else h2h.get("team1_h2h_wins", 0)
                            if rec_h2h > opp_h2h:
                                quick_pills.append(_lol_pill("🤝 H2H favors pick", "playable"))
                            elif rec_h2h < opp_h2h:
                                quick_pills.append(_lol_pill("⚠️ H2H favors opponent", "lean"))

                        in_tourn = r.get("in_tournament_form") or {}
                        combined_tournament_games = in_tourn.get("team1_total", 0) + in_tourn.get("team2_total", 0)
                        if combined_tournament_games >= 4:
                            rec_wins = in_tourn.get('team1_wins', 0) if rec_is_team1 else in_tourn.get('team2_wins', 0)
                            rec_losses = in_tourn.get('team1_losses', 0) if rec_is_team1 else in_tourn.get('team2_losses', 0)
                            # Real fix (August 2026, per direct user
                            # report) — "this split" implied a real,
                            # strict boundary to one specific split,
                            # but this record actually comes from a
                            # real, recency-weighted rolling window
                            # (up to 120 real days back — see
                            # IN_TOURNAMENT_FORM_MAX_DAYS_BACK), which
                            # doesn't always line up with one exact
                            # real split. "Recently" is a more honest,
                            # accurate real label for what this
                            # actually represents.
                            _split_record_icon = "🔥" if rec_wins > rec_losses else ("📉" if rec_wins < rec_losses else "➖")
                            quick_pills.append(_lol_pill(f"{_split_record_icon} {rec_wins}-{rec_losses} recently", "playable" if rec_wins >= rec_losses else "lean"))
                        else:
                            quick_pills.append(_lol_pill("⚠️ Limited recent data", "lean"))

                        if r.get("no_real_data"):
                            quick_pills.append(_lol_pill("⚠️ Limited history", "lean"))
                        if r.get("is_low_volume"):
                            quick_pills.append(_lol_pill("⚠️ Low volume", "lean"))

                        st.markdown("".join(quick_pills), unsafe_allow_html=True)

                        why_lines = [
                            f"**{r['recommended_team_name']}**'s real Elo rating is {r['team1_rating'] if r['recommended_side'] == 'team1' else r['team2_rating']}, vs {r['team2_rating'] if r['recommended_side'] == 'team1' else r['team1_rating']} for the opponent — built from real, completed match history.",
                            f"Model gives {r['recommended_team_name']} a {r['recommended_model_prob']*100:.1f}% chance to win, vs {r['recommended_market_prob']*100:.1f}% implied by the current market price — a real, computed gap, not a guess.",
                        ]
                        if r.get("no_real_data"):
                            why_lines.append("⚠️ Neither team has real completed-game history in this dataset yet — this pick carries real uncertainty beyond the normal model error.")
                        team1_intl = r.get("team1_international_matches", 0)
                        team2_intl = r.get("team2_international_matches", 0)
                        why_lines.append(f"Real cross-region international games in history: {r['team1_name']} — {team1_intl}, {r['team2_name']} — {team2_intl}. (International tournaments like MSI/Worlds/EWC are infrequent, so 0 is common and not itself a red flag — just means that team's rating hasn't yet been tested against other regions.)")
                        if h2h.get("total_h2h_series", 0) > 0:
                            # Real fix (July 2026) — these are genuinely
                            # recency-weighted values by design (older
                            # meetings count less in the actual model
                            # blend, per yesterday's fix), not raw
                            # integer counts. The display previously
                            # showed the raw, unrounded floats directly
                            # (e.g. "0.18 — 3.76"), which is honest but
                            # unreadable. Now rounds to 1 decimal and
                            # labels it clearly as recency-weighted.
                            t1_h2h = round(h2h.get("team1_h2h_wins", 0), 1)
                            t2_h2h = round(h2h.get("team2_h2h_wins", 0), 1)
                            total_h2h = round(h2h.get("total_h2h_series", 0), 1)
                            why_lines.append(f"Real head-to-head history (recency-weighted — recent meetings count more than old ones): {r['team1_name']} {t1_h2h} — {t2_h2h} {r['team2_name']} (~{total_h2h} effective prior meetings). This is already factored into the model probability above, not just background info.")
                        if in_tourn.get("team1_total", 0) > 0 or in_tourn.get("team2_total", 0) > 0:
                            t1_rec = f"{in_tourn.get('team1_wins', 0)}-{in_tourn.get('team1_losses', 0)}"
                            t2_rec = f"{in_tourn.get('team2_wins', 0)}-{in_tourn.get('team2_losses', 0)}"
                            why_lines.append(f"Real record in this specific tournament: {r['team1_name']} {t1_rec}, {r['team2_name']} {t2_rec}. A team's overall rating can miss real, current form within one event (e.g. fielding substitutes, a hot or cold streak) — this is already factored into the model probability above.")
                        # Real addition (July 2026) — reuses the same
                        # in-tournament data already computed above, no
                        # new fetching needed. Also fixes a real gap:
                        # the line above only shows when at least one
                        # team already has 1+ games in this tournament
                        # — meaning the very first games of a brand new
                        # split/season (zero real games for EITHER
                        # team yet) previously showed nothing about this
                        # at all, when that's exactly the case that
                        # most needs a real, honest heads-up.
                        if combined_tournament_games < 4:
                            why_lines.append(f"⚠️ Early in this tournament/split — only {combined_tournament_games} real game{'s' if combined_tournament_games != 1 else ''} played so far between both teams in this specific event. The overall rating leans more on past splits/tournaments until more real data exists here — treat with extra caution.")
                        with st.expander(f"📋 Full Breakdown — {r['team1_name']} vs {r['team2_name']}"):
                            for line in why_lines:
                                st.markdown(line)
                            if r.get("context_description"):
                                st.markdown("---")
                                st.caption("Additional real market context:")
                                st.markdown(r["context_description"])
                            st.markdown("---")
                            st.caption(f"Real market liquidity: {r.get('market_liquidity')} | 24hr volume: {r.get('market_volume24hr')} | Total volume: {r.get('market_volume')}")

                        # Real addition (August 2026, per direct user
                        # request — "can we have a little dropdown to
                        # show the teams last 5-10 games with the
                        # results?"). Reuses the SAME real
                        # sorted_history data this whole pipeline
                        # already fetched and computed everything else
                        # from — the expensive full-history scan now
                        # happens ONCE, before this loop, via
                        # _team_recent_games_index above — this is just
                        # a real, instant dict lookup per team.
                        recent_col1, recent_col2 = st.columns(2)
                        for _col, _team_slug, _team_name in [(recent_col1, r["team1_slug"], r["team1_name"]), (recent_col2, r["team2_slug"], r["team2_name"])]:
                            with _col:
                                _recent = _team_recent_games_index.get(_team_slug, [])
                                with st.expander(f"📅 {_team_name} — last {len(_recent)} games"):
                                    if not _recent:
                                        st.caption("No real recent match history found for this team.")
                                    for _g in _recent:
                                        _date_str = (_g["date"] or "")[:10] if _g["date"] else "—"
                                        _badge_kind = "best" if _g["result"] == "W" else "pass"
                                        st.markdown(
                                            f"<span class='mm-badge mm-badge-{_badge_kind}' style='margin-right:8px;'>{_g['result']}</span>"
                                            f"<span style='font-family: var(--mm-mono); font-size: 0.85rem;'>{_date_str} vs {_g['opponent']}</span>",
                                            unsafe_allow_html=True,
                                        )

                        stake_info = {
                            'MM Tier': r.get('mm_tier'), 'Model Prob': r.get('recommended_model_prob'),
                            'Odds': r.get('recommended_odds'), 'EV%': r.get('ev_pct'),
                            # 'Edge' deliberately omitted — calculate_mm_stake's edge-magnitude
                            # bonus was calibrated for stat-unit prop edges (e.g. 0.3 strikeouts),
                            # not probability-percentage-point edges here; omitting it safely
                            # skips that adjustment rather than misapplying mismatched thresholds.
                        }
                        stake_result = {}
                        render_mm_stake_block(stake_info, stake_result, bankroll, risk_style)

                        if st.session_state.get(f'lol_log_modal_{matchup_key}'):
                            with st.expander(f"📝 Log Bet — {r['recommended_team_name']}", expanded=True):
                                log_mm_stake_dollars = None
                                mm_stake_calc = calculate_mm_stake(stake_info, stake_result, bankroll, risk_style) if bankroll else None
                                if mm_stake_calc and not mm_stake_calc.get('pass'):
                                    log_mm_stake_dollars = mm_stake_calc.get('stake_dollars')

                                col_a, col_b = st.columns(2)
                                with col_a:
                                    log_bet = st.number_input("Bet Amount ($)", value=None, min_value=0.0, placeholder="e.g. 100.50", step=0.01, format="%.2f", key=f"lol_log_bet_{matchup_key}")
                                    log_odds = st.number_input("Odds (e.g. -140 or +110)", value=r.get('recommended_odds'), step=1, key=f"lol_log_odds_{matchup_key}")
                                with col_b:
                                    log_result = st.selectbox("Result", ["Pending", "Win", "Loss"], key=f"lol_log_result_{matchup_key}")

                                # Real fix (August 2026, per direct user
                                # report — "it doesn't have the
                                # calculation thing at the bottom of the
                                # bet logger telling you if you are a
                                # percent over the recommended stake
                                # like MLB does") — log_mm_stake_dollars
                                # was already being computed above, just
                                # never actually shown anywhere. Same
                                # real display MLB/NBA/NFL now all use.
                                if log_mm_stake_dollars is not None:
                                    if log_bet:
                                        st.caption(format_stake_deviation_message(log_mm_stake_dollars, log_bet))
                                    else:
                                        st.caption(f"💰 MM Stake recommendation: ${log_mm_stake_dollars:,.2f}")

                                if st.button("✅ Confirm Log Bet", key=f"lol_log_confirm_{matchup_key}", use_container_width=True):
                                    odds = int(log_odds) if log_odds else -110
                                    bet_val = round(float(log_bet), 2) if log_bet else 0.0
                                    profit = calc_profit(bet_val, odds, log_result)
                                    # Real fix (July 2026, per direct
                                    # user feedback) — uses real,
                                    # already-short team identifiers
                                    # (team1_slug/team2_slug, Cito's own
                                    # real slugs — e.g. "dk" for Dplus
                                    # KIA, "t1" for T1) via
                                    # recommended_side, instead of the
                                    # full team names, so the matchup
                                    # text stays compact and fully
                                    # visible instead of getting cut off
                                    # by long full names.
                                    if r.get('recommended_side') == 'team1':
                                        lol_picked_abbrev = r['team1_slug'].upper()
                                        lol_opponent_abbrev = r['team2_slug'].upper()
                                    else:
                                        lol_picked_abbrev = r['team2_slug'].upper()
                                        lol_opponent_abbrev = r['team1_slug'].upper()
                                    save_bet({
                                        'date': mm_today_str(), 'pitcher': f"{lol_picked_abbrev} (vs {lol_opponent_abbrev})",
                                        'projection': r.get('recommended_model_prob'),
                                        'opening_line': r.get('recommended_market_prob'),
                                        # Real fix (July 2026) — over/
                                        # under genuinely doesn't apply
                                        # to a moneyline bet. This used
                                        # to store the picked team name
                                        # here instead (which didn't
                                        # even fit the Over/Under
                                        # dropdown options), but now
                                        # that the pick is shown clearly
                                        # in the matchup text above,
                                        # this can honestly just be a
                                        # real "-" placeholder.
                                        'over_under': '-', 'odds': odds,
                                        'bet_amount': bet_val, 'result': log_result,
                                        'actual': 0, 'profit': profit,
                                        'sport': 'LOL', 'ev_pct': r.get('ev_pct'),
                                        'mm_tier': r.get('mm_tier'),
                                        'model_prob': r.get('recommended_model_prob'),
                                        'mm_stake_recommended': log_mm_stake_dollars,
                                        'probability_waterfall': r.get('probability_waterfall'),
                                    })
                                    st.session_state[f'lol_log_modal_{matchup_key}'] = False
                                    st.success(f"✅ Bet logged for {r['recommended_team_name']}!")
                                    st.rerun()
                        st.divider()

    if is_admin:
        with st.expander("🔧 Admin: Diagnostics & Data Pipeline Tools", expanded=False):
            st.caption("Real diagnostic tools used to build and debug this pipeline — hidden from regular users, kept here since they've caught real, genuine bugs and will likely be needed again as coverage expands to more leagues/games.")

            st.subheader("🔍 League/Tournament Data Investigation")
            st.caption("Real investigation before building league-strength adjustment — checks how tournament/league info is actually structured in a team's real match history (tournamentId/tournamentName field, not necessarily a clean leagueSlug like the schedule endpoint has), and counts how many real cross-league/international games actually exist to derive a meaningful signal from.")
            diag_league_slug = st.text_input("Team slug to check", value="t1", key="lol_league_diag_slug")
            if st.button("Investigate league data", key="lol_league_diag_btn"):
                with st.spinner(f"Fetching real match history for {diag_league_slug}..."):
                    try:
                        from cito_api import get_lol_team_matches, extract_completed_matches
                        raw = get_lol_team_matches(st.secrets["CITO_API_KEY"], diag_league_slug)
                        completed = extract_completed_matches(raw)
                        tournaments_seen = {}
                        for m in completed:
                            tid = m.get("tournamentId")
                            tname = m.get("tournamentName")
                            tournaments_seen.setdefault(f"{tid} ({tname})", 0)
                            tournaments_seen[f"{tid} ({tname})"] += 1
                        st.write(f"**{len(completed)} real completed matches found. Unique tournaments/leagues played in:**")
                        st.json(tournaments_seen)

                        # Real fix (August 2026, per direct user report —
                        # "it only shows like 1 game") — this used to
                        # always show completed[0], regardless of which
                        # tournament happened to sort first. That's a
                        # real, direct blocker for exactly the kind of
                        # investigation that found the real Challengers/
                        # main-roster contamination bug — there was no
                        # way to specifically inspect a match from a
                        # DIFFERENT real tournament than whatever
                        # happened to be first. Now shows ONE real
                        # sample PER unique real tournament, with the
                        # real isRequested side called out directly, so
                        # a real contamination pattern (isRequested on a
                        # slug unrelated to what was requested) is
                        # visible for every real tournament in one pass.
                        st.write(f"**One real sample match per unique tournament ({len(tournaments_seen)} total):**")
                        seen_tournament_keys = set()
                        for m in completed:
                            tid = m.get("tournamentId")
                            tname = m.get("tournamentName")
                            key = f"{tid} ({tname})"
                            if key in seen_tournament_keys:
                                continue
                            seen_tournament_keys.add(key)
                            t1 = m.get("team1") or {}
                            t2 = m.get("team2") or {}
                            requested_side = t1 if t1.get("isRequested") else (t2 if t2.get("isRequested") else None)
                            with st.expander(f"{key} — requested-side slug: {requested_side.get('slug') if requested_side else '⚠️ NEITHER side marked isRequested'}"):
                                st.json(m)
                    except Exception as e:
                        st.error(f"❌ Real error: {e}")

            st.markdown("---")
            st.subheader("🔍 Roster Continuity Investigation")
            st.caption("Real, first investigation for roster continuity — a known gap where a team's rating is built entirely from past results with no concept of WHO was actually playing. Motivated by a real, concrete case: a CBLOL season-opener where both teams could have entirely different rosters than whatever played their existing rated games. Checks the real, raw shape of Cito's roster/history endpoint before any logic gets designed around assumptions about it.")
            roster_team_slug = st.text_input("Team slug to check", value="red-canids", key="lol_roster_diag_slug")
            if st.button("Investigate roster history", key="lol_roster_diag_btn"):
                with st.spinner(f"Fetching real roster history for {roster_team_slug}..."):
                    try:
                        from cito_api import get_lol_team_roster_history
                        roster_data = get_lol_team_roster_history(st.secrets["CITO_API_KEY"], roster_team_slug)
                        st.success("✅ Real response received from the roster/history endpoint:")
                        st.json(roster_data)
                    except Exception as e:
                        st.error(f"❌ Real error: {e}")

            st.markdown("---")
            st.subheader("🔍 Head-to-Head Investigation")
            st.caption("Real diagnostic for a reported head-to-head discrepancy — fetches BOTH teams' real match histories separately and combines them (matching exactly what the real pipeline does), then shows every real match object between them. This reveals whether a missing match exists on one team's side but not the other (a combine/dedupe issue) versus genuinely missing from both (a real Cito data gap) — two very different explanations.")
            h2h_team1 = st.text_input("Team 1 slug", value="kc", key="lol_h2h_team1")
            h2h_team2 = st.text_input("Team 2 slug", value="mkoi", key="lol_h2h_team2")
            if st.button("Investigate head-to-head", key="lol_h2h_diag_btn"):
                with st.spinner(f"Fetching real match history for both {h2h_team1} and {h2h_team2}..."):
                    try:
                        from cito_api import get_lol_team_matches, extract_completed_matches, infer_missing_game_winners, sort_matches_chronologically
                        from lol_elo import get_head_to_head_record, combine_and_dedupe_matches

                        raw1 = get_lol_team_matches(st.secrets["CITO_API_KEY"], h2h_team1)
                        completed1 = extract_completed_matches(raw1)
                        raw2 = get_lol_team_matches(st.secrets["CITO_API_KEY"], h2h_team2)
                        completed2 = extract_completed_matches(raw2)

                        st.write(f"**Real completed matches found on {h2h_team1}'s own fetch: {len(completed1)}**")
                        st.write(f"**Real completed matches found on {h2h_team2}'s own fetch: {len(completed2)}**")

                        combined = combine_and_dedupe_matches([completed1, completed2])
                        combined = infer_missing_game_winners(combined)
                        sorted_combined = sort_matches_chronologically(combined)

                        h2h_matches = [
                            {
                                "matchId": m.get("matchId"), "tournamentName": m.get("tournamentName"),
                                "startTime": m.get("startTime"),
                                "team1_slug": (m.get("team1") or {}).get("slug"), "team1_score": (m.get("team1") or {}).get("score"),
                                "team2_slug": (m.get("team2") or {}).get("slug"), "team2_score": (m.get("team2") or {}).get("score"),
                                "winner": m.get("winner"),
                                "num_games_in_array": len(m.get("games") or []),
                            }
                            for m in sorted_combined
                            if {(m.get("team1") or {}).get("slug"), (m.get("team2") or {}).get("slug")} == {h2h_team1, h2h_team2}
                        ]
                        st.write(f"**Found {len(h2h_matches)} real, combined match object(s) between {h2h_team1} and {h2h_team2} (after fetching both sides and deduping):**")
                        st.json(h2h_matches)
                        t1_wins, t2_wins, total = get_head_to_head_record(h2h_team1, h2h_team2, sorted_combined)
                        st.write(f"**What get_head_to_head_record() actually computes from the properly-combined data: {h2h_team1} {t1_wins} — {t2_wins} {h2h_team2} ({total} total)**")
                    except Exception as e:
                        st.error(f"❌ Real error: {e}")

            st.markdown("---")
            st.caption("Real, live test of Cito's own dedicated head-to-head endpoint — found in their full API list, never verified against a live response before. Testing whether this is a more complete data source than reconstructing head-to-head from each team's own /matches history (which was just confirmed to have a real gap — two missing EWC matches between KC and Movistar KOI).")
            if st.button("Test dedicated /h2h endpoint", key="lol_h2h_endpoint_test_btn"):
                with st.spinner(f"Fetching real /h2h data for {h2h_team1} vs {h2h_team2}..."):
                    try:
                        from cito_api import get_lol_head_to_head
                        h2h_raw = get_lol_head_to_head(st.secrets["CITO_API_KEY"], h2h_team1, h2h_team2)
                        st.success("✅ Real response received from the dedicated /h2h endpoint:")
                        st.json(h2h_raw)
                    except Exception as e:
                        st.error(f"❌ Real error: {e}")

            st.markdown("---")
            st.caption("Real, live test of the league-level schedule endpoint — a real, raw dump of EWC's own league entity showed 0 teams linked to it ('_count': {'teams': 0}), suggesting per-team endpoints (both /matches and /h2h) may miss matches that a direct, league-level query wouldn't. Checking specifically whether this surfaces the two real EWC matches (May 14/17, 2026, Karmine Corp vs Movistar KOI) that neither team-level endpoint could find.")
            h2h_league_slug = st.text_input("League slug to check", value="lol-ewc_lol", key="lol_league_schedule_slug")
            if st.button("Test league-level schedule endpoint", key="lol_league_schedule_test_btn"):
                with st.spinner(f"Fetching real league schedule for {h2h_league_slug}..."):
                    try:
                        from cito_api import get_lol_league_schedule
                        league_schedule = get_lol_league_schedule(st.secrets["CITO_API_KEY"], h2h_league_slug)
                        st.success(f"✅ Real response received from the league schedule endpoint:")
                        st.json(league_schedule)
                    except Exception as e:
                        st.error(f"❌ Real error: {e}")


            st.subheader("🧪 Live Polymarket Safety Check")
            if st.button("Test Polymarket LoL fetch", key="polymarket_lol_safety_check"):
                with st.spinner("Fetching live Polymarket data..."):
                    try:
                        from polymarket_api import get_polymarket_safety_check
                        result = get_polymarket_safety_check()
                    except ImportError:
                        st.error("❌ Couldn't import polymarket_api.")
                        result = None
                if result:
                    if result.get("fetch_ok"):
                        st.success(f"✅ Fetch succeeded — {result['event_count']} LoL event(s) returned")
                        st.write("**Sample event titles:**")
                        for title in result["sample_titles"]:
                            st.write(f"- {title}")
                        st.write(f"**Real match-winner markets found:** {result['match_winner_market_count']}")
                    else:
                        st.error(f"❌ Real fetch error: {result.get('error')}")

            st.markdown("---")
            st.subheader("🔍 Raw Market/Event Field Inspector")
            st.caption("Answers 'why isn't the real match time available?' with real data instead of another guess — real fix (July 2026): now fetches EVERY real 'Match Winner' market (not season-long futures markets like 'LCK 2026 Season Winner') and lets you pick a SPECIFIC one to inspect, instead of always grabbing whichever came first. Useful for checking a real matchup you already know is missing an exact time from the Pipeline Diagnostics panel above.")
            if st.button("Fetch all real Match Winner markets", key="lol_raw_inspector_fetch_btn"):
                with st.spinner("Fetching raw Polymarket data..."):
                    try:
                        from polymarket_api import get_all_polymarket_events
                        raw_events = get_all_polymarket_events(tag_slug="league-of-legends", closed=False)
                        real_match_pairs = []
                        for event in raw_events:
                            for market in event.get("markets", []):
                                if (market.get("groupItemTitle") or "").strip().lower() == "match winner":
                                    real_match_pairs.append({"event": event, "market": market})
                        st.session_state['_lol_raw_inspector_matches'] = real_match_pairs
                        st.success(f"✅ Found {len(real_match_pairs)} real 'Match Winner' market(s) out of {len(raw_events)} total events fetched.")
                    except Exception as e:
                        st.error(f"❌ Real error: {e}")

            _inspector_matches = st.session_state.get('_lol_raw_inspector_matches', [])
            if _inspector_matches:
                def _inspector_label(idx):
                    _m = _inspector_matches[idx]["market"]
                    _e = _inspector_matches[idx]["event"]
                    _label_text = _m.get("question") or _e.get("title") or "Unknown matchup"
                    return f"{idx}: {_label_text}"

                selected_idx = st.selectbox(
                    "Pick a specific real matchup to inspect",
                    options=list(range(len(_inspector_matches))),
                    format_func=_inspector_label,
                    key="lol_raw_inspector_select",
                )
                _selected = _inspector_matches[selected_idx]
                st.write("**Complete, raw market object:**")
                st.json(_selected["market"])
                st.write("**Complete, raw parent event object (top-level fields only, not the full nested markets list):**")
                st.json({k: v for k, v in _selected["event"].items() if k != "markets"})

            st.markdown("---")
            st.subheader("🧪 Live Cito API Safety Check")
            if st.button("Test Cito API endpoints", key="cito_safety_check"):
                with st.spinner("Fetching live Cito data..."):
                    try:
                        from cito_api import get_cito_safety_check
                        cito_result = get_cito_safety_check(st.secrets["CITO_API_KEY"])
                    except ImportError:
                        st.error("❌ Couldn't import cito_api.")
                        cito_result = None
                if cito_result:
                    for label, res in cito_result.items():
                        st.write(f"**{label}**")
                        if res.get("ok"):
                            if label == "team_matches_t1":
                                st.success(f"✅ {res.get('total_entries')} total entries, {res.get('completed_match_count')} completed")
                                st.json(res.get("sample_completed"))
                            elif label == "teams_list":
                                st.success(f"✅ {res.get('total_fetched')} total teams fetched")
                                st.json(res.get("sample_first_5"))
                                st.json(res.get("sample_last_5"))
                            else:
                                st.success(f"✅ type: {res['type']}" + (f", count: {res['count']}" if res.get('count') is not None else ""))
                                st.json(res["sample"])
                        else:
                            st.error(f"❌ Real error: {res.get('error')}")
                        st.markdown("---")

            st.markdown("---")
            st.subheader("⏱️ Last Auto-Run Timing Breakdown")
            # Real addition (August 2026, per direct user report — the
            # API bridge showing "0 total picks" even right after a
            # real, successful auto-run). Shows the real, direct result
            # of the last attempt to persist all sports' finished picks
            # for the API bridge to read — either the real counts per
            # sport (confirming it worked), or the real, actual
            # exception if it silently failed, instead of guessing.
            _persist_error = st.session_state.get('_last_all_picks_persist_error')
            _persist_counts = st.session_state.get('_last_all_picks_persist_counts')
            if _persist_error:
                st.error(f"❌ Real error persisting all-sport picks for the API bridge: {_persist_error}")
            elif _persist_counts:
                st.success(f"✅ Last persist succeeded: {_persist_counts}")
            else:
                st.caption("No persist attempt recorded yet this session.")

            st.markdown("---")
            # Real addition (August 2026, per direct user report — a
            # real, confirmed-successful cache-warmer run, checked only
            # 11 real minutes later, STILL took ~2 real minutes).
            # Shows the real, actual wall-clock time each sport's
            # block took during the LAST real run_todays_card_auto_run()
            # call THIS session — direct, real evidence of where the
            # time actually goes, instead of guessing whether a
            # specific sport's cache is genuinely missing or whether
            # even a real "cache hit" path is doing unexpectedly slow
            # real work (e.g. many sequential real Supabase round-
            # trips, one per player, even when nothing needs
            # recomputing).
            _last_timing = st.session_state.get('_last_auto_run_timing')
            if _last_timing:
                _timing_df = pd.DataFrame([{"Sport": k.upper(), "Seconds": v} for k, v in _last_timing.items()]).sort_values("Seconds", ascending=False)
                st.dataframe(_timing_df, use_container_width=True)
                st.caption(f"Total: {round(sum(_last_timing.values()), 1)}s — the slowest sport above is where a real fix should focus next, if this still feels slow even after a real, confirmed-warm cache-warmer run.")
            else:
                st.caption("No timing recorded yet this session — reload any page that triggers the auto-run (Home, Today's Card, or any sport page) to populate this.")

            # Real addition (August 2026, per direct user finding — NFL
            # alone ate 105 of ~120 real total seconds). Breaks NFL's
            # own real block down further — per model variant (Pass
            # Attempts/Completions/Receptions), and per real phase
            # (the live real props/odds fetch vs the real per-player
            # model computation) — direct, real evidence of exactly
            # where inside NFL specifically the time goes, rather than
            # guessing between "the live odds API is slow" and "the
            # real per-player cache isn't actually hitting."
            _nfl_phase_timing = st.session_state.get('_last_nfl_phase_timing')
            if _nfl_phase_timing:
                st.caption("NFL breakdown (load = live odds fetch, run = per-player model computation):")
                _nfl_phase_df = pd.DataFrame([{"Phase": k, "Seconds": v} for k, v in _nfl_phase_timing.items()]).sort_values("Seconds", ascending=False)
                st.dataframe(_nfl_phase_df, use_container_width=True)

            # Real addition (August 2026, per direct user report — "we
            # gotta figure out why the model is so slow too"). Same
            # real breakdown, applied to MLB — especially relevant
            # right now since MLB's "run" phase just picked up real,
            # new work (computing EV for every real alternate line, not
            # just the one main line).
            _mlb_phase_timing = st.session_state.get('_last_mlb_phase_timing')
            if _mlb_phase_timing:
                st.caption("MLB breakdown (load = live odds fetch, run = per-pitcher model computation):")
                _mlb_phase_df = pd.DataFrame([{"Phase": k, "Seconds": v} for k, v in _mlb_phase_timing.items()]).sort_values("Seconds", ascending=False)
                st.dataframe(_mlb_phase_df, use_container_width=True)

            st.markdown("---")
            st.subheader("⚠️ Teams Stuck At Default Rating")
            # Real addition (August 2026, per direct user report — "so
            # many of these lol teams just don't work") — rather than
            # continuing to find these one at a time when a real
            # matchup happens to surface one, this scans the SAME real
            # team_history_diagnostics data already computed for the
            # last run (no new real API calls) and surfaces EVERY team
            # currently stuck at the default 1500 rating in one real
            # view, sorted by whether they actually have real match
            # data that just isn't reaching them (the concerning,
            # actionable case) versus genuinely having none yet (an
            # honest, expected case).
            #
            # Real fix (August 2026, per direct user report — "i have
            # to run the LOL projections AGAIN and it literally takes
            # like 5+ minutes") — this used to ONLY check st.session_
            # state['lol_pipeline_output'], which resets on a real,
            # ordinary session refresh/new tab, even though the real,
            # underlying _cached_lol_full_pipeline result was still
            # genuinely warm server-side (2-hour real cache, shared
            # across every real session). Now checks session_state
            # FIRST (instant, no real click needed, if already
            # populated this session), and falls back to calling the
            # real, cached wrapper directly — which resolves instantly
            # on a real cache hit (the common case right after any
            # recent real run) and only genuinely takes real minutes
            # if the real cache itself has actually expired.
            last_output_for_stuck = st.session_state.get('lol_pipeline_output')
            if not last_output_for_stuck and "CITO_API_KEY" in st.secrets:
                if st.button("📋 Load diagnostics (uses the real, shared cache — instant if warm)", key="lol_load_diag_from_cache"):
                    with st.spinner("Checking the real, shared cache..."):
                        last_output_for_stuck = _cached_lol_full_pipeline(st.secrets["CITO_API_KEY"])
                        st.session_state['_lol_diag_cached_output'] = last_output_for_stuck
                else:
                    last_output_for_stuck = st.session_state.get('_lol_diag_cached_output')
            if last_output_for_stuck and isinstance(last_output_for_stuck, dict):
                _team_diag = (last_output_for_stuck.get("debug") or {}).get("team_history_diagnostics") or {}
                _stuck_rows = []
                for _slug, _info in _team_diag.items():
                    _rating = _info.get("final_rating")
                    if _rating is None or round(_rating, 1) == 1500.0:
                        _real_matches = _info.get("real_completed_matches_this_run")
                        _stuck_rows.append({
                            "Team Slug": _slug,
                            "Real Matches This Run": _real_matches if _real_matches is not None else "fetch failed",
                            "Ended Up In Ratings": _info.get("ended_up_in_ratings"),
                            "Likely Cause": (
                                "⚠️ Has real data — investigate (slug alias, tier mismatch, or a new bug)"
                                if (_real_matches or 0) > 0
                                else "Genuinely no real data yet — honest, expected"
                            ),
                        })
                if not _stuck_rows:
                    st.success("✅ No teams stuck at the default rating in the last run.")
                else:
                    _stuck_df = pd.DataFrame(_stuck_rows).sort_values("Likely Cause")
                    _concerning_count = sum(1 for r in _stuck_rows if "investigate" in r["Likely Cause"])
                    if _concerning_count:
                        st.warning(f"⚠️ {_concerning_count} team(s) have real match data that isn't reaching their rating — worth investigating each one the same way we did for paiN/DK/DNS/BRO.")
                    st.dataframe(_stuck_df, use_container_width=True)

                    # Real addition (August 2026, per direct user
                    # report — "so many of these lol teams just dont
                    # work... i literally saw half of these playing
                    # within the last 2 days"). Rather than asking for
                    # another real, manual, multi-step investigation
                    # per team, this automates the FULL real cross-
                    # check in one click: fetches Cito's real, full
                    # team database ONCE (same real endpoint the
                    # existing "Search Real Team Database" tool already
                    # uses, same real, bounded, one-time admin-
                    # triggered cost — not run automatically or
                    # repeatedly), then for EVERY real "stuck" slug,
                    # searches for real candidate teams with a similar
                    # real name and checks EACH candidate's real match
                    # coverage directly — surfacing a real, direct
                    # answer (a real duplicate slug with real data, if
                    # one exists) instead of raw diagnostic output that
                    # still needs manual interpretation.
                    st.markdown("---")
                    if st.button("🔎 Auto-Investigate All Stuck Teams (checks Cito's full team database)", key="lol_auto_investigate_stuck"):
                        with st.spinner("Fetching Cito's full real team database and cross-checking every stuck team — this can take a real minute..."):
                            try:
                                from cito_api import get_lol_teams_list, get_lol_team_matches, diagnose_team_match_coverage
                                _all_teams_raw = get_lol_teams_list(st.secrets["CITO_API_KEY"])
                                # Real fix (August 2026, per direct user
                                # report — "'str' object has no
                                # attribute 'get'") — get_lol_teams_list
                                # can return a real, dict-wrapped
                                # response ({"teams": [...]} or {"data":
                                # [...]}), not always a plain real list
                                # directly — this was iterating the raw
                                # response unconditionally, which for a
                                # dict-wrapped response iterates its
                                # real KEYS (strings) instead of the
                                # real team objects. Matches the same
                                # real unwrapping already used correctly
                                # elsewhere (search_teams_list_for_name).
                                if isinstance(_all_teams_raw, dict):
                                    _all_teams = _all_teams_raw.get("teams") or _all_teams_raw.get("data") or []
                                elif isinstance(_all_teams_raw, list):
                                    _all_teams = _all_teams_raw
                                else:
                                    _all_teams = []
                                _findings = []
                                for _row in _stuck_rows:
                                    _stuck_slug = _row["Team Slug"]
                                    _search_term = _stuck_slug.replace("-", " ").replace("_", " ").strip().lower()
                                    # Real fix (August 2026, per direct
                                    # user report — several real,
                                    # confirmed false-positive matches
                                    # in the very first real use of this
                                    # tool, e.g. "Way Gaming Esports"
                                    # matching "3BL Galaxy Esports"
                                    # purely on the generic word
                                    # "esports"). These generic, low-
                                    # information words appear in SO
                                    # many real team names that matching
                                    # on them alone proves nothing —
                                    # excluded here so only real,
                                    # distinguishing words drive a match.
                                    _GENERIC_LOL_TEAM_WORDS = {"esports", "esport", "challengers", "challenger", "academy", "gaming", "team", "club", "the"}
                                    _search_words = [w for w in _search_term.split() if len(w) > 2 and w not in _GENERIC_LOL_TEAM_WORDS]
                                    _candidates = []
                                    for _team in _all_teams:
                                        if not isinstance(_team, dict):
                                            continue
                                        _team_slug = (_team.get("slug") or "")
                                        _team_name = (_team.get("name") or "").lower()
                                        if _team_slug == _stuck_slug:
                                            continue  # the same real slug we already know is stuck — not a candidate
                                        if any(w in _team_name or w in _team_slug.replace("-", " ") for w in _search_words):
                                            _candidates.append(_team)
                                    if not _candidates:
                                        _findings.append({"Stuck Slug": _stuck_slug, "Candidate Slug": "(none found)", "Candidate Name": "—", "Real Completed Matches": "—", "Verdict": "No similarly-named real team found in Cito's database at all"})
                                        continue
                                    for _cand in _candidates[:3]:  # cap at 3 real candidates per stuck team to keep this bounded
                                        _cand_slug = _cand.get("slug")
                                        try:
                                            _cand_raw = get_lol_team_matches(st.secrets["CITO_API_KEY"], _cand_slug)
                                            _cand_diag = diagnose_team_match_coverage(_cand_raw)
                                            _cand_completed = _cand_diag.get("completed_count", 0)
                                        except Exception as _e:
                                            _cand_completed = f"fetch error: {_e}"
                                        _verdict = "⚠️ REAL CANDIDATE — has completed matches, likely the correct slug" if isinstance(_cand_completed, int) and _cand_completed > 0 else "No real completed matches under this slug either"
                                        _findings.append({
                                            "Stuck Slug": _stuck_slug, "Candidate Slug": _cand_slug,
                                            "Candidate Name": _cand.get("name"), "Real Completed Matches": _cand_completed,
                                            "Verdict": _verdict,
                                        })
                                st.session_state['_lol_auto_investigate_findings'] = _findings
                            except Exception as e:
                                st.error(f"❌ Real error during auto-investigation: {e}")

                    _findings = st.session_state.get('_lol_auto_investigate_findings')
                    if _findings:
                        _real_candidates = [f for f in _findings if "REAL CANDIDATE" in f["Verdict"]]
                        if _real_candidates:
                            st.success(f"✅ Found {len(_real_candidates)} real, likely-correct alternate slug(s) — add these to MANUAL_TEAM_ALIASES in cito_api.py:")
                            st.dataframe(pd.DataFrame(_real_candidates), use_container_width=True)
                        else:
                            st.info("No alternate slugs with real match data found for any stuck team — these genuinely look like real data gaps, not a resolution bug.")
                        with st.expander("See all real candidates checked (including dead ends)"):
                            st.dataframe(pd.DataFrame(_findings), use_container_width=True)
            else:
                st.caption("Click \"📋 Load diagnostics\" above (uses the real, shared cache — instant if warm), or run the projections above first if you haven't loaded matchups recently.")

            st.markdown("---")
            st.subheader("🔍 Pipeline Diagnostics (last run)")
            last_output = st.session_state.get('lol_pipeline_output')
            if last_output and isinstance(last_output, dict) and last_output.get("debug"):
                st.json(last_output["debug"])
            else:
                st.caption("Run the projections above first to see diagnostics for that run.")

            st.markdown("---")
            st.subheader("🔍 Team Match Coverage Diagnostic")
            # Real addition (July 2026, per direct user report — C9 vs
            # Dignitas both showing the default 1500 rating despite real,
            # recent match results existing per the market's own context
            # text) — this diagnostic needs the EXACT real Cito slug for
            # a team, which isn't always the obvious guess (Polymarket's
            # own abbreviation, e.g. "dig", may not match Cito's real
            # slug at all). Pulls every real team_name -> resolved_slug
            # pair straight from the LAST real pipeline run's own
            # results — no new API calls, no guessing required.
            _last_lol_output = st.session_state.get('lol_pipeline_output')
            if isinstance(_last_lol_output, dict) and _last_lol_output.get("results"):
                _slug_lookup_rows = []
                _seen_slug_pairs = set()
                for _r in _last_lol_output["results"]:
                    for _name_key, _slug_key in [("team1_name", "team1_slug"), ("team2_name", "team2_slug")]:
                        _pair = (_r.get(_name_key), _r.get(_slug_key))
                        if _pair not in _seen_slug_pairs:
                            _seen_slug_pairs.add(_pair)
                            _slug_lookup_rows.append({"Team Name": _r.get(_name_key), "Real Resolved Slug": _r.get(_slug_key)})
                with st.expander(f"Real team_name → slug lookup from the last run ({len(_slug_lookup_rows)} teams)"):
                    st.dataframe(pd.DataFrame(_slug_lookup_rows), use_container_width=True)
                # Real addition (July 2026, per direct user report) — the
                # real fetch_errors list from _fetch_lol_team_histories()
                # was already being attached to every real result dict
                # (result["fetch_errors"] = fetch_errors), but never
                # actually surfaced anywhere in the UI — meaning a real,
                # transient failure fetching one specific team's match
                # history during a real run (which would leave that team
                # stuck at the default 1500 rating despite their real,
                # underlying Cito data being completely healthy) was
                # invisible without this. Same fetch_errors list is
                # shared across every result from one run, so grabbing
                # it from the first result is enough.
                _run_fetch_errors = (_last_lol_output["results"][0].get("fetch_errors") or []) if _last_lol_output["results"] else []
                if _run_fetch_errors:
                    st.error(f"⚠️ {len(_run_fetch_errors)} real fetch error(s) occurred during the last run's team-history fetch — any team listed here had ZERO real games processed for it (stuck at the default 1500 rating), even if its underlying Cito data is completely fine:")
                    for _err in _run_fetch_errors:
                        st.code(_err)
                else:
                    st.caption("✅ No fetch errors recorded during the last run's team-history fetch phase.")
            else:
                st.caption("Run the projections above at least once first to populate a real team_name → slug lookup here.")

            # Real fix (July 2026, per direct user report — the coverage
            # tool's own header, slug lookup, and fetch-errors box got
            # visually separated from ITS OWN input field and button by
            # two other, unrelated tools inserted in between during an
            # earlier round tonight, making the coverage checker look
            # like it didn't exist even though the code was still there.
            # This input/button now sit directly after their own real,
            # supporting content above, with the two other tools moved
            # to after this complete block instead.
            diag_team_slug = st.text_input("Team slug to check (e.g. g2, t1, kc)", value="g2", key="lol_coverage_diag_slug")
            if st.button("Check coverage", key="lol_coverage_diag_btn"):
                with st.spinner(f"Fetching real match history for {diag_team_slug}..."):
                    try:
                        from cito_api import get_lol_team_matches, diagnose_team_match_coverage
                        raw = get_lol_team_matches(st.secrets["CITO_API_KEY"], diag_team_slug)
                        diag = diagnose_team_match_coverage(raw)
                        st.json(diag)
                    except Exception as e:
                        st.error(f"❌ Real error: {e}")

            # Real addition (July 2026, per direct user report — a
            # team's real in-tournament record looked internally
            # inconsistent with real market context describing them
            # as one of the league's strongest teams, raising a
            # real concern that the same-day tournament-name
            # matching fix might now be matching TOO broadly for a
            # short, common league acronym). Shows exactly which
            # real games get counted toward a given team's
            # in-tournament record, using the same real matching
            # logic the pricing pipeline itself uses — lets an
            # admin directly SEE the real tournamentName values
            # that got pulled in and confirm whether they genuinely
            # represent the same real tournament/split.
            st.markdown("---")
            st.subheader("🔍 In-Tournament Record Diagnostic")
            st.caption("Shows exactly which real games get counted toward a team's in-tournament record — uses the same real matching logic the pricing pipeline itself uses, against the real match history from the LAST run above (no new fetch).")
            _diag_tourn_team_slug = st.text_input("Team slug (from the lookup table above)", key="lol_tourn_diag_team_slug")
            _diag_tourn_name = st.text_input("Tournament name substring (as passed to the model — e.g. 'LCK Round 3-4 Legend Group')", key="lol_tourn_diag_name")
            if st.button("Check in-tournament matches", key="lol_tourn_diag_btn"):
                if not _diag_tourn_team_slug or not _diag_tourn_name:
                    st.warning("Enter both a team slug and a tournament name substring.")
                elif not isinstance(_last_lol_output, dict):
                    st.warning("Run the projections above at least once first.")
                else:
                    _last_sorted_history = _last_lol_output.get("sorted_history") or []
                    if not _last_sorted_history:
                        st.warning("No real match history saved from the last run — run the projections again first.")
                    else:
                        from lol_elo import diagnose_in_tournament_matches
                        _matched = diagnose_in_tournament_matches(_diag_tourn_team_slug, _diag_tourn_name, _last_sorted_history)
                        if not _matched:
                            st.info(f"0 real matches found for slug '{_diag_tourn_team_slug}' against tournament name '{_diag_tourn_name}' — the matching correctly found nothing here.")
                        else:
                            st.success(f"✅ {len(_matched)} real match(es) matched — check the 'Real Tournament Name' column below to confirm these all genuinely represent the same real tournament/split you expect, not something else that happened to share a token:")
                            st.dataframe(pd.DataFrame([
                                {"Opponent Slug": m["opponent_slug"], "Real Tournament Name": m["tournament_name"], "Real Tournament ID": m.get("tournament_id"), "Start Time": m["start_time"], "Result": m["result"]}
                                for m in _matched
                            ]), use_container_width=True)

            st.markdown("---")
            # Real addition (July 2026, per direct user report — "can
            # we make sure this is good for EVERY tourney not just
            # LPL") — the tournamentId fix was only ever CONFIRMED
            # against one real, concrete case (LPL's real
            # "lol-lpl_split_3_2026"). The fix's LOGIC is fully
            # general (no LPL-specific code anywhere), but whether
            # Cito's real tournamentId genuinely follows the same
            # "lol-{league}_..." pattern for EVERY OTHER real league
            # (LCK, LEC, LCS, CBLOL, VCS, PCS, LJL, NACL, etc.) was
            # never actually verified — an untested assumption, not
            # a confirmed fact, and this project's whole standing
            # principle has been "verify with real data, don't
            # guess." This scans the REAL, full combined match
            # history from the last run (every league currently
            # being pulled in, not just LPL) and shows every unique
            # real (tournamentId, tournamentName) pair seen, plus
            # exactly what real tokens _normalize_tournament_name_
            # for_matching() would extract from each — letting a
            # real, direct visual check confirm the pattern holds
            # broadly, or reveal a real league where it doesn't.
            st.subheader("🔍 All Real Tournament ID/Name Pairs (last run, every league)")
            st.caption("Real, direct evidence for whether the tournamentId fix generalizes — one row per unique real (tournamentId, tournamentName) combination seen across ALL leagues in the last run's match history, with the exact tokens the matching logic would actually extract from each.")
            if st.button("Show all real tournament ID/name pairs", key="lol_all_tourney_ids_btn"):
                _history_for_scan = (_last_lol_output.get("sorted_history") or []) if isinstance(_last_lol_output, dict) else []
                if not _history_for_scan:
                    st.warning("No real match history saved from the last run — run the projections again first.")
                else:
                    from lol_elo import _normalize_tournament_name_for_matching
                    _seen_pairs = {}
                    for _match in _history_for_scan:
                        _tid = _match.get("tournamentId") or ""
                        _tname = _match.get("tournamentName") or ""
                        _key = (_tid, _tname)
                        if _key not in _seen_pairs:
                            _combined_tokens = _normalize_tournament_name_for_matching(_tname) | _normalize_tournament_name_for_matching(_tid)
                            _seen_pairs[_key] = {
                                "Real Tournament ID": _tid or "(missing)",
                                "Real Tournament Name": _tname or "(missing)",
                                "Extracted Matching Tokens": ", ".join(sorted(_combined_tokens)) if _combined_tokens else "⚠️ NONE — this tournament can NEVER match anything",
                                "Real Games Seen": 0,
                            }
                        _seen_pairs[_key]["Real Games Seen"] += 1
                    st.success(f"✅ {len(_seen_pairs)} unique real (tournamentId, tournamentName) combination(s) found across {len(_history_for_scan)} total real matches in the last run.")
                    st.caption("Check 'Extracted Matching Tokens' for every row — a real, sensible league acronym (lck, lpl, lec, cblol, etc.) should be present for each real tournament. A row showing ⚠️ NONE has no identifying token from EITHER field and can never be matched by anything — a real, genuine gap worth investigating for that specific league/tournament.")
                    st.dataframe(pd.DataFrame(list(_seen_pairs.values())).sort_values("Real Games Seen", ascending=False), use_container_width=True)

            st.markdown("---")
            st.subheader("🔎 Search Real Team Database")
            search_term = st.text_input("Search term (e.g. 'cloud', 'liquid', 'WE')", value="", key="lol_team_search")
            if search_term and st.button("Search", key="lol_team_search_btn"):
                with st.spinner(f"Searching the real team database for '{search_term}'..."):
                    try:
                        from cito_api import get_lol_teams_list, search_teams_list_for_name
                        teams_list = get_lol_teams_list(st.secrets["CITO_API_KEY"])
                        matches = search_teams_list_for_name(teams_list, search_term)
                        if matches:
                            st.success(f"✅ Found {len(matches)} real, partial match(es):")
                            st.json(matches)
                        else:
                            st.warning(f"⚠️ Genuinely zero matches for '{search_term}'.")
                    except Exception as e:
                        st.error(f"❌ Real error: {e}")

elif nav == "🧪 Backtest" and is_admin:
    st.title("🧪 Backtest")

    with st.expander("🔧 balldontlie Diagnostic (debug)"):
        st.caption("Checks player lookup + season game log against the real balldontlie API — useful the first few times to confirm the pipeline is working before running a full batch.")
        if st.button("🗑️ Clear All Cache (forces every cached function to re-fetch fresh)"):
            st.cache_data.clear()
            st.success("Cache cleared — next run will fetch everything fresh.")
        debug_player = st.text_input("Player name", value="Nikola Jokić", key="debug_player_name")
        debug_season = st.number_input("Season (start year, e.g. 2025 for 2025-26)", value=2025, key="debug_bdl_season")
        debug_date_for_pace = st.date_input("Date to check team pace math", value=date(2025, 12, 1), key="debug_pace_date")
        if st.button("Check Per-Team Pace Math For This Date"):
            try:
                date_str_check = debug_date_for_pace.strftime('%Y-%m-%d')
                box_check_df = get_bdl_games_for_date(date_str_check)
                if box_check_df.empty:
                    st.error("No games found for that date.")
                else:
                    box_check_df['team_id_check'] = box_check_df['team'].apply(lambda t: (t or {}).get('id'))
                    box_check_df['team_name_check'] = box_check_df['team'].apply(lambda t: (t or {}).get('full_name'))
                    rows_out = []
                    for team_id_val, group in box_check_df.groupby('team_id_check'):
                        fga_sum = pd.to_numeric(group['fga'], errors='coerce').sum()
                        fta_sum = pd.to_numeric(group['fta'], errors='coerce').sum()
                        oreb_sum = pd.to_numeric(group['oreb'], errors='coerce').sum()
                        tov_sum = pd.to_numeric(group['turnover'], errors='coerce').sum()
                        pace_val = round(fga_sum + 0.44 * fta_sum - oreb_sum + tov_sum, 1)
                        rows_out.append({
                            'Team': group['team_name_check'].iloc[0], 'Players': len(group),
                            'FGA': fga_sum, 'FTA': fta_sum, 'OREB': oreb_sum, 'TOV': tov_sum, 'Pace': pace_val
                        })
                    st.dataframe(pd.DataFrame(rows_out), use_container_width=True)
            except Exception as e:
                st.error(f"Real error: {e}")
                import traceback
                st.code(traceback.format_exc())
        if st.button("Check Raw /games Schema (for leak-free pace rebuild)"):
            try:
                sample_games = bdl_get("games", {"seasons[]": 2025, "per_page": 3})
                st.write(f"Got {len(sample_games)} games back")
                st.json(sample_games)
            except Exception as e:
                st.error(f"Real error: {e}")
                import traceback
                st.code(traceback.format_exc())
        debug_trace_date = st.date_input("Date to trace as_of_date against", value=date(2025, 12, 5), key="debug_trace_date_input")
        if st.button("Trace Assists Pipeline Step-by-Step (for a specific player/date)"):
            try:
                trace_bdl_season = int(debug_season)
                trace_df, trace_pid = get_bdl_player_game_log(debug_player, trace_bdl_season)
                st.write(f"**Step 1 — raw fetch:** {len(trace_df)} rows, player_id={trace_pid}")
                if trace_df.empty:
                    st.error("Empty at step 1 — nothing further to trace.")
                else:
                    # Matching the REAL function's exact order this time —
                    # active-minutes filter happens FIRST, before game_date
                    # even exists as a column, then date-filter happens
                    # LATER after sorting. Earlier trace applied these in
                    # the opposite order, which (while mathematically
                    # equivalent for a simple AND) didn't actually catch
                    # what was different about the real code path.
                    trace_df['minutes_played'] = trace_df['min'].apply(bdl_parse_minutes)
                    active_first_df = trace_df[trace_df['minutes_played'] > 0]
                    st.write(f"**Step 2 — active-minutes filter (real function's FIRST filter, before date even exists as a column):** {len(active_first_df)} rows")

                    active_first_df = active_first_df.copy()
                    active_first_df['assists'] = pd.to_numeric(active_first_df['ast'], errors='coerce')
                    active_first_df['turnovers'] = pd.to_numeric(active_first_df['turnover'], errors='coerce') if 'turnover' in active_first_df.columns else 0
                    active_first_df['game_date'] = pd.to_datetime(active_first_df['game'].apply(lambda g: (g or {}).get('date')))
                    active_first_df = active_first_df.sort_values('game_date').reset_index(drop=True)
                    st.write(f"**Step 3 — after adding computed columns + sort:** {len(active_first_df)} rows")

                    filtered_df = active_first_df[active_first_df['game_date'] < pd.Timestamp(debug_trace_date)].reset_index(drop=True)
                    st.write(f"**Step 4 — after as_of_date filter (< {debug_trace_date}):** {len(filtered_df)} rows")

                    cleaned_df = filtered_df.dropna(subset=['assists', 'minutes_played', 'game_date']).copy()
                    st.write(f"**Step 5 — after dropna on essential columns:** {len(cleaned_df)} rows")

                    if len(cleaned_df) < 5:
                        st.error(f"❌ Ends at {len(cleaned_df)} rows — this IS why it returns None. Compare to the earlier (different-order) trace to see where the discrepancy comes from.")
                    else:
                        st.success(f"✅ Ends at {len(cleaned_df)} rows — should NOT be returning None here either. If it's still failing, the issue is genuinely later in the function (injury lookup, pace, or a rate calculation) — worth checking with debug mode + the main Backtest run again, now that we've ruled out the data-loading stage twice.")
            except Exception as e:
                st.error(f"Real error: {e}")
                import traceback
                st.code(traceback.format_exc())
        if st.button("Check Injuries Endpoint + player_ids[] Filter"):
            try:
                all_injuries = bdl_get("player_injuries", {"per_page": 100})
                st.write(f"Got {len(all_injuries)} total injury rows back (unfiltered)")
                if all_injuries:
                    st.json(all_injuries[:3])
                    test_player = all_injuries[0].get('player', {})
                    test_id = test_player.get('id')
                    test_name = f"{test_player.get('first_name')} {test_player.get('last_name')}"
                    st.write(f"Now testing player_ids[] filter using **{test_name}** (id={test_id})...")
                    filtered = bdl_get("player_injuries", {"player_ids[]": test_id, "per_page": 100})
                    filtered_names = set()
                    for r in filtered:
                        p = r.get('player', {})
                        filtered_names.add(f"{p.get('first_name')} {p.get('last_name')}")
                    if filtered_names == {test_name}:
                        st.success(f"✅ Filter works correctly — only got {test_name} back ({len(filtered)} row(s)).")
                    else:
                        st.error(f"❌ Filter did NOT work as documented — got {len(filtered)} rows for these players instead of just {test_name}: {filtered_names}")
                else:
                    st.warning("No injuries currently on the report — can't test the filter without at least one entry. Try again another day.")
            except Exception as e:
                st.error(f"Real error: {e}")
                import traceback
                st.code(traceback.format_exc())
        if st.button("Check Team Filter (Denver Nuggets, id=8)"):
            try:
                team_rows = bdl_get("stats", {"team_ids[]": 8, "seasons[]": int(debug_season), "per_page": 100})
                st.write(f"Got {len(team_rows)} rows back")
                unique_teams = set()
                for r in team_rows[:200]:
                    t = (r.get("team") or {}).get("full_name")
                    unique_teams.add(t)
                st.write("Distinct teams in the returned rows (should be JUST 'Denver Nuggets' if the filter works):", unique_teams)
            except Exception as e:
                st.error(f"Real error: {e}")
                import traceback
                st.code(traceback.format_exc())
        if st.button("Check Raw Player Search Response"):
            try:
                suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
                name_parts = [p for p in debug_player.strip().split(" ") if p.lower().rstrip(".") not in suffixes]
                debug_last_name = strip_accents(name_parts[-1] if name_parts else debug_player.strip())
                st.caption(f"Searching last name only (matches real production logic): '{debug_last_name}'")
                raw_rows = bdl_get("players", {"search": debug_last_name, "per_page": 25})
                st.write(f"Got {len(raw_rows)} rows back")
                st.json(raw_rows[:10] if raw_rows else raw_rows)
            except Exception as e:
                st.error(f"Real error: {e}")
                import traceback
                st.code(traceback.format_exc())
        if st.button("Check Player Lookup + Game Log"):
            debug_pid = get_bdl_player_id(debug_player)
            if not debug_pid:
                st.error("No player ID resolved for this exact name.")
            else:
                st.write(f"Resolved player ID: **{debug_pid}**")
                debug_df, _ = get_bdl_player_game_log(debug_player, int(debug_season))
                if debug_df.empty:
                    st.error("Player ID resolved, but game log came back empty.")
                else:
                    st.write(f"{len(debug_df)} games found. Columns:", debug_df.columns.tolist())
                    st.dataframe(debug_df.head(3))
        debug_sport = st.radio("Sport to test", ["NBA Points", "NBA Assists"], key="debug_sport_radio", horizontal=True)
        debug_use_backtest_date = st.checkbox("Test in backtest mode (use the trace date above as as_of_date)", key="debug_use_backtest_mode")
        if st.button("Run Full Projection (show real error if it fails)"):
            st.session_state['_nba_debug_mode'] = True
            try:
                test_as_of_date = datetime.combine(debug_trace_date, datetime.min.time()) if debug_use_backtest_date else None
                season_str = f"{int(debug_season)}-{str(int(debug_season)+1)[2:]}"
                if debug_sport == "NBA Assists":
                    debug_result = run_nba_assists_projection(debug_player, '', 'Houston Rockets', 'Denver Nuggets', 'home', season_str, as_of_date=test_as_of_date)
                else:
                    debug_result = run_nba_points_projection(debug_player, '', 'Houston Rockets', 'Denver Nuggets', 'home', season_str, as_of_date=test_as_of_date)
                if debug_result:
                    st.success(f"✅ Worked! Projection: {debug_result['projection']}")
                    st.json(debug_result)
                else:
                    st.error("Returned None cleanly (no exception raised) — the failure is a normal 'return None' somewhere in the function, not a crash. Debug mode only reveals actual exceptions, so this confirms it's hitting an intentional early-return check we haven't found yet, not a bug that throws an error.")
            except Exception as e:
                st.error(f"❌ Real error: {e}")
                import traceback
                st.code(traceback.format_exc())
            finally:
                st.session_state['_nba_debug_mode'] = False

    backtest_sport = st.selectbox("Sport", ["MLB Strikeouts", "NBA Points", "NBA Assists", "NFL Pass Attempts", "NFL Pass Completions", "NFL Receptions"], key="backtest_sport")
    if backtest_sport not in ("NFL Pass Attempts", "NFL Pass Completions", "NFL Receptions"):
        backtest_date = st.date_input("Select a past date", value=date.today() - timedelta(days=7))

    if backtest_sport == "MLB Strikeouts":
        backtest_season = st.selectbox("Season", ["2026", "2025", "2024"], key="backtest_season")

        if st.button("🔍 Load Games & Run Projections", use_container_width=True):
            with st.spinner(f"Pulling starters for {backtest_date}..."):
                date_str = backtest_date.strftime('%Y-%m-%d')
                starters = get_starters_for_date(date_str)
                if not starters:
                    st.error("No games found for that date")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results = []
                    for i, starter in enumerate(starters):
                        status_text.text(f"Running {starter['pitcher']} ({i+1} of {len(starters)})")
                        progress_bar.progress((i+1) / len(starters))
                        result = run_projection(starter['pitcher'], starter['opponent'], starter['home_team'], backtest_season, before_date=date_str)
                        actual_k = get_actual_strikeouts(starter['game_pk'], starter['pitcher'])
                        if result and actual_k is not None:
                            results.append({
                                'Pitcher': starter['pitcher'],
                                'Matchup': f"{starter['opponent']} @ {starter['home_team']}",
                                'Projection': result['projection'], 'Actual K': actual_k,
                                'Error': round(abs(result['projection'] - actual_k), 1),
                                'Tier': result['confidence_tier']
                            })
                    st.session_state['backtest_results'] = results
                    st.session_state['backtest_date'] = date_str
                    status_text.text(f"✅ Done! {len(results)} pitchers projected.")
                    progress_bar.progress(1.0)

    elif backtest_sport == "NFL Pass Attempts":
        backtest_season_nfl = st.selectbox("Season", ["2025", "2024", "2023"], key="backtest_season_nfl")
        col_wk1, col_wk2 = st.columns(2)
        with col_wk1:
            backtest_week_start_nfl = st.number_input("Start week", min_value=1, max_value=18, value=10, key="backtest_week_start_nfl")
        with col_wk2:
            backtest_week_end_nfl = st.number_input("End week (same as start = single week)", min_value=1, max_value=18, value=10, key="backtest_week_end_nfl")
        num_weeks_selected = max(0, int(backtest_week_end_nfl) - int(backtest_week_start_nfl) + 1)
        if num_weeks_selected > 1:
            st.caption(f"Testing {num_weeks_selected} weeks in one run (~{num_weeks_selected * 30} projections total) — this accumulates into ONE combined report across the whole range, so you get one set of tier/bucket/architecture-gap tables instead of having to stitch together {num_weeks_selected} separate runs yourself. This will take a while — early weeks especially, since they need real prior-season data fetched too.")
        accumulate_nfl = st.checkbox("➕ Accumulate — add these results to what's already loaded, instead of replacing them", key="nfl_backtest_accumulate", help="Turn this on to build up a full season across several smaller runs (e.g. weeks 1-6, then 7-12, then 13-18) without losing earlier results each time. Safer than one giant run for a whole season, which risks timing out.")
        debug_this_run_nfl = st.checkbox("🔧 Show real errors instead of generic 'returned None' (debug)", key="nfl_backtest_debug")

        col_run, col_clear = st.columns([3, 1])
        with col_clear:
            if st.button("🗑️ Clear All", use_container_width=True):
                st.session_state['nfl_backtest_results'] = []
                st.session_state['nfl_backtest_skipped'] = []
                st.session_state['nfl_backtest_week'] = ""
                st.rerun()

        with col_run:
            run_clicked = st.button("🔍 Load Week(s) & Run Projections", use_container_width=True)
        if run_clicked:
            st.session_state['_nfl_debug_mode'] = debug_this_run_nfl
            weeks_to_test = list(range(int(backtest_week_start_nfl), int(backtest_week_end_nfl) + 1))
            with st.spinner(f"Pulling {len(weeks_to_test)} week(s) of games..."):
                try:
                    schedules = get_nfl_schedules([int(backtest_season_nfl)])
                    actual_stats = get_nfl_player_stats([int(backtest_season_nfl)])
                    results = list(st.session_state.get('nfl_backtest_results', [])) if accumulate_nfl else []
                    skipped = list(st.session_state.get('nfl_backtest_skipped', [])) if accumulate_nfl else []
                    already_covered_weeks = set(r.get('Week') for r in results) if accumulate_nfl else set()
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    all_qb_matchups = []
                    for wk in weeks_to_test:
                        week_games = schedules[schedules['week'] == wk]
                        for _, g in week_games.iterrows():
                            if pd.notna(g.get('home_qb_name')):
                                all_qb_matchups.append({'qb': g['home_qb_name'], 'team': g['home_team'], 'opponent': g['away_team'], 'week': wk})
                            if pd.notna(g.get('away_qb_name')):
                                all_qb_matchups.append({'qb': g['away_qb_name'], 'team': g['away_team'], 'opponent': g['home_team'], 'week': wk})

                    if not all_qb_matchups:
                        st.error("No games found for that season/week range")
                    else:
                        for i, m in enumerate(all_qb_matchups):
                            status_text.text(f"Week {m['week']}: {m['qb']} ({i+1} of {len(all_qb_matchups)})")
                            progress_bar.progress((i+1) / len(all_qb_matchups))
                            try:
                                result = run_nfl_pass_attempts_projection(m['qb'], m['team'], m['opponent'], int(backtest_season_nfl), as_of_week=m['week'])
                            except Exception as e:
                                skipped.append({'QB': m['qb'], 'Week': m['week'], 'Reason': f'Exception: {e}'})
                                continue
                            actual_row = actual_stats[(actual_stats['player_display_name'] == m['qb']) & (actual_stats['week'] == m['week']) & (actual_stats['position'] == 'QB')]
                            if actual_row.empty:
                                skipped.append({'QB': m['qb'], 'Week': m['week'], 'Reason': "Didn't play or no stats found for this exact week"})
                                continue
                            actual_attempts = actual_row['attempts'].iloc[0]
                            if not result:
                                skipped.append({'QB': m['qb'], 'Week': m['week'], 'Reason': "Fewer than 3 games of prior history — insufficient for a projection"})
                                continue
                            gctx = result.get('game_context') or {}
                            results.append({
                                'QB': m['qb'], 'Week': m['week'], 'Matchup': f"{m['opponent']} @ {m['team']}",
                                'Projection': result['projection'], 'Actual': actual_attempts,
                                'Error': round(abs(result['projection'] - actual_attempts), 1),
                                'Error %': round(abs(result['projection'] - actual_attempts) / actual_attempts * 100, 1) if actual_attempts > 0 else None,
                                'Games Used': result['games_used'], 'Pace Factor': result['pace_factor'], 'Opp Factor': result['opp_factor'],
                                'Confidence Tier': result.get('confidence_tier'),
                                'Architecture Gap': result.get('architecture_gap'),
                                'Spread': gctx.get('spread'), 'Total': gctx.get('total'),
                                'Wind': gctx.get('wind'), 'Roof': gctx.get('roof'),
                                'Is Home': gctx.get('is_home'),
                                'Starter Filter': result.get('starter_filter_used'),
                            })
                        st.session_state['nfl_backtest_results'] = results
                        st.session_state['nfl_backtest_skipped'] = skipped
                        all_weeks_covered = sorted(set(r['Week'] for r in results))
                        if len(all_weeks_covered) == 1:
                            week_label = f"Week {all_weeks_covered[0]}"
                        else:
                            week_label = f"Weeks {', '.join(str(w) for w in all_weeks_covered)}"
                        st.session_state['nfl_backtest_week'] = f"Season {backtest_season_nfl}, {week_label}"
                        newly_added = len(all_qb_matchups) - len(already_covered_weeks.intersection(set(m['week'] for m in all_qb_matchups))) if accumulate_nfl else len(results)
                        status_text.text(f"✅ Done! {len(results)} total projections accumulated across {len(all_weeks_covered)} week(s) so far, {len(skipped)} skipped total." if accumulate_nfl else f"✅ Done! {len(results)} projections across {len(weeks_to_test)} week(s), {len(skipped)} skipped.")
                        progress_bar.progress(1.0)
                except Exception as e:
                    st.error(f"Real error: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                finally:
                    st.session_state['_nfl_debug_mode'] = False

        if 'nfl_backtest_results' in st.session_state and st.session_state['nfl_backtest_results']:
            st.markdown("---")
            st.subheader(f"📋 Results for {st.session_state.get('nfl_backtest_week', '')}")
            nfl_results_df = pd.DataFrame(st.session_state['nfl_backtest_results'])
            st.dataframe(nfl_results_df.sort_values('Error'), use_container_width=True)
            col1, col2, col3 = st.columns(3)
            col1.metric("Avg Error (MAE)", f"{round(nfl_results_df['Error'].mean(), 2)}")
            col2.metric("Best Projection", f"{nfl_results_df['Error'].min()} error")
            col3.metric("Worst Projection", f"{nfl_results_df['Error'].max()} error")
            within_metrics = nfl_results_df['Error'].agg(**{
                'Within 3': lambda x: round((x <= 3).mean() * 100, 1),
                'Within 5': lambda x: round((x <= 5).mean() * 100, 1),
                'Within 8': lambda x: round((x <= 8).mean() * 100, 1),
            })
            wcol1, wcol2, wcol3 = st.columns(3)
            wcol1.metric("Within 3 attempts", f"{within_metrics['Within 3']}%")
            wcol2.metric("Within 5 attempts", f"{within_metrics['Within 5']}%")
            wcol3.metric("Within 8 attempts", f"{within_metrics['Within 8']}%")

            st.markdown("---")
            st.subheader("🔬 Validation Buckets")
            st.caption("Splits accuracy by real game context instead of just an overall average — this is how you find out where the model is actually strong or weak, rather than assuming one MAE number tells the whole story.")

            def _bucket_table(df, group_col, label):
                if group_col not in df.columns or df[group_col].isna().all():
                    return
                sub = df.dropna(subset=[group_col]).copy()
                if sub.empty:
                    return
                summary = sub.groupby(group_col).agg(Predictions=('Error', 'count'), MAE=('Error', 'mean')).reset_index()
                summary['MAE'] = summary['MAE'].round(2)
                st.write(f"**{label}**")
                st.dataframe(summary, use_container_width=True)

            nfl_results_df['Favorite/Dog'] = nfl_results_df['Spread'].apply(lambda s: 'Favorite' if pd.notna(s) and s < 0 else ('Underdog' if pd.notna(s) and s > 0 else None))
            nfl_results_df['Dome/Outdoor'] = nfl_results_df['Roof'].apply(lambda r: 'Dome' if r in ('dome', 'closed') else ('Outdoor' if pd.notna(r) else None))
            nfl_results_df['Wind Risk'] = nfl_results_df['Wind'].apply(lambda w: 'High Wind (15+)' if pd.notna(w) and w >= 15 else ('Normal' if pd.notna(w) else None))
            nfl_results_df['Home/Road'] = nfl_results_df['Is Home'].apply(lambda h: 'Home' if h is True else ('Road' if h is False else None))
            spread_bins = [-100, -13, -9, -6, -3, 0, 3, 6, 9, 13, 100]
            spread_labels = ["Favorite 13+", "Favorite 9-13", "Favorite 6-9", "Favorite 3-6", "Favorite 0-3",
                              "Underdog 0-3", "Underdog 3-6", "Underdog 6-9", "Underdog 9-13", "Underdog 13+"]
            nfl_results_df['Spread Bucket'] = pd.cut(nfl_results_df['Spread'], bins=spread_bins, labels=spread_labels) if nfl_results_df['Spread'].notna().any() else None
            total_bins = [0, 42, 47, 100]
            total_labels = ["Low Total (<42)", "Mid Total (42-47)", "High Total (47+)"]
            nfl_results_df['Total Bucket'] = pd.cut(nfl_results_df['Total'], bins=total_bins, labels=total_labels) if nfl_results_df['Total'].notna().any() else None

            _bucket_table(nfl_results_df, 'Week', "By Week (useful once you've accumulated multiple weeks)")
            _bucket_table(nfl_results_df, 'Favorite/Dog', "Favorite vs. Underdog")
            _bucket_table(nfl_results_df, 'Spread Bucket', "Spread Range")
            st.caption("Buckets are now finer-grained (5 tiers per side, 3-point windows) — a 3-point spread and a 7-point spread are genuinely different game-script situations and no longer get lumped together. The tradeoff: the extreme buckets (13+) will naturally have fewer predictions, so read those more cautiously than the middle buckets.")
            _bucket_table(nfl_results_df, 'Total Bucket', "Game Total Range")
            _bucket_table(nfl_results_df, 'Dome/Outdoor', "Dome vs. Outdoor")
            _bucket_table(nfl_results_df, 'Wind Risk', "Wind Risk")
            _bucket_table(nfl_results_df, 'Home/Road', "Home vs. Road")
            _bucket_table(nfl_results_df, 'Confidence Tier', "Confidence Tier")

            if nfl_results_df['Architecture Gap'].notna().any():
                st.write("**Architecture Gap vs. MAE** — how much the QB-history projection disagreed with the independent Expected Plays x Rate view, and whether that disagreement actually predicted error")
                gap_bins = [-0.01, 1, 2, 3, 4, 100]
                gap_labels = ["0-1", "1-2", "2-3", "3-4", "5+"]
                nfl_results_df['Gap Bucket'] = pd.cut(nfl_results_df['Architecture Gap'], bins=gap_bins, labels=gap_labels)
                gap_summary = nfl_results_df.dropna(subset=['Gap Bucket']).groupby('Gap Bucket', observed=True).agg(Predictions=('Error', 'count'), MAE=('Error', 'mean')).reset_index()
                gap_summary['MAE'] = gap_summary['MAE'].round(2)
                st.dataframe(gap_summary, use_container_width=True)

            st.markdown("---")
            st.subheader("🔬 Residual Analysis (bias, not just error)")
            st.caption("This is the real decision-gate before committing to any structural rebuild, per external review: MAE alone can't tell you WHY the error exists. This checks the SIGNED residual (Actual - Projection, not absolute error) for systematic bias — if the model isn't just noisy but consistently over- or under-projects in specific situations, that's real evidence a structural rebuild has genuine potential. If residuals show no consistent pattern anywhere, the remaining error is more likely pure variance a rebuild won't fix.")

            nfl_results_df['Signed Residual'] = nfl_results_df['Actual'] - nfl_results_df['Projection']
            overall_bias = round(nfl_results_df['Signed Residual'].mean(), 2)
            st.metric("Overall bias (Actual - Projection, averaged)", overall_bias,
                      help="Near 0 = no systematic over/under-projection overall. A bucket showing a bias far from 0 (even if overall is near 0) is the real signal to look for below.")

            def _bias_table(df, group_col, label):
                if group_col not in df.columns or df[group_col].isna().all():
                    return
                sub = df.dropna(subset=[group_col]).copy()
                if sub.empty:
                    return
                summary = sub.groupby(group_col, observed=True).agg(
                    Predictions=('Signed Residual', 'count'),
                    Bias=('Signed Residual', 'mean'),
                    MAE=('Error', 'mean'),
                ).reset_index()
                summary['Bias'] = summary['Bias'].round(2)
                summary['MAE'] = summary['MAE'].round(2)
                st.write(f"**{label}**")
                st.dataframe(summary, use_container_width=True)

            _bias_table(nfl_results_df, 'Spread Bucket', "Bias by Spread Range (positive = model UNDER-projects, negative = OVER-projects)")
            _bias_table(nfl_results_df, 'Total Bucket', "Bias by Game Total Range")
            _bias_table(nfl_results_df, 'Confidence Tier', "Bias by Confidence Tier")
            _bias_table(nfl_results_df, 'Week', "Bias by Week")
            if 'QB' in nfl_results_df.columns:
                qb_bias = nfl_results_df.groupby('QB').agg(Predictions=('Signed Residual', 'count'), Bias=('Signed Residual', 'mean'), MAE=('Error', 'mean')).reset_index()
                qb_bias = qb_bias[qb_bias['Predictions'] >= 5].sort_values('Bias')
                qb_bias['Bias'] = qb_bias['Bias'].round(2)
                qb_bias['MAE'] = qb_bias['MAE'].round(2)
                st.write("**Bias by QB (5+ predictions only)** — sorted most-under-projected to most-over-projected")
                st.dataframe(qb_bias, use_container_width=True)

            st.caption("How to read this: if bias stays close to 0 across every single breakdown, that matches the theoretical-floor finding — the remaining error is likely mostly irreducible variance, and a full structural rebuild is unlikely to move the needle much. If one or more buckets show a real, consistent bias (not just higher MAE, but a real +/- lean), that's genuine evidence worth pursuing further before building anything.")

            st.subheader("💰 Check Against Real Historical Sportsbook Lines")
            nfl_weeks_in_results = sorted(nfl_results_df['Week'].unique()) if 'Week' in nfl_results_df.columns else [int(backtest_week_start_nfl)]
            unique_games_nfl = nfl_results_df['Matchup'].nunique()
            est_quota = unique_games_nfl * 10
            st.caption(f"Same question as the NBA version: did the model's recommended side (Over/Under vs. the ACTUAL sportsbook line) actually win — not just how close the raw number was. Market: player_pass_attempts, confirmed real on The Odds API. Now works across your FULL accumulated week range automatically (previously required one week at a time) — fetches a separate historical snapshot per week, then combines everything into one final win rate. **Your results span {len(nfl_weeks_in_results)} week(s) with {unique_games_nfl} unique games total, so roughly {est_quota} quota units** — a full 18-week season could run into the thousands, so check your remaining Odds API quota before running a really wide range.")
            if st.button(f"Check Historical Lines (~{est_quota} quota units)", key="nfl_check_lines_btn"):
                with st.spinner(f"Fetching historical NFL events and lines across {len(nfl_weeks_in_results)} week(s)..."):
                    schedules_for_odds = get_nfl_schedules([int(backtest_season_nfl)])
                    all_lines_nfl = {}
                    checked_games_nfl = 0
                    events_by_week = {}
                    week_diagnostics_nfl = []
                    progress_bar_odds = st.progress(0)
                    status_text_odds = st.empty()

                    for wi, wk in enumerate(nfl_weeks_in_results):
                        status_text_odds.text(f"Week {wk} ({wi+1} of {len(nfl_weeks_in_results)})")
                        progress_bar_odds.progress((wi + 1) / len(nfl_weeks_in_results))
                        week_games_for_odds = schedules_for_odds[schedules_for_odds['week'] == wk]
                        if week_games_for_odds.empty:
                            week_diagnostics_nfl.append({'Week': wk, 'Events Returned': 0, 'Expected Matchups': 0, 'Matched': 0, 'Lines Found': 0, 'Note': 'No schedule rows found for this week'})
                            continue
                        week_start_row = week_games_for_odds.iloc[0]
                        snapshot_date = pd.to_datetime(week_start_row['gameday']).strftime('%Y-%m-%dT12:00:00Z')
                        events = get_historical_events_cached("americanfootball_nfl", snapshot_date)
                        events_by_week[wk] = events
                        matchup_to_event_nfl = {}
                        for ev in events:
                            h, a = ev.get('home_team'), ev.get('away_team')
                            if h and a:
                                matchup_to_event_nfl[f"{a} @ {h}"] = (ev.get('id'), ev.get('commence_time'))

                        week_matchups = nfl_results_df[nfl_results_df['Week'] == wk]['Matchup'].unique() if 'Week' in nfl_results_df.columns else nfl_results_df['Matchup'].unique()
                        week_matched_nfl = 0
                        week_lines_found_nfl = 0
                        for matchup in week_matchups:
                            away_abbrev, home_abbrev = matchup.split(' @ ')
                            away_full = nfl_abbrev_to_name.get(away_abbrev, away_abbrev)
                            home_full = nfl_abbrev_to_name.get(home_abbrev, home_abbrev)
                            full_matchup = f"{away_full} @ {home_full}"
                            event_info = matchup_to_event_nfl.get(full_matchup)
                            if not event_info:
                                continue
                            week_matched_nfl += 1
                            event_id, commence_time = event_info
                            game_data = get_historical_event_odds_cached("americanfootball_nfl", event_id, "player_pass_attempts", commence_time)
                            lines_this_game_nfl = 0
                            for bookmaker in game_data.get('bookmakers', []):
                                for market in bookmaker.get('markets', []):
                                    if market.get('key') == 'player_pass_attempts':
                                        for outcome in market.get('outcomes', []):
                                            pname = outcome.get('description')
                                            point = outcome.get('point')
                                            # Keyed by (player, week) now, not just player — a QB could
                                            # appear in multiple weeks across a multi-week range, and each
                                            # week has its own real line.
                                            if pname and point is not None:
                                                all_lines_nfl[(pname, wk)] = point
                                                lines_this_game_nfl += 1
                            week_lines_found_nfl += lines_this_game_nfl
                            checked_games_nfl += 1
                            time.sleep(0.5)
                        week_diagnostics_nfl.append({
                            'Week': wk, 'Events Returned': len(events),
                            'Expected Matchups': len(week_matchups), 'Matched': week_matched_nfl,
                            'Lines Found': week_lines_found_nfl,
                            'Note': 'OK' if len(events) > 0 else 'ZERO events returned from historical API for this snapshot date',
                        })

                    status_text_odds.text(f"✅ Done checking {len(nfl_weeks_in_results)} week(s).")
                    progress_bar_odds.progress(1.0)
                    st.write("**Per-week diagnostic — this shows exactly where any gaps are coming from**")
                    st.dataframe(pd.DataFrame(week_diagnostics_nfl), use_container_width=True)
                    if st.session_state.get('_historical_odds_errors'):
                        st.error(f"⚠️ {len(st.session_state['_historical_odds_errors'])} real API error(s) captured — this is the ACTUAL reason behind any zero/empty results above, not a silent failure anymore:")
                        st.dataframe(pd.DataFrame(st.session_state['_historical_odds_errors']), use_container_width=True)
                        st.session_state['_historical_odds_errors'] = []

                    nfl_results_df['Sportsbook Line'] = nfl_results_df.apply(lambda r: all_lines_nfl.get((r['QB'], r['Week']) if 'Week' in nfl_results_df.columns else (r['QB'], nfl_weeks_in_results[0])), axis=1)

                    def _nfl_model_side(row):
                        if pd.isna(row['Sportsbook Line']):
                            return None
                        return 'Over' if row['Projection'] > row['Sportsbook Line'] else ('Under' if row['Projection'] < row['Sportsbook Line'] else 'Push')

                    def _nfl_did_win(row):
                        if pd.isna(row['Sportsbook Line']):
                            return None
                        if row['Actual'] > row['Sportsbook Line']:
                            actual_side = 'Over'
                        elif row['Actual'] < row['Sportsbook Line']:
                            actual_side = 'Under'
                        else:
                            return 'Push'
                        model_side = _nfl_model_side(row)
                        if model_side in (None, 'Push'):
                            return None
                        return 'Win' if model_side == actual_side else 'Loss'

                    nfl_results_df['Model Side'] = nfl_results_df.apply(_nfl_model_side, axis=1)
                    nfl_results_df['Bet Result'] = nfl_results_df.apply(_nfl_did_win, axis=1)
                    matched_nfl = nfl_results_df['Sportsbook Line'].notna().sum()
                    if checked_games_nfl == 0:
                        st.error("0 games matched across any week — likely a team name format mismatch (nflverse uses abbreviations like 'KC', The Odds API uses full names like 'Kansas City Chiefs'). Diagnostic below (showing the most recent week checked):")
                        st.write("Our Matchup strings (from nflverse):", list(nfl_results_df['Matchup'].unique()))
                        last_week_events = list(events_by_week.values())[-1] if events_by_week else []
                        st.write("Real event team names (from The Odds API):", [(ev.get('away_team'), ev.get('home_team')) for ev in last_week_events])
                    st.success(f"✅ Checked {checked_games_nfl} game(s) across {len(nfl_weeks_in_results)} week(s), matched real lines for {matched_nfl}/{len(nfl_results_df)} QBs.")
                    result_cols_nfl = ['QB', 'Week', 'Matchup', 'Projection', 'Sportsbook Line', 'Actual', 'Model Side', 'Bet Result']
                    if 'Confidence Tier' in nfl_results_df.columns:
                        result_cols_nfl.append('Confidence Tier')
                    if 'Week' not in nfl_results_df.columns:
                        result_cols_nfl.remove('Week')
                    line_results_nfl = nfl_results_df[nfl_results_df['Sportsbook Line'].notna()][result_cols_nfl]
                    st.dataframe(line_results_nfl, use_container_width=True)
                    graded_nfl = line_results_nfl[line_results_nfl['Bet Result'].isin(['Win', 'Loss'])]
                    if not graded_nfl.empty:
                        win_rate_nfl = round((graded_nfl['Bet Result'] == 'Win').mean() * 100, 1)
                        st.metric(f"Win rate vs. real historical lines (all {len(nfl_weeks_in_results)} week(s) combined)", f"{win_rate_nfl}% ({len(graded_nfl)} graded bets)")
                        st.caption("A rate meaningfully above ~52.4% (the -110 breakeven point) across a real, combined multi-week sample is a genuine signal — this is now the full-range number you were previously having to piece together week by week yourself.")
                        if 'Confidence Tier' in graded_nfl.columns:
                            st.write("**Win rate by Confidence Tier** — this is the real question. The blended win rate above lumps every prediction together, but nobody actually bets a Volatile-tier pick the same way as a Reliable one — this shows whether the tiers you'd genuinely trust look different from the overall number.")
                            tier_win_summary_nfl = graded_nfl.groupby('Confidence Tier').apply(lambda g: round((g['Bet Result'] == 'Win').mean() * 100, 1)).reset_index(name='Win Rate %')
                            tier_win_summary_nfl['Graded Bets'] = graded_nfl.groupby('Confidence Tier').size().values
                            st.dataframe(tier_win_summary_nfl.sort_values('Win Rate %', ascending=False), use_container_width=True)
                        if 'Week' in line_results_nfl.columns and line_results_nfl['Week'].nunique() > 1:
                            st.write("**Win rate by week** (useful to spot whether one specific week is dragging the average)")
                            week_win_summary = graded_nfl.groupby('Week').apply(lambda g: round((g['Bet Result'] == 'Win').mean() * 100, 1)).reset_index(name='Win Rate %')
                            week_win_summary['Graded Bets'] = graded_nfl.groupby('Week').size().values
                            st.dataframe(week_win_summary, use_container_width=True)
                        result_counts_nfl = line_results_nfl['Bet Result'].fillna('No Bet/Push').value_counts()
                        st.bar_chart(result_counts_nfl)
                        chart_df_nfl = line_results_nfl[line_results_nfl['Bet Result'].isin(['Win', 'Loss'])].copy()
                        chart_df_nfl['Result Color'] = chart_df_nfl['Bet Result'].map({'Win': '#2ecc71', 'Loss': '#e74c3c'})
                        st.scatter_chart(chart_df_nfl, x='Projection', y='Actual', color='Result Color')

        st.markdown("---")
        st.subheader("🎛️ Coefficient Optimizer")
        st.caption("Grid search over the base weighting (season/last-5/last-10) and Vegas coefficients (spread, total) — these were always reasonable starting guesses, never actually tuned against real data. Searches on a TRAINING season, then validates the winning combination against the OTHER season as a genuinely held-out test — the same overfitting protection discussed before ever building this: don't trust a combination that only looks good on the data it was picked from.")

        opt_train_season = st.selectbox("Train on", ["2024", "2025"], key="nfl_opt_train_season")
        opt_validate_season = "2025" if opt_train_season == "2024" else "2024"
        st.caption(f"Will validate the best combination against {opt_validate_season} automatically.")
        col_opt_wk1, col_opt_wk2 = st.columns(2)
        with col_opt_wk1:
            opt_week_start = st.number_input("Training week range - start", min_value=7, max_value=18, value=7, key="nfl_opt_week_start")
        with col_opt_wk2:
            opt_week_end = st.number_input("Training week range - end", min_value=7, max_value=18, value=12, key="nfl_opt_week_end")
        st.caption("Kept to week 7+ deliberately — avoids the early-season prior-season-bridge complexity, keeping the search focused purely on the coefficients themselves. A 6-week window is a reasonable, tractable sample without an excessive number of model runs.")

        if st.button("🔍 Run Grid Search", use_container_width=True):
            with st.spinner("Running grid search..."):
                try:
                    # Updated (July 2026, round 17) — moderate_tier_bias_
                    # correction VALIDATED and locked in last round (0.03,
                    # third real win of the session, the most convincing
                    # yet — a genuine peaked shape in training). This
                    # search tests reliable_tier_bias_correction — real
                    # residual analysis found the Reliable tier showed a
                    # consistent POSITIVE bias (under-projection, opposite
                    # direction from the other three) in BOTH 2024 (+0.29)
                    # and 2025 (+0.69). ADDITIONAL upward correction
                    # specifically for Reliable-tier predictions, layered
                    # on top of all 3 already-validated corrections (left
                    # unset below, so they use their locked-in defaults).
                    reliable_correction_options = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05]

                    train_weeks = list(range(int(opt_week_start), int(opt_week_end) + 1))
                    schedules_opt = get_nfl_schedules([int(opt_train_season)])
                    actual_stats_opt = get_nfl_player_stats([int(opt_train_season)])
                    matchups_opt = []
                    for wk in train_weeks:
                        week_games = schedules_opt[schedules_opt['week'] == wk]
                        for _, g in week_games.iterrows():
                            if pd.notna(g.get('home_qb_name')):
                                matchups_opt.append({'qb': g['home_qb_name'], 'team': g['home_team'], 'opponent': g['away_team'], 'week': wk})
                            if pd.notna(g.get('away_qb_name')):
                                matchups_opt.append({'qb': g['away_qb_name'], 'team': g['away_team'], 'opponent': g['home_team'], 'week': wk})

                    combos = [((0.45, 0.35, 0.20), 0.008, 0.004, rc) for rc in reliable_correction_options]
                    st.caption(f"Testing {len(combos)} Reliable-tier-specific correction sizes (0% = no extra correction like now, up to 5% additional UPWARD for Reliable-tier predictions only) across {len(matchups_opt)} QB-weeks ({len(train_weeks)} weeks). All 3 already-validated corrections are active in every combination.")
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    combo_results = []

                    for ci, (blend, spread_c, total_c, reliable_c) in enumerate(combos):
                        status_text.text(f"Testing Reliable-tier correction {reliable_c} ({ci+1} of {len(combos)})")
                        progress_bar.progress((ci + 1) / len(combos))
                        errors = []
                        for m in matchups_opt:
                            result = run_nfl_pass_attempts_projection(
                                m['qb'], m['team'], m['opponent'], int(opt_train_season), as_of_week=m['week'],
                                season_weight=blend[0], last5_weight=blend[1], last10_weight=blend[2],
                                spread_coef=spread_c, total_coef=total_c, reliable_tier_bias_correction=reliable_c,
                            )
                            if not result:
                                continue
                            actual_row = actual_stats_opt[(actual_stats_opt['player_display_name'] == m['qb']) & (actual_stats_opt['week'] == m['week']) & (actual_stats_opt['position'] == 'QB')]
                            if actual_row.empty:
                                continue
                            errors.append(abs(result['projection'] - actual_row['attempts'].iloc[0]))
                        if errors:
                            combo_results.append({
                                'Reliable Tier Bias Correction': reliable_c,
                                'MAE': round(sum(errors) / len(errors), 3), 'N': len(errors),
                            })

                    combo_df = pd.DataFrame(combo_results).sort_values('MAE')
                    st.session_state['nfl_optimizer_results'] = combo_df
                    st.session_state['nfl_optimizer_train_season'] = opt_train_season
                    st.session_state['nfl_optimizer_weeks'] = train_weeks
                    status_text.text(f"✅ Done! Tested {len(combos)} combinations.")
                    progress_bar.progress(1.0)
                except Exception as e:
                    st.error(f"Real error: {e}")
                    import traceback
                    st.code(traceback.format_exc())

        if 'nfl_optimizer_results' in st.session_state:
            combo_df = st.session_state['nfl_optimizer_results']
            st.write(f"**All Reliable-tier bias corrections tested (trained on {st.session_state.get('nfl_optimizer_train_season', '')}), sorted best to worst:**")
            st.dataframe(combo_df, use_container_width=True)

            best = combo_df.iloc[0]
            st.success(f"Best on training season: MAE {best['MAE']} at reliable_tier_bias_correction={best['Reliable Tier Bias Correction']}")

            if st.button("✅ Validate Best Combination on the OTHER season", use_container_width=True):
                validate_season = "2025" if st.session_state.get('nfl_optimizer_train_season') == "2024" else "2024"
                val_weeks = st.session_state.get('nfl_optimizer_weeks', list(range(int(opt_week_start), int(opt_week_end) + 1)))
                with st.spinner(f"Validating against {validate_season} (same week range)..."):
                    try:
                        schedules_val = get_nfl_schedules([int(validate_season)])
                        actual_stats_val = get_nfl_player_stats([int(validate_season)])
                        matchups_val = []
                        for wk in val_weeks:
                            week_games = schedules_val[schedules_val['week'] == wk]
                            for _, g in week_games.iterrows():
                                if pd.notna(g.get('home_qb_name')):
                                    matchups_val.append({'qb': g['home_qb_name'], 'team': g['home_team'], 'opponent': g['away_team'], 'week': wk})
                                if pd.notna(g.get('away_qb_name')):
                                    matchups_val.append({'qb': g['away_qb_name'], 'team': g['away_team'], 'opponent': g['home_team'], 'week': wk})

                        val_errors_new = []
                        val_errors_old = []
                        for m in matchups_val:
                            result_new = run_nfl_pass_attempts_projection(
                                m['qb'], m['team'], m['opponent'], int(validate_season), as_of_week=m['week'],
                                reliable_tier_bias_correction=best['Reliable Tier Bias Correction'],
                            )
                            result_old = run_nfl_pass_attempts_projection(m['qb'], m['team'], m['opponent'], int(validate_season), as_of_week=m['week'])
                            actual_row = actual_stats_val[(actual_stats_val['player_display_name'] == m['qb']) & (actual_stats_val['week'] == m['week']) & (actual_stats_val['position'] == 'QB')]
                            if actual_row.empty:
                                continue
                            actual_val = actual_row['attempts'].iloc[0]
                            if result_new:
                                val_errors_new.append(abs(result_new['projection'] - actual_val))
                            if result_old:
                                val_errors_old.append(abs(result_old['projection'] - actual_val))

                        new_mae = round(sum(val_errors_new) / len(val_errors_new), 3) if val_errors_new else None
                        old_mae = round(sum(val_errors_old) / len(val_errors_old), 3) if val_errors_old else None
                        st.write(f"**On {validate_season} (held-out, same week range):**")
                        vcol1, vcol2 = st.columns(2)
                        vcol1.metric("Current defaults MAE", old_mae)
                        vcol2.metric("New combination MAE", new_mae, delta=round(new_mae - old_mae, 3) if new_mae and old_mae else None, delta_color="inverse")
                        if new_mae and old_mae:
                            if new_mae < old_mae:
                                st.success("✅ The new combination genuinely improves on the held-out season too — real evidence, not just overfitting to the training season.")
                            else:
                                st.warning("⚠️ The new combination does NOT improve (or is worse) on the held-out season — this looks like overfitting to the training season's noise. Don't lock these values in.")
                    except Exception as e:
                        st.error(f"Real error: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        if 'nfl_backtest_skipped' in st.session_state and st.session_state['nfl_backtest_skipped']:
            with st.expander(f"Skipped ({len(st.session_state['nfl_backtest_skipped'])})"):
                st.dataframe(pd.DataFrame(st.session_state['nfl_backtest_skipped']), use_container_width=True)

    elif backtest_sport == "NFL Pass Completions":
        st.caption("Full error decomposition (external review) — completions error has TWO sources (attempts volume error and completion-rate error), and this separates them instead of showing one blended number. Also computes two oracle diagnostics: 'actual attempts x projected completion%' isolates how good the completion-rate model would be if attempts were known perfectly, and 'projected attempts x actual completion%' isolates how much error comes from the attempts stage specifically.")
        backtest_season_comp = st.selectbox("Season", ["2025", "2024", "2023"], key="backtest_season_comp")
        col_cwk1, col_cwk2 = st.columns(2)
        with col_cwk1:
            backtest_week_start_comp = st.number_input("Start week", min_value=1, max_value=18, value=7, key="backtest_week_start_comp")
        with col_cwk2:
            backtest_week_end_comp = st.number_input("End week", min_value=1, max_value=18, value=18, key="backtest_week_end_comp")

        if st.button("🔄 Reset to Validated Defaults", key="comp_reset_defaults"):
            st.session_state['comp_weighting_test'] = 'attempt_weighted'
            st.session_state['comp_bridge_test'] = 'attempts'
            st.session_state['comp_team_mult_test'] = 0.0
            st.session_state['comp_use_cpoe_test'] = False
            st.session_state['comp_bias_correction_test'] = 0.0
            st.session_state['comp_moderate_correction_test'] = 0.06
            st.session_state['comp_volatile_correction_test'] = 0.20
            st.rerun()

        st.write("**Testable parameters** — defaults now match what's actually been VALIDATED (attempt_weighted, team-change=0.0), not the original pre-correction values. A real bug was just caught here: these widgets were silently overriding the model's own validated defaults with stale ones every time a normal backtest ran, which is why full-season results looked identical to the very first, pre-correction run.")
        col_cp1, col_cp2 = st.columns(2)
        with col_cp1:
            comp_weighting = st.selectbox("Completion weighting", ["attempt_weighted", "equal"], key="comp_weighting_test")
            comp_bridge = st.selectbox("Bridge schedule", ["attempts", "slow_fade", "medium_fade"], key="comp_bridge_test")
        with col_cp2:
            comp_team_mult = st.slider("Team-change multiplier", 0.0, 1.0, 0.0, 0.05, key="comp_team_mult_test")
            comp_use_cpoe = st.checkbox("Use CPOE challenger model instead of historical blend", key="comp_use_cpoe_test")

        st.write("**Bias corrections** — Moderate and Volatile now default to their VALIDATED values (0.06 / 0.20); general correction stays at 0.0, since it was tested and rejected.")
        col_cb1, col_cb2, col_cb3 = st.columns(3)
        with col_cb1:
            comp_bias_correction = st.slider("General correction (all tiers)", 0.0, 0.15, 0.0, 0.01, key="comp_bias_correction_test", help="Rejected — stays at 0.0. Upward would mean the model under-projects overall.")
        with col_cb2:
            comp_moderate_correction = st.slider("Additional: Moderate tier", 0.0, 0.15, 0.06, 0.01, key="comp_moderate_correction_test", help="Validated — first real Completions correction of the session.")
        with col_cb3:
            comp_volatile_correction = st.slider("Additional: Volatile tier", 0.0, 0.30, 0.20, 0.01, key="comp_volatile_correction_test", help="Validated — largest bias of the three, and the largest correction.")

        accumulate_comp = st.checkbox("➕ Accumulate — add to existing results instead of replacing", key="comp_backtest_accumulate")
        debug_comp = st.checkbox("🔧 Show real errors (debug)", key="comp_backtest_debug")

        col_run_comp, col_clear_comp = st.columns([3, 1])
        with col_clear_comp:
            if st.button("🗑️ Clear All", key="comp_clear_all", use_container_width=True):
                st.session_state['comp_backtest_results'] = []
                st.rerun()
        with col_run_comp:
            run_comp_clicked = st.button("🔍 Load Week(s) & Run Projections", key="comp_run_button", use_container_width=True)

        if run_comp_clicked:
            st.session_state['_nfl_debug_mode'] = debug_comp
            weeks_to_test_comp = list(range(int(backtest_week_start_comp), int(backtest_week_end_comp) + 1))
            with st.spinner(f"Pulling {len(weeks_to_test_comp)} week(s) of games..."):
                try:
                    schedules_comp = get_nfl_schedules([int(backtest_season_comp)])
                    actual_stats_comp = get_nfl_player_stats([int(backtest_season_comp)])
                    results_comp = list(st.session_state.get('comp_backtest_results', [])) if accumulate_comp else []
                    skipped_comp = []
                    progress_bar_comp = st.progress(0)
                    status_text_comp = st.empty()

                    matchups_comp = []
                    for wk in weeks_to_test_comp:
                        week_games = schedules_comp[schedules_comp['week'] == wk]
                        for _, g in week_games.iterrows():
                            if pd.notna(g.get('home_qb_name')):
                                matchups_comp.append({'qb': g['home_qb_name'], 'team': g['home_team'], 'opponent': g['away_team'], 'week': wk})
                            if pd.notna(g.get('away_qb_name')):
                                matchups_comp.append({'qb': g['away_qb_name'], 'team': g['away_team'], 'opponent': g['home_team'], 'week': wk})

                    for i, m in enumerate(matchups_comp):
                        status_text_comp.text(f"Week {m['week']}: {m['qb']} ({i+1} of {len(matchups_comp)})")
                        progress_bar_comp.progress((i+1) / len(matchups_comp))
                        try:
                            result = run_nfl_pass_completions_projection(
                                m['qb'], m['team'], m['opponent'], int(backtest_season_comp), as_of_week=m['week'],
                                completion_weighting=comp_weighting, bridge_schedule=comp_bridge,
                                team_change_multiplier=comp_team_mult, use_cpoe_model=comp_use_cpoe,
                                completions_bias_correction=comp_bias_correction,
                                completions_moderate_tier_correction=comp_moderate_correction,
                                completions_volatile_tier_correction=comp_volatile_correction,
                            )
                        except Exception as e:
                            skipped_comp.append({'QB': m['qb'], 'Week': m['week'], 'Reason': f'Exception: {e}'})
                            continue
                        actual_row = actual_stats_comp[(actual_stats_comp['player_display_name'] == m['qb']) & (actual_stats_comp['week'] == m['week']) & (actual_stats_comp['position'] == 'QB')]
                        if actual_row.empty:
                            skipped_comp.append({'QB': m['qb'], 'Week': m['week'], 'Reason': "Didn't play or no stats found"})
                            continue
                        actual_attempts = actual_row['attempts'].iloc[0]
                        actual_completions = actual_row['completions'].iloc[0]
                        if not result or actual_attempts <= 0:
                            real_reason = st.session_state.get('_completions_fail_reasons', {}).get(m['qb'], "Insufficient history or zero actual attempts")
                            skipped_comp.append({'QB': m['qb'], 'Week': m['week'], 'Reason': real_reason})
                            continue
                        actual_completion_pct = actual_completions / actual_attempts

                        # Full error decomposition (external review item 5)
                        projected_attempts = result['projected_attempts']
                        projected_completion_pct = result['projected_completion_pct']
                        projected_completions = result['projection']

                        oracle_volume_completions = actual_attempts * projected_completion_pct  # isolates completion-rate model quality
                        oracle_efficiency_completions = projected_attempts * actual_completion_pct  # isolates attempts-stage contribution

                        results_comp.append({
                            'QB': m['qb'], 'Week': m['week'], 'Matchup': f"{m['opponent']} @ {m['team']}",
                            'Proj Attempts': projected_attempts, 'Actual Attempts': actual_attempts,
                            'Attempts Error': round(abs(projected_attempts - actual_attempts), 1),
                            'Proj Comp%': round(projected_completion_pct, 3), 'Actual Comp%': round(actual_completion_pct, 3),
                            'Comp% Error': round(abs(projected_completion_pct - actual_completion_pct), 3),
                            'Proj Completions': projected_completions, 'Actual Completions': actual_completions,
                            'Completions Error': round(abs(projected_completions - actual_completions), 1),
                            'Signed Residual': round(actual_completions - projected_completions, 1),
                            'Oracle Volume Error': round(abs(oracle_volume_completions - actual_completions), 1),
                            'Oracle Efficiency Error': round(abs(oracle_efficiency_completions - actual_completions), 1),
                            'Confidence Tier': result.get('confidence_tier'),
                        })
                    st.session_state['comp_backtest_results'] = results_comp
                    st.session_state['comp_backtest_skipped'] = skipped_comp
                    status_text_comp.text(f"✅ Done! {len(results_comp)} total projections, {len(skipped_comp)} skipped.")
                    progress_bar_comp.progress(1.0)
                except Exception as e:
                    st.error(f"Real error: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                finally:
                    st.session_state['_nfl_debug_mode'] = False

        if 'comp_backtest_results' in st.session_state and st.session_state['comp_backtest_results']:
            comp_df = pd.DataFrame(st.session_state['comp_backtest_results'])
            st.dataframe(comp_df, use_container_width=True)

            st.markdown("---")
            st.subheader("📊 Error Decomposition")
            attempts_mae = round(comp_df['Attempts Error'].mean(), 2)
            comp_pct_mae = round(comp_df['Comp% Error'].mean(), 4)
            completions_mae = round(comp_df['Completions Error'].mean(), 2)
            oracle_volume_mae = round(comp_df['Oracle Volume Error'].mean(), 2)
            oracle_efficiency_mae = round(comp_df['Oracle Efficiency Error'].mean(), 2)

            col_e1, col_e2, col_e3 = st.columns(3)
            col_e1.metric("Attempts MAE", attempts_mae, help="Error in the underlying Attempts projection this model depends on")
            col_e2.metric("Completion% MAE", comp_pct_mae, help="Error in the completion-rate projection specifically")
            col_e3.metric("Completions MAE", completions_mae, help="The real, final, blended error")

            col_o1, col_o2 = st.columns(2)
            col_o1.metric("Oracle: Actual Attempts x Proj Comp%", oracle_volume_mae, help="If attempts were known PERFECTLY, this is how good the completion-rate model alone would be")
            col_o2.metric("Oracle: Proj Attempts x Actual Comp%", oracle_efficiency_mae, help="If completion% were known PERFECTLY, this shows how much error comes from the attempts stage alone")
            if oracle_volume_mae < oracle_efficiency_mae:
                st.caption(f"**Bottleneck read:** completion-rate error ({oracle_volume_mae}) is smaller than attempts-stage error ({oracle_efficiency_mae}) — the ATTEMPTS projection is contributing more to the final error here. Improving Completions further may mean improving Attempts, not this model's own logic.")
            else:
                st.caption(f"**Bottleneck read:** attempts-stage error ({oracle_efficiency_mae}) is smaller than completion-rate error ({oracle_volume_mae}) — the COMPLETION-RATE projection is contributing more to the final error here. Worth focusing improvement efforts on completion% specifically, not attempts.")

            st.markdown("---")
            st.write("**Completions MAE + Bias by Confidence Tier**")
            st.caption("Bias (signed: Actual - Projection) is the real test of whether a tier's error is a fixable systematic pattern or genuine noise. High MAE with bias near 0 means the tier is just noisier (small sample, high variance) — not something a correction can fix, since there's no consistent direction to correct toward. High MAE WITH a real, non-zero bias means there's a genuine, fixable pattern, the same way Moderate tier's bias was found and corrected for Attempts.")
            tier_summary_comp = comp_df.groupby('Confidence Tier').agg(Predictions=('Completions Error', 'count'), MAE=('Completions Error', 'mean'), Bias=('Signed Residual', 'mean')).reset_index()
            tier_summary_comp['MAE'] = tier_summary_comp['MAE'].round(2)
            tier_summary_comp['Bias'] = tier_summary_comp['Bias'].round(2)
            st.dataframe(tier_summary_comp, use_container_width=True)

            st.markdown("---")
            st.subheader("💰 Check Against Real Historical Sportsbook Lines")
            comp_weeks_in_results = sorted(comp_df['Week'].unique()) if 'Week' in comp_df.columns else []
            unique_games_comp = comp_df['Matchup'].nunique()
            est_quota_comp = unique_games_comp * 10
            st.caption(f"Same question as the Attempts version: did the model's recommended side (Over/Under vs. the ACTUAL sportsbook line) actually win. Market: player_pass_completions, confirmed real on The Odds API. Works across your full accumulated week range automatically. **Your results span {len(comp_weeks_in_results)} week(s) with {unique_games_comp} unique games total, so roughly {est_quota_comp} quota units** — check your remaining Odds API quota before running a wide range.")
            if st.button(f"Check Historical Lines (~{est_quota_comp} quota units)", key="comp_check_lines_btn"):
                with st.spinner(f"Fetching historical NFL events and lines across {len(comp_weeks_in_results)} week(s)..."):
                    schedules_for_odds_comp = get_nfl_schedules([int(backtest_season_comp)])
                    all_lines_comp = {}
                    checked_games_comp = 0
                    events_by_week_comp = {}
                    week_diagnostics_comp = []
                    progress_bar_odds_comp = st.progress(0)
                    status_text_odds_comp = st.empty()

                    for wi, wk in enumerate(comp_weeks_in_results):
                        status_text_odds_comp.text(f"Week {wk} ({wi+1} of {len(comp_weeks_in_results)})")
                        progress_bar_odds_comp.progress((wi + 1) / len(comp_weeks_in_results))
                        week_games_for_odds = schedules_for_odds_comp[schedules_for_odds_comp['week'] == wk]
                        if week_games_for_odds.empty:
                            week_diagnostics_comp.append({'Week': wk, 'Events Returned': 0, 'Expected Matchups': 0, 'Matched': 0, 'Lines Found': 0, 'Note': 'No schedule rows found for this week'})
                            continue
                        week_start_row = week_games_for_odds.iloc[0]
                        snapshot_date = pd.to_datetime(week_start_row['gameday']).strftime('%Y-%m-%dT12:00:00Z')
                        events = get_historical_events_cached("americanfootball_nfl", snapshot_date)
                        events_by_week_comp[wk] = events
                        matchup_to_event_comp = {}
                        for ev in events:
                            h, a = ev.get('home_team'), ev.get('away_team')
                            if h and a:
                                matchup_to_event_comp[f"{a} @ {h}"] = (ev.get('id'), ev.get('commence_time'))

                        week_matchups = comp_df[comp_df['Week'] == wk]['Matchup'].unique()
                        week_matched = 0
                        week_lines_found = 0
                        for matchup in week_matchups:
                            away_abbrev, home_abbrev = matchup.split(' @ ')
                            away_full = nfl_abbrev_to_name.get(away_abbrev, away_abbrev)
                            home_full = nfl_abbrev_to_name.get(home_abbrev, home_abbrev)
                            full_matchup = f"{away_full} @ {home_full}"
                            event_info = matchup_to_event_comp.get(full_matchup)
                            if not event_info:
                                continue
                            week_matched += 1
                            event_id, commence_time = event_info
                            game_data = get_historical_event_odds_cached("americanfootball_nfl", event_id, "player_pass_completions", commence_time)
                            lines_this_game = 0
                            for bookmaker in game_data.get('bookmakers', []):
                                for market in bookmaker.get('markets', []):
                                    if market.get('key') == 'player_pass_completions':
                                        for outcome in market.get('outcomes', []):
                                            pname = outcome.get('description')
                                            point = outcome.get('point')
                                            if pname and point is not None:
                                                all_lines_comp[(pname, wk)] = point
                                                lines_this_game += 1
                            week_lines_found += lines_this_game
                            checked_games_comp += 1
                            time.sleep(0.5)
                        week_diagnostics_comp.append({
                            'Week': wk, 'Events Returned': len(events),
                            'Expected Matchups': len(week_matchups), 'Matched': week_matched,
                            'Lines Found': week_lines_found,
                            'Note': 'OK' if len(events) > 0 else 'ZERO events returned from historical API for this snapshot date',
                        })

                    status_text_odds_comp.text(f"✅ Done checking {len(comp_weeks_in_results)} week(s).")
                    progress_bar_odds_comp.progress(1.0)
                    st.write("**Per-week diagnostic — this shows exactly where any gaps are coming from**")
                    st.dataframe(pd.DataFrame(week_diagnostics_comp), use_container_width=True)
                    if st.session_state.get('_historical_odds_errors'):
                        st.error(f"⚠️ {len(st.session_state['_historical_odds_errors'])} real API error(s) captured — this is the ACTUAL reason behind any zero/empty results above, not a silent failure anymore:")
                        st.dataframe(pd.DataFrame(st.session_state['_historical_odds_errors']), use_container_width=True)
                        st.session_state['_historical_odds_errors'] = []

                    comp_df['Sportsbook Line'] = comp_df.apply(lambda r: all_lines_comp.get((r['QB'], r['Week'])), axis=1)

                    def _comp_model_side(row):
                        if pd.isna(row['Sportsbook Line']):
                            return None
                        return 'Over' if row['Proj Completions'] > row['Sportsbook Line'] else ('Under' if row['Proj Completions'] < row['Sportsbook Line'] else 'Push')

                    def _comp_did_win(row):
                        if pd.isna(row['Sportsbook Line']):
                            return None
                        if row['Actual Completions'] > row['Sportsbook Line']:
                            actual_side = 'Over'
                        elif row['Actual Completions'] < row['Sportsbook Line']:
                            actual_side = 'Under'
                        else:
                            return 'Push'
                        model_side = _comp_model_side(row)
                        if model_side in (None, 'Push'):
                            return None
                        return 'Win' if model_side == actual_side else 'Loss'

                    comp_df['Model Side'] = comp_df.apply(_comp_model_side, axis=1)
                    comp_df['Bet Result'] = comp_df.apply(_comp_did_win, axis=1)
                    matched_comp = comp_df['Sportsbook Line'].notna().sum()
                    if checked_games_comp == 0:
                        st.error("0 games matched across any week — likely a team name format mismatch. Diagnostic below (most recent week checked):")
                        st.write("Our Matchup strings (from nflverse):", list(comp_df['Matchup'].unique()))
                        last_week_events_comp = list(events_by_week_comp.values())[-1] if events_by_week_comp else []
                        st.write("Real event team names (from The Odds API):", [(ev.get('away_team'), ev.get('home_team')) for ev in last_week_events_comp])
                    st.success(f"✅ Checked {checked_games_comp} game(s) across {len(comp_weeks_in_results)} week(s), matched real lines for {matched_comp}/{len(comp_df)} QBs.")
                    result_cols_comp = ['QB', 'Week', 'Matchup', 'Proj Completions', 'Sportsbook Line', 'Actual Completions', 'Model Side', 'Bet Result']
                    if 'Confidence Tier' in comp_df.columns:
                        result_cols_comp.append('Confidence Tier')
                    line_results_comp = comp_df[comp_df['Sportsbook Line'].notna()][result_cols_comp]
                    st.dataframe(line_results_comp, use_container_width=True)
                    graded_comp = line_results_comp[line_results_comp['Bet Result'].isin(['Win', 'Loss'])]
                    if not graded_comp.empty:
                        win_rate_comp = round((graded_comp['Bet Result'] == 'Win').mean() * 100, 1)
                        st.metric(f"Win rate vs. real historical lines (all {len(comp_weeks_in_results)} week(s) combined)", f"{win_rate_comp}% ({len(graded_comp)} graded bets)")
                        st.caption("A rate meaningfully above ~52.4% (the -110 breakeven point) across a real, combined multi-week sample is a genuine signal.")
                        if 'Confidence Tier' in graded_comp.columns:
                            st.write("**Win rate by Confidence Tier** — the blended win rate above lumps every prediction together; nobody actually bets a Volatile-tier pick the same way as a Reliable one.")
                            tier_win_summary_comp = graded_comp.groupby('Confidence Tier').apply(lambda g: round((g['Bet Result'] == 'Win').mean() * 100, 1)).reset_index(name='Win Rate %')
                            tier_win_summary_comp['Graded Bets'] = graded_comp.groupby('Confidence Tier').size().values
                            st.dataframe(tier_win_summary_comp.sort_values('Win Rate %', ascending=False), use_container_width=True)
                        if line_results_comp['Week'].nunique() > 1:
                            st.write("**Win rate by week**")
                            week_win_summary_comp = graded_comp.groupby('Week').apply(lambda g: round((g['Bet Result'] == 'Win').mean() * 100, 1)).reset_index(name='Win Rate %')
                            week_win_summary_comp['Graded Bets'] = graded_comp.groupby('Week').size().values
                            st.dataframe(week_win_summary_comp, use_container_width=True)
                        result_counts_comp = line_results_comp['Bet Result'].fillna('No Bet/Push').value_counts()
                        st.bar_chart(result_counts_comp)
                        chart_df_comp = line_results_comp[line_results_comp['Bet Result'].isin(['Win', 'Loss'])].copy()
                        chart_df_comp['Result Color'] = chart_df_comp['Bet Result'].map({'Win': '#2ecc71', 'Loss': '#e74c3c'})
                        st.scatter_chart(chart_df_comp, x='Proj Completions', y='Actual Completions', color='Result Color')

        if 'comp_backtest_skipped' in st.session_state and st.session_state['comp_backtest_skipped']:
            with st.expander(f"Skipped ({len(st.session_state['comp_backtest_skipped'])})"):
                st.dataframe(pd.DataFrame(st.session_state['comp_backtest_skipped']), use_container_width=True)

        st.markdown("---")
        st.subheader("🎛️ Completions Coefficient Optimizer")
        st.caption("Same proven train/validate pattern as the Attempts optimizer — search on one season, validate the winner on the OTHER season before trusting it. General correction: rejected. Moderate-tier: validated (0.06). Volatile-tier: validated (0.20). Completion weighting: validated (attempt_weighted). Bridge schedule: no real effect. Team-change multiplier: validated (0.0). CPOE full replacement: rejected (historical blend won outright). Now testing a genuinely different idea from a follow-up review — BLENDING a small amount of CPOE into the historical projection instead of replacing it entirely.")

        opt_train_season_comp = st.selectbox("Train on", ["2024", "2025"], key="comp_opt_train_season")
        col_owk1, col_owk2 = st.columns(2)
        with col_owk1:
            opt_week_start_comp = st.number_input("Training week range - start", min_value=1, max_value=18, value=1, key="comp_opt_week_start")
        with col_owk2:
            opt_week_end_comp = st.number_input("Training week range - end", min_value=1, max_value=18, value=18, key="comp_opt_week_end")

        if st.button("🔍 Run Grid Search", key="comp_opt_run", use_container_width=True):
            with st.spinner("Running grid search..."):
                try:
                    # Updated — use_cpoe_model (full replacement) tested
                    # and REJECTED (historical blend won outright, 4.942
                    # vs 4.954, no validation even needed). Per a follow-
                    # up review: that doesn't mean CPOE has zero signal —
                    # replacing the whole model may have just been too
                    # aggressive. Now testing cpoe_blend_weight — MIXING
                    # a small amount of CPOE into the historical
                    # projection instead of swapping it out entirely,
                    # using the reviewer's own suggested test values.
                    blend_options_comp = [0.0, 0.10, 0.20, 0.30, 0.40]

                    train_weeks_comp = list(range(int(opt_week_start_comp), int(opt_week_end_comp) + 1))
                    schedules_opt_comp = get_nfl_schedules([int(opt_train_season_comp)])
                    actual_stats_opt_comp = get_nfl_player_stats([int(opt_train_season_comp)])
                    matchups_opt_comp = []
                    for wk in train_weeks_comp:
                        week_games = schedules_opt_comp[schedules_opt_comp['week'] == wk]
                        for _, g in week_games.iterrows():
                            if pd.notna(g.get('home_qb_name')):
                                matchups_opt_comp.append({'qb': g['home_qb_name'], 'team': g['home_team'], 'opponent': g['away_team'], 'week': wk})
                            if pd.notna(g.get('away_qb_name')):
                                matchups_opt_comp.append({'qb': g['away_qb_name'], 'team': g['away_team'], 'opponent': g['home_team'], 'week': wk})

                    st.caption(f"Testing {len(blend_options_comp)} CPOE blend weights across {len(matchups_opt_comp)} QB-weeks ({len(train_weeks_comp)} weeks). This runs Attempts internally for every QB too, so it'll take roughly 2x as long as the Attempts-only optimizer. All 5 already-validated pieces stay active in every combination.")
                    progress_bar_comp_opt = st.progress(0)
                    status_text_comp_opt = st.empty()
                    combo_results_comp = []

                    for ci, bopt in enumerate(blend_options_comp):
                        status_text_comp_opt.text(f"Testing cpoe_blend_weight={bopt} ({ci+1} of {len(blend_options_comp)})")
                        progress_bar_comp_opt.progress((ci + 1) / len(blend_options_comp))
                        errors = []
                        for m in matchups_opt_comp:
                            result = run_nfl_pass_completions_projection(
                                m['qb'], m['team'], m['opponent'], int(opt_train_season_comp), as_of_week=m['week'],
                                cpoe_blend_weight=bopt,
                            )
                            if not result:
                                continue
                            actual_row = actual_stats_opt_comp[(actual_stats_opt_comp['player_display_name'] == m['qb']) & (actual_stats_opt_comp['week'] == m['week']) & (actual_stats_opt_comp['position'] == 'QB')]
                            if actual_row.empty:
                                continue
                            errors.append(abs(result['projection'] - actual_row['completions'].iloc[0]))
                        if errors:
                            combo_results_comp.append({
                                'CPOE Blend Weight': bopt,
                                'MAE': round(sum(errors) / len(errors), 3), 'N': len(errors),
                            })

                    combo_df_comp = pd.DataFrame(combo_results_comp).sort_values('MAE')
                    st.session_state['comp_optimizer_results'] = combo_df_comp
                    st.session_state['comp_optimizer_train_season'] = opt_train_season_comp
                    st.session_state['comp_optimizer_weeks'] = train_weeks_comp
                    status_text_comp_opt.text(f"✅ Done! Tested {len(blend_options_comp)} combinations.")
                    progress_bar_comp_opt.progress(1.0)
                except Exception as e:
                    st.error(f"Real error: {e}")
                    import traceback
                    st.code(traceback.format_exc())

        if 'comp_optimizer_results' in st.session_state:
            combo_df_comp = st.session_state['comp_optimizer_results']
            st.write(f"**CPOE blend weights tested (trained on {st.session_state.get('comp_optimizer_train_season', '')}), sorted best to worst:**")
            st.dataframe(combo_df_comp, use_container_width=True)

            best_comp = combo_df_comp.iloc[0]
            st.success(f"Best on training season: MAE {best_comp['MAE']} at cpoe_blend_weight={best_comp['CPOE Blend Weight']}")

            if st.button("✅ Validate Best Combination on the OTHER season", key="comp_opt_validate", use_container_width=True):
                validate_season_comp = "2025" if st.session_state.get('comp_optimizer_train_season') == "2024" else "2024"
                val_weeks_comp = st.session_state.get('comp_optimizer_weeks', list(range(int(opt_week_start_comp), int(opt_week_end_comp) + 1)))
                with st.spinner(f"Validating against {validate_season_comp} (same week range)..."):
                    try:
                        schedules_val_comp = get_nfl_schedules([int(validate_season_comp)])
                        actual_stats_val_comp = get_nfl_player_stats([int(validate_season_comp)])
                        matchups_val_comp = []
                        for wk in val_weeks_comp:
                            week_games = schedules_val_comp[schedules_val_comp['week'] == wk]
                            for _, g in week_games.iterrows():
                                if pd.notna(g.get('home_qb_name')):
                                    matchups_val_comp.append({'qb': g['home_qb_name'], 'team': g['home_team'], 'opponent': g['away_team'], 'week': wk})
                                if pd.notna(g.get('away_qb_name')):
                                    matchups_val_comp.append({'qb': g['away_qb_name'], 'team': g['away_team'], 'opponent': g['home_team'], 'week': wk})

                        val_errors_new_comp = []
                        val_errors_old_comp = []
                        for m in matchups_val_comp:
                            result_new = run_nfl_pass_completions_projection(
                                m['qb'], m['team'], m['opponent'], int(validate_season_comp), as_of_week=m['week'],
                                cpoe_blend_weight=best_comp['CPOE Blend Weight'],
                            )
                            result_old = run_nfl_pass_completions_projection(m['qb'], m['team'], m['opponent'], int(validate_season_comp), as_of_week=m['week'])
                            actual_row = actual_stats_val_comp[(actual_stats_val_comp['player_display_name'] == m['qb']) & (actual_stats_val_comp['week'] == m['week']) & (actual_stats_val_comp['position'] == 'QB')]
                            if actual_row.empty:
                                continue
                            actual_val = actual_row['completions'].iloc[0]
                            if result_new:
                                val_errors_new_comp.append(abs(result_new['projection'] - actual_val))
                            if result_old:
                                val_errors_old_comp.append(abs(result_old['projection'] - actual_val))

                        new_mae_comp = round(sum(val_errors_new_comp) / len(val_errors_new_comp), 3) if val_errors_new_comp else None
                        old_mae_comp = round(sum(val_errors_old_comp) / len(val_errors_old_comp), 3) if val_errors_old_comp else None
                        st.write(f"**On {validate_season_comp} (held-out, same week range):**")
                        vcol1c, vcol2c = st.columns(2)
                        vcol1c.metric("Current defaults MAE", old_mae_comp)
                        vcol2c.metric("New combination MAE", new_mae_comp, delta=round(new_mae_comp - old_mae_comp, 3) if new_mae_comp and old_mae_comp else None, delta_color="inverse")
                        if new_mae_comp and old_mae_comp:
                            if new_mae_comp < old_mae_comp:
                                st.success("✅ The new combination genuinely improves on the held-out season too — real evidence, not just overfitting to the training season.")
                            else:
                                st.warning("⚠️ The new combination does NOT improve (or is worse) on the held-out season — this looks like overfitting to the training season's noise. Don't lock these values in.")
                    except Exception as e:
                        st.error(f"Real error: {e}")
                        import traceback
                        st.code(traceback.format_exc())

    elif backtest_sport == "NFL Receptions":
        st.caption("Full error decomposition, same discipline as Completions. This model has ZERO backtest history until you run this for the first time — no corrections have been attempted yet, everything below is genuinely untested.")
        rec_model_choice = st.radio(
            "Which architecture to test",
            ["Model A — Attempts → Target Share → Catch Rate", "Model B — Completions → Completion Share", "Both — common-sample comparison"],
            key="rec_model_choice",
            help="A genuine, unresolved architectural question per external review — neither is assumed correct. 'Both' runs A and B on the EXACT same player-games in one pass and reports common-sample MAE — the fairest real comparison, since neither model can improve its MAE just by skipping harder cases the other model handled."
        )
        st.caption("Model A uses target_share x catch_rate as two separate stages, built on the raw Attempts model. Model B uses a receiver's direct share of team COMPLETIONS, built on the more-validated Completions model. Per external review: don't compare each model only on the rows it successfully projects — use 'Both' for the fair, common-sample test.")
        backtest_season_rec = st.selectbox("Season", ["2025", "2024", "2023"], key="backtest_season_rec")
        col_rwk1, col_rwk2 = st.columns(2)
        with col_rwk1:
            backtest_week_start_rec = st.number_input("Start week", min_value=1, max_value=18, value=1, key="backtest_week_start_rec")
        with col_rwk2:
            backtest_week_end_rec = st.number_input("End week", min_value=1, max_value=18, value=18, key="backtest_week_end_rec")

        st.write("**Testable parameters** (all genuinely untested — this is the model's first real backtest)")
        col_rp1, col_rp2 = st.columns(2)
        with col_rp1:
            rec_weighting = st.selectbox("Target share weighting (Model A only)", ["target_weighted", "equal"], key="rec_weighting_test")
            rec_bridge = st.selectbox("Bridge schedule", ["attempts", "slow_fade", "medium_fade"], key="rec_bridge_test")
        with col_rp2:
            rec_team_mult = st.slider("Team-change prior retention", 0.0, 1.0, 0.0, 0.05, key="rec_team_mult_test", help="Fraction of scheduled prior-season weight RETAINED after a team change. 0.0 = fully discarded.")
            rec_min_targets = st.number_input("Min targets threshold (0 = no filtering, per real fix — was defaulting to 2, which created survivorship bias)", min_value=0, max_value=5, value=0, key="rec_min_targets_test")

        rec_use_opp_factor = st.checkbox("Use opponent factor (Model A only)", value=False, key="rec_use_opp_factor_test", help="Defaults to OFF now, per external review — the fair comparison should be the default behavior, not something a tester has to remember. Model B has no opponent factor at all, so turning this on confounds any A-vs-B comparison (architecture + extra feature vs. architecture alone) unless deliberately testing the opponent factor as its own separate experiment.")

        accumulate_rec = st.checkbox("➕ Accumulate — add to existing results instead of replacing", key="rec_backtest_accumulate")
        debug_rec = st.checkbox("🔧 Show real errors (debug)", key="rec_backtest_debug")

        col_run_rec, col_clear_rec = st.columns([3, 1])
        with col_clear_rec:
            if st.button("🗑️ Clear All", key="rec_clear_all", use_container_width=True):
                st.session_state['rec_backtest_results'] = []
                st.session_state['rec_common_sample_results'] = []
                st.session_state['_receptions_targets_missing_log'] = []
                st.rerun()
        with col_run_rec:
            run_rec_clicked = st.button("🔍 Load Week(s) & Run Projections", key="rec_run_button", use_container_width=True)

        if run_rec_clicked:
            st.session_state['_nfl_debug_mode'] = debug_rec
            weeks_to_test_rec = list(range(int(backtest_week_start_rec), int(backtest_week_end_rec) + 1))
            with st.spinner(f"Pulling {len(weeks_to_test_rec)} week(s) of games..."):
                try:
                    schedules_rec = get_nfl_schedules([int(backtest_season_rec)])
                    weekly_stats_rec = get_nfl_player_stats([int(backtest_season_rec)])
                    results_rec = list(st.session_state.get('rec_backtest_results', [])) if accumulate_rec else []
                    skipped_rec = []
                    progress_bar_rec = st.progress(0)
                    status_text_rec = st.empty()

                    # Building the test set: unlike QB models, there's no
                    # single "starter" per team — iterate every WR/TE who
                    # actually had a real, meaningful game (targets >=
                    # the threshold) that week, using their real team's
                    # real opponent and real starting QB from the schedule.
                    matchups_rec = []
                    for wk in weeks_to_test_rec:
                        week_games = schedules_rec[schedules_rec['week'] == wk]
                        wr_te_week = weekly_stats_rec[(weekly_stats_rec['week'] == wk) & (weekly_stats_rec['position'].isin(RECEPTION_POSITIONS))]
                        if 'season_type' in wr_te_week.columns:
                            wr_te_week = wr_te_week[wr_te_week['season_type'] == 'REG']
                        for _, g in week_games.iterrows():
                            for side_team, opp_team, qb_col in [(g['home_team'], g['away_team'], 'home_qb_name'), (g['away_team'], g['home_team'], 'away_qb_name')]:
                                if pd.isna(g.get(qb_col)):
                                    continue
                                team_players = wr_te_week[wr_te_week['team'] == side_team]
                                for _, prow in team_players.iterrows():
                                    targets_val = pd.to_numeric(prow.get('targets', 0), errors='coerce')
                                    if pd.isna(targets_val) or targets_val < rec_min_targets:
                                        continue
                                    matchups_rec.append({
                                        'player': prow['player_display_name'], 'team': side_team, 'opponent': opp_team,
                                        'qb': g[qb_col], 'week': wk, 'position': prow.get('position'),
                                    })

                    common_results_rec = []
                    for i, m in enumerate(matchups_rec):
                        status_text_rec.text(f"Week {m['week']}: {m['player']} ({i+1} of {len(matchups_rec)})")
                        progress_bar_rec.progress((i+1) / len(matchups_rec))

                        actual_row = weekly_stats_rec[(weekly_stats_rec['player_display_name'] == m['player']) & (weekly_stats_rec['week'] == m['week']) & (weekly_stats_rec['position'].isin(RECEPTION_POSITIONS))]
                        if actual_row.empty:
                            skipped_rec.append({'Player': m['player'], 'Week': m['week'], 'Reason': "No stats row found"})
                            continue
                        actual_targets = pd.to_numeric(actual_row['targets'].iloc[0], errors='coerce')
                        actual_receptions = pd.to_numeric(actual_row['receptions'].iloc[0], errors='coerce')
                        if pd.isna(actual_targets) or actual_targets <= 0:
                            skipped_rec.append({'Player': m['player'], 'Week': m['week'], 'Reason': "Zero actual targets"})
                            continue

                        if rec_model_choice.startswith("Both"):
                            # Real fix (per external review) — do NOT
                            # compare each model only on the rows it
                            # successfully projects, since one model
                            # could improve its MAE simply by skipping
                            # harder cases. Run BOTH on the exact same
                            # matchup, track each model's own result
                            # (or None) separately, then compute
                            # common-sample MAE only on rows where BOTH
                            # succeeded — the fairest real comparison.
                            try:
                                result_a = run_nfl_receptions_projection(
                                    m['player'], m['team'], m['opponent'], m['qb'], int(backtest_season_rec), as_of_week=m['week'],
                                    target_share_weighting=rec_weighting, bridge_schedule=rec_bridge,
                                    team_change_prior_retention=rec_team_mult, min_targets=rec_min_targets,
                                    use_opponent_factor=rec_use_opp_factor,
                                )
                            except Exception:
                                result_a = None
                            try:
                                result_b = run_nfl_receptions_model_b_projection(
                                    m['player'], m['team'], m['opponent'], m['qb'], int(backtest_season_rec), as_of_week=m['week'],
                                    bridge_schedule=rec_bridge, team_change_prior_retention=rec_team_mult, min_targets=rec_min_targets,
                                )
                            except Exception:
                                result_b = None

                            common_results_rec.append({
                                'Player': m['player'], 'Week': m['week'], 'Matchup': f"{m['opponent']} @ {m['team']}",
                                'Position': m.get('position'), 'Actual Receptions': actual_receptions,
                                'A Projection': result_a['projection'] if result_a else None,
                                'A Error': round(abs(result_a['projection'] - actual_receptions), 1) if result_a else None,
                                'B Projection': result_b['projection'] if result_b else None,
                                'B Error': round(abs(result_b['projection'] - actual_receptions), 1) if result_b else None,
                                'Both Succeeded': result_a is not None and result_b is not None,
                            })
                            continue

                        try:
                            if rec_model_choice.startswith("Model A"):
                                result = run_nfl_receptions_projection(
                                    m['player'], m['team'], m['opponent'], m['qb'], int(backtest_season_rec), as_of_week=m['week'],
                                    target_share_weighting=rec_weighting, bridge_schedule=rec_bridge,
                                    team_change_prior_retention=rec_team_mult, min_targets=rec_min_targets,
                                    use_opponent_factor=rec_use_opp_factor,
                                )
                            else:
                                result = run_nfl_receptions_model_b_projection(
                                    m['player'], m['team'], m['opponent'], m['qb'], int(backtest_season_rec), as_of_week=m['week'],
                                    bridge_schedule=rec_bridge, team_change_prior_retention=rec_team_mult, min_targets=rec_min_targets,
                                )
                        except Exception as e:
                            skipped_rec.append({'Player': m['player'], 'Week': m['week'], 'Reason': f'Exception: {e}'})
                            continue
                        if not result:
                            skipped_rec.append({'Player': m['player'], 'Week': m['week'], 'Reason': "Insufficient history or zero actual targets"})
                            continue

                        projected_receptions = result['projection']
                        row_data = {
                            'Player': m['player'], 'Week': m['week'], 'Matchup': f"{m['opponent']} @ {m['team']}",
                            'Position': m.get('position'), 'Model': result.get('model', 'A_target_share'),
                            'Proj Receptions': projected_receptions, 'Actual Receptions': actual_receptions,
                            'Receptions Error': round(abs(projected_receptions - actual_receptions), 1),
                            'Signed Residual': round(actual_receptions - projected_receptions, 1),
                            'Confidence Tier': result.get('confidence_tier'),
                            'Share CV': result.get('target_share_cv', result.get('completion_share_cv')),
                            'Games Used': result.get('games_used'),
                        }

                        if rec_model_choice.startswith("Model A"):
                            # Model A's real decomposition: targets stage vs catch-rate stage.
                            actual_catch_rate = actual_receptions / actual_targets
                            projected_targets = result['projected_targets']
                            projected_catch_rate = result['projected_catch_rate']
                            oracle_volume_rec = actual_targets * projected_catch_rate
                            oracle_efficiency_rec = projected_targets * actual_catch_rate
                            row_data.update({
                                'Proj Targets': projected_targets, 'Actual Targets': actual_targets,
                                'Targets Error': round(abs(projected_targets - actual_targets), 1),
                                'Proj Catch Rate': round(projected_catch_rate, 3), 'Actual Catch Rate': round(actual_catch_rate, 3),
                                'Catch Rate Error': round(abs(projected_catch_rate - actual_catch_rate), 3),
                                'Oracle Volume Error': round(abs(oracle_volume_rec - actual_receptions), 1),
                                'Oracle Efficiency Error': round(abs(oracle_efficiency_rec - actual_receptions), 1),
                            })
                        else:
                            # Model B's own real oracle decomposition
                            # (per external review — Model B needs the
                            # same diagnostic power Model A already has,
                            # not a weaker comparison). Needs the
                            # ACTUAL team completions for this specific
                            # game to compute actual_completion_share —
                            # looked up directly from the QB rows already
                            # loaded for this backtest, same aggregation
                            # get_nfl_team_game_completions itself uses.
                            actual_team_completions_rows = weekly_stats_rec[(weekly_stats_rec['team'] == m['team']) & (weekly_stats_rec['week'] == m['week']) & (weekly_stats_rec['position'] == 'QB')]
                            actual_team_completions = pd.to_numeric(actual_team_completions_rows['completions'], errors='coerce').sum() if not actual_team_completions_rows.empty else None
                            projected_team_completions = result.get('projected_team_completions')
                            projected_completion_share = result.get('projected_completion_share')
                            row_data.update({
                                'Proj Team Completions': projected_team_completions,
                                'Actual Team Completions': actual_team_completions,
                                'Proj Completion Share': round(projected_completion_share, 3) if projected_completion_share is not None else None,
                            })
                            if actual_team_completions is not None and actual_team_completions > 0:
                                actual_completion_share = actual_receptions / actual_team_completions
                                oracle_completions_rec = actual_team_completions * projected_completion_share
                                oracle_share_rec = projected_team_completions * actual_completion_share
                                row_data.update({
                                    'Team Completions Error': round(abs(projected_team_completions - actual_team_completions), 1),
                                    'Actual Completion Share': round(actual_completion_share, 3),
                                    'Completion Share Error': round(abs(projected_completion_share - actual_completion_share), 3),
                                    'Oracle Completions Error': round(abs(oracle_completions_rec - actual_receptions), 1),
                                    'Oracle Share Error': round(abs(oracle_share_rec - actual_receptions), 1),
                                })

                        results_rec.append(row_data)
                    st.session_state['rec_backtest_results'] = results_rec
                    st.session_state['rec_common_sample_results'] = common_results_rec
                    st.session_state['rec_backtest_skipped'] = skipped_rec
                    status_text_rec.text(f"✅ Done! {len(results_rec)} total projections, {len(common_results_rec)} common-sample rows, {len(skipped_rec)} skipped.")
                    progress_bar_rec.progress(1.0)
                except Exception as e:
                    st.error(f"Real error: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                finally:
                    st.session_state['_nfl_debug_mode'] = False

        if 'rec_common_sample_results' in st.session_state and st.session_state['rec_common_sample_results']:
            common_df = pd.DataFrame(st.session_state['rec_common_sample_results'])
            st.markdown("---")
            st.subheader("⚖️ Common-Sample A vs. B Comparison")
            st.caption("The fairest real comparison, per external review — neither model can improve its MAE just by skipping harder cases the other model handled. Coverage and each model's own MAE are shown too, since a model that projects fewer players isn't automatically better just because its own MAE looks smaller.")
            st.dataframe(common_df, use_container_width=True)

            total_rows = len(common_df)
            a_covered = common_df['A Projection'].notna().sum()
            b_covered = common_df['B Projection'].notna().sum()
            both_covered = common_df['Both Succeeded'].sum()

            col_cov1, col_cov2, col_cov3 = st.columns(3)
            col_cov1.metric("Model A coverage", f"{a_covered}/{total_rows}", help="How many player-games Model A successfully projected")
            col_cov2.metric("Model B coverage", f"{b_covered}/{total_rows}", help="How many player-games Model B successfully projected")
            col_cov3.metric("Common sample", f"{both_covered}/{total_rows}", help="Rows where BOTH models succeeded — this is the fair comparison set")

            col_mae1, col_mae2 = st.columns(2)
            a_own_mae = round(common_df['A Error'].mean(), 2) if a_covered > 0 else None
            b_own_mae = round(common_df['B Error'].mean(), 2) if b_covered > 0 else None
            col_mae1.metric("Model A MAE (its own coverage)", a_own_mae)
            col_mae2.metric("Model B MAE (its own coverage)", b_own_mae)

            common_only = common_df[common_df['Both Succeeded']]
            if not common_only.empty:
                a_common_mae = round(common_only['A Error'].mean(), 2)
                b_common_mae = round(common_only['B Error'].mean(), 2)
                st.write(f"**Common-sample MAE ({len(common_only)} rows both models projected):**")
                col_cmae1, col_cmae2 = st.columns(2)
                col_cmae1.metric("Model A", a_common_mae)
                col_cmae2.metric("Model B", b_common_mae)
                if a_common_mae < b_common_mae:
                    st.success(f"On the fair, common sample, Model A wins ({a_common_mae} vs {b_common_mae}).")
                elif b_common_mae < a_common_mae:
                    st.success(f"On the fair, common sample, Model B wins ({b_common_mae} vs {a_common_mae}).")
                else:
                    st.info("Dead even on the common sample.")

                if 'Position' in common_only.columns:
                    st.write("**Common-sample MAE by Position**")
                    pos_compare = common_only.groupby('Position').apply(lambda g: pd.Series({'A MAE': round(g['A Error'].mean(), 2), 'B MAE': round(g['B Error'].mean(), 2), 'N': len(g)})).reset_index()
                    st.dataframe(pos_compare, use_container_width=True)
            else:
                st.warning("No rows where both models succeeded — can't compute a common-sample MAE. Check coverage above for why.")

        if 'rec_backtest_results' in st.session_state and st.session_state['rec_backtest_results']:
            rec_df = pd.DataFrame(st.session_state['rec_backtest_results'])
            st.dataframe(rec_df, use_container_width=True)

            st.markdown("---")
            receptions_mae_rec = round(rec_df['Receptions Error'].mean(), 2)
            model_used_rec = rec_df['Model'].iloc[0] if 'Model' in rec_df.columns and not rec_df.empty else 'unknown'
            st.subheader(f"📊 Receptions MAE — {model_used_rec} — {receptions_mae_rec}")
            st.caption("Run the OTHER model on the same season/weeks and compare this number directly — that's the real test of which architecture actually predicts better, not which one sounds more elegant.")

            if 'Targets Error' in rec_df.columns:
                st.write("**Model A's full decomposition** (Targets stage vs. Catch Rate stage)")
                targets_mae_rec = round(rec_df['Targets Error'].mean(), 2)
                catch_rate_mae_rec = round(rec_df['Catch Rate Error'].mean(), 4)
                oracle_volume_mae_rec = round(rec_df['Oracle Volume Error'].mean(), 2)
                oracle_efficiency_mae_rec = round(rec_df['Oracle Efficiency Error'].mean(), 2)

                col_re1, col_re2, col_re3 = st.columns(3)
                col_re1.metric("Targets MAE", targets_mae_rec, help="Error in the projected target volume (team attempts x target share)")
                col_re2.metric("Catch Rate MAE", catch_rate_mae_rec, help="Error in the catch-rate projection specifically")
                col_re3.metric("Receptions MAE", receptions_mae_rec, help="The real, final, blended error")

                col_ro1, col_ro2 = st.columns(2)
                col_ro1.metric("Oracle: Actual Targets x Proj Catch Rate", oracle_volume_mae_rec, help="If targets were known PERFECTLY, this is how good the catch-rate model alone would be")
                col_ro2.metric("Oracle: Proj Targets x Actual Catch Rate", oracle_efficiency_mae_rec, help="If catch rate were known PERFECTLY, this shows how much error comes from the targets/share stage alone")
                if oracle_volume_mae_rec < oracle_efficiency_mae_rec:
                    st.caption(f"**Bottleneck read:** catch-rate error ({oracle_volume_mae_rec}) is smaller than targets-stage error ({oracle_efficiency_mae_rec}) — the TARGET SHARE / VOLUME projection is contributing more to the final error. Improving Receptions further likely means improving target-share estimation, not catch-rate logic.")
                else:
                    st.caption(f"**Bottleneck read:** targets-stage error ({oracle_efficiency_mae_rec}) is smaller than catch-rate error ({oracle_volume_mae_rec}) — the CATCH-RATE projection is contributing more to the final error. Worth focusing improvement efforts on catch-rate specifically.")
            else:
                st.write("**Model B's full decomposition** (Team Completions stage vs. Completion Share stage) — its own real oracle diagnostics, per external review, matching the same diagnostic power Model A already has.")
                if 'Team Completions Error' in rec_df.columns:
                    team_comp_mae_rec = round(rec_df['Team Completions Error'].mean(), 2)
                    comp_share_mae_rec = round(rec_df['Completion Share Error'].mean(), 4)
                    oracle_completions_mae_rec = round(rec_df['Oracle Completions Error'].mean(), 2)
                    oracle_share_mae_rec = round(rec_df['Oracle Share Error'].mean(), 2)

                    col_rb1, col_rb2, col_rb3 = st.columns(3)
                    col_rb1.metric("Team Completions MAE", team_comp_mae_rec, help="Error in the projected team completions volume (from the Completions model)")
                    col_rb2.metric("Completion Share MAE", comp_share_mae_rec, help="Error in the completion-share projection specifically")
                    col_rb3.metric("Receptions MAE", receptions_mae_rec, help="The real, final, blended error")

                    col_rbo1, col_rbo2 = st.columns(2)
                    col_rbo1.metric("Oracle: Actual Team Completions x Proj Share", oracle_completions_mae_rec, help="If team completions were known PERFECTLY, this is how good the completion-share model alone would be")
                    col_rbo2.metric("Oracle: Proj Team Completions x Actual Share", oracle_share_mae_rec, help="If completion share were known PERFECTLY, this shows how much error comes from the upstream Completions model alone")
                    if oracle_completions_mae_rec < oracle_share_mae_rec:
                        st.caption(f"**Bottleneck read:** completion-share error ({oracle_completions_mae_rec}) is smaller than team-completions-stage error ({oracle_share_mae_rec}) — the upstream COMPLETIONS projection is contributing more to the final error. Improving Model B further likely means improving the Completions model, not completion-share estimation.")
                    else:
                        st.caption(f"**Bottleneck read:** team-completions-stage error ({oracle_share_mae_rec}) is smaller than completion-share error ({oracle_completions_mae_rec}) — the COMPLETION-SHARE projection is contributing more to the final error. Worth focusing improvement efforts on completion-share estimation specifically.")
                else:
                    st.caption("Oracle diagnostics unavailable for this result set — actual team completions couldn't be matched for some or all rows (check that weekly QB stats were available for the tested weeks).")

            st.markdown("---")
            st.write("**Receptions MAE by Position**")
            st.caption("A model can look good overall while performing poorly for one position specifically — worth checking before trusting the blended number, especially now that RBs are included alongside WR/TE.")
            if 'Position' in rec_df.columns:
                position_summary_rec = rec_df.groupby('Position').agg(Predictions=('Receptions Error', 'count'), MAE=('Receptions Error', 'mean')).reset_index()
                position_summary_rec['MAE'] = position_summary_rec['MAE'].round(2)
                st.dataframe(position_summary_rec.sort_values('MAE'), use_container_width=True)

            st.markdown("---")
            st.write("**Receptions MAE + Bias by Confidence Tier**")
            st.caption("Bias (signed: Actual - Projection) distinguishes a fixable systematic pattern from genuine noise — same check that found real, validated corrections for Completions.")
            tier_summary_rec = rec_df.groupby('Confidence Tier').agg(Predictions=('Receptions Error', 'count'), MAE=('Receptions Error', 'mean'), Bias=('Signed Residual', 'mean')).reset_index()
            tier_summary_rec['MAE'] = tier_summary_rec['MAE'].round(2)
            tier_summary_rec['Bias'] = tier_summary_rec['Bias'].round(2)
            st.dataframe(tier_summary_rec, use_container_width=True)

            if 'Share CV' in rec_df.columns and rec_df['Share CV'].notna().any():
                st.markdown("---")
                st.subheader("🎯 Confidence Tier Recalibration")
                st.caption("A real, found problem — the Reliable tier's CV<0.20 threshold was copied directly from QB stats (Attempts/Completions), never validated for receivers specifically. Target share is naturally far more volatile week to week than QB attempt/completion volume (game script, other receivers' health, defensive scheme all move it around), so that threshold turned out to be far too strict — only ~0.75% of predictions were landing in Reliable, versus ~27% for Completions. This shows the REAL distribution of CV from this backtest, so new thresholds can be set based on actual data instead of reused guesses.")

                cv_data = rec_df['Share CV'].dropna()
                if len(cv_data) > 10:
                    col_cvd1, col_cvd2, col_cvd3, col_cvd4 = st.columns(4)
                    col_cvd1.metric("Median CV", round(cv_data.median(), 3))
                    col_cvd2.metric("25th percentile", round(cv_data.quantile(0.25), 3))
                    col_cvd3.metric("50th percentile", round(cv_data.quantile(0.50), 3))
                    col_cvd4.metric("75th percentile", round(cv_data.quantile(0.75), 3))

                    st.write("**Adjustable percentile split** — the 33rd/67th split gives a statistically even sample, but 'even' isn't necessarily 'correct.' A tighter, more exclusive Reliable tier (e.g. top 20%) may be more honest about which players are genuinely trustworthy, at the cost of a smaller sample. Test different splits directly.")
                    col_pct1, col_pct2 = st.columns(2)
                    with col_pct1:
                        reliable_pctile = st.slider("Reliable = bottom X% CV (most stable)", 10, 50, 33, 1, key="rec_reliable_pctile") / 100
                    with col_pct2:
                        volatile_pctile = st.slider("Volatile = top X% CV (least stable)", 10, 50, 33, 1, key="rec_volatile_pctile") / 100

                    suggested_reliable_cutoff = round(cv_data.quantile(reliable_pctile), 3)
                    suggested_volatile_cutoff = round(cv_data.quantile(1 - volatile_pctile), 3)
                    col_sug1, col_sug2 = st.columns(2)
                    col_sug1.metric("Suggested Reliable cutoff (CV <)", suggested_reliable_cutoff, help=f"Currently hardcoded at 0.20 — copied from QB stats, never validated for receivers")
                    col_sug2.metric("Suggested Volatile cutoff (CV >)", suggested_volatile_cutoff, help=f"Currently hardcoded at 0.35 — copied from QB stats, never validated for receivers")

                    # Show what the tier distribution WOULD look like with these new cutoffs
                    def _simulated_tier(cv):
                        if pd.isna(cv):
                            return None
                        if cv < suggested_reliable_cutoff:
                            return "🟢 Reliable (simulated)"
                        elif cv > suggested_volatile_cutoff:
                            return "🔴 Volatile (simulated)"
                        else:
                            return "🟠 Moderate (simulated)"
                    rec_df['Simulated Tier'] = rec_df['Share CV'].apply(_simulated_tier)
                    sim_summary = rec_df.dropna(subset=['Simulated Tier']).groupby('Simulated Tier').agg(
                        Predictions=('Receptions Error', 'count'), MAE=('Receptions Error', 'mean'),
                        Bias=('Signed Residual', 'mean'), **{'Avg Actual Receptions': ('Actual Receptions', 'mean')}
                    ).reset_index()
                    sim_summary['MAE'] = sim_summary['MAE'].round(2)
                    sim_summary['Bias'] = sim_summary['Bias'].round(2)
                    sim_summary['Avg Actual Receptions'] = sim_summary['Avg Actual Receptions'].round(2)
                    # Real test (per direct question raised while reviewing
                    # this) — is the MAE "inversion" explained by naturally
                    # higher-volume players landing in Reliable (a star WR1
                    # with a stable, low-CV target share also just has more
                    # receptions to be wrong about), rather than the model
                    # genuinely performing worse on them? MAE-as-%-of-volume
                    # answers this directly — if THIS reorders correctly
                    # (Reliable best, Volatile worst) even though raw MAE
                    # doesn't, that confirms it's a volume effect, not a
                    # real modeling problem.
                    sim_summary['MAE as % of Avg Volume'] = round((sim_summary['MAE'] / sim_summary['Avg Actual Receptions']) * 100, 1)
                    st.write("**What the tiers would look like with these suggested cutoffs (not yet applied to the actual model — for comparison only)**")
                    st.caption("Avg Actual Receptions and MAE-as-%-of-volume are included to test a real, specific hypothesis: a 'Reliable' player (stable, low-CV target share) is plausibly a high-volume WR1-type with naturally more receptions to be wrong about, while a 'Volatile' player is plausibly a low-volume role player with less room for error. If the raw MAE ordering looks inverted but the %-of-volume ordering looks correct (Reliable best, Volatile worst), that confirms this is a real volume effect, not the model actually performing worse on Reliable players.")
                    st.dataframe(sim_summary, use_container_width=True)
                else:
                    st.warning("Not enough CV data in this result set to compute reliable percentiles — run a larger backtest first.")

            st.markdown("---")
            st.subheader("🔍 Data Quality Diagnostics")

            # Missing-targets log (per external review — "just
            # transparency"). Logged via session_state during
            # get_wr_te_rows calls throughout this backtest run.
            missing_log = st.session_state.get('_receptions_targets_missing_log', [])
            total_missing = sum(entry['missing_count'] for entry in missing_log)
            st.write(f"**Targets originally missing:** {total_missing if total_missing else 0} row(s)" + (f" across {len(missing_log)} player-season(s)" if missing_log else ""))
            if missing_log:
                st.caption("If this number is effectively zero, the fillna(0) in get_wr_te_rows was never really doing anything meaningful. If it's a real, non-trivial count, that's worth a closer look — does missing genuinely mean zero targets, or did the provider just not report a value for that game?")
                st.dataframe(pd.DataFrame(missing_log), use_container_width=True)

            # team_targets_vs_attempts_difference — a validation tool,
            # not a modeling bug per external review, but worth checking
            # before drawing strong conclusions from Model A specifically.
            st.write("**team_targets vs. official team pass attempts**")
            st.caption("team_targets (summed from every real pass-catcher's targets per team-game) should generally track closely with official pass attempts (from play-by-play) — they're conceptually the same volume, just aggregated two different ways. A consistently small gap means the denominator used for Model A's target_share is trustworthy; a large or inconsistent one means the aggregation needs a closer look.")
            if st.button("Check team_targets vs. attempts", key="rec_targets_diagnostic_btn"):
                with st.spinner("Comparing team_targets against official attempts..."):
                    diag_df = get_team_targets_vs_attempts_diagnostic([int(backtest_season_rec)])
                    if diag_df.empty:
                        st.warning("Couldn't compute this diagnostic — one of the underlying aggregates came back empty.")
                    else:
                        col_d1, col_d2, col_d3 = st.columns(3)
                        col_d1.metric("Average gap", round(diag_df['target_attempt_gap'].mean(), 2))
                        col_d2.metric("Median gap", round(diag_df['target_attempt_gap'].median(), 2))
                        col_d3.metric("Max gap", round(diag_df['target_attempt_gap'].abs().max(), 2))
                        st.dataframe(diag_df.sort_values('target_attempt_gap', key=abs, ascending=False).head(20), use_container_width=True)

        if 'rec_backtest_skipped' in st.session_state and st.session_state['rec_backtest_skipped']:
            with st.expander(f"Skipped ({len(st.session_state['rec_backtest_skipped'])})"):
                st.dataframe(pd.DataFrame(st.session_state['rec_backtest_skipped']), use_container_width=True)

    else:
        backtest_season_nba = st.selectbox("Season", ["2025-26", "2024-25", "2023-24"], key="backtest_season_nba")
        is_assists = backtest_sport == "NBA Assists"
        max_players = st.number_input(
            "Max players to test", min_value=5, max_value=500, value=15, step=5,
            help="balldontlie is a real API with a documented rate limit, but a big slate still means many sequential requests — a run this large will genuinely take a while (each player is roughly 1-2 seconds plus retries). Keep it modest for a first test on a new date."
        )
        debug_this_run = st.checkbox("🔧 Show real errors instead of generic 'returned None' (debug)")

        if st.button("🔍 Load NBA Games & Run Projections", use_container_width=True):
            st.session_state['_nba_debug_mode'] = debug_this_run
            with st.spinner(f"Pulling NBA games for {backtest_date}..."):
                bdl_season = int(backtest_season_nba.split("-")[0])
                date_str = backtest_date.strftime('%Y-%m-%d')
                try:
                    box_rows_df = get_bdl_games_for_date(date_str)
                except Exception as e:
                    st.error(f"Failed to fetch games after retries — try again shortly. ({e})")
                    box_rows_df = pd.DataFrame()
                if box_rows_df.empty:
                    st.error("No NBA games found for that date (balldontlie)")
                else:
                    box_df = box_rows_df.head(int(max_players))
                    team_ids_map = get_bdl_team_ids()
                    id_to_name = {v: k for k, v in team_ids_map.items()}
                    # Supplement with team names pulled directly from this
                    # date's own box score data — the static team list can
                    # occasionally mismatch for recently-traded players, but
                    # every row's own 'team' object reliably has the correct
                    # current full_name.
                    for _, r in box_rows_df.iterrows():
                        t = r.get('team') or {}
                        if t.get('id') is not None and t.get('full_name'):
                            id_to_name.setdefault(t.get('id'), t.get('full_name'))
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results = []
                    skipped = []
                    total = len(box_df)
                    for i, row in box_df.iterrows():
                        status_text.text(f"Processing player {i+1} of {total}")
                        progress_bar.progress((i+1) / total)
                        player_info = row.get('player') or {}
                        player_name = f"{player_info.get('first_name', '')} {player_info.get('last_name', '')}".strip()
                        try:
                            actual_val = row.get('ast') if is_assists else row.get('pts')
                            if not player_name or actual_val is None:
                                skipped.append({'Player': player_name or 'Unknown', 'Reason': 'Missing name or box score stat in raw data'})
                                continue
                            minutes_this_game = bdl_parse_minutes(row.get('min'))
                            if minutes_this_game <= 0:
                                skipped.append({'Player': player_name, 'Reason': f"Didn't play (0 minutes) on {backtest_date} — excluded, not a fair test of scoring prediction"})
                                continue
                            team_info = row.get('team') or {}
                            game_info = row.get('game') or {}
                            team_id = team_info.get('id')
                            home_team_id = game_info.get('home_team_id')
                            visitor_team_id = game_info.get('visitor_team_id')
                            home_or_away = 'home' if home_team_id == team_id else 'away'
                            team_name = id_to_name.get(team_id, team_info.get('full_name', 'Unknown'))
                            opp_team_id = visitor_team_id if home_or_away == 'home' else home_team_id
                            opp_name = id_to_name.get(opp_team_id, 'Unknown')
                            home_name = team_name if home_or_away == 'home' else opp_name
                            away_name = opp_name if home_or_away == 'home' else team_name
                            opp_abbrev = nba_name_to_abbrev.get(opp_name, '')

                            # Real actual usage % for this specific game — a
                            # post-hoc comparison value only (not fed into the
                            # projection itself, so no leakage concern here —
                            # unlike the old pace override this replaced,
                            # which DID feed the completed game's own data
                            # into its own prediction. See July 2026 fix:
                            # the engine now computes pace internally using
                            # only games strictly before this date.
                            own_team_rows = box_rows_df[box_rows_df['team'].apply(lambda t: (t or {}).get('id')) == team_id]
                            actual_usage_pct = None
                            if not own_team_rows.empty:
                                team_fga_sum = pd.to_numeric(own_team_rows['fga'], errors='coerce').sum()
                                team_fta_sum = pd.to_numeric(own_team_rows['fta'], errors='coerce').sum()
                                team_oreb_sum = pd.to_numeric(own_team_rows['oreb'], errors='coerce').sum()
                                team_tov_sum = pd.to_numeric(own_team_rows['turnover'], errors='coerce').sum()
                                team_min_sum = sum(bdl_parse_minutes(m) for m in own_team_rows['min'])
                                team_poss_this_game = team_fga_sum + 0.44 * team_fta_sum - team_oreb_sum + team_tov_sum
                                player_fta_val = row.get('fta') or 0
                                player_tov_val = row.get('turnover') or 0
                                player_poss_this_game = (row.get('fga') or 0) + 0.44 * player_fta_val + player_tov_val
                                if team_poss_this_game > 0 and minutes_this_game > 0:
                                    actual_usage_pct = round((player_poss_this_game * (team_min_sum / 5)) / (minutes_this_game * team_poss_this_game) * 100, 1)

                            if is_assists:
                                result = run_nba_assists_projection(player_name, opp_abbrev, home_name, away_name, home_or_away, backtest_season_nba, as_of_date=datetime.combine(backtest_date, datetime.min.time()))
                            else:
                                result = run_nba_points_projection(player_name, opp_abbrev, home_name, away_name, home_or_away, backtest_season_nba, as_of_date=datetime.combine(backtest_date, datetime.min.time()))
                            time.sleep(1)
                            if not result:
                                try:
                                    check_df, check_id = get_bdl_player_game_log(player_name, bdl_season)
                                    if not check_id:
                                        reason = "No player ID resolved for this exact name"
                                    elif check_df.empty:
                                        reason = f"Player ID '{check_id}' resolved but game log came back empty"
                                    else:
                                        check_df['_active'] = check_df['min'].apply(bdl_parse_minutes) > 0
                                        check_df['_game_date'] = pd.to_datetime(check_df['game'].apply(lambda g: (g or {}).get('date')))
                                        before_date_df = check_df[check_df['_game_date'] < pd.Timestamp(backtest_date)]
                                        active_before = before_date_df['_active'].sum()
                                        active_total = check_df['_active'].sum()
                                        reason = f"Player ID '{check_id}' found — {active_before} active games BEFORE {backtest_date} (need 5), {active_total} active games all season"
                                except Exception as diag_e:
                                    reason = f"Diagnostic check itself failed: {diag_e}"
                                skipped.append({'Player': player_name, 'Reason': reason})
                            else:
                                error_val = round(abs(result['projection'] - actual_val), 1)
                                error_pct = round(error_val / actual_val * 100, 1) if actual_val > 0 else None
                                proj_min = result.get('expected_minutes')
                                min_error = round(minutes_this_game - proj_min, 1) if proj_min is not None else None
                                proj_fga = result.get('projected_fga')
                                actual_fga = row.get('fga')
                                fga_error = round(actual_fga - proj_fga, 1) if proj_fga is not None and actual_fga is not None else None
                                actual_fgm = row.get('fgm')
                                actual_fg_pct = round(actual_fgm / actual_fga * 100, 1) if actual_fga else None
                                results.append({
                                    'Player': player_name,
                                    'Matchup': f"{away_name} @ {home_name}",
                                    'Projection': result['projection'], 'Actual': actual_val,
                                    'Error': error_val, 'Error %': error_pct,
                                    'Tier': result['confidence_tier'],
                                    'Proj Min': proj_min, 'Actual Min': round(minutes_this_game, 1), 'Min Error': min_error,
                                    'Proj FGA': proj_fga, 'Actual FGA': actual_fga, 'FGA Error': fga_error,
                                    'Actual FG%': actual_fg_pct, 'Season FG%': result.get('season_fg_pct'),
                                    'Recent Touches/Min': result.get('recent_touches_per_min'),
                                    'Actual Usage %': actual_usage_pct,
                                    'Opp Pace': result.get('opp_pace'),
                                    'Pace Adj': result.get('pace_adj'),
                                })
                        except Exception as e:
                            skipped.append({'Player': player_name or 'Unknown', 'Reason': f'Exception: {e}'})
                            continue

                    # Second pass: retry players who failed for reasons that
                    # can plausibly be transient API flakiness rather than a
                    # real fact about the player. Originally just player-ID
                    # resolution / empty game log failures — expanded (July
                    # 2026) after directly proving a player showing "20
                    # active games (need 5)" can STILL be a transient
                    # failure: re-running that exact player in isolation
                    # worked perfectly and produced a real projection. Only
                    # retries "insufficient games" cases where the
                    # diagnostic's OWN reported count actually contradicts
                    # the None result (>=5) — a genuine "2 games, need 5"
                    # skip is a real fact retrying can't change, so those
                    # are deliberately left alone.
                    import re
                    def _is_contradictory_insufficient_games(reason):
                        m = re.search(r'(\d+) active games BEFORE .+ \(need 5\)', reason)
                        return bool(m) and int(m.group(1)) >= 5

                    retry_candidates = [
                        s for s in skipped
                        if "No player ID resolved" in s['Reason']
                        or "game log came back empty" in s['Reason']
                        or _is_contradictory_insufficient_games(s['Reason'])
                    ]
                    if retry_candidates:
                        status_text.text(f"Retrying {len(retry_candidates)} players who may have hit transient API flakiness...")
                        get_bdl_player_id.clear()  # clear ONLY this function's cache, not the whole app's
                        for s in retry_candidates:
                            retry_name = s['Player']
                            retry_row = None
                            for _, r in box_df.iterrows():
                                pinfo = r.get('player') or {}
                                if f"{pinfo.get('first_name', '')} {pinfo.get('last_name', '')}".strip() == retry_name:
                                    retry_row = r
                                    break
                            if retry_row is None:
                                continue
                            try:
                                r_team_info = retry_row.get('team') or {}
                                r_game_info = retry_row.get('game') or {}
                                r_team_id = r_team_info.get('id')
                                r_home_team_id = r_game_info.get('home_team_id')
                                r_visitor_team_id = r_game_info.get('visitor_team_id')
                                r_home_or_away = 'home' if r_home_team_id == r_team_id else 'away'
                                r_team_name = id_to_name.get(r_team_id, r_team_info.get('full_name', 'Unknown'))
                                r_opp_team_id = r_visitor_team_id if r_home_or_away == 'home' else r_home_team_id
                                r_opp_name = id_to_name.get(r_opp_team_id, 'Unknown')
                                r_home_name = r_team_name if r_home_or_away == 'home' else r_opp_name
                                r_away_name = r_opp_name if r_home_or_away == 'home' else r_team_name
                                r_opp_abbrev = nba_name_to_abbrev.get(r_opp_name, '')
                                if is_assists:
                                    retry_result = run_nba_assists_projection(retry_name, r_opp_abbrev, r_home_name, r_away_name, r_home_or_away, backtest_season_nba, as_of_date=datetime.combine(backtest_date, datetime.min.time()))
                                else:
                                    retry_result = run_nba_points_projection(retry_name, r_opp_abbrev, r_home_name, r_away_name, r_home_or_away, backtest_season_nba, as_of_date=datetime.combine(backtest_date, datetime.min.time()))
                                if retry_result:
                                    r_actual_val = retry_row.get('ast') if is_assists else retry_row.get('pts')
                                    r_error_val = round(abs(retry_result['projection'] - r_actual_val), 1)
                                    r_error_pct = round(r_error_val / r_actual_val * 100, 1) if r_actual_val > 0 else None
                                    r_minutes_this_game = bdl_parse_minutes(retry_row.get('min'))
                                    r_proj_min = retry_result.get('expected_minutes')
                                    r_min_error = round(r_minutes_this_game - r_proj_min, 1) if r_proj_min is not None else None
                                    r_proj_fga = retry_result.get('projected_fga')
                                    r_actual_fga = retry_row.get('fga')
                                    r_fga_error = round(r_actual_fga - r_proj_fga, 1) if r_proj_fga is not None and r_actual_fga is not None else None
                                    r_actual_fgm = retry_row.get('fgm')
                                    r_actual_fg_pct = round(r_actual_fgm / r_actual_fga * 100, 1) if r_actual_fga else None
                                    r_own_team_rows = box_rows_df[box_rows_df['team'].apply(lambda t: (t or {}).get('id')) == r_team_id]
                                    r_actual_usage_pct = None
                                    if not r_own_team_rows.empty:
                                        rt_fga_sum = pd.to_numeric(r_own_team_rows['fga'], errors='coerce').sum()
                                        rt_fta_sum = pd.to_numeric(r_own_team_rows['fta'], errors='coerce').sum()
                                        rt_oreb_sum = pd.to_numeric(r_own_team_rows['oreb'], errors='coerce').sum()
                                        rt_tov_sum = pd.to_numeric(r_own_team_rows['turnover'], errors='coerce').sum()
                                        rt_min_sum = sum(bdl_parse_minutes(m) for m in r_own_team_rows['min'])
                                        rt_poss_this_game = rt_fga_sum + 0.44 * rt_fta_sum - rt_oreb_sum + rt_tov_sum
                                        r_player_fta_val = retry_row.get('fta') or 0
                                        r_player_tov_val = retry_row.get('turnover') or 0
                                        r_player_poss_this_game = (retry_row.get('fga') or 0) + 0.44 * r_player_fta_val + r_player_tov_val
                                        if rt_poss_this_game > 0 and r_minutes_this_game > 0:
                                            r_actual_usage_pct = round((r_player_poss_this_game * (rt_min_sum / 5)) / (r_minutes_this_game * rt_poss_this_game) * 100, 1)
                                    results.append({
                                        'Player': retry_name, 'Matchup': f"{r_away_name} @ {r_home_name}",
                                        'Projection': retry_result['projection'], 'Actual': r_actual_val,
                                        'Error': r_error_val, 'Error %': r_error_pct,
                                        'Tier': retry_result['confidence_tier'],
                                        'Proj Min': r_proj_min, 'Actual Min': round(r_minutes_this_game, 1), 'Min Error': r_min_error,
                                        'Proj FGA': r_proj_fga, 'Actual FGA': r_actual_fga, 'FGA Error': r_fga_error,
                                        'Actual FG%': r_actual_fg_pct, 'Season FG%': retry_result.get('season_fg_pct'),
                                        'Recent Touches/Min': retry_result.get('recent_touches_per_min'),
                                        'Actual Usage %': r_actual_usage_pct,
                                        'Opp Pace': retry_result.get('opp_pace'), 'Pace Adj': retry_result.get('pace_adj'),
                                    })
                                    skipped.remove(s)
                            except Exception:
                                pass  # still failed on retry — leave it in skipped as-is
                            time.sleep(1)

                    st.session_state['backtest_results'] = results
                    st.session_state['backtest_skipped'] = skipped
                    st.session_state['backtest_date'] = backtest_date.strftime('%Y-%m-%d')
                    status_text.text(f"✅ Done! {len(results)} players projected, {len(skipped)} skipped.")
                    progress_bar.progress(1.0)
            st.session_state['_nba_debug_mode'] = False

    if st.session_state.get('backtest_skipped'):
        with st.expander(f"⚠️ {len(st.session_state['backtest_skipped'])} players skipped — see why"):
            st.dataframe(pd.DataFrame(st.session_state['backtest_skipped']), use_container_width=True)

    if 'backtest_results' in st.session_state and st.session_state['backtest_results']:
        st.markdown("---")
        st.subheader(f"📋 Results for {st.session_state.get('backtest_date', '')}")
        results_df = pd.DataFrame(st.session_state['backtest_results'])
        st.dataframe(results_df.sort_values('Error'), use_container_width=True)

        if backtest_sport in ("NBA Points", "NBA Assists") and 'Matchup' in results_df.columns:
            st.markdown("---")
            st.subheader("💰 Check Against Real Historical Sportsbook Lines")
            unique_games = results_df['Matchup'].nunique()
            st.caption(f"This is a genuinely different question than accuracy alone: did the model's recommended side (Over/Under vs. the ACTUAL sportsbook line, not just the true result) actually win? This uses real API quota — costs ~10 units per game, per The Odds API's historical pricing. **This test has {unique_games} unique game(s), so it would cost roughly {unique_games * 10} quota units.** Opt-in only — never runs automatically.")
            if st.button(f"Check Historical Lines (~{unique_games * 10} quota units)"):
                market_key = "player_assists" if backtest_sport == "NBA Assists" else "player_points"
                bt_date_str = st.session_state.get('backtest_date', '')
                with st.spinner("Fetching historical events and lines..."):
                    events = get_historical_nba_events_for_date(bt_date_str)
                    matchup_to_event = {}
                    for ev in events:
                        h, a = ev.get('home_team'), ev.get('away_team')
                        if h and a:
                            matchup_to_event[f"{a} @ {h}"] = ev.get('id')
                    all_lines = {}
                    checked_games = 0
                    for matchup in results_df['Matchup'].unique():
                        event_id = matchup_to_event.get(matchup)
                        if not event_id:
                            continue
                        game_lines = get_historical_prop_lines_for_game(event_id, market_key, bt_date_str)
                        all_lines.update(game_lines)
                        checked_games += 1
                        time.sleep(0.5)

                    def _line_lookup(pname):
                        return all_lines.get(pname)
                    results_df['Sportsbook Line'] = results_df['Player'].apply(_line_lookup)

                    def _model_side(row):
                        if pd.isna(row['Sportsbook Line']):
                            return None
                        return 'Over' if row['Projection'] > row['Sportsbook Line'] else ('Under' if row['Projection'] < row['Sportsbook Line'] else 'Push')

                    def _did_win(row):
                        if pd.isna(row['Sportsbook Line']) or row['Sportsbook Line'] is None:
                            return None
                        if row['Actual'] > row['Sportsbook Line']:
                            actual_side = 'Over'
                        elif row['Actual'] < row['Sportsbook Line']:
                            actual_side = 'Under'
                        else:
                            return 'Push'
                        model_side = _model_side(row)
                        if model_side in (None, 'Push'):
                            return None
                        return 'Win' if model_side == actual_side else 'Loss'

                    results_df['Model Side'] = results_df.apply(_model_side, axis=1)
                    results_df['Bet Result'] = results_df.apply(_did_win, axis=1)
                    matched = results_df['Sportsbook Line'].notna().sum()
                    st.success(f"✅ Checked {checked_games} game(s), matched real lines for {matched}/{len(results_df)} players.")
                    line_results_df = results_df[results_df['Sportsbook Line'].notna()][['Player', 'Matchup', 'Projection', 'Sportsbook Line', 'Actual', 'Model Side', 'Bet Result']]
                    st.dataframe(line_results_df, use_container_width=True)
                    graded = line_results_df[line_results_df['Bet Result'].isin(['Win', 'Loss'])]
                    if not graded.empty:
                        win_rate = round((graded['Bet Result'] == 'Win').mean() * 100, 1)
                        st.metric("Win rate vs. real historical lines", f"{win_rate}% ({len(graded)} graded bets)")
                        st.caption("A win rate meaningfully above ~52.4% (the standard -110 breakeven point) across a real sample would be a genuine signal of edge — though treat this cautiously until it holds up across many more dates, same as any other backtest metric here.")

                        result_counts = line_results_df['Bet Result'].fillna('No Bet/Push').value_counts()
                        st.bar_chart(result_counts)

                        st.caption("Projection vs. Actual result, colored by whether that bet would have won or lost — points sitting on the diagonal are perfect calls; the further off the line, the bigger the miss. Green = win, red = loss.")
                        chart_df = line_results_df[line_results_df['Bet Result'].isin(['Win', 'Loss'])].copy()
                        chart_df['Result Color'] = chart_df['Bet Result'].map({'Win': '#2ecc71', 'Loss': '#e74c3c'})
                        st.scatter_chart(chart_df, x='Projection', y='Actual', color='Result Color')

        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        col1.metric("Avg Error (MAE)", f"{round(results_df['Error'].mean(), 2)}")
        col2.metric("Best Projection", f"{results_df['Error'].min()} error")
        col3.metric("Worst Projection", f"{results_df['Error'].max()} error")
        if 'Tier' in results_df.columns:
            st.markdown("---")
            st.subheader("🎯 Accuracy by Confidence Tier")
            st.caption("Error % (Error ÷ Actual) is the fair comparison across players with very different scoring scales, but it can blow up to an extreme, meaningless number when a player scores 0-1 points — that's why the mean can look extreme in some samples. 'Within X pts' hit-rate columns are a scale-independent alternative that doesn't have that problem: what share of predictions landed within 2, 3, or 5 points of the real result, regardless of whether the player scored 3 or 30.")
            if 'Error %' in results_df.columns:
                tier_summary = results_df.groupby('Tier').agg(
                    Predictions=('Error', 'count'),
                    MAE=('Error', 'mean'),
                    **{'Mean Error %': ('Error %', 'mean'), 'Median Error %': ('Error %', 'median')}
                ).reset_index()
                tier_summary['MAE'] = tier_summary['MAE'].round(2)
                tier_summary['Mean Error %'] = tier_summary['Mean Error %'].round(1)
                tier_summary['Median Error %'] = tier_summary['Median Error %'].round(1)
            else:
                tier_summary = results_df.groupby('Tier').agg(Predictions=('Error', 'count'), MAE=('Error', 'mean')).reset_index()
                tier_summary['MAE'] = tier_summary['MAE'].round(2)
            hit_rates = results_df.groupby('Tier')['Error'].agg(
                **{'Within 2pts %': lambda x: round((x <= 2).mean() * 100, 1),
                   'Within 3pts %': lambda x: round((x <= 3).mean() * 100, 1),
                   'Within 5pts %': lambda x: round((x <= 5).mean() * 100, 1)}
            ).reset_index()
            tier_summary = tier_summary.merge(hit_rates, on='Tier')
            st.dataframe(tier_summary, use_container_width=True)

            st.markdown("---")
            st.subheader("📏 MAE by Projection Size")
            st.caption("Buckets by how big the model's own projection was, not by confidence tier — this can reveal a systematic bias the tier breakdown alone wouldn't show (e.g. great on role players but consistently off on stars, or vice versa). 'Bias' is the signed average error (Projection − Actual) — a high MAE with bias near zero means the model is unbiased but those players are just genuinely volatile; a high MAE with a strong bias means there's a real systematic issue (consistently over- or under-projecting) worth fixing.")
            if backtest_sport == "NBA Assists":
                bins = [-0.01, 3, 5, 7, 9, 999]
                labels = ["0-3 AST", "3-5 AST", "5-7 AST", "7-9 AST", "9+ AST"]
            elif backtest_sport == "NBA Points":
                bins = [-0.01, 10, 15, 20, 25, 999]
                labels = ["0-10 PTS", "10-15 PTS", "15-20 PTS", "20-25 PTS", "25+ PTS"]
            else:  # MLB Strikeouts
                bins = [-0.01, 3, 5, 7, 9, 999]
                labels = ["0-3 K", "3-5 K", "5-7 K", "7-9 K", "9+ K"]
            size_col = 'Projection'
            results_df['Projection Bucket'] = pd.cut(results_df[size_col], bins=bins, labels=labels)
            results_df['Signed Error'] = results_df['Projection'] - results_df['Actual']
            size_summary = results_df.groupby('Projection Bucket', observed=True).agg(
                Predictions=('Error', 'count'), MAE=('Error', 'mean'),
                **{'Bias (Avg Error)': ('Signed Error', 'mean')}
            ).reset_index()
            size_summary['MAE'] = size_summary['MAE'].round(2)
            size_summary['Bias (Avg Error)'] = size_summary['Bias (Avg Error)'].round(2)
            size_hit_rates = results_df.groupby('Projection Bucket', observed=True)['Error'].agg(
                **{'Within 2pts %': lambda x: round((x <= 2).mean() * 100, 1)}
            ).reset_index()
            size_summary = size_summary.merge(size_hit_rates, on='Projection Bucket')
            st.dataframe(size_summary, use_container_width=True)

            if 'Proj Min' in results_df.columns and results_df['Proj Min'].notna().any():
                st.markdown("---")
                st.subheader("🏀 MAE by Role (Starter vs. Bench)")
                st.caption("Real starting-lineup data isn't available at this data tier, so this uses projected minutes as a proxy for role (24+ minutes ≈ starter-level workload) — an approximation, not a confirmed starter/bench designation. If bench players are meaningfully worse, expected-minutes logic for rotation players may still need work. If starters and bench are similar, that's reassuring.")
                results_df['Role (proxy)'] = results_df['Proj Min'].apply(lambda m: 'Starter (24+ min)' if pd.notna(m) and m >= 24 else 'Bench (<24 min)')
                role_summary = results_df.groupby('Role (proxy)').agg(
                    Predictions=('Error', 'count'), MAE=('Error', 'mean'),
                    **{'Bias (Avg Error)': ('Signed Error', 'mean')}
                ).reset_index()
                role_summary['MAE'] = role_summary['MAE'].round(2)
                role_summary['Bias (Avg Error)'] = role_summary['Bias (Avg Error)'].round(2)
                role_hit_rates = results_df.groupby('Role (proxy)')['Error'].agg(
                    **{'Within 2pts %': lambda x: round((x <= 2).mean() * 100, 1)}
                ).reset_index()
                role_summary = role_summary.merge(role_hit_rates, on='Role (proxy)')
                st.dataframe(role_summary, use_container_width=True)

# ---- SETTINGS PAGE ----
elif nav == "⚙️ Settings":
    st.title("⚙️ Settings")
    st.markdown("---")
    st.subheader("Account Information")
    st.write(f"**Email:** {user.email}")
    st.markdown("---")

    st.subheader("💰 Build Your Bankroll Profile")
    st.caption("Powers MM Stake — a real Quarter-Kelly stake recommendation on every prop, sized to your actual bankroll.")

    settings = get_user_settings()
    current_bankroll = get_current_bankroll(settings)

    if current_bankroll is not None:
        st.metric("Current Bankroll", f"${current_bankroll:,.2f}")
        st.caption(f"Baseline of ${settings['starting_bankroll']:,.2f} set on {settings.get('bankroll_set_date')}, adjusted live by your settled bet profit since then.")
    else:
        st.info("No bankroll set yet — set one below to enable MM Stake recommendations.")

    with st.form("bankroll_form"):
        col1, col2 = st.columns(2)
        with col1:
            new_bankroll = st.number_input(
                "Set / Reset Bankroll ($)", value=None, min_value=0.0, step=0.01, format="%.2f",
                placeholder="e.g. 2500.00",
                help="Setting this creates a new baseline dated today — your Current Bankroll going forward is this number plus/minus profit from bets settled after today."
            )
        with col2:
            risk_style = st.selectbox(
                "Risk Style", ["Conservative", "Standard", "Aggressive"],
                index=["Conservative", "Standard", "Aggressive"].index(settings.get('risk_style', 'Standard')) if settings else 1,
                help="Caps the maximum single-bet stake: Conservative 1% of bankroll, Standard 2%, Aggressive 3%."
            )
        if st.form_submit_button("💾 Save Bankroll Settings"):
            if new_bankroll is not None:
                if save_user_settings(round(float(new_bankroll), 2), risk_style):
                    st.success("✅ Bankroll settings saved.")
                    st.rerun()
            elif settings:
                # Risk style changed without resetting the bankroll baseline
                if save_user_settings(settings['starting_bankroll'], risk_style, reset_baseline=False):
                    st.success("✅ Risk style updated.")
                    st.rerun()
            else:
                st.warning("Enter a starting bankroll to get started.")

    if settings and settings.get('starting_bankroll') is not None:
        with st.form("bankroll_adjust_form"):
            st.caption("Deposited more money, or pulled some out? Adjust your bankroll without resetting your tracking history or start date — a top-up doesn't erase your profit/loss record.")
            adjustment = st.number_input(
                "Add or Remove Funds ($)", value=None, step=0.01, format="%.2f",
                placeholder="e.g. 500 to add, -200 to remove",
                help="Positive to deposit, negative to withdraw. This shifts your Current Bankroll by exactly this amount — your original start date and all past profit tracking stay untouched."
            )
            if st.form_submit_button("➕ Apply Adjustment"):
                if adjustment:
                    new_starting = round(settings['starting_bankroll'] + float(adjustment), 2)
                    if save_user_settings(new_starting, settings.get('risk_style', 'Standard'), reset_baseline=False):
                        st.success(f"✅ Bankroll adjusted by {'+' if adjustment > 0 else ''}${adjustment:,.2f}.")
                        st.rerun()
                else:
                    st.warning("Enter a nonzero amount to adjust.")

    st.markdown("---")
    st.subheader("Subscription")
    if not PAYWALL_ENABLED:
        st.info("💳 Subscription management coming soon — stay tuned!")
    elif subscription_status["status"] == "active":
        st.success("✅ You're subscribed — full access to every model.")
        try:
            _sub_row_res = supabase.table("subscriptions").select("stripe_customer_id, current_period_end").eq("user_id", user_id).execute()
            _sub_row = _sub_row_res.data[0] if _sub_row_res.data else None
        except Exception:
            _sub_row = None
        if _sub_row and _sub_row.get("current_period_end"):
            try:
                _period_end_dt = datetime.fromisoformat(str(_sub_row["current_period_end"]).replace("Z", "+00:00"))
                st.caption(f"Renews {_period_end_dt.strftime('%B %d, %Y')}")
            except Exception:
                pass
        if _sub_row and _sub_row.get("stripe_customer_id"):
            _portal_url = create_stripe_billing_portal_url(_sub_row["stripe_customer_id"])
            if _portal_url:
                st.link_button("Manage Subscription", _portal_url, use_container_width=True)
    elif subscription_status["status"] == "trialing":
        _days_left = subscription_status["days_left_in_trial"]
        st.info(f"🎉 {_days_left} day{'s' if _days_left != 1 else ''} left in your free trial.")
        _settings_checkout_url = create_stripe_checkout_url(user_id, user.email)
        if _settings_checkout_url:
            st.link_button("🔓 Subscribe Now", _settings_checkout_url, use_container_width=True, type="primary")
    else:
        st.warning("🔒 Your free trial has ended.")
        _settings_checkout_url = create_stripe_checkout_url(user_id, user.email)
        if _settings_checkout_url:
            st.link_button("🔓 Subscribe Now", _settings_checkout_url, use_container_width=True, type="primary")
    st.markdown("---")
    st.subheader("Danger Zone")
    if st.button("🚪 Logout", use_container_width=True):
        sign_out()
        st.rerun()
