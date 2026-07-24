"""
bet_math.py — pure betting-math functions, extracted from mlb_app.py
(July 2026, per external review, items 8 and 12).

Every function and constant here is genuinely self-contained: no
Streamlit, no Supabase, no network calls, no external API keys. That
makes this the safest possible first piece to extract out of the
single-file app — exactly the "move one stable section at a time and
verify imports still work" approach the review recommended, rather
than attempting a large, risky rewrite all at once.

This module is imported directly by mlb_app.py (which no longer
defines these functions inline — see the import line near the top of
that file) AND by test_bet_math.py, which contains real, automated
tests against this actual code — not a hand-copied duplicate that
could quietly drift out of sync with what's really running in
production.

Depends only on the Python standard library and scipy.stats (for the
normal-distribution probability calculation).
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from scipy import stats


def mm_today_str():
    """'Today' in Eastern Time, not the server's clock (likely UTC) — matters for
    cache date keys since MLB's day rolls over on Eastern time, not UTC."""
    return datetime.now(ZoneInfo("America/New_York")).strftime('%Y-%m-%d')


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
    except Exception:
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
    if v is None or (isinstance(v, float) and v != v):  # v != v is a NaN check without needing pandas
        return "—"
    if abs(v) < 10 ** (-decimals) / 2:
        return f"{0:.{decimals}f}"
    sign = "+" if v > 0 else ""
    return f"{sign}{round(v, decimals)}"


def calc_profit(bet_amount, odds, result):
    if result == 'Win':
        if odds > 0:
            return round(bet_amount * (odds / 100), 2)
        else:
            return round(bet_amount * (100 / abs(odds)), 2)
    elif result == 'Loss':
        return -bet_amount
    return 0.0


def calc_profit_this_month(bets):
    month_prefix = mm_today_str()[:7]  # 'YYYY-MM'
    return round(sum(
        (b.get('profit') or 0) for b in bets
        if b.get('result') != 'Pending' and (b.get('date') or '').startswith(month_prefix)
    ), 2)


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


# ---- BANKROLL / MM STAKE ----
RISK_STYLE_CAPS = {'Conservative': 0.01, 'Standard': 0.02, 'Aggressive': 0.03}
# Scales the tier unit ranges themselves (not just the final $ cap) so Aggressive
# genuinely recommends bigger individual stakes and Conservative genuinely
# recommends smaller ones — matches the same 1%/2%/3% ratio as the caps above.
RISK_STYLE_RANGE_MULTIPLIER = {'Conservative': 0.5, 'Standard': 1.0, 'Aggressive': 1.5}

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
