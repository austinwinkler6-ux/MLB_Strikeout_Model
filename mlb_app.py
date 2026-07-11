import streamlit as st
import time
import requests
import pandas as pd
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from collections import Counter
from io import StringIO
from supabase import create_client, Client
from nba_api.stats.endpoints import playergamelog, leaguedashplayerstats, leaguedashteamstats, leaguedashptstats
from nba_api.stats.static import players as nba_players
from basketball_reference_web_scraper import client as bref_client
from basketball_reference_web_scraper.data import OutputType as BRefOutputType
from scipy import stats

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
    }

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

def workload_evidence_line(result):
    """Builds the strongest available one-line workload explanation from real
    numbers, instead of just describing which rule fired. Deliberately does NOT
    guess at a cause (injury, demotion, call-up, workload management, etc.) —
    we have no data on why a workload changed, only that it did, so the wording
    stays descriptive rather than diagnostic."""
    if not result:
        return None
    workload_tier = result.get('workload_tier')
    if not workload_tier:
        return None

    season_avg_ip = result.get('season_avg_ip')
    last5_avg_ip = result.get('last5_avg_ip')
    expected_innings = result.get('expected_innings')
    streak = result.get('consecutive_5ip_starts')

    if "Stable" in workload_tier:
        if streak is not None and streak >= 3 and last5_avg_ip is not None and season_avg_ip is not None:
            return f"✅ {streak} straight starts of 5+ IP — averaging **{last5_avg_ip} IP** over that stretch, in line with his **{season_avg_ip} IP** season average"
        elif season_avg_ip is not None:
            return f"✅ Workhorse role — averaging **{season_avg_ip} IP** across the season"
    elif "Changing" in workload_tier:
        if last5_avg_ip is not None and season_avg_ip is not None and last5_avg_ip < season_avg_ip - 0.5:
            gap = round(season_avg_ip - last5_avg_ip, 1)
            return f"⚠️ Workload running below season norm — averaging **{last5_avg_ip} IP** over his last 5 starts vs **{season_avg_ip} IP** season average ({gap} IP short)"
        elif expected_innings is not None:
            return f"⚠️ Workload trending inconsistent — model expects **{expected_innings} IP** tonight"
    else:
        if last5_avg_ip is not None and season_avg_ip is not None:
            gap = round(abs(season_avg_ip - last5_avg_ip), 1)
            direction = "below" if last5_avg_ip < season_avg_ip else "above"
            return f"❌ Role remains unsettled — last 5 starts averaging **{last5_avg_ip} IP**, {gap} IP {direction} his season norm"
        elif expected_innings is not None:
            return f"❌ Role remains unsettled — model expects only **{expected_innings} IP** tonight"

    return None

ODDS_API_KEY = st.secrets["ODDS_API_KEY"]
ADMIN_EMAIL = "austinwinkler6@icloud.com"

# ---- EV CALCULATOR ----
EDGE_THRESHOLDS = {
    "mlb_strikeouts": 0.75,
    "nba_assists": 0.75,
    "nba_points": 1.5,
    "nfl_pass_attempts": 2.0,
    "nfl_completions": 1.5,
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
    elif sport == 'nba_points':
        return max(5.0, projection * 0.22)
    elif sport == 'nba_assists':
        return max(1.5, projection * 0.25)
    return max(1.5, projection * 0.25)

def remove_vig(over_odds, under_odds):
    def to_prob(odds):
        if odds > 0:
            return 100 / (odds + 100)
        else:
            return abs(odds) / (abs(odds) + 100)
    over_prob = to_prob(over_odds)
    under_prob = to_prob(under_odds)
    total = over_prob + under_prob
    return round(over_prob / total, 3), round(under_prob / total, 3)

def projection_to_probability(projection, line, std_dev, direction='over'):
    if std_dev <= 0:
        return 0.5
    z_score = (line - projection) / std_dev
    if direction == 'over':
        return round(1 - stats.norm.cdf(z_score), 3)
    else:
        return round(stats.norm.cdf(z_score), 3)

def calculate_ev(model_prob, odds, bet_amount=100):
    if odds > 0:
        profit = (odds / 100) * bet_amount
    else:
        profit = (100 / abs(odds)) * bet_amount
    return round((model_prob * profit) - ((1 - model_prob) * bet_amount), 2)

def calculate_ev_pct(model_prob, odds, bet_amount=100):
    return round((calculate_ev(model_prob, odds, bet_amount) / bet_amount) * 100, 2)

def prob_to_american_odds(prob):
    try:
        if prob is None or prob <= 0 or prob >= 1:
            return None
        if prob >= 0.5:
            return int(round(-100 * prob / (1 - prob)))
        else:
            return int(round(100 * (1 - prob) / prob))
    except:
        return None

def odds_to_cents(odds):
    if odds is None:
        return None
    if odds > 0:
        return round(100 - odds, 1)
    else:
        return round(abs(odds) - 100, 1)

def calculate_odds_edge_cents(market_odds, fair_odds):
    market_cents = odds_to_cents(market_odds)
    fair_cents = odds_to_cents(fair_odds)
    if market_cents is None or fair_cents is None:
        return None
    return round(fair_cents - market_cents, 1)

def odds_to_implied_prob(odds):
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)

def calculate_odds_clv(placed_odds, closing_odds):
    """Compares the odds a bet was placed at against the closing odds, via
    implied probability rather than the cents-based market-vs-fair formula
    (that formula is for a different comparison and gives wrong signs here).
    Positive = the closing price implied a higher probability than what you
    got, i.e. the market moved in your favor after you bet (good CLV)."""
    if placed_odds is None or closing_odds is None:
        return None
    placed_prob = odds_to_implied_prob(placed_odds)
    closing_prob = odds_to_implied_prob(closing_odds)
    return round((closing_prob - placed_prob) * 100, 2)

def fmt_signed_num(v, decimals=1):
    """Formats a number with an explicit + sign for positive values,
    plain 0 for zero, and — for missing data. Used for CLV displays."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if abs(v) < 10 ** (-decimals) / 2:
        return f"{0:.{decimals}f}"
    sign = "+" if v > 0 else ""
    return f"{sign}{round(v, decimals)}"

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
    """Tier answers exactly ONE question: is there positive expected value,
    and how strong is it? Confidence (cv + workload) and MM Stake (sizing)
    are separate, independent axes — a low-confidence pick with real EV is a
    Lean with a small stake, not a Pass. Pass means the model doesn't see
    positive expected value, full stop; it says nothing about how much to
    trust the number or how much to risk on it."""
    threshold = EDGE_THRESHOLDS.get(sport, 0.75)
    ev_threshold = 12.0

    same_direction = model_edge is not None and ev_pct is not None and model_edge > 0 and ev_pct > 0
    if not same_direction:
        return "🔴 Pass"

    model_strong = model_edge >= threshold
    ev_strong = ev_pct >= ev_threshold

    if model_strong and ev_strong:
        return "🟢 Best Bet"
    elif model_strong or ev_strong:
        return "🔵 Worth a Look"
    else:
        return "🟡 Lean"

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

def generate_why(info, result, direction, sport='mlb_strikeouts'):
    lines = []
    proj = info.get('Projection')
    line = info.get('FanDuel Line') or info.get('DraftKings Line')
    over_odds = info.get('FanDuel Over') or info.get('DraftKings Over')
    under_odds = info.get('FanDuel Under') or info.get('DraftKings Under')
    odds = over_odds if direction == 'over' else under_odds
    model_prob = info.get('Model Prob')
    no_vig_prob = info.get('No Vig Prob')
    ev_pct = info.get('EV%')
    tier = info.get('Tier')

    mm_tier = info.get('MM Tier')
    pass_reason = info.get('Pass Reason')
    confidence_level = info.get('Confidence Level')
    if mm_tier == "🔴 Pass" and pass_reason:
        lines.append(f"🔴 **Pass** — Reason: **{pass_reason}**")
    elif mm_tier and confidence_level == "🔴 Low":
        lines.append(f"{mm_tier} · Confidence: **{confidence_level}**")

    if proj and line:
        diff = round(proj - line, 1)
        if direction == 'over':
            icon = "✅" if diff > 0 else "⚠️"
            lines.append(f"{icon} Model projects **{proj}** vs book line of **{line}** ({'+'if diff>0 else ''}{diff} edge)")
        else:
            diff_under = round(line - proj, 1)
            icon = "✅" if diff_under > 0 else "⚠️"
            lines.append(f"{icon} Model projects **{proj}** vs book line of **{line}** ({'+'if diff_under>0 else ''}{diff_under} under edge)")

    if odds:
        if odds > 0:
            lines.append(f"✅ Book offering **+{odds}** — plus-money on this side")
        elif odds >= -115:
            lines.append(f"✅ Book offering **{odds}** — near even money, reasonable")
        elif odds >= -130:
            lines.append(f"⚠️ Book offering **{odds}** — moderate juice")
        else:
            lines.append(f"⚠️ Book offering **{odds}** — heavy juice, higher break-even needed")

    fair_odds = info.get('Fair Odds')
    edge_cents = info.get('Edge Cents')
    if odds and fair_odds is not None and edge_cents is not None:
        icon = "✅" if edge_cents > 0 else ("⚠️" if edge_cents == 0 else "❌")
        lines.append(f"{icon} Market Odds: **{fmt_odds(odds)}** → Fair Odds: **{fmt_odds(fair_odds)}** ({'+' if edge_cents > 0 else ''}{edge_cents} cents edge)")

    if no_vig_prob and model_prob:
        no_vig_pct = round(no_vig_prob * 100, 1)
        model_pct = round(model_prob * 100, 1)
        prob_diff = round((model_prob - no_vig_prob) * 100, 1)
        icon = "✅" if prob_diff > 3 else ("⚠️" if prob_diff > 0 else "❌")
        lines.append(f"{icon} No-vig probability: **{no_vig_pct}%** → Model probability: **{model_pct}%** ({'+'if prob_diff>0 else ''}{prob_diff}% edge)")

    raw_ev_pct = info.get('Raw EV%')
    if ev_pct is not None:
        if raw_ev_pct is not None and abs(raw_ev_pct - ev_pct) >= 3:
            lines.append(f"⚠️ Raw EV: **+{raw_ev_pct}%** → Confidence-Adjusted EV: **{'+' if ev_pct >= 0 else ''}{ev_pct}%** — the price may be good, but the model doesn't trust the workload enough to fully credit it")
        elif ev_pct >= 15:
            lines.append(f"✅ EV: **+{ev_pct}%** — exceptional value")
        elif ev_pct >= 10:
            lines.append(f"✅ EV: **+{ev_pct}%** — strong value")
        elif ev_pct >= 5:
            lines.append(f"⚠️ EV: **+{ev_pct}%** — good value")
        elif ev_pct > 0:
            lines.append(f"⚠️ EV: **+{ev_pct}%** — slight edge")
        else:
            lines.append(f"❌ EV: **{ev_pct}%** — negative expected value")

    if info.get('Low Confidence'):
        lines.append("⚠️ **Low Confidence** — this projection carries very high variance. The EV above is calculated the same as any other prop, but treat it with caution and consider passing.")

    if tier:
        reliability_label = "Pitcher Reliability" if sport == 'mlb_strikeouts' else "Player Reliability"
        if "Reliable" in tier:
            lines.append(f"✅ {reliability_label}: **{tier}** — consistent performer, low variance")
        elif "Volatile" in tier:
            lines.append(f"⚠️ {reliability_label}: **{tier}** — results vary significantly game to game")
        elif "Uncertain Workload" in tier:
            lines.append(f"❌ {reliability_label}: **{tier}** — extremely high variance, use caution")

    if result:
        workload_tier = result.get('workload_tier')
        expected_innings = result.get('expected_innings')
        expected_minutes = result.get('expected_minutes')
        if workload_tier:
            if "Stable" in workload_tier:
                icon = "✅"
            elif "Changing" in workload_tier:
                icon = "⚠️"
            else:
                icon = "❌"
            if expected_innings is not None:
                workload_note = f" — expected **{expected_innings} IP**"
            elif expected_minutes is not None:
                workload_note = f" — expected **{expected_minutes} MIN**"
            else:
                workload_note = ""
            lines.append(f"{icon} Role Stability: **{workload_tier}**{workload_note}")

        evidence_line = workload_evidence_line(result)
        if evidence_line:
            lines.append(evidence_line)

        def _dir_icon(factor_boosts_stat):
            """✅ if this factor works in favor of the bet's actual direction, ⚠️ if against it."""
            if direction == 'over':
                return "✅" if factor_boosts_stat else "⚠️"
            else:
                return "⚠️" if factor_boosts_stat else "✅"

        opp_factor = result.get('opp_factor')
        if opp_factor:
            if opp_factor >= 1.05:
                matchup_word = "favorable" if direction == 'over' else "tougher"
                lines.append(f"{_dir_icon(True)} Opponent K% is **above average** — {matchup_word} matchup")
            elif opp_factor <= 0.95:
                matchup_word = "tougher" if direction == 'over' else "favorable"
                lines.append(f"{_dir_icon(False)} Opponent K% is **below average** — {matchup_word} matchup")
            else:
                lines.append(f"➖ Opponent K% is near league average")

        park_factor = result.get('park_factor')
        if park_factor:
            if park_factor >= 1.03:
                lines.append(f"{_dir_icon(True)} Park factor **{park_factor}** — pitcher-friendly park")
            elif park_factor <= 0.97:
                lines.append(f"{_dir_icon(False)} Park factor **{park_factor}** — hitter-friendly park")

        umpire_factor = result.get('umpire_factor')
        umpire_name = result.get('umpire_name')
        if umpire_factor and umpire_name:
            if umpire_factor >= 1.02:
                lines.append(f"{_dir_icon(True)} Umpire **{umpire_name}** has a larger strike zone — boosts K rate")
            elif umpire_factor <= 0.98:
                lines.append(f"{_dir_icon(False)} Umpire **{umpire_name}** has a tighter strike zone — hurts K rate")

        lineup_factor = result.get('lineup_factor')
        if lineup_factor:
            if lineup_factor >= 0.24:
                lines.append(f"{_dir_icon(True)} Today's lineup K% is **above average** — {'favorable' if direction == 'over' else 'tougher'}")
            elif lineup_factor <= 0.20:
                lines.append(f"{_dir_icon(False)} Today's lineup K% is **below average** — {'tougher' if direction == 'over' else 'favorable'}")

        if sport in ('nba_points', 'nba_assists'):
            opp_pace = result.get('opp_pace')
            if opp_pace:
                if opp_pace >= league_avg_pace + 2:
                    lines.append(f"{_dir_icon(True)} Opponent pace **{opp_pace}** — faster pace, more possessions")
                elif opp_pace <= league_avg_pace - 2:
                    lines.append(f"{_dir_icon(False)} Opponent pace **{opp_pace}** — slower pace, fewer possessions")
                else:
                    lines.append(f"➖ Opponent pace **{opp_pace}** — near league average")

            rest_adj = result.get('rest_adj')
            days_rest = result.get('days_rest')
            if rest_adj:
                icon = _dir_icon(rest_adj > 0)
                rest_note = f" ({days_rest} days rest)" if days_rest is not None else ""
                lines.append(f"{icon} Rest adjustment **{rest_adj:+}**{rest_note}")

            if sport == 'nba_points':
                opp_def_rating = result.get('opp_def_rating')
                if opp_def_rating:
                    if opp_def_rating >= league_avg_def_rating + 2:
                        lines.append(f"{_dir_icon(True)} Opponent defensive rating **{opp_def_rating}** — weaker defense, {'favorable' if direction == 'over' else 'tougher'} matchup")
                    elif opp_def_rating <= league_avg_def_rating - 2:
                        lines.append(f"{_dir_icon(False)} Opponent defensive rating **{opp_def_rating}** — stronger defense, {'tougher' if direction == 'over' else 'favorable'} matchup")

                usage_adj = result.get('usage_adj')
                if usage_adj:
                    icon = _dir_icon(usage_adj > 0)
                    lines.append(f"{icon} Usage adjustment **{usage_adj:+}** based on recent shot volume")

            elif sport == 'nba_assists':
                ast_pct_adj = result.get('ast_pct_adj')
                if ast_pct_adj:
                    icon = _dir_icon(ast_pct_adj > 0)
                    lines.append(f"{icon} Assist rate adjustment **{ast_pct_adj:+}** based on playmaking usage")

                potential_ast_adj = result.get('potential_ast_adj')
                if potential_ast_adj:
                    icon = _dir_icon(potential_ast_adj > 0)
                    lines.append(f"{icon} Potential-assists tracking adjustment **{potential_ast_adj:+}**")

                opp_ast_adj = result.get('opp_ast_adj')
                if opp_ast_adj:
                    icon = _dir_icon(opp_ast_adj > 0)
                    lines.append(f"{icon} Opponent assists-allowed adjustment **{opp_ast_adj:+}**")

    return lines

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
            'tier': get_tier(model_edge, ev_pct, cv, sport, workload_tier),
            'pass_reason': get_pass_reason(model_edge, ev_pct, cv, workload_tier),
            'confidence_level': get_confidence_level(cv, workload_tier)
        }
    except:
        return None

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

def sign_out():
    try:
        supabase.auth.sign_out()
    except:
        pass
    st.session_state.clear()

# ---- AUTH WALL ----
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
                st.error(f"Login failed: {error}")
            else:
                st.session_state['user'] = user
                st.session_state['session'] = session
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
                        st.session_state['user'] = user2
                        st.session_state['session'] = session
                        st.session_state['just_signed_up'] = True
                        st.rerun()
    st.stop()

# ---- LOGGED IN ----
user = st.session_state['user']
user_id = user.id
is_admin = user.email.lower() == ADMIN_EMAIL.lower()

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
        st.session_state['_session_refreshed_at'] = now
    except Exception:
        # If the refresh token itself is invalid/expired (e.g. laptop closed
        # for days), the user will hit an auth error on their next action and
        # need to log out/back in — no clean way to force that from here.
        pass

refresh_supabase_session_if_needed()
supabase.postgrest.auth(st.session_state['session'].access_token)

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
    return {sport: get_already_bet_players_today(sport) for sport in ('MLB', 'NBA', 'NBA_AST')}

def sport_key_to_bet_label(sport_key):
    return 'MLB' if sport_key == 'mlb_strikeouts' else nba_bet_sport_label(sport_key)

def save_bet(bet):
    try:
        bet['user_id'] = user_id
        supabase.table("bets").insert(bet).execute()
    except Exception as e:
        st.error(f"Error saving bet: {e}")

def update_bet(bet_id, updates):
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
        pred['user_id'] = user_id
        # Avoid duplicate rows for the same pitcher/date/sport — the shared
        # cache means projections are cheap to re-serve, but that shouldn't
        # mean a fresh prediction row gets saved every time some session's
        # auto-run happens to re-process a pitcher already logged today.
        existing = supabase.table("predictions").select("id") \
            .eq("user_id", user_id).eq("pitcher", pred.get("pitcher")) \
            .eq("date", pred.get("date")).eq("sport", pred.get("sport")) \
            .execute()
        if existing.data:
            return
        supabase.table("predictions").insert(pred).execute()
    except Exception as e:
        st.error(f"Error saving prediction: {e}")

def update_prediction(pred_id, updates):
    try:
        supabase.table("predictions").update(updates).eq("id", pred_id).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Error updating prediction: {e}")

def calc_profit(bet_amount, odds, result):
    if result == 'Win':
        if odds > 0:
            return round(bet_amount * (odds / 100), 2)
        else:
            return round(bet_amount * (100 / abs(odds)), 2)
    elif result == 'Loss':
        return -bet_amount
    return 0.0

# ---- BANKROLL / MM STAKE ----
RISK_STYLE_CAPS = {'Conservative': 0.01, 'Standard': 0.02, 'Aggressive': 0.03}
# Scales the tier unit ranges themselves (not just the final $ cap) so Aggressive
# genuinely recommends bigger individual stakes and Conservative genuinely
# recommends smaller ones — matches the same 1%/2%/3% ratio as the caps above.
RISK_STYLE_RANGE_MULTIPLIER = {'Conservative': 0.5, 'Standard': 1.0, 'Aggressive': 1.5}

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
            payload["bankroll_set_date"] = str(date.today())
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

def calc_decimal_odds(american_odds):
    if american_odds is None:
        return None
    if american_odds > 0:
        return 1 + (american_odds / 100)
    return 1 + (100 / abs(american_odds))

def has_book_disagreement(info):
    """A real, computed signal — not invented — using the FanDuel/DraftKings
    lines and odds already fetched for this prop."""
    fd_line = info.get('FanDuel Line')
    dk_line = info.get('DraftKings Line')
    if fd_line is not None and dk_line is not None and fd_line != dk_line:
        return True
    direction = info.get('Direction', 'over')
    fd_odds = info.get('FanDuel Over') if direction == 'over' else info.get('FanDuel Under')
    dk_odds = info.get('DraftKings Over') if direction == 'over' else info.get('DraftKings Under')
    if fd_odds is not None and dk_odds is not None:
        if abs(odds_to_cents(fd_odds) - odds_to_cents(dk_odds)) >= 10:
            return True
    return False

TIER_STAKE_RANGES = {
    "🟡 Lean": (0.25, 0.75),
    "🔵 Worth a Look": (0.50, 1.25),
    "🟢 Best Bet": (1.00, 2.00),
}

def calculate_mm_stake(info, result, bankroll, risk_style):
    """MM Stake v2: the confidence tier (which already weighs EV, edge, reliability,
    and workload) sets the unit RANGE for a play — Kelly only decides where within
    that range the stake lands, rather than driving the number outright. This keeps
    stake sizing telling the same story as the rest of the model: a Lean should
    feel like a Lean, a Best Bet should feel like a Best Bet, regardless of what
    the raw Kelly fraction happens to compute to."""
    if not bankroll or bankroll <= 0:
        return None

    confidence_tier = result.get('confidence_tier', '') if result else ''
    workload_tier = result.get('workload_tier', '') if result else ''
    mm_tier = info.get('MM Tier', '')
    if mm_tier == "🔴 Pass":
        return {'pass': True, 'reason': 'Model tier is Pass — no positive expected value'}

    tier_range = TIER_STAKE_RANGES.get(mm_tier)
    if not tier_range:
        return None
    range_mult = RISK_STYLE_RANGE_MULTIPLIER.get(risk_style, 1.0)
    tier_min, tier_max = tier_range[0] * range_mult, tier_range[1] * range_mult

    model_prob = info.get('Model Prob')
    odds = info.get('Odds')
    if model_prob is None or odds is None:
        return None

    decimal_odds = calc_decimal_odds(odds)
    if not decimal_odds or decimal_odds <= 1:
        return None

    base_fraction = 0.25 * ((model_prob * decimal_odds - 1) / (decimal_odds - 1))
    if base_fraction <= 0:
        return {'pass': True, 'reason': 'No positive edge after Kelly calculation'}

    # Kelly only positions the stake within the tier's range (0 = bottom, 1 = top)
    # — it no longer sets the dollar amount directly. 0.06 is the reference
    # Kelly fraction treated as "full range" — a strong-but-realistic edge.
    kelly_position = min(1.0, max(0.0, base_fraction / 0.06))
    stake_units = tier_min + kelly_position * (tier_max - tier_min)

    tier_label = mm_tier.split(" ", 1)[1] if " " in mm_tier else mm_tier
    reasoning = [f"{tier_label} tier sets a {tier_min}\u2013{tier_max} unit range", "Quarter-Kelly positions the stake within that range"]

    if "Reliable" in confidence_tier:
        stake_units *= 1.10
        reasoning.append("Reliable pitcher increased stake")
    elif "Volatile" in confidence_tier:
        stake_units *= 0.80
        reasoning.append("Volatile pitcher reduced stake")

    workload_hard_cap = None
    if "Changing" in workload_tier:
        stake_units *= 0.85
        reasoning.append("Recently changing workload reduced stake")
    elif "Highly Volatile" in workload_tier:
        stake_units *= 0.65
        reasoning.append("Highly volatile workload reduced stake")
        workload_hard_cap = 0.75

    if has_book_disagreement(info):
        stake_units *= 1.08
        reasoning.append("Sportsbook disagreement boosted stake")

    edge_magnitude = abs(info['Edge']) if info.get('Edge') is not None else None
    if edge_magnitude is not None:
        if edge_magnitude < 0.3:
            stake_units *= 0.85
            reasoning.append("Small projection edge reduced stake")
        elif edge_magnitude < 0.8:
            pass
        elif edge_magnitude < 1.3:
            stake_units *= 1.10
            reasoning.append("Solid projection edge increased stake")
        else:
            stake_units *= 1.20
            reasoning.append("Strong projection edge increased stake")

    ev_pct = info.get('EV%')
    if ev_pct is not None:
        if ev_pct < 5:
            pass
        elif ev_pct < 10:
            stake_units *= 1.05
            reasoning.append("Moderate EV increased stake")
        elif ev_pct < 15:
            stake_units *= 1.10
            reasoning.append("Strong EV increased stake")
        else:
            stake_units *= 1.15
            reasoning.append("Exceptional EV increased stake")

    # Modifiers can nudge within the tier's range, but never push outside it —
    # the tier's judgment is the outer boundary, not just a starting point.
    stake_units = max(tier_min, min(tier_max, stake_units))

    if workload_hard_cap is not None:
        stake_units = min(stake_units, workload_hard_cap)

    # True max reserved for the strongest confluence of signals only —
    # threshold scales with tier_max so this stays meaningful at every risk style
    near_max_threshold = tier_max * 0.75
    if mm_tier == "🟢 Best Bet" and stake_units > near_max_threshold:
        meets_max_criteria = (
            ev_pct is not None and ev_pct >= 15 and
            "Reliable" in confidence_tier and
            "Stable" in workload_tier and
            edge_magnitude is not None and edge_magnitude >= 1.0
        )
        if not meets_max_criteria:
            stake_units = min(stake_units, near_max_threshold)
            reasoning.append("Held below maximum — not all top-tier criteria met")

    stake_units = round(stake_units, 2)
    unit_value = bankroll * 0.01  # 1 unit = 1% of bankroll, standard convention
    stake_dollars = round(stake_units * unit_value, 2)

    cap_pct = RISK_STYLE_CAPS.get(risk_style, 0.02)
    max_stake_dollars = bankroll * cap_pct
    if stake_dollars > max_stake_dollars:
        stake_dollars = round(max_stake_dollars, 2)
        stake_units = round(stake_dollars / unit_value, 2) if unit_value > 0 else 0
        reasoning.append(f"Capped at {int(cap_pct*100)}% of bankroll ({risk_style})")

    return {
        'pass': stake_dollars <= 0,
        'stake_dollars': stake_dollars,
        'stake_units': stake_units,
        'reasoning': reasoning,
    }

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

def calc_profit_this_month(bets):
    month_prefix = mm_today_str()[:7]  # 'YYYY-MM'
    return round(sum(
        (b.get('profit') or 0) for b in bets
        if b.get('result') != 'Pending' and (b.get('date') or '').startswith(month_prefix)
    ), 2)

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
STAKE_DEVIATION_PERFECT_THRESHOLD = 10   # within ±10% = "perfect sizing"

def get_stake_deviation_pct(recommended, actual):
    if not recommended or recommended <= 0 or actual is None:
        return None
    return round((actual - recommended) / recommended * 100, 1)

def format_stake_deviation_message(recommended, actual):
    """The per-bet feedback shown right after logging — 'Perfect sizing' or
    a plain '% above/below recommendation' callout."""
    deviation = get_stake_deviation_pct(recommended, actual)
    if deviation is None:
        return None
    if abs(deviation) <= STAKE_DEVIATION_PERFECT_THRESHOLD:
        return f"✅ Perfect sizing — MM Stake ${recommended:,.2f}, your stake ${actual:,.2f}"
    elif deviation > 0:
        return f"⚠️ {abs(deviation):.0f}% above recommendation — MM Stake ${recommended:,.2f}, your stake ${actual:,.2f}"
    else:
        return f"⚠️ {abs(deviation):.0f}% below recommendation — MM Stake ${recommended:,.2f}, your stake ${actual:,.2f}"

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

def mm_today_str():
    """'Today' in Eastern Time, not the server's clock (likely UTC) — matters for
    cache date keys since MLB's day rolls over on Eastern time, not UTC."""
    return datetime.now(ZoneInfo("America/New_York")).strftime('%Y-%m-%d')

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
        consecutive = result.get('consecutive_5ip_starts')
        last5_avg_ip = result.get('last5_avg_ip')
        season_avg_ip = result.get('season_avg_ip')
        opp_factor = result.get('opp_factor')
        park_factor = result.get('park_factor')
        umpire_factor = result.get('umpire_factor')
        workload_tier = result.get('workload_tier', '')
        confidence_tier = result.get('confidence_tier', '')

        season_implied_k_per_start = (season_k_pct * expected_bf) if (season_k_pct and expected_bf) else None
        workload_recovering = (
            consecutive is not None and consecutive >= 2 and
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
                (consecutive is None or consecutive <= 1)):
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
        if result.get('consecutive_5ip_starts') is not None:
            facts.append(f"Consecutive starts of 5+ IP (most recent streak): {result['consecutive_5ip_starts']}")
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

    thesis_label = classify_thesis(info, result, 'mlb_strikeouts' if sport == 'MLB' else ('nba_points' if sport == 'NBA' else 'nba_assists'))
    insight = generate_ai_insight(player_name, info, result, 'mlb_strikeouts' if sport == 'MLB' else ('nba_points' if sport == 'NBA' else 'nba_assists'), thesis_label)
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
    it's a provisional (pre-lineup) MLB entry old enough to be worth re-checking."""
    cached = get_cached_projection(cache_date_str, 'MLB', pitcher_name)
    if cached and not _cache_is_stale_provisional(cached):
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
    """Pulls together whatever's currently loaded in session state (MLB + both NBA
    prop types) into one unified, ranked list. Shared by Today's Card and the Home
    page 'Today's Highest Rated Bet' section so they never show different data."""
    card_entries = []

    mlb_pitchers = st.session_state.get('all_pitchers', {})
    mlb_results = st.session_state.get('pitcher_results', {})
    for name, info in mlb_pitchers.items():
        if info.get('Projection') is not None and info.get('MM Tier'):
            card_entries.append({
                'sport_label': '⚾ MLB', 'sport_key': 'mlb_strikeouts', 'name': name,
                'line': info.get('FanDuel Line') or info.get('DraftKings Line'),
                'play': info.get('Play'), 'edge': info.get('Edge'),
                'ev_pct': info.get('EV%'), 'tier': info.get('MM Tier'),
                'info': info, 'result': mlb_results.get(name),
            })

    nba_pts = st.session_state.get('all_nba_players', {})
    nba_pts_results = st.session_state.get('nba_pts_results', {})
    for name, info in nba_pts.items():
        if info.get('Projection') is not None and info.get('MM Tier'):
            card_entries.append({
                'sport_label': '🏀 NBA Pts', 'sport_key': 'nba_points', 'name': name,
                'line': info.get('FanDuel Line') or info.get('DraftKings Line'),
                'play': info.get('Play'), 'edge': info.get('Edge'),
                'ev_pct': info.get('EV%'), 'tier': info.get('MM Tier'),
                'info': info, 'result': nba_pts_results.get(name),
            })

    nba_ast = st.session_state.get('all_nba_assist_players', {})
    nba_ast_results = st.session_state.get('nba_ast_results', {})
    for name, info in nba_ast.items():
        if info.get('Projection') is not None and info.get('MM Tier'):
            card_entries.append({
                'sport_label': '🏀 NBA Ast', 'sport_key': 'nba_assists', 'name': name,
                'line': info.get('FanDuel Line') or info.get('DraftKings Line'),
                'play': info.get('Play'), 'edge': info.get('Edge'),
                'ev_pct': info.get('EV%'), 'tier': info.get('MM Tier'),
                'info': info, 'result': nba_ast_results.get(name),
            })
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

# ---- PARK FACTORS ----
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
    response = requests.get(url)
    data = response.json()
    pitchers = []
    for player in data['people']:
        if player.get('primaryPosition', {}).get('code') == '1':
            pitchers.append(player['fullName'])
    return sorted(pitchers)

@st.cache_data(ttl=3600)
def get_batter_k_pcts():
    url = "https://baseballsavant.mlb.com/leaderboard/custom?year=2026&type=batter&filter=&sort=4&sortDir=desc&min=10&selections=k_percent&chart=false&x=k_percent&y=k_percent&r=no&chartType=beeswarm&csv=true"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    df = pd.read_csv(StringIO(response.text))
    df['full_name'] = df['last_name, first_name'].apply(lambda x: f"{x.split(', ')[1]} {x.split(', ')[0]}")
    df['k_pct'] = df['k_percent'] / 100
    return df[['full_name', 'k_pct', 'player_id']]

@st.cache_data(ttl=1800)
def get_pitcher_game_info(pitcher_name, game_date=None):
    try:
        check_date = game_date or date.today().strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=probablePitcher"
        data = requests.get(url).json()
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
    except:
        pass
    return None, None, None

def fmt_odds(o):
    if o is None:
        return 'N/A'
    return f"+{o}" if o > 0 else str(o)

def get_starters_for_date(game_date_str):
    try:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={game_date_str}&hydrate=probablePitcher,linescore"
        data = requests.get(url).json()
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
    except:
        return []

def get_actual_strikeouts(game_pk, pitcher_name):
    try:
        url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
        data = requests.get(url).json()
        for side in ['home', 'away']:
            for pid in data['teams'][side]['pitchers']:
                player = data['teams'][side]['players'].get(f'ID{pid}', {})
                name = player.get('person', {}).get('fullName', '')
                if name.lower() == pitcher_name.lower():
                    return player.get('stats', {}).get('pitching', {}).get('strikeOuts', None)
    except:
        pass
    return None

def get_nba_games_for_date(game_date_str):
    url = f"https://stats.nba.com/stats/scoreboardV2?DayOffset=0&LeagueID=00&gameDate={game_date_str}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.nba.com/',
        'Origin': 'https://www.nba.com',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'x-nba-stats-origin': 'stats',
        'x-nba-stats-token': 'true',
        'Connection': 'keep-alive',
    }
    last_error = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=NBA_API_TIMEOUT, proxies=NBA_PROXY_DICT)
            response.raise_for_status()
            data = response.json()
            games = []
            game_header = data['resultSets'][0]
            headers_list = game_header['headers']
            for row in game_header['rowSet']:
                game = dict(zip(headers_list, row))
                games.append({
                    'game_id': game['GAME_ID'],
                    'home_team_abbrev': game.get('HOME_TEAM_ABBREVIATION', ''),
                    'away_team_abbrev': game.get('VISITOR_TEAM_ABBREVIATION', '')
                })
            return games
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(2)
    st.error(f"Error fetching NBA games after 3 attempts: {last_error}")
    return []

# ---- MLB PROJECTION ENGINE ----
def run_projection(pitcher_name, opponent_team, home_team, season, weather_adj=1.0, before_date=None,
                   use_umpire=True, use_park=True, use_lineup=True, use_pitch_count=True, use_total=True):
    try:
        league_avg_k_pct_vr = 0.222
        league_avg_k_pct_vl = 0.218
        league_avg_favor = 0.43

        search = requests.get(f"https://statsapi.mlb.com/api/v1/people/search?names={pitcher_name}&sportId=1")
        player_data = search.json()['people'][0]
        player_id = player_data['id']
        pitcher_hand = player_data['pitchHand']['code']

        season_stat = requests.get(f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=pitching&season={season}&sportId=1").json()['stats'][0]['splits'][0]['stat']

        season_k = int(season_stat['strikeOuts'])
        season_bf = int(season_stat['battersFaced'])
        season_k_pct = round(season_k / season_bf, 3)
        season_pitches_total = int(season_stat.get('numberOfPitches', 0))
        season_strikes = int(season_stat.get('strikes', 0))
        season_strike_pct = round(season_strikes / season_pitches_total, 3) if season_pitches_total > 0 else 0.65

        splits = requests.get(f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group=pitching&season={season}&sportId=1").json()['stats'][0]['splits']

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

        last10_ip = df['innings'].head(10)
        last10_ip_std = round(last10_ip.std(), 2) if len(last10_ip) > 1 else 0.0
        ip_cv = round(last10_ip_std / last10_avg_ip, 3) if last10_avg_ip > 0 else 1.0

        if ip_cv < 0.20:
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
        last10_pitches = round(df['pitches'].head(10).mean(), 1)
        season_avg_pitches = round(df['pitches'].mean(), 1)
        career_high_pitches = df['pitches'].max()
        pitches_per_inning = round(df['pitches_per_inning'].head(10).mean(), 2)

        if use_pitch_count:
            expected_pitch_count = round((season_avg_pitches * 0.30) + (last10_pitches * 0.30) + (last3_pitches * 0.40), 1)
            if last3_pitches < season_avg_pitches * 0.80:
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

        # Count consecutive recent starts (most recent first) with 5+ IP,
        # so a pitcher moving back into a normal starter role is recognized quickly.
        consecutive_5ip_starts = 0
        for ip in df['innings']:
            if ip >= 5.0:
                consecutive_5ip_starts += 1
            else:
                break

        if consecutive_5ip_starts >= 3:
            # Confirmed back to a normal starter role — trust season/role baseline again
            ip_season_w, ip_last10_w, ip_last5_w = 0.35, 0.40, 0.25
        elif consecutive_5ip_starts == 2:
            # Role change likely underway — lean harder into recent workload
            ip_season_w, ip_last10_w, ip_last5_w = 0.15, 0.25, 0.60
        elif last3_starter:
            ip_season_w, ip_last10_w, ip_last5_w = 0.20, 0.30, 0.50
        elif last5_avg_ip > season_avg_ip * 1.5 or last5_avg_ip < season_avg_ip * 0.6:
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
        team_data = requests.get(f"https://statsapi.mlb.com/api/v1/teams/stats?stats=season&group=hitting&season={season}&sportId=1").json()

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
                check_date = before_date or date.today().strftime('%Y-%m-%d')
                sched_data = requests.get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=lineups").json()
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
            except:
                pass

        opp_factor = round(final_opp_k_pct / league_avg_k_pct, 3)
        park_factor = park_factors.get(home_team, 1.0) if use_park else 1.0

        umpire_factor = 1.0
        umpire_name = None
        if use_umpire:
            try:
                check_date = before_date or date.today().strftime('%Y-%m-%d')
                sched_data = requests.get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=officials").json()
                if sched_data.get('dates'):
                    for game in sched_data['dates'][0]['games']:
                        if home_team in game['teams']['home']['team']['name'] or home_team in game['teams']['away']['team']['name']:
                            for official in game.get('officials', []):
                                if official['officialType'] == 'Home Plate':
                                    umpire_name = official['official']['fullName']
                            break
                if umpire_name:
                    ump_data = requests.get("https://umpscorecards.com/api/umpires", headers={'User-Agent': 'Mozilla/5.0'}).json()
                    for ump in ump_data['rows']:
                        if ump['umpire'].lower() == umpire_name.lower():
                            umpire_factor = max(0.97, min(1.03, round(1.0 + ((round(ump['favor_abs_mean'], 3) - league_avg_favor) * 0.5), 3)))
                            break
            except:
                pass

        total_factor = 1.0
        if use_total:
            try:
                if before_date:
                    params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals', 'oddsFormat': 'american', 'date': f"{before_date}T18:00:00Z"}
                    games_data = requests.get("https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds", params=params).json().get('data', [])
                else:
                    params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals', 'oddsFormat': 'american'}
                    games_data = requests.get("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds", params=params).json()

                for game in games_data:
                    if home_team in game.get('home_team', '') or home_team in game.get('away_team', ''):
                        for bookmaker in game.get('bookmakers', []):
                            for market in bookmaker.get('markets', []):
                                if market['key'] == 'totals':
                                    game_total = market['outcomes'][0]['point']
                                    total_factor = max(0.95, min(1.05, round(1 - ((game_total - 8.5) * 0.02), 3)))
                            break
                        break
            except:
                pass

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
            'consecutive_5ip_starts': consecutive_5ip_starts,
        }
    except Exception as e:
        return None

NBA_API_TIMEOUT = 20  # seconds — fail fast instead of hanging indefinitely on a stalled request
# Optional proxy specifically for stats.nba.com calls (that host appears to block
# datacenter/cloud IPs). Deliberately scoped to NBA calls only — not a blanket
# proxy — so Supabase/Odds API/Anthropic traffic doesn't burn paid proxy bandwidth
# it never needed. Format: "http://username:password@host:port". Leave unset and
# everything falls back to direct connections, same as before.
NBA_PROXY_URL = st.secrets.get("NBA_PROXY_URL")
NBA_PROXY_DICT = {"http": NBA_PROXY_URL, "https": NBA_PROXY_URL} if NBA_PROXY_URL else None

# ---- BASKETBALL-REFERENCE DATA LAYER ----
# stats.nba.com blocks every IP type we tested (datacenter, sticky residential,
# rotating residential) at the request-fingerprint level, not the IP level — see
# July 2026 diagnostic session. Basketball-Reference is a separate company
# (Sports Reference LLC) with no known equivalent bot detection, and is the
# standard fallback data source used by the wider NBA-stats community for
# exactly this reason. This layer replaces stats.nba.com as the data source;
# the actual projection math (blending, workload tiers, EV/tier system) is
# unchanged — only how the raw numbers get fetched.

@st.cache_data(ttl=86400)
def get_bref_player_slug(player_name):
    """Basketball-Reference identifies players by a 'slug' (e.g. 'westbru01'),
    not by name — resolve name -> slug once per day per player, cached, since
    it rarely changes and this search hits the site directly."""
    try:
        last_name = player_name.strip().split(" ")[-1]
        results = bref_client.search(term=last_name)
        players_results = results.get("players", []) if isinstance(results, dict) else []
        name_lower = player_name.strip().lower()
        for p in players_results:
            if p.get("name", "").strip().lower() == name_lower:
                return p.get("slug") or p.get("identifier")
        # Fallback: first result if no exact match (e.g. suffix/accent mismatch)
        if players_results:
            return players_results[0].get("slug") or players_results[0].get("identifier")
        return None
    except Exception:
        return None

@st.cache_data(ttl=3600)
def get_bref_league_advanced_stats(season_end_year):
    """League-wide advanced stats (usage rate and similar) for every player —
    one call, cached, shared across every player evaluated that hour."""
    try:
        data = bref_client.players_advanced_season_totals(season_end_year=season_end_year)
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_bref_league_season_totals(season_end_year):
    """League-wide basic season totals for every player — used to derive
    season-long per-game averages (points, assists) by dividing by games played."""
    try:
        data = bref_client.players_season_totals(season_end_year=season_end_year)
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_bref_standings(season_end_year):
    """Team win/loss + point differential — used as our best available proxy
    for opponent strength/pace, since Basketball-Reference's library doesn't
    expose a direct 'team pace' stat the way stats.nba.com's LeagueDashTeamStats
    does. This is a known, deliberate simplification versus the old data source."""
    try:
        data = bref_client.standings(season_end_year=season_end_year)
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

def get_bref_player_game_log(player_name, season_end_year):
    """A player's full-season game log — the direct replacement for stats.nba.com's
    PlayerGameLog. Not cached at this layer (keyed by resolved slug in the caller)
    since Streamlit's cache_data needs hashable args and player_name -> slug
    resolution already has its own cache."""
    slug = get_bref_player_slug(player_name)
    if not slug:
        return pd.DataFrame(), None
    try:
        data = _cached_bref_player_box_scores(slug, season_end_year)
        return pd.DataFrame(data), slug
    except Exception:
        return pd.DataFrame(), slug

@st.cache_data(ttl=3600)
def _cached_bref_player_box_scores(player_identifier, season_end_year):
    return bref_client.regular_season_player_box_scores(player_identifier=player_identifier, season_end_year=season_end_year)

@st.cache_data(ttl=3600)
def get_bref_games_for_date(year, month, day):
    """All player box scores league-wide for one specific date — replaces both
    get_nba_games_for_date() AND the per-game box score fetch in Backtest with a
    single call, since Basketball-Reference's player_box_scores() already returns
    every player who played that day across every game."""
    try:
        data = bref_client.player_box_scores(day=day, month=month, year=year)
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_league_player_advanced_stats(season, measure_type='Advanced'):
    """League-wide player stats are the same regardless of which player is being
    evaluated — cached so a Backtest run processing 100+ players doesn't re-fetch
    this identical table from the NBA API for every single one of them."""
    stats = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season, per_mode_detailed='PerGame', measure_type_detailed_defense=measure_type,
        timeout=NBA_API_TIMEOUT, proxy=NBA_PROXY_URL
    )
    return stats.get_data_frames()[0]

@st.cache_data(ttl=3600)
def get_league_team_stats(season, measure_type='Advanced'):
    """Same reasoning as get_league_player_advanced_stats — one league-wide
    team table, cached instead of re-fetched per player."""
    stats = leaguedashteamstats.LeagueDashTeamStats(
        season=season, per_mode_detailed='PerGame', measure_type_detailed_defense=measure_type,
        timeout=NBA_API_TIMEOUT, proxy=NBA_PROXY_URL
    )
    return stats.get_data_frames()[0]

@st.cache_data(ttl=3600)
def get_league_passing_stats(season):
    stats = leaguedashptstats.LeagueDashPtStats(
        season=season, per_mode_simple='PerGame', player_or_team='Player', pt_measure_type='Passing',
        timeout=NBA_API_TIMEOUT, proxy=NBA_PROXY_URL
    )
    return stats.get_data_frames()[0]

# ---- NBA POINTS PROJECTION ENGINE ----
def run_nba_points_projection(player_name, opponent_abbrev, home_team, away_team, home_or_away, season='2025-26'):
    try:
        season_end_year = int(season.split("-")[0]) + 1

        df, slug = get_bref_player_game_log(player_name, season_end_year)
        if df.empty or len(df) < 5 or not slug:
            return None

        df['minutes_played'] = pd.to_numeric(df.get('seconds_played', 0), errors='coerce') / 60.0
        df['attempted_field_goals'] = pd.to_numeric(df.get('attempted_field_goals', 0), errors='coerce')
        made_fg = pd.to_numeric(df.get('made_field_goals', 0), errors='coerce')
        made_3pt = pd.to_numeric(df.get('made_three_point_field_goals', 0), errors='coerce')
        made_ft = pd.to_numeric(df.get('made_free_throws', 0), errors='coerce')
        df['points'] = 2 * made_fg + made_3pt + made_ft
        df = df.reset_index(drop=True)

        season_ppg = round(df['points'].mean(), 1)
        season_mpg = round(df['minutes_played'].mean(), 1)
        season_fga = round(df['attempted_field_goals'].mean(), 1)
        last5_avg = round(df['points'].tail(5).mean(), 1)
        last10_avg = round(df['points'].tail(10).mean(), 1)
        last5_fga = round(df['attempted_field_goals'].tail(5).mean(), 1)
        last5_min = round(df['minutes_played'].tail(5).mean(), 1)
        last10_min = round(df['minutes_played'].tail(10).mean(), 1)

        last10_pts = df['points'].tail(10)
        last10_pts_std = round(last10_pts.std(), 2) if len(last10_pts) > 1 else 0.0
        cv = round(last10_pts_std / round(last10_pts.mean(), 2), 3) if round(last10_pts.mean(), 2) > 0 else 1.0

        if cv < 0.35: confidence_tier = "🟢 Reliable"
        elif cv < 0.50: confidence_tier = "🟠 Volatile"
        else: confidence_tier = "🔴 Uncertain Workload"

        last10_min_series = df['minutes_played'].tail(10)
        last10_min_std = round(last10_min_series.std(), 2) if len(last10_min_series) > 1 else 0.0
        min_cv = round(last10_min_std / last10_min, 3) if last10_min > 0 else 1.0

        if min_cv < 0.20:
            workload_tier = "🟢 Stable Rotation Player"
        elif min_cv < 0.35:
            workload_tier = "🟡 Changing Role"
        else:
            workload_tier = "🔴 Highly Volatile Minutes"

        base = (last5_avg * 0.40) + (last10_avg * 0.30) + (season_ppg * 0.30)
        fga_factor = max(0.95, min(1.05, round(last5_fga / season_fga, 3) if season_fga > 0 else 1.0))

        adv_df = get_bref_league_advanced_stats(season_end_year)
        usage_rate = 0.20
        if not adv_df.empty and 'slug' in adv_df.columns:
            player_adv = adv_df[adv_df['slug'] == slug]
            usage_col = next((c for c in ['usage_percentage', 'usage_percent', 'usg_pct'] if c in adv_df.columns), None)
            if not player_adv.empty and usage_col:
                usage_rate = round(float(player_adv[usage_col].iloc[0]), 3)

        # Known limitation: Basketball-Reference's library doesn't expose a direct
        # team pace / defensive rating stat like stats.nba.com did — falling back
        # to league averages here rather than a real opponent-specific number.
        opp_def_rating = league_avg_def_rating
        opp_pace = league_avg_pace

        location_col = 'location' if 'location' in df.columns else None
        if location_col:
            home_games = df[df[location_col].astype(str).str.contains('HOME', case=False, na=False)]
            away_games = df[df[location_col].astype(str).str.contains('AWAY', case=False, na=False)]
        else:
            home_games = away_games = df.iloc[0:0]
        home_ppg = round(home_games['points'].mean(), 1) if not home_games.empty else season_ppg
        away_ppg = round(away_games['points'].mean(), 1) if not away_games.empty else season_ppg
        location_adj = max(-2.0, min(2.0, round(home_ppg - season_ppg, 2) if home_or_away == 'home' else round(away_ppg - season_ppg, 2)))

        expected_minutes = round((season_mpg * 0.30) + (last10_min * 0.30) + (last5_min * 0.40), 1)

        date_col = 'date' if 'date' in df.columns else None
        if date_col:
            df[date_col] = pd.to_datetime(df[date_col])
            days_rest = (datetime.today() - df[date_col].iloc[-1]).days
        else:
            days_rest = 2
        rest_adj = -1.5 if days_rest == 0 else (1.0 if days_rest >= 3 else 0)

        game_total = spread = None
        try:
            games_data = requests.get("https://api.the-odds-api.com/v4/sports/basketball_nba/odds",
                params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals,spreads', 'oddsFormat': 'american'}).json()
            for game in games_data:
                if home_team in game.get('home_team', '') or home_team in game.get('away_team', ''):
                    for bookmaker in game.get('bookmakers', []):
                        for market in bookmaker.get('markets', []):
                            if market['key'] == 'totals':
                                game_total = market['outcomes'][0]['point']
                            if market['key'] == 'spreads':
                                for outcome in market['outcomes']:
                                    if home_team in outcome['name']:
                                        spread = outcome['point']
                        break
                    break
        except:
            pass

        team_total_adj = blowout_minutes_adj = 0
        implied_team_total = None
        if game_total and spread:
            if home_or_away == 'home':
                implied_team_total = round((game_total / 2) + (abs(spread) / 2 * (1 if spread < 0 else -1)), 1)
            else:
                implied_team_total = round((game_total / 2) - (abs(spread) / 2 * (1 if spread < 0 else -1)), 1)
            team_total_adj = round((implied_team_total - league_avg_team_score) * 0.08, 2)
            blowout_minutes_adj = -4 if abs(spread) >= 12 else (-2 if abs(spread) >= 9 else 0)

        final_expected_minutes = round(expected_minutes + blowout_minutes_adj, 1)
        pts_per_minute = round(season_ppg / season_mpg, 3) if season_mpg > 0 else 0
        minutes_pts_adj = round((final_expected_minutes - season_mpg) * pts_per_minute, 2)
        usage_adj = round((usage_rate - 0.20) * 10, 2)
        def_adj = round((opp_def_rating - league_avg_def_rating) * 0.2, 2)
        pace_adj = round((opp_pace - league_avg_pace) * 0.25, 2)

        raw_adjustment = max(-6.0, min(6.0, usage_adj + def_adj + pace_adj + team_total_adj + location_adj + rest_adj + minutes_pts_adj))
        final_projection = round((base + raw_adjustment) * fga_factor, 1)

        return {
            'projection': final_projection, 'base': round(base, 2),
            'season_ppg': season_ppg, 'last5_avg': last5_avg, 'last10_avg': last10_avg,
            'last10_pts_std': last10_pts_std, 'season_mpg': season_mpg,
            'expected_minutes': final_expected_minutes, 'usage_rate': usage_rate,
            'fga_factor': fga_factor, 'opp_def_rating': opp_def_rating, 'opp_pace': opp_pace,
            'location_adj': location_adj, 'rest_adj': rest_adj, 'team_total_adj': team_total_adj,
            'minutes_pts_adj': minutes_pts_adj, 'usage_adj': usage_adj, 'def_adj': def_adj,
            'pace_adj': pace_adj, 'implied_team_total': implied_team_total, 'game_total': game_total,
            'cv': cv, 'confidence_tier': confidence_tier, 'days_rest': days_rest,
            'min_cv': min_cv, 'workload_tier': workload_tier,
        }
    except Exception as e:
        return None

# ---- NBA ASSISTS PROJECTION ENGINE ----
def run_nba_assists_projection(player_name, opponent_abbrev, home_team, away_team, home_or_away, season='2025-26'):
    try:
        season_end_year = int(season.split("-")[0]) + 1

        df, slug = get_bref_player_game_log(player_name, season_end_year)
        if df.empty or len(df) < 5 or not slug:
            return None

        df['minutes_played'] = pd.to_numeric(df.get('seconds_played', 0), errors='coerce') / 60.0
        df['assists'] = pd.to_numeric(df.get('assists', 0), errors='coerce')
        df['turnovers'] = pd.to_numeric(df.get('turnovers', 0), errors='coerce')
        df = df.reset_index(drop=True)

        season_apg = round(df['assists'].mean(), 1)
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
        cv = round(last10_ast_std / last10_ast_avg, 3) if last10_ast_avg > 0 else 1.0

        if cv < 0.35: confidence_tier = "🟢 Reliable"
        elif cv < 0.50: confidence_tier = "🟠 Volatile"
        else: confidence_tier = "🔴 Uncertain Workload"

        last10_min_series = df['minutes_played'].tail(10)
        last10_min_std = round(last10_min_series.std(), 2) if len(last10_min_series) > 1 else 0.0
        min_cv = round(last10_min_std / last10_min, 3) if last10_min > 0 else 1.0

        if min_cv < 0.20:
            workload_tier = "🟢 Stable Rotation Player"
        elif min_cv < 0.35:
            workload_tier = "🟡 Changing Role"
        else:
            workload_tier = "🔴 Highly Volatile Minutes"

        base = (last5_avg * 0.40) + (last10_avg * 0.30) + (season_apg * 0.30)
        tov_factor = max(0.95, min(1.05, round(last5_tov / season_tov, 3) if season_tov > 0 else 1.0))

        adv_df = get_bref_league_advanced_stats(season_end_year)
        usage_rate, ast_pct = 0.20, 0.15
        if not adv_df.empty and 'slug' in adv_df.columns:
            player_adv = adv_df[adv_df['slug'] == slug]
            usage_col = next((c for c in ['usage_percentage', 'usage_percent', 'usg_pct'] if c in adv_df.columns), None)
            ast_col = next((c for c in ['assist_percentage', 'assist_percent', 'ast_pct'] if c in adv_df.columns), None)
            if not player_adv.empty:
                if usage_col:
                    usage_rate = round(float(player_adv[usage_col].iloc[0]), 3)
                if ast_col:
                    ast_pct = round(float(player_adv[ast_col].iloc[0]), 3)

        # Known limitations: Basketball-Reference's library doesn't expose
        # "potential assists" (a tracking-data stat unique to stats.nba.com) or
        # opponent-assists-allowed / team pace the way the old data source did.
        # These fall back to neutral/league-average rather than being computed —
        # a real precision trade-off versus the old pipeline, not a bug.
        potential_assists = None
        potential_ast_adj = 0
        opp_pace = league_avg_pace
        opp_ast_allowed = 25.0
        opp_ast_adj = 0

        location_col = 'location' if 'location' in df.columns else None
        if location_col:
            home_games = df[df[location_col].astype(str).str.contains('HOME', case=False, na=False)]
            away_games = df[df[location_col].astype(str).str.contains('AWAY', case=False, na=False)]
        else:
            home_games = away_games = df.iloc[0:0]
        home_apg = round(home_games['assists'].mean(), 1) if not home_games.empty else season_apg
        away_apg = round(away_games['assists'].mean(), 1) if not away_games.empty else season_apg
        location_adj = max(-1.5, min(1.5, round(home_apg - season_apg, 2) if home_or_away == 'home' else round(away_apg - season_apg, 2)))

        expected_minutes = round((season_mpg * 0.30) + (last10_min * 0.30) + (last5_min * 0.40), 1)

        date_col = 'date' if 'date' in df.columns else None
        if date_col:
            df[date_col] = pd.to_datetime(df[date_col])
            days_rest = (datetime.today() - df[date_col].iloc[-1]).days
        else:
            days_rest = 2
        rest_adj = -0.5 if days_rest == 0 else (0.3 if days_rest >= 3 else 0)

        game_total = spread = None
        try:
            games_data = requests.get("https://api.the-odds-api.com/v4/sports/basketball_nba/odds",
                params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals,spreads', 'oddsFormat': 'american'}).json()
            for game in games_data:
                if home_team in game.get('home_team', '') or home_team in game.get('away_team', ''):
                    for bookmaker in game.get('bookmakers', []):
                        for market in bookmaker.get('markets', []):
                            if market['key'] == 'totals':
                                game_total = market['outcomes'][0]['point']
                            if market['key'] == 'spreads':
                                for outcome in market['outcomes']:
                                    if home_team in outcome['name']:
                                        spread = outcome['point']
                        break
                    break
        except:
            pass

        total_adj = max(-0.5, min(0.5, round((game_total - 225) * 0.015, 2))) if game_total else 0
        blowout_minutes_adj = -4 if (spread and abs(spread) >= 12) else (-2 if (spread and abs(spread) >= 9) else 0)
        pace_adj = round((opp_pace - league_avg_pace) * 0.12, 2)
        final_expected_minutes = round(expected_minutes + blowout_minutes_adj, 1)
        ast_per_minute = round(season_apg / season_mpg, 3) if season_mpg > 0 else 0
        minutes_ast_adj = round((final_expected_minutes - season_mpg) * ast_per_minute, 2)
        ast_pct_adj = max(-1.5, min(1.5, round((ast_pct - 0.25) * 6, 2)))

        raw_adjustment = max(-3.0, min(3.0, pace_adj + location_adj + rest_adj + minutes_ast_adj + ast_pct_adj + opp_ast_adj + total_adj + potential_ast_adj))
        final_projection = max(0, round(base + raw_adjustment, 1))

        return {
            'projection': final_projection, 'base': round(base, 2),
            'season_apg': season_apg, 'last5_avg': last5_avg, 'last10_avg': last10_avg,
            'last10_ast_std': last10_ast_std, 'season_mpg': season_mpg,
            'expected_minutes': final_expected_minutes, 'blowout_minutes_adj': blowout_minutes_adj,
            'usage_rate': usage_rate, 'ast_pct': ast_pct, 'ast_pct_adj': ast_pct_adj,
            'tov_factor': tov_factor, 'potential_assists': potential_assists,
            'potential_ast_adj': potential_ast_adj, 'opp_pace': opp_pace,
            'location_adj': location_adj, 'rest_adj': rest_adj, 'minutes_ast_adj': minutes_ast_adj,
            'pace_adj': pace_adj, 'opp_ast_adj': opp_ast_adj, 'opp_ast_allowed': opp_ast_allowed,
            'total_adj': total_adj, 'raw_adjustment': round(raw_adjustment, 2),
            'game_total': game_total, 'spread': spread, 'cv': cv,
            'confidence_tier': confidence_tier, 'days_rest': days_rest,
            'min_cv': min_cv, 'workload_tier': workload_tier,
        }
    except Exception as e:
        return None

def nba_bet_sport_label(sport_key):
    """Maps the internal NBA projection sport_key ('nba_points'/'nba_assists')
    to the sport label used consistently across bets/predictions ('NBA'/'NBA_AST')."""
    return 'NBA' if sport_key == 'nba_points' else 'NBA_AST'

# ---- CLOSING LINE / CLV TRACKING ----
def get_odds_api_sport_and_market(sport):
    if sport == 'MLB':
        return 'baseball_mlb', 'pitcher_strikeouts'
    elif sport == 'NBA':
        return 'basketball_nba', 'player_points'
    elif sport == 'NBA_AST':
        return 'basketball_nba', 'player_assists'
    return None, None

@st.cache_data(ttl=604800)
def get_historical_events_cached(api_sport, snapshot_time):
    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/historical/sports/{api_sport}/events",
            params={'apiKey': ODDS_API_KEY, 'date': snapshot_time}
        ).json()
        return resp.get('data', [])
    except:
        return []

@st.cache_data(ttl=604800)
def get_historical_event_odds_cached(api_sport, event_id, market, commence_time):
    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/historical/sports/{api_sport}/events/{event_id}/odds",
            params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': market, 'oddsFormat': 'american', 'date': commence_time}
        ).json()
        return resp.get('data', {}) or {}
    except:
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
    except:
        return None, None

def load_mlb_props_data():
    """Fetches today's MLB pitcher-strikeout props from FanDuel/DraftKings.
    Returns an all_pitchers dict (empty on failure) — same shape used throughout the app."""
    try:
        events_data = requests.get("https://api.the-odds-api.com/v4/sports/baseball_mlb/events",
            params={'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'}).json()
        all_pitchers = {}

        for event in events_data:
            home = event['home_team']
            away = event['away_team']
            event_id = event['id']
            props_data = requests.get(
                f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds",
                params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'pitcher_strikeouts', 'oddsFormat': 'american'}
            ).json()

            for bookmaker in props_data.get('bookmakers', []):
                if bookmaker['key'] in ['fanduel', 'draftkings']:
                    book_name = bookmaker['title']
                    for market in bookmaker.get('markets', []):
                        if market['key'] == 'pitcher_strikeouts':
                            for outcome in market['outcomes']:
                                pitcher = outcome['description']
                                if pitcher not in all_pitchers:
                                    all_pitchers[pitcher] = {
                                        'home': home, 'away': away,
                                        'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                        'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                        'Projection': None, 'Edge': None, 'Play': None,
                                        'Tier': None,
                                        'EV%': None, 'MM Tier': None,
                                        'Model Prob': None, 'No Vig Prob': None,
                                        'Model Edge': None, 'Odds': None, 'Direction': None,
                                        'Fair Odds': None, 'Edge Cents': None, 'Low Confidence': None
                                    }
                                if 'FanDuel' in book_name:
                                    all_pitchers[pitcher]['FanDuel Line'] = outcome['point']
                                    if outcome['name'] == 'Over':
                                        all_pitchers[pitcher]['FanDuel Over'] = outcome['price']
                                    else:
                                        all_pitchers[pitcher]['FanDuel Under'] = outcome['price']
                                elif 'DraftKings' in book_name:
                                    all_pitchers[pitcher]['DraftKings Line'] = outcome['point']
                                    if outcome['name'] == 'Over':
                                        all_pitchers[pitcher]['DraftKings Over'] = outcome['price']
                                    else:
                                        all_pitchers[pitcher]['DraftKings Under'] = outcome['price']
        return all_pitchers
    except Exception:
        return {}

def run_all_mlb_projections(all_pitchers, season, progress_callback=None):
    """Runs the projection + EV pipeline for every pitcher in all_pitchers (mutated in place),
    saves each as a prediction, and returns the pitcher_results dict.
    progress_callback(i, total, name), if given, is called before each pitcher runs —
    lets callers render their own progress bar (MLB page) or run silently (Today's Card)."""
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
                    'Edge Cents': ev_result['edge_cents'] if ev_result else None,
                    'Low Confidence': ev_result['low_confidence'] if ev_result else None,
                })
                pitcher_results[pitcher] = result

                save_prediction({
                    'date': date.today().strftime('%Y-%m-%d'),
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
    return pitcher_results

def load_nba_props_data(prop_market):
    """Fetches today's NBA player props for the given market
    ('player_points' or 'player_assists'). Returns an all_players dict."""
    try:
        events_data = requests.get("https://api.the-odds-api.com/v4/sports/basketball_nba/events",
            params={'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'}).json()
        all_players = {}

        for event in events_data:
            home = event['home_team']
            away = event['away_team']
            event_id = event['id']
            props_data = requests.get(
                f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds",
                params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': prop_market, 'oddsFormat': 'american'}
            ).json()

            for bookmaker in props_data.get('bookmakers', []):
                if bookmaker['key'] in ['fanduel', 'draftkings']:
                    book_name = bookmaker['title']
                    for market in bookmaker.get('markets', []):
                        if market['key'] == prop_market:
                            for outcome in market['outcomes']:
                                player = outcome['description']
                                if player not in all_players:
                                    all_players[player] = {
                                        'home': home, 'away': away,
                                        'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                        'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                        'Projection': None, 'Edge': None, 'Play': None,
                                        'Tier': None, 'EV%': None, 'MM Tier': None, 'Low Confidence': None,
                                        'Fair Odds': None, 'Edge Cents': None, 'Direction': None, 'Odds': None,
                                        'Model Prob': None, 'No Vig Prob': None
                                    }
                                if 'FanDuel' in book_name:
                                    all_players[player]['FanDuel Line'] = outcome['point']
                                    if outcome['name'] == 'Over':
                                        all_players[player]['FanDuel Over'] = outcome['price']
                                    else:
                                        all_players[player]['FanDuel Under'] = outcome['price']
                                elif 'DraftKings' in book_name:
                                    all_players[player]['DraftKings Line'] = outcome['point']
                                    if outcome['name'] == 'Over':
                                        all_players[player]['DraftKings Over'] = outcome['price']
                                    else:
                                        all_players[player]['DraftKings Under'] = outcome['price']
        return all_players
    except Exception:
        return {}

def run_all_nba_projections(all_players, run_fn, sport_key, season, progress_callback=None):
    """Runs the projection + EV pipeline for every player in all_players (mutated in place),
    saves each as a prediction, and returns the results dict.
    progress_callback(i, total, name), if given, is called before each player runs."""
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
            season_end_year = int(season.split("-")[0]) + 1
            check_df, _ = get_bref_player_game_log(player, season_end_year)
            if check_df.empty:
                continue
            last_row = check_df.iloc[-1]
            location_val = last_row.get('location')
            home_or_away = 'home' if 'HOME' in str(location_val).upper() else 'away'
            opp_abbrev = away_abbrev if home_or_away == 'home' else home_abbrev
        except:
            home_or_away = 'home'
            opp_abbrev = away_abbrev

        result = cached_run_nba_projection(
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
                    'Edge Cents': ev_result['edge_cents'] if ev_result else None,
                    'Direction': direction,
                    'Odds': over_odds if direction == 'over' else under_odds,
                    'Model Prob': ev_result['model_prob'] if ev_result else None,
                    'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
                })
                results[player] = result
                bet_sport_label = nba_bet_sport_label(sport_key)
                save_prediction({
                    'date': date.today().strftime('%Y-%m-%d'),
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
                })
    return results

def run_todays_card_auto_run(minimal_ui=False):
    """Loads and runs today's MLB + NBA models if not already done this session.
    minimal_ui=False (Today's Card): shows the detailed technical checklist.
    minimal_ui=True (Home): shows polished, on-brand copy instead — a first-time
    visitor landing on the homepage shouldn't see raw step names like "Loading
    NBA assists props," that reads like an unfinished dev tool, not a product."""
    if st.session_state.get('today_card_auto_ran'):
        return

    steps = [
        "Loading MLB props", "Running MLB projections",
        "Loading NBA points props", "Running NBA points projections",
        "Loading NBA assists props", "Running NBA assists projections",
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

    if 'all_pitchers' not in st.session_state:
        render("Loading MLB props")
        mlb_props = load_mlb_props_data()
        completed.append("Loading MLB props")
        if mlb_props:
            render("Running MLB projections")
            mlb_results = run_all_mlb_projections(mlb_props, '2026')
            completed.append("Running MLB projections")
            st.session_state['all_pitchers'] = mlb_props
            st.session_state['pitcher_results'] = mlb_results
            st.session_state['season'] = '2026'
            st.session_state.setdefault('manual_run_order', {})
            st.session_state.setdefault('manual_run_counter', 0)
        else:
            completed.append("Running MLB projections")
    else:
        completed.extend(["Loading MLB props", "Running MLB projections"])

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
    nav_options = ["🏠 Home", "🎯 Today's Card", "⚾ MLB Models", "🏈 NFL Models", "🏀 NBA Models", "📒 Bet Tracker", "📊 Model Performance"] + admin_nav + ["⚙️ Settings"]
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

# ---- HOME PAGE ----
if nav == "🏠 Home":
    _bankroll_settings = get_user_settings()
    _has_bankroll = bool(_bankroll_settings and _bankroll_settings.get('starting_bankroll') is not None)

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

    st.markdown("""
        <div style='text-align: center; padding: 8px 0 4px 0;'>
            <div style='color: var(--mm-accent); font-family: var(--mm-mono); font-size: 0.8rem; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 14px;'>
                Player Prop Analytics
            </div>
            <h1 style='font-size: 3rem; margin: 0 0 14px 0; line-height: 1.1;'>Sharp Data. Sharp Bets.</h1>
        </div>
    """, unsafe_allow_html=True)

    run_todays_card_auto_run(minimal_ui=True)
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
    col1, col2, col3 = st.columns(3)
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
    st.caption("Ranked, not listed. Loads and runs today's MLB + NBA models automatically.")

    run_todays_card_auto_run(minimal_ui=True)

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
                if show_why_expander and e['result']:
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
    bankroll, risk_style = get_bankroll_context()
    already_bet_today = get_already_bet_players_today('MLB')

    col_load, col_run_all = st.columns(2)

    with col_load:
        if st.button("📋 Load Today's Props", use_container_width=True):
            with st.spinner("Pulling today's props..."):
                all_pitchers = load_mlb_props_data()
                if all_pitchers:
                    st.session_state['all_pitchers'] = all_pitchers
                    st.session_state['season'] = '2026'
                    st.session_state['pitcher_results'] = {}
                    st.session_state['manual_run_order'] = {}
                    st.session_state['manual_run_counter'] = 0
                else:
                    st.error("Couldn't load today's props — no games found or the odds API request failed.")

    with col_run_all:
        if st.button("🚀 Run All Projections", use_container_width=True):
            if 'all_pitchers' not in st.session_state:
                st.warning("Load today's props first!")
            else:
                all_pitchers = st.session_state['all_pitchers']
                season = st.session_state.get('season', '2026')
                progress_bar = st.progress(0)
                status_text = st.empty()
                total = len(all_pitchers)

                def _update_progress(i, total, name):
                    status_text.text(f"Running {i+1} of {total}: {name}")
                    progress_bar.progress((i + 1) / total)

                pitcher_results = run_all_mlb_projections(all_pitchers, season, progress_callback=_update_progress)
                st.session_state['all_pitchers'] = all_pitchers
                st.session_state['pitcher_results'] = pitcher_results

                status_text.text(f"✅ Done! All {total} projections complete.")
                progress_bar.progress(1.0)
                st.rerun()

    if 'all_pitchers' in st.session_state:
        all_pitchers = st.session_state['all_pitchers']
        season = st.session_state.get('season', '2026')
        pitcher_results = st.session_state.get('pitcher_results', {})

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
                                    'Edge Cents': ev_result['edge_cents'] if ev_result else None,
                                    'Low Confidence': ev_result['low_confidence'] if ev_result else None,
                                })
                                st.session_state['pitcher_results'][pitcher] = result
                                st.session_state['last_pitcher'] = pitcher
                                st.session_state.setdefault('manual_run_order', {})
                                st.session_state['manual_run_counter'] = st.session_state.get('manual_run_counter', 0) + 1
                                st.session_state['manual_run_order'][pitcher] = st.session_state['manual_run_counter']
                                save_prediction({
                                    'date': date.today().strftime('%Y-%m-%d'),
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
                        odds = int(log_odds) if log_odds else -110
                        bet_val = round(float(log_bet), 2) if log_bet else 0.0
                        profit = calc_profit(bet_val, odds, log_result)
                        save_bet({
                            'date': str(date.today()), 'pitcher': pitcher,
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
                        })
                        st.session_state[f'log_modal_{pitcher}'] = False
                        st.success(f"✅ Bet logged for {pitcher}!")
                        st.rerun()

            st.divider()

# ---- NFL PAGE ----
elif nav == "🏈 NFL Models":
    st.title("🏈 NFL Models")
    st.markdown("---")
    nfl_model = st.selectbox("Select Model", ["NFL Pass Attempts", "NFL Pass Completions", "NFL Receptions"])
    st.markdown("""
        <div style='text-align: center; padding: 80px 0;'>
            <h2>🚧 Coming Soon</h2>
            <p style='color: #64748B; font-size: 18px;'>NFL models are currently in development.<br>Check back when the season starts!</p>
        </div>
    """, unsafe_allow_html=True)

# ---- NBA PAGE ----
elif nav == "🏀 NBA Models":
    st.title("🏀 NBA Models")
    st.markdown("---")

    nba_model_select = st.selectbox("Select Model", ["NBA Points", "NBA Assists"])

    def run_nba_display(all_players_key, run_fn, sport_key, prop_market, session_key):
        bankroll, risk_style = get_bankroll_context()
        already_bet_today = get_already_bet_players_today(nba_bet_sport_label(sport_key))
        col_load, col_run_all = st.columns(2)

        with col_load:
            label = "NBA Points" if prop_market == 'player_points' else "Assist"
            if st.button(f"📋 Load Today's {label} Props", use_container_width=True, key=f"load_{session_key}"):
                with st.spinner(f"Pulling {label} props..."):
                    all_players = load_nba_props_data(prop_market)
                    if all_players:
                        st.session_state[all_players_key] = all_players
                        st.session_state['nba_season'] = '2025-26'
                        st.session_state[f'{session_key}_results'] = {}
                        st.session_state[f'manual_run_order_{session_key}'] = {}
                        st.success(f"Loaded {len(all_players)} players!")
                    else:
                        st.error("Couldn't load today's props — no games found or the odds API request failed.")

        with col_run_all:
            if st.button(f"🚀 Run All Projections", use_container_width=True, key=f"run_all_{session_key}"):
                if all_players_key not in st.session_state:
                    st.warning("Load today's props first!")
                else:
                    all_players = st.session_state[all_players_key]
                    season = st.session_state.get('nba_season', '2025-26')
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    total = len(all_players)

                    def _update_progress(i, total, name):
                        status_text.text(f"Running {i+1} of {total}: {name}")
                        progress_bar.progress((i + 1) / total)

                    results = run_all_nba_projections(all_players, run_fn, sport_key, season, progress_callback=_update_progress)
                    st.session_state[all_players_key] = all_players
                    st.session_state.setdefault(f'{session_key}_results', {})
                    st.session_state[f'{session_key}_results'].update(results)

                    status_text.text(f"✅ Done! All {total} projections complete.")
                    progress_bar.progress(1.0)
                    st.rerun()

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
                                season_end_year = int(season.split("-")[0]) + 1
                                check_df, _ = get_bref_player_game_log(player, season_end_year)
                                if not check_df.empty:
                                    last_row = check_df.iloc[-1]
                                    location_val = last_row.get('location')
                                    home_or_away = 'home' if 'HOME' in str(location_val).upper() else 'away'
                                    opp_abbrev = away_abbrev if home_or_away == 'home' else home_abbrev
                                else:
                                    home_or_away = 'home'
                                    opp_abbrev = away_abbrev
                            except:
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
                            odds = int(log_odds) if log_odds else -110
                            bet_val = round(float(log_bet), 2) if log_bet else 0.0
                            profit = calc_profit(bet_val, odds, log_result)
                            save_bet({
                                'date': str(date.today()), 'pitcher': player,
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

    sport_filter = st.selectbox("Filter by Sport", ["All", "MLB", "NBA", "NBA_AST"], key="bet_sport_filter")
    sport_query = None if sport_filter == "All" else sport_filter

    st.markdown("---")
    with st.expander("➕ Log a Bet Manually", expanded=False):
        st.caption("For bets outside today's model run (backfilling, or a prop not pulled from MLB/NBA Models). For anything you ran through the models, use the 📝 Log button on that row instead — it auto-fills everything and includes your MM Stake recommendation.")

        bet_sport = st.selectbox("Sport", ["MLB", "NBA", "NBA_AST"], key="new_bet_sport")

        col1, col2, col3 = st.columns(3)
        with col1:
            if bet_sport == "MLB":
                bt_player = st.selectbox("Pitcher", pitchers_list, index=0)
            else:
                bt_player = st.text_input("Player Name", placeholder="e.g. LeBron James")
            bt_projection = st.number_input("Your Projection", value=None, placeholder="e.g. 6.4")
            bt_opening_line = st.number_input("Book Line", value=None, placeholder="e.g. 5.5")
            bt_bet = st.number_input("Bet Amount ($)", value=None, min_value=0.0, placeholder="e.g. 100.50", step=0.01, format="%.2f")
            bt_model_edge = st.number_input("Model Edge", value=None, placeholder="e.g. 0.9")
        with col2:
            bt_date = st.date_input("Date")
            bt_over_under = st.selectbox("Over or Under?", ["Over", "Under"])
            bt_odds = st.number_input("Odds (e.g. -140 or +110)", value=None, placeholder="e.g. -140")
            bt_actual = st.number_input("Actual Statistic", value=None, placeholder="e.g. 7")
            bt_ev_pct = st.number_input("EV% at time of bet", value=None, placeholder="e.g. 6.2")
        with col3:
            bt_result = st.selectbox("Result", ["Pending", "Win", "Loss"])
            bt_confidence_tier = st.selectbox("Reliability", ["", "🟢 Reliable", "🟠 Volatile", "🔴 Uncertain Workload"])
            bt_no_vig_prob = st.number_input("No-Vig Prob", value=None, placeholder="e.g. 0.52")
            bt_model_prob = st.number_input("Model Prob", value=None, placeholder="e.g. 0.61")

        if st.button("Log Bet"):
            odds_val = bt_odds or -110
            bet_val = round(float(bt_bet), 2) if bt_bet else 0.0
            profit = calc_profit(bet_val, odds_val, bt_result)
            save_bet({
                'date': str(bt_date), 'pitcher': bt_player,
                'projection': bt_projection or 0, 'opening_line': bt_opening_line or 0,
                'over_under': bt_over_under, 'odds': odds_val,
                'bet_amount': bet_val, 'result': bt_result,
                'actual': bt_actual or 0, 'profit': profit,
                'sport': bet_sport, 'ev_pct': bt_ev_pct,
                'model_edge': bt_model_edge, 'no_vig_prob': bt_no_vig_prob,
                'model_prob': bt_model_prob, 'confidence_tier': bt_confidence_tier or None,
            })
            st.rerun()

    bets = load_bets(sport_query)

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
        today_str = date.today().strftime('%Y-%m-%d')
        all_settled_for_closing = [
            b for b in bets
            if b.get('date') and b['date'] < today_str and b.get('sport') in ('MLB', 'NBA', 'NBA_AST')
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

        st.markdown("---")
        st.subheader("📝 All Bets")
        display_df = bets_df.drop(columns=[c for c in ['created_at', 'user_id', 'mm_score', 'mm_tier'] if c in bets_df.columns], errors='ignore')
        if 'no_vig_prob' in display_df.columns:
            display_df['no_vig_prob'] = display_df['no_vig_prob'].apply(lambda v: round(v * 100, 1) if pd.notna(v) else v)
        if 'model_prob' in display_df.columns:
            display_df['model_prob'] = display_df['model_prob'].apply(lambda v: round(v * 100, 1) if pd.notna(v) else v)

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
                'result': st.column_config.SelectboxColumn('Result', options=['Pending', 'Win', 'Loss']),
                'actual': st.column_config.NumberColumn('Actual Statistic', min_value=0),
                'opening_line': st.column_config.NumberColumn('Book Line', min_value=0.0, step=0.5),
                'projection': st.column_config.NumberColumn('Projection', min_value=0.0, step=0.1),
                'bet_amount': st.column_config.NumberColumn('Bet ($)', min_value=0.0, step=0.01, format="%.2f"),
                'odds': st.column_config.NumberColumn('Odds', format="%+d"),
                'profit': st.column_config.NumberColumn('Profit ($)'),
                'over_under': st.column_config.SelectboxColumn('O/U', options=['Over', 'Under']),
                'sport': st.column_config.SelectboxColumn('Sport', options=['MLB', 'NBA', 'NBA_AST', 'NFL']),
                'ev_pct': st.column_config.NumberColumn('EV%'),
                'no_vig_prob': st.column_config.NumberColumn('No-Vig Prob (%)', min_value=0.0, max_value=100.0, step=0.1),
                'model_prob': st.column_config.NumberColumn('Model Prob (%)', min_value=0.0, max_value=100.0, step=0.1),
                'confidence_tier': st.column_config.SelectboxColumn('Reliability', options=['🟢 Reliable', '🟠 Volatile', '🔴 Uncertain Workload']),
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
                    update_bet(row_id, {
                        'actual': b.get('actual'), 'result': b.get('result'),
                        'odds': b.get('odds'), 'bet_amount': b.get('bet_amount'),
                        'opening_line': b.get('opening_line'),
                        'projection': b.get('projection'), 'over_under': b.get('over_under'),
                        'profit': b['profit'], 'sport': b.get('sport', 'MLB'),
                        'ev_pct': b.get('ev_pct'),
                        'model_edge': b.get('model_edge'),
                        'no_vig_prob': round(no_vig_val / 100, 3) if no_vig_val is not None and pd.notna(no_vig_val) else None,
                        'model_prob': round(model_prob_val / 100, 3) if model_prob_val is not None and pd.notna(model_prob_val) else None,
                        'confidence_tier': b.get('confidence_tier')
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

    lab_sport = st.selectbox("Sport", ["MLB", "NBA Points", "NBA Assists"], key="lab_sport")
    sport_key = 'MLB' if lab_sport == 'MLB' else ('NBA' if lab_sport == 'NBA Points' else 'NBA_AST')

    preds = load_predictions(sport_key)
    preds_with_actual = [p for p in preds if p.get('actual') is not None]

    st.subheader("📥 Update Actual Results")
    today_str = date.today().strftime('%Y-%m-%d')
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

        elif lab_sport == "NBA Points":
            st.subheader("🏀 NBA Points Model Performance")

        else:
            st.subheader("🏀 NBA Assists — Conversion Rate Tester")
            conversion_rate = st.select_slider("Potential Assist Conversion Rate", options=[0.42, 0.45, 0.48], value=0.45)
            st.caption(f"Testing: expected assists = potential assists × {conversion_rate}")
            if preds_with_actual:
                errors_by_rate = {rate: round(sum(abs(p['projection'] - p['actual']) for p in preds_with_actual) / len(preds_with_actual), 2) for rate in [0.42, 0.45, 0.48]}
                rate_df = pd.DataFrame([{'Conversion Rate': k, 'MAE': v} for k, v in errors_by_rate.items()])
                st.dataframe(rate_df, use_container_width=True)
                best_rate = min(errors_by_rate, key=errors_by_rate.get)
                st.success(f"✅ Best conversion rate so far: **{best_rate}** with MAE of **{errors_by_rate[best_rate]}**")

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

# ---- BACKTEST (ADMIN ONLY) ----
elif nav == "🧪 Backtest" and is_admin:
    st.title("🧪 Backtest")

    with st.expander("🔧 Player Game Log Diagnostic (debug)"):
        st.caption("Checks the raw season game log for one player — specifically whether it's in chronological order, since 'last 5/10 games' depends entirely on that.")
        debug_player = st.text_input("Player name", value="Nikola Jokić", key="debug_player_name")
        debug_season_end_year = st.number_input("Season end year", value=2026, key="debug_season_end_year")
        if st.button("Check Game Log"):
            debug_df, debug_slug = get_bref_player_game_log(debug_player, int(debug_season_end_year))
            if debug_df.empty:
                st.error(f"No game log returned (slug resolved to: {debug_slug})")
            else:
                st.write(f"Resolved slug: **{debug_slug}** — {len(debug_df)} games found")
                st.write("Columns:", debug_df.columns.tolist())
                st.write("**First 3 rows (should be EARLIEST games if chronological):**")
                st.dataframe(debug_df.head(3))
                st.write("**Last 3 rows (should be MOST RECENT games if chronological):**")
                st.dataframe(debug_df.tail(3))

    backtest_sport = st.selectbox("Sport", ["MLB Strikeouts", "NBA Points", "NBA Assists"], key="backtest_sport")
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

    else:
        backtest_season_nba = st.selectbox("Season", ["2025-26", "2024-25", "2023-24"], key="backtest_season_nba")
        is_assists = backtest_sport == "NBA Assists"
        max_players = st.number_input(
            "Max players to test", min_value=5, max_value=200, value=15, step=5,
            help="Basketball-Reference scraping is slower per player than an API call. Keep this small for a quick test — a big slate (like Christmas Day) can have 80-100+ players and take long enough to hit a timeout. Raise this once you've confirmed it works."
        )

        if st.button("🔍 Load NBA Games & Run Projections", use_container_width=True):
            with st.spinner(f"Pulling NBA games for {backtest_date}..."):
                box_df = get_bref_games_for_date(backtest_date.year, backtest_date.month, backtest_date.day)
                if box_df.empty:
                    st.error("No NBA games found for that date (Basketball-Reference)")
                else:
                    box_df = box_df.head(int(max_players))
                    with st.expander("🔧 Raw data preview (debug)"):
                        st.write("Columns:", box_df.columns.tolist())
                        st.dataframe(box_df.head(3))
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results = []
                    total = len(box_df)
                    for i, row in box_df.iterrows():
                        status_text.text(f"Processing player {i+1} of {total}")
                        progress_bar.progress((i+1) / total)
                        try:
                            player_name = row.get('name')
                            if is_assists:
                                actual_val = row.get('assists')
                                if pd.isna(actual_val):
                                    actual_val = None
                            else:
                                fg = row.get('made_field_goals')
                                fg3 = row.get('made_three_point_field_goals')
                                ft = row.get('made_free_throws')
                                if pd.notna(fg) and pd.notna(fg3) and pd.notna(ft):
                                    actual_val = 2 * fg + fg3 + ft
                                else:
                                    actual_val = None
                            if player_name is None or actual_val is None:
                                continue
                            team_val = row.get('team')
                            opponent_val = row.get('opponent')
                            location_val = row.get('location')
                            team_name = team_val.value.replace('_', ' ').title() if hasattr(team_val, 'value') else str(team_val).replace('_', ' ').title()
                            opp_name = opponent_val.value.replace('_', ' ').title() if hasattr(opponent_val, 'value') else str(opponent_val).replace('_', ' ').title()
                            home_or_away = 'home' if 'HOME' in str(location_val).upper() else 'away'
                            home_name = team_name if home_or_away == 'home' else opp_name
                            away_name = opp_name if home_or_away == 'home' else team_name
                            opp_abbrev = nba_name_to_abbrev.get(opp_name, '')
                            if is_assists:
                                result = run_nba_assists_projection(player_name, opp_abbrev, home_name, away_name, home_or_away, backtest_season_nba)
                            else:
                                result = run_nba_points_projection(player_name, opp_abbrev, home_name, away_name, home_or_away, backtest_season_nba)
                            time.sleep(0.5)
                            if result:
                                results.append({
                                    'Player': player_name,
                                    'Matchup': f"{away_name} @ {home_name}",
                                    'Projection': result['projection'], 'Actual': actual_val,
                                    'Error': round(abs(result['projection'] - actual_val), 1),
                                    'Tier': result['confidence_tier']
                                })
                        except:
                            continue
                    st.session_state['backtest_results'] = results
                    st.session_state['backtest_date'] = backtest_date.strftime('%Y-%m-%d')
                    status_text.text(f"✅ Done! {len(results)} players projected.")
                    progress_bar.progress(1.0)

    if 'backtest_results' in st.session_state and st.session_state['backtest_results']:
        st.markdown("---")
        st.subheader(f"📋 Results for {st.session_state.get('backtest_date', '')}")
        results_df = pd.DataFrame(st.session_state['backtest_results'])
        st.dataframe(results_df.sort_values('Error'), use_container_width=True)
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        col1.metric("Avg Error (MAE)", f"{round(results_df['Error'].mean(), 2)}")
        col2.metric("Best Projection", f"{results_df['Error'].min()} error")
        col3.metric("Worst Projection", f"{results_df['Error'].max()} error")
        if 'Tier' in results_df.columns:
            st.markdown("---")
            st.subheader("🎯 MAE by Confidence Tier")
            tier_summary = results_df.groupby('Tier').agg(Predictions=('Error', 'count'), MAE=('Error', 'mean')).reset_index()
            tier_summary['MAE'] = tier_summary['MAE'].round(2)
            st.dataframe(tier_summary, use_container_width=True)

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
    st.info("💳 Subscription management coming soon — stay tuned!")
    st.markdown("---")
    st.subheader("Danger Zone")
    if st.button("🚪 Logout", use_container_width=True):
        sign_out()
        st.rerun()
