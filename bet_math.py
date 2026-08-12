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

    # Real, final override — runs AFTER the tier floor/ceiling and the
    # near-max gate above, specifically so it can push below even a
    # tier's own stated minimum for genuinely extreme real odds.
    if odds is not None and odds > 0:
        if odds >= 3000:
            stake_units *= 0.08
            reasoning.append("Extreme long-shot odds (+3000 or higher) sharply reduced stake — small model errors are massively amplified at these odds")
        elif odds >= 2000:
            stake_units *= 0.12
            reasoning.append("Very long-shot odds (+2000 to +2999) sharply reduced stake")
        elif odds >= 1000:
            stake_units *= 0.20
            reasoning.append("Long-shot odds (+1000 to +1999) sharply reduced stake")
        elif odds >= 500:
            stake_units *= 0.30
            reasoning.append("Real underdog odds (+500 to +999) sharply reduced stake")
        elif odds >= 300:
            stake_units *= 0.55
            reasoning.append("Moderate underdog odds (+300 to +499) reduced stake")

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


# Real, moved from mlb_app.py (August 2026, per direct user request —
# "the why this bet" and "MM stake" shown on the new Next.js site too,
# not just Streamlit). Both functions were already pure, real logic
# with zero real Streamlit dependencies, confirmed line by line before
# moving — living here now means api_server.py can call the exact same
# real logic mlb_app.py uses, with zero real risk of the two products'
# explanations drifting out of sync over time.

def fmt_odds(o):
    if o is None:
        return 'N/A'
    return f"+{o}" if o > 0 else str(o)


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
    recent_5ip_count = result.get('recent_5ip_starts_count')

    if "Stable" in workload_tier:
        if recent_5ip_count is not None and recent_5ip_count >= 3 and last5_avg_ip is not None and season_avg_ip is not None:
            return f"✅ {recent_5ip_count} of his last 5 starts have gone 5+ IP — averaging **{last5_avg_ip} IP** over that stretch, in line with his **{season_avg_ip} IP** season average"
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
            lines.append(f"{icon} Usage Workload: **{workload_tier}**{workload_note}")

        evidence_line = workload_evidence_line(result)
        if evidence_line:
            lines.append(evidence_line)

        def _dir_icon(factor_boosts_stat):
            """✅ if this factor works in favor of the bet's actual direction, ⚠️ if against it."""
            if direction == 'over':
                return "✅" if factor_boosts_stat else "⚠️"
            else:
                return "⚠️" if factor_boosts_stat else "✅"

        # ---- MLB-SPECIFIC FACTORS ----
        # Real fix (August 2026) — gated to MLB only. Previously the
        # opp_factor block was ungated, which meant NFL's own, different
        # opp_factor (opponent pass funnel, not opponent K%) would
        # incorrectly produce "Opponent K% is above average" text for
        # NFL picks. park_factor/umpire_factor/lineup_factor naturally
        # only fire for MLB (only MLB results have those fields), but
        # opp_factor exists in both MLB and NFL results.
        if sport == 'mlb_strikeouts':
            opp_factor = result.get('opp_factor')
            if opp_factor:
                if opp_factor >= 1.05:
                    lines.append(f"{_dir_icon(True)} Opponent K% is **above average** — favorable matchup for strikeouts")
                elif opp_factor <= 0.95:
                    lines.append(f"{_dir_icon(False)} Opponent K% is **below average** — tougher matchup for strikeouts")
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

        # ---- NBA-SPECIFIC FACTORS ----
        if sport in ('nba_points', 'nba_assists'):
            opp_pace = result.get('opp_pace')
            if opp_pace:
                league_avg_pace = 98.5
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
                league_avg_def_rating = 114.0
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

        # ---- NFL-SPECIFIC FACTORS ----
        # Real, new addition (August 2026, per direct user request —
        # "why this bet" for NFL). Mirrors the depth of the MLB/NBA
        # branches above, using only fields that actually exist in the
        # real NFL projection result dicts (confirmed by inspecting
        # run_nfl_pass_attempts_projection, run_nfl_pass_completions_
        # projection, and run_nfl_receptions_projection directly).
        if sport in ('nfl_pass_attempts', 'nfl_pass_completions', 'nfl_receptions'):
            game_context = result.get('game_context') or {}

            # -- Game script (spread) --
            # A team's spread directly impacts expected passing volume:
            # underdogs tend to throw more (playing catch-up), favorites
            # tend to throw less (protecting a lead with the run game).
            spread = game_context.get('spread')
            if spread is not None:
                if spread >= 6:
                    lines.append(f"{_dir_icon(True)} Spread: **+{spread}** (big underdog) — game script favors more passing volume")
                elif spread >= 3:
                    lines.append(f"{_dir_icon(True)} Spread: **+{spread}** (underdog) — likely chasing, boosting pass volume")
                elif spread <= -6:
                    lines.append(f"{_dir_icon(False)} Spread: **{spread}** (big favorite) — game script favors running the ball late")
                elif spread <= -3:
                    lines.append(f"{_dir_icon(False)} Spread: **{spread}** (favorite) — may lean on the run game with a lead")
                else:
                    lines.append(f"➖ Spread: **{'+' if spread > 0 else ''}{spread}** — close game expected, neutral game script")

            # -- Game total --
            # A higher total implies a shootout (more possessions, more
            # passing), a lower total implies a grind-it-out game.
            total = game_context.get('total')
            if total is not None:
                if total >= 49:
                    lines.append(f"{_dir_icon(True)} Game total: **{total}** — shootout expected, more passing volume likely")
                elif total >= 45:
                    lines.append(f"{_dir_icon(True)} Game total: **{total}** — above-average total, slightly higher volume expected")
                elif total <= 39:
                    lines.append(f"{_dir_icon(False)} Game total: **{total}** — low total, a grind-it-out defensive game expected")
                elif total <= 42:
                    lines.append(f"{_dir_icon(False)} Game total: **{total}** — below-average total, lower volume expected")
                else:
                    lines.append(f"➖ Game total: **{total}** — near average, neutral volume signal")

            # -- Weather (wind) --
            wind = game_context.get('wind')
            roof = game_context.get('roof')
            if roof in ('dome', 'closed'):
                lines.append("✅ Playing indoors — no weather risk to passing")
            elif roof in ('outdoors', 'open') and wind is not None:
                if wind >= 20:
                    lines.append(f"{_dir_icon(False)} Wind: **{wind} mph** — significant passing-game risk, both volume and accuracy affected")
                elif wind >= 15:
                    lines.append(f"{_dir_icon(False)} Wind: **{wind} mph** — moderate wind, a real factor for the passing game")

            # -- Rest days --
            rest_days = game_context.get('rest_days')
            if rest_days is not None:
                if rest_days <= 4:
                    lines.append(f"⚠️ Short week (**{rest_days} days rest**) — less prep time, often a simpler game plan")
                elif rest_days >= 10:
                    lines.append(f"✅ Extra rest (**{rest_days} days**) — more prep time and recovery")

            # -- Opponent factor (shared across all 3 NFL models) --
            opp_factor = result.get('opp_factor')
            if opp_factor is not None and opp_factor != 1.0:
                if sport == 'nfl_pass_attempts':
                    if opp_factor >= 1.05:
                        lines.append(f"{_dir_icon(True)} Opponent pass-funnel factor: **{opp_factor}** — this defense tends to face more passing than average")
                    elif opp_factor <= 0.95:
                        lines.append(f"{_dir_icon(False)} Opponent pass-funnel factor: **{opp_factor}** — this defense limits opposing pass volume")
                    else:
                        lines.append(f"➖ Opponent pass-funnel factor: **{opp_factor}** — near league average")
                elif sport == 'nfl_pass_completions':
                    if opp_factor >= 1.05:
                        lines.append(f"{_dir_icon(True)} Opponent completion factor: **{opp_factor}** — this defense allows a higher completion rate")
                    elif opp_factor <= 0.95:
                        lines.append(f"{_dir_icon(False)} Opponent completion factor: **{opp_factor}** — this defense suppresses completion rate")
                    else:
                        lines.append(f"➖ Opponent completion factor: **{opp_factor}** — near league average")

            # -- Pass Attempts-specific factors --
            if sport == 'nfl_pass_attempts':
                # QB rushing tendency — a mobile QB converts some
                # would-be pass attempts into scrambles.
                qb_carries = result.get('qb_carries_per_game')
                qb_rush_factor = result.get('qb_rush_factor')
                if qb_carries is not None and qb_rush_factor is not None and qb_rush_factor < 0.99:
                    lines.append(f"{_dir_icon(False)} QB averages **{qb_carries:.1f} carries/game** — mobile QB, some dropbacks become scrambles instead of pass attempts")

                # Vegas factor — overall game-environment adjustment
                vegas_factor = result.get('vegas_factor')
                if vegas_factor is not None and abs(vegas_factor - 1.0) >= 0.02:
                    vegas_pct = round((vegas_factor - 1.0) * 100, 1)
                    icon = _dir_icon(vegas_factor > 1.0)
                    lines.append(f"{icon} Vegas environment adjustment: **{'+' if vegas_pct > 0 else ''}{vegas_pct}%** based on spread + game total combined")

            # -- Pass Completions-specific factors --
            elif sport == 'nfl_pass_completions':
                proj_comp_pct = result.get('projected_completion_pct')
                proj_attempts = result.get('projected_attempts')
                if proj_comp_pct is not None and proj_attempts is not None:
                    lines.append(f"📊 Built from **{proj_attempts}** projected attempts × **{round(proj_comp_pct * 100, 1)}%** completion rate")

                opp_comp_pct_allowed = result.get('opp_completion_pct_allowed')
                if opp_comp_pct_allowed is not None:
                    opp_pct_display = round(opp_comp_pct_allowed * 100, 1)
                    if opp_comp_pct_allowed >= 0.67:
                        lines.append(f"{_dir_icon(True)} Opponent allows **{opp_pct_display}%** completions — soft secondary")
                    elif opp_comp_pct_allowed <= 0.61:
                        lines.append(f"{_dir_icon(False)} Opponent allows **{opp_pct_display}%** completions — tough secondary")

                weather_factor = result.get('weather_factor')
                if weather_factor is not None and weather_factor < 0.99:
                    lines.append(f"{_dir_icon(False)} Weather is impacting projected completion rate (factor: **{weather_factor}**)")

            # -- Receptions-specific factors --
            elif sport == 'nfl_receptions':
                target_share = result.get('projected_target_share')
                proj_team_attempts = result.get('projected_team_attempts')
                catch_rate = result.get('projected_catch_rate')
                if target_share is not None and proj_team_attempts is not None and catch_rate is not None:
                    lines.append(f"📊 Built from **{proj_team_attempts}** team attempts × **{round(target_share * 100, 1)}%** target share × **{round(catch_rate * 100, 1)}%** catch rate")

                opp_targets_allowed = result.get('opp_targets_allowed')
                if opp_targets_allowed is not None:
                    if opp_targets_allowed >= 35:
                        lines.append(f"{_dir_icon(True)} Opponent allows **{opp_targets_allowed:.1f}** WR/TE targets per game — soft coverage")
                    elif opp_targets_allowed <= 28:
                        lines.append(f"{_dir_icon(False)} Opponent allows **{opp_targets_allowed:.1f}** WR/TE targets per game — tight coverage")

                opp_catch_rate = result.get('opp_catch_rate_allowed')
                if opp_catch_rate is not None:
                    opp_cr_display = round(opp_catch_rate * 100, 1)
                    if opp_catch_rate >= 0.72:
                        lines.append(f"{_dir_icon(True)} Opponent allows **{opp_cr_display}%** catch rate — receivers complete at a high rate against them")
                    elif opp_catch_rate <= 0.62:
                        lines.append(f"{_dir_icon(False)} Opponent allows **{opp_cr_display}%** catch rate — difficult to haul in passes against them")

                share_cv = result.get('target_share_cv')
                if share_cv is not None:
                    if share_cv >= 0.60:
                        lines.append(f"⚠️ Target share volatility is **high** (CV: {share_cv}) — this player's usage varies significantly week to week")
                    elif share_cv <= 0.30:
                        lines.append(f"✅ Target share volatility is **low** (CV: {share_cv}) — consistent, stable role in the offense")

            # -- Prior-season bridge (shared across all 3 NFL models) --
            prior_weight = result.get('prior_season_weight')
            if prior_weight is not None and prior_weight > 0:
                prior_pct = round(prior_weight * 100)
                starts = result.get('starts_this_season', result.get('games_this_season'))
                team_changed = result.get('team_changed')
                bridge_note = f"⚠️ Limited current-season data (**{starts}** game{'s' if starts != 1 else ''} so far) — projection blends **{prior_pct}%** prior-season data"
                if team_changed:
                    bridge_note += " (reduced further — QB changed teams)"
                lines.append(bridge_note)

    return lines
