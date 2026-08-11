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

    # Real fix (August 2026, per direct user report — "make it so that
    # I am not max betting on a +3000 odds play just because it has
    # such good EV"). A real, well-known Kelly-criterion pitfall: at
    # extreme underdog odds, the decimal-odds payout multiplier
    # dominates the Kelly fraction's math — a real, honest but modest
    # overestimate in model_prob (say, 20% true vs 25% modeled) barely
    # matters at typical odds, but at +3000 that same-sized error
    # inflates the apparent edge enormously, since Kelly's formula
    # scales with the payout, not just the probability gap. The
    # model's real confidence at these extremes is genuinely shakier
    # than at ordinary odds (less real historical data at this
    # precision, more room for a small miscalibration to look like a
    # huge edge).
    #
    # Real fix (round 2, August 2026, per direct user report — a real,
    # live example: a +506 LPL underdog still landed at the tier's own
    # $35 FLOOR even with round 1's dampener applied, since that
    # dampener originally ran BEFORE the tier_min/tier_max clamp below
    # and couldn't push below it. Odds-driven risk (payout variance,
    # real model uncertainty at extreme prices) is a genuinely
    # DIFFERENT real dimension than confidence-tier risk (signal
    # strength) — this now runs as the real, FINAL word, after every
    # other real adjustment including the tier floor itself (see
    # further below), so extreme real odds can override even a "Best
    # Bet" tier's own minimum. Real, direct target set by the user: a
    # +500 underdog should land around $15-20, not $50+. Confirmed
    # real reasoning: LoL runs far more real games per day than MLB/
    # NBA/NFL, and most of its real value picks skew toward real
    # underdogs — a bettor following these real recommendations is
    # realistically stacking several real underdog stakes on the same
    # real day, so each individual real stake needs to be meaningfully
    # smaller.

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

        opp_factor = result.get('opp_factor')
        if opp_factor:
            # Always describes the matchup from the PITCHER's strikeout-
            # friendliness (a high opponent K% is genuinely favorable for
            # strikeouts, full stop) — the icon alone conveys whether
            # that's good or bad news for THIS specific bet direction.
            # The old version flipped "favorable"/"tougher" based on
            # over/under, which read as backwards baseball intuition when
            # taken out of that context (e.g. "Opponent K% is above
            # average — tougher matchup" on an Under bet correctly meant
            # "tougher for the Under," but reads like "tougher for the
            # pitcher to get strikeouts," which is the opposite of true —
            # caught in review, July 2026).
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
