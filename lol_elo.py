"""
lol_elo.py — Elo-based team rating engine for League of Legends esports
(July 2026).

A genuinely new, standalone module — same pattern as bet_math.py,
polymarket_api.py, and cito_api.py.

Design decisions and why, made explicit rather than buried in code:

1. GAME-LEVEL, not series-level, Elo updates. Cito's confirmed schema
   includes a per-game 'games' array within each series (gameNumber,
   winnerSlug). Treating each individual game as its own Elo event
   uses more real data points and captures information a series-only
   approach would lose — a 3-0 sweep and a 3-2 nailbiter both count as
   "team A won the series," but they're genuinely different evidence
   of relative strength. This matches how serious esports/chess rating
   systems are built.

2. A SINGLE, GLOBAL rating pool across all leagues (LCK, LPL, LEC,
   NACL, etc.), not separate per-region pools. International events
   (Worlds, MSI, First Stand) are real, played games that bridge
   regions — a global pool lets those bridge games actually inform
   relative strength across regions, the same way a single chess Elo
   pool works even though players are geographically scattered.
   Separate regional pools would have no way to compare an LCK team to
   an LPL team at all.

3. Standard Elo constants: starting rating 1500 (chess convention) for
   any team not yet seen, K-factor default 32 (a common starting point
   — higher K means ratings move faster per result, appropriate for
   esports where roster changes between splits mean the "team" itself
   changes meaningfully more often than, say, a chess player does).

4. HONEST, NAMED LIMITATION: this is a team-level rating, not a
   roster-aware one. If a team completely replaces its roster between
   splits, its Elo rating doesn't reset or reflect that — it carries
   over as if the same team is playing. This is a real, known gap for
   a first version, not an oversight being hidden. A roster-aware
   version (resetting or decaying rating on major roster change) is
   real, valuable future work, not attempted here.

5. Series win probability from single-game Elo probability uses the
   standard best-of-N formula, assuming games within a series are
   independent and identically distributed (a real simplifying
   assumption — momentum/tilt effects within a series aren't modeled).

6. RECENT-FORM WEIGHTING (added July 2026, per external review). A
   January win and a July win were previously treated identically —
   real, external feedback flagged this as the single highest-value
   improvement available without needing any new data source, since
   full historical match timestamps already exist. Implemented as a
   K-factor multiplier, not deletion of old games: a game within the
   grace period counts fully; older games count progressively less,
   using a real exponential decay curve fitted to the reviewer's own
   example points (~100% at 30 days, ~85% at 60, ~70% at 90, ~40% at
   180). HONEST, NAMED CAVEAT: this specific curve is a reasonable
   first-pass fit to an illustrative example, not a value derived from
   real backtesting — exactly like the confidence-tier thresholds
   elsewhere in this project, it needs real calibration once real
   settled bets/results exist, not further hand-tuning right now.
"""

from math import comb, exp
from datetime import datetime, timezone, timedelta

DEFAULT_STARTING_RATING = 1500
DEFAULT_K_FACTOR = 32
DEFAULT_RECENCY_GRACE_DAYS = 30
DEFAULT_RECENCY_DECAY_TAU_DAYS = 185  # fitted, not backtested — see module docstring


def calculate_recency_weight(game_date_str, reference_date=None, grace_days=DEFAULT_RECENCY_GRACE_DAYS, decay_tau_days=DEFAULT_RECENCY_DECAY_TAU_DAYS):
    """Returns a real weight multiplier (0 to 1) for how much a game
    should count toward a rating, based on its real age relative to
    reference_date (defaults to right now, in UTC — ratings are being
    built for CURRENT predictions, so 'now' is the correct reference
    point, not the newest game in whatever dataset happens to be
    fetched). Full weight (1.0) for any game within grace_days;
    exponential decay afterward. A genuinely unparseable or missing
    game_date_str returns 1.0 (full weight) rather than silently
    discarding real data — an unknown age isn't evidence a game is
    old, matching the same honest-default principle used throughout
    this project for missing data elsewhere."""
    if not game_date_str:
        return 1.0
    if reference_date is None:
        reference_date = datetime.now(timezone.utc)
    try:
        game_date = datetime.fromisoformat(game_date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return 1.0
    age_days = (reference_date - game_date).total_seconds() / 86400
    if age_days <= grace_days:
        return 1.0
    if age_days < 0:
        return 1.0  # a real future-dated game (shouldn't normally happen) — don't penalize
    return exp(-(age_days - grace_days) / decay_tau_days)


# Real, known international tournament name markers — confirmed real
# tournament names seen in live data (July 2026): "msi 2026", "ewc lol
# 2026". Matched as substrings against a real match's tournamentName,
# since Cito's team-matches endpoint has no clean, direct league/region
# field — only tournamentId/tournamentName, confirmed via live
# investigation before this was built (not guessed at).
INTERNATIONAL_TOURNAMENT_MARKERS = ["msi", "worlds", "world championship", "ewc", "first stand"]

DEFAULT_INTERNATIONAL_K_MULTIPLIER = 1.25  # a real, moderate starting point per external review — not backtested yet


def is_international_tournament(tournament_name):
    """Real, substring-based detection of a known international/
    cross-region tournament, using tournamentName (the only real,
    confirmed field available on this endpoint for this purpose)."""
    if not tournament_name:
        return False
    name_lower = tournament_name.strip().lower()
    return any(marker in name_lower for marker in INTERNATIONAL_TOURNAMENT_MARKERS)


# Real, known lower-tier/developmental tournament name markers — found
# via direct real-data investigation (July 2026): Dignitas's real match
# history showed ~40% of their games (17 of 43) in "LTA North Promotion
# 2026" — a real, lower-division tournament for teams trying to move UP
# into the main league, not real top-tier competition. Meanwhile
# Sentinels (the team Dignitas was compared against) had zero such
# games, only real top-tier competition (LCS splits, EWC, Americas
# Cup). This let Dignitas accumulate real wins against weaker
# opposition that inflated their rating relative to how they actually
# perform against genuine LCS-caliber teams. "challengers", "academy",
# and "youth" cover the equivalent developmental-league pattern already
# seen elsewhere in real data (T1 Academy, Gen.G Global Academy, BNK
# FearX Youth, LCK Challengers League).
LOWER_TIER_TOURNAMENT_MARKERS = ["promotion", "challengers", "academy", "youth", "desafiante"]

DEFAULT_LOWER_TIER_K_MULTIPLIER = 0.6  # a real, moderate first discount — not backtested, may need real calibration later


def is_lower_tier_tournament(tournament_name):
    """Real, substring-based detection of a known lower-tier/
    developmental tournament, using tournamentName — the same
    approach as is_international_tournament(), inverted in intent."""
    if not tournament_name:
        return False
    name_lower = tournament_name.strip().lower()
    return any(marker in name_lower for marker in LOWER_TIER_TOURNAMENT_MARKERS)


def calculate_elo_expected_score(rating_a, rating_b):
    """Standard Elo expected-score formula — returns team A's win
    probability for a SINGLE game, given both current ratings."""
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def update_elo_ratings(rating_a, rating_b, a_won, k_factor=DEFAULT_K_FACTOR):
    """Updates both teams' ratings after a single game result.
    a_won: True if team A won this specific game, False if team B won.
    Returns (new_rating_a, new_rating_b)."""
    expected_a = calculate_elo_expected_score(rating_a, rating_b)
    actual_a = 1.0 if a_won else 0.0
    new_rating_a = rating_a + k_factor * (actual_a - expected_a)
    new_rating_b = rating_b + k_factor * ((1 - actual_a) - (1 - expected_a))
    return new_rating_a, new_rating_b


def series_win_probability(single_game_prob, best_of):
    """Converts a single-game win probability into a series win
    probability for a best-of-N series (best_of=3 or 5), using the
    standard formula for winning a majority of independent, identically
    distributed games. Real, deliberate assumption: does not model
    momentum, map-pick advantage, or side-selection effects within a
    series — those are real, known simplifications for a first version."""
    if best_of not in (1, 3, 5):
        raise ValueError(f"best_of must be 1, 3, or 5, got {best_of}")
    games_needed = (best_of // 2) + 1
    p = single_game_prob
    # P(win series) = P(win exactly games_needed games before opponent does)
    # Standard best-of-N formula: sum over k = games_needed to best_of of
    # (ways to arrange a series that ends exactly at game k with the
    # target team winning game k and games_needed-1 of the previous k-1 games)
    total_prob = 0.0
    for total_games in range(games_needed, best_of + 1):
        # Team must win the LAST game of the series (it ends there) and
        # exactly (games_needed - 1) of the (total_games - 1) games before it
        wins_before_last = games_needed - 1
        games_before_last = total_games - 1
        ways = comb(games_before_last, wins_before_last)
        prob_this_path = ways * (p ** (wins_before_last + 1)) * ((1 - p) ** (games_before_last - wins_before_last))
        total_prob += prob_this_path
    return total_prob


def build_team_ratings_from_history(sorted_completed_matches, starting_rating=DEFAULT_STARTING_RATING, k_factor=DEFAULT_K_FACTOR, use_recency_weighting=True, reference_date=None, team_region_map=None, international_k_multiplier=DEFAULT_INTERNATIONAL_K_MULTIPLIER, lower_tier_k_multiplier=DEFAULT_LOWER_TIER_K_MULTIPLIER):
    """Processes a chronologically-sorted list of completed matches
    (the output of cito_api.sort_matches_chronologically applied to
    cito_api.extract_completed_matches) and builds up current Elo
    ratings for every team seen, game by game (not series by series —
    see module docstring for why). Teams not yet seen start at
    starting_rating. Returns a dict of {team_slug: current_rating}.

    Expects each match dict to have 'team1'/'team2' (each with 'slug')
    and a 'games' list of {'winnerSlug': ...} — the confirmed real
    shape from Cito's team-matches endpoint. Matches missing a 'games'
    array (or with an empty one) are skipped for game-level updates —
    a real, honest gap rather than silently guessing at a series-level
    substitute that would mix two different granularities together.

    Real addition (July 2026): use_recency_weighting (default True,
    the new baseline behavior) scales each game's effective K-factor
    by calculate_recency_weight(), using the parent match's real
    'startTime' field — individual games within a series don't have
    their own timestamps in Cito's confirmed schema, only the match
    does, so every game within one match shares that match's single
    age/weight. A match with a missing/unparseable startTime gets full
    weight (1.0), not silently excluded.

    Real addition (July 2026, per external review's own precise
    refinement): a moderate K-factor boost for genuinely cross-region
    international matches (MSI/Worlds/EWC where the two teams are from
    DIFFERENT regions) — these rare bridge games carry more real
    information about how separate regional rating pools relate to
    each other than an ordinary domestic game does. Deliberately NOT
    applied to a same-region matchup at an international event (e.g.
    two LCK teams playing each other at Worlds) — per the review,
    that tells the model nothing new about cross-region strength.
    Requires team_region_map ({slug: region}, built from the real
    teams-list data, since match data itself carries no region field)
    — if not provided, this boost is simply never applied (an honest,
    safe default, not an error) and behavior is identical to before
    this feature existed.

    Real addition (July 2026, found via direct real-data
    investigation, not a hypothesis): a moderate K-factor discount for
    known lower-tier/developmental tournaments (promotion leagues,
    challengers/academy circuits). Found via a real case — Dignitas
    had ~40% of their real match history in a lower-division
    "promotion" tournament while their opponent (Sentinels) had zero
    such games, only real top-tier competition — letting Dignitas
    accumulate real wins against weaker opposition that inflated their
    rating relative to genuine LCS-caliber performance. This is the
    inverse of the international boost: applied unconditionally to any
    game in a known lower-tier tournament, not conditional on the two
    teams' regions (a promotion-tier game is a weaker signal regardless
    of who's playing in it)."""
    ratings = {}
    team_region_map = team_region_map or {}

    def _get_rating(slug):
        return ratings.setdefault(slug, starting_rating)

    for match in sorted_completed_matches:
        team1_slug = match.get("team1", {}).get("slug")
        team2_slug = match.get("team2", {}).get("slug")
        games = match.get("games") or []
        if not team1_slug or not team2_slug or not games:
            continue

        if use_recency_weighting:
            recency_weight = calculate_recency_weight(match.get("startTime"), reference_date)
            effective_k = k_factor * recency_weight
        else:
            effective_k = k_factor

        # Real, precise cross-region international boost — both
        # conditions must be true, matching the review's exact spec.
        if is_international_tournament(match.get("tournamentName")):
            region1 = team_region_map.get(team1_slug)
            region2 = team_region_map.get(team2_slug)
            if region1 and region2 and region1 != region2:
                effective_k *= international_k_multiplier

        # Real, found-via-direct-evidence lower-tier discount —
        # unconditional on region, since a promotion/academy game is a
        # weaker signal regardless of who's involved.
        if is_lower_tier_tournament(match.get("tournamentName")):
            effective_k *= lower_tier_k_multiplier

        for game in games:
            winner_slug = game.get("winnerSlug")
            if winner_slug not in (team1_slug, team2_slug):
                continue  # malformed/unexpected data — skip rather than guess
            r1 = _get_rating(team1_slug)
            r2 = _get_rating(team2_slug)
            team1_won = (winner_slug == team1_slug)
            new_r1, new_r2 = update_elo_ratings(r1, r2, team1_won, effective_k)
            ratings[team1_slug] = new_r1
            ratings[team2_slug] = new_r2

    return ratings


def predict_series(ratings, team1_slug, team2_slug, best_of, starting_rating=DEFAULT_STARTING_RATING):
    """Given a ratings dict (from build_team_ratings_from_history) and
    two team slugs, returns team1's win probability for a real,
    upcoming best-of-N series. Teams not present in the ratings dict
    (no completed-game history yet) default to starting_rating — a
    real, honest fallback for genuinely new/unrated teams, not a
    hidden assumption."""
    r1 = ratings.get(team1_slug, starting_rating)
    r2 = ratings.get(team2_slug, starting_rating)
    single_game_prob = calculate_elo_expected_score(r1, r2)
    return series_win_probability(single_game_prob, best_of)


# Real, conservative head-to-head blending parameters (July 2026, per
# direct user feedback and a real, concrete case: Dignitas and
# Sentinels had two prior meetings, both real 2-0 sweeps in Sentinels'
# favor — a clean, consistent pattern our overall-rating-only Elo
# system had no way to see at all). Deliberately capped: even with
# many real head-to-head meetings, this can never contribute more than
# MAX_HEAD_TO_HEAD_WEIGHT to the final probability — head-to-head
# history is real, relevant evidence, but overall recent form (Elo)
# should remain the primary signal, not be overridden by a small
# sample of direct meetings. Not backtested — a reasonable, honest
# first attempt, same as every other new threshold in this project.
MAX_HEAD_TO_HEAD_WEIGHT = 0.30
HEAD_TO_HEAD_WEIGHT_PER_SERIES = 0.10


def get_head_to_head_record(team1_slug, team2_slug, sorted_completed_matches):
    """Real, direct scan of the combined match history for every real,
    completed SERIES (not individual game) played directly between
    these two specific teams — matching how a person actually thinks
    about head-to-head ("they've swept us twice"), not game-level
    counting. Returns (team1_series_wins, team2_series_wins,
    total_series). Uses each match's real 'winner' field (the series
    winner) rather than re-deriving it from individual games, since
    that's the most direct, real signal available.

    Real, honest limitation (kept for backward compatibility/display
    purposes): this returns RAW, unweighted counts — see
    get_recency_weighted_head_to_head_record() below for the real,
    recency-aware version now used in the actual blending logic."""
    team1_wins = 0
    team2_wins = 0
    total = 0
    for match in sorted_completed_matches:
        m_team1 = (match.get("team1") or {}).get("slug")
        m_team2 = (match.get("team2") or {}).get("slug")
        if {m_team1, m_team2} != {team1_slug, team2_slug}:
            continue
        winner = match.get("winner")
        if winner == team1_slug:
            team1_wins += 1
            total += 1
        elif winner == team2_slug:
            team2_wins += 1
            total += 1
        # a match with a genuinely missing/unrecognized winner is
        # skipped, not guessed at — consistent with this project's
        # standing principle throughout
    return team1_wins, team2_wins, total


def get_recency_weighted_head_to_head_record(team1_slug, team2_slug, sorted_completed_matches, reference_date=None):
    """Real fix (July 2026) — found via a real, concrete case: RED
    Canids vs Vivo Keyd Stars showed a head-to-head record favoring
    VKS (7-4), but the real market's own context text explicitly said
    "current momentum and team form heavily favor RED," mentioning a
    recent RED win. The raw, unweighted head-to-head record was
    treating an old VKS advantage as equally meaningful as recent form
    — actively pulling the prediction in the WRONG direction from what
    real, current results actually show.

    Applies the same real recency-decay curve already proven for the
    main Elo rating (calculate_recency_weight) to each head-to-head
    meeting — a recent head-to-head win counts close to fully, an old
    one counts for much less, rather than all prior meetings counting
    identically regardless of when they happened. Returns
    (weighted_team1_wins, weighted_total_series) — both REAL NUMBERS
    (not integers), the sum of recency weights for team1's wins / all
    matches, not raw counts. A team1_needed of 0 total_series means
    genuinely no real head-to-head evidence exists, same meaning as
    before, just measured in weighted terms now."""
    weighted_team1_wins = 0.0
    weighted_total = 0.0
    for match in sorted_completed_matches:
        m_team1 = (match.get("team1") or {}).get("slug")
        m_team2 = (match.get("team2") or {}).get("slug")
        if {m_team1, m_team2} != {team1_slug, team2_slug}:
            continue
        winner = match.get("winner")
        if winner not in (team1_slug, team2_slug):
            continue  # a genuinely missing/unrecognized winner — skipped, not guessed at
        weight = calculate_recency_weight(match.get("startTime"), reference_date)
        weighted_total += weight
        if winner == team1_slug:
            weighted_team1_wins += weight
    return weighted_team1_wins, weighted_total


def _blend_elo_with_h2h_rate(elo_prob_team1, team1_wins, total_series, max_weight, weight_per_series):
    """Shared blending math used by both blend_with_head_to_head() and
    blend_with_head_to_head_from_api() — kept in one place so the two
    real data sources (reconstructed vs Cito's dedicated endpoint)
    always apply identical, consistent blending logic."""
    detail = {
        "team1_h2h_wins": team1_wins, "team2_h2h_wins": total_series - team1_wins if total_series else 0,
        "total_h2h_series": total_series, "h2h_weight_applied": 0.0,
    }
    if not total_series:
        return elo_prob_team1, detail
    h2h_win_rate_team1 = team1_wins / total_series
    weight = min(max_weight, total_series * weight_per_series)
    blended_prob = (1 - weight) * elo_prob_team1 + weight * h2h_win_rate_team1
    detail["h2h_weight_applied"] = round(weight, 3)
    detail["h2h_win_rate_team1"] = round(h2h_win_rate_team1, 3)
    return blended_prob, detail


def blend_with_head_to_head(elo_prob_team1, team1_slug, team2_slug, sorted_completed_matches, reference_date=None, max_weight=MAX_HEAD_TO_HEAD_WEIGHT, weight_per_series=HEAD_TO_HEAD_WEIGHT_PER_SERIES):
    """Real, conservative blend of the Elo-based series probability
    with real, direct head-to-head history between these two specific
    teams, RECONSTRUCTED from each team's own real /matches history.

    Real fix (July 2026) — now uses recency-weighted head-to-head
    (get_recency_weighted_head_to_head_record) instead of raw counts.
    Found necessary via a real case: an old head-to-head advantage was
    fighting against real, recent form the market itself was pricing
    in — a recent head-to-head win should matter more than one from
    years ago, same principle already proven for the main Elo rating.

    Real, honest limitation confirmed via live investigation (July
    2026): this reconstruction can miss real matches that are absent
    from BOTH teams' own /matches fetches (two real matches between
    Karmine Corp and Movistar KOI were confirmed missing from both
    sides — later found to be from a genuinely different, untracked
    qualifier tournament, not a real gap in this data source itself).
    blend_with_head_to_head_from_api() below uses Cito's own dedicated
    /h2h endpoint instead, confirmed via live testing to return more
    complete data — that function is the real, preferred path in the
    pipeline; this one remains as an honest fallback if that API call
    fails for a specific pair."""
    weighted_team1_wins, weighted_total = get_recency_weighted_head_to_head_record(team1_slug, team2_slug, sorted_completed_matches, reference_date)
    return _blend_elo_with_h2h_rate(elo_prob_team1, weighted_team1_wins, weighted_total, max_weight, weight_per_series)


def blend_with_head_to_head_from_api(elo_prob_team1, h2h_api_response, team1_slug, reference_date=None, max_weight=MAX_HEAD_TO_HEAD_WEIGHT, weight_per_series=HEAD_TO_HEAD_WEIGHT_PER_SERIES):
    """Real, preferred head-to-head blend (July 2026) — uses Cito's own
    dedicated GET /lol/teams/{slug}/h2h/{opponentSlug} endpoint
    (cito_api.get_lol_head_to_head) instead of reconstructing from
    each team's own /matches history. Confirmed via live testing to
    return meaningfully more complete real data (10 real matches back
    to January 2025 for a real pair, vs only 4 found by the
    reconstruction approach for the same real pair) — a real,
    verified improvement, not a guess.

    Real fix (July 2026) — now uses the real 'recentMatches' array
    (each with a real 'date' and 'winner' slug) to apply the same
    recency-decay weighting as the reconstruction method, instead of
    the earlier version which used the aggregate 'matches.total/wins'
    summary — that summary has NO date information at all, so it could
    not distinguish a recent head-to-head win from an old one. Found
    necessary via the same real case that motivated the reconstruction
    method's fix (an old head-to-head advantage fighting against real,
    current form). HONEST, NAMED TRADEOFF: recentMatches is confirmed
    to cap at some real limit (10 in live testing) — this sees
    whatever recentMatches actually provides, not necessarily every
    real match counted in the aggregate 'matches.total' figure, but
    gains real recency-awareness that aggregate figure could never
    provide.

    HONEST, NAMED LIMITATION found via the same live test: even this
    dedicated endpoint was confirmed MISSING two real matches between
    KC and Movistar KOI that the reconstruction approach was also
    missing — later confirmed to be from a genuinely different,
    untracked qualifier tournament, not a real gap in this endpoint
    specifically."""
    recent_matches = (h2h_api_response or {}).get("recentMatches") or []
    weighted_team1_wins = 0.0
    weighted_total = 0.0
    for match in recent_matches:
        winner = match.get("winner")
        if not winner:
            continue  # a genuinely missing winner — skipped, not guessed at
        weight = calculate_recency_weight(match.get("date"), reference_date)
        weighted_total += weight
        if winner == team1_slug:
            weighted_team1_wins += weight
    return _blend_elo_with_h2h_rate(elo_prob_team1, weighted_team1_wins, weighted_total, max_weight, weight_per_series)


# Real, conservative in-tournament-form blending parameters (July
# 2026) — same real motivating principle as head-to-head: a team's
# overall Elo rating is a real, useful summary, but it can miss a
# real, current signal specific to one tournament. Concrete case:
# Dplus KIA (rated 1684.7, one of the best teams in the world) was
# genuinely 0-2 in the exact KeSPA Cup tournament this prediction was
# for, while HANJIN BRION (rated far lower, 1415.4) was 2-2 in that
# same event — real, direct evidence our overall rating had no way to
# see, since KeSPA Cup is a real, known tournament where teams often
# field substitute/academy players instead of their main roster.
# Deliberately capped, same as head-to-head — a handful of real games
# within one tournament shouldn't be able to fully override a team's
# much larger, broader Elo history, but should be able to meaningfully
# shift the prediction toward what's actually happening right now.
MAX_IN_TOURNAMENT_FORM_WEIGHT = 0.35
IN_TOURNAMENT_FORM_WEIGHT_PER_GAME = 0.12


# Real, common stage/qualifier words that show up in real tournament
# names across regions without being part of the actual tournament's
# core identity — e.g. Polymarket's event_title might say "LCS Regular
# Season" or "KeSPA Cup Group Stage" while Cito's real tournamentName
# for the exact same real tournament says "LCS 2026 Summer" or "KeSPA
# Cup 2026". Stripping these lets the two real, differently-worded
# strings be compared on their actual shared identity instead of
# failing a strict substring check that has no real reason to succeed.
_TOURNAMENT_NAME_NOISE_WORDS = {
    "regular", "season", "group", "stage", "playoffs", "playoff",
    "finals", "final", "split", "summer", "spring", "winter", "fall",
    "qualifier", "qualifiers", "promotion", "main", "event", "round",
    # "lol" added (round 3) — Cito's real tournamentId always starts
    # with a "lol-" sport prefix (e.g. "lol-lpl_split_3_2026"), which
    # would otherwise become a token on every single real match
    # regardless of league — the exact same class of coincidental,
    # meaningless-overlap risk the earlier number-stripping fix was
    # built to close, just with a word instead of a digit this time.
    "lol",
}


def _normalize_tournament_name_for_matching(name):
    """Strips real, common stage/qualifier words and ANY standalone
    number, leaving just the core tournament-identity tokens (e.g.
    "LCS Regular Season" -> {"lcs"}, "KeSPA Cup Group Stage" -> {"kespa",
    "cup"}) — the real, shared signal between Polymarket's event_title
    and Cito's real tournamentName, which often describe the exact same
    real tournament using genuinely different stage/qualifier wording.

    Real fix (July 2026, round 2, per direct user report) — originally
    only stripped standalone 4-digit years, leaving other bare numbers
    (round numbers, split numbers, stage numbers) as real tokens. This
    produced a real, confirmed false match: "LCK Round 3-4 Legend
    Group" (main roster) and "Split 3 2026" (a genuinely different real
    tournament — the LCK Challengers/academy split) share NOTHING in
    common except the bare number "3", which was enough for the old
    version to treat them as the same real tournament, silently pulling
    a team's B-team/academy results into their main-roster in-tournament
    record. A bare number can never, by itself, prove two tournament
    names refer to the same real event — round/split/stage numbering
    schemes are reused across completely unrelated real tournaments all
    the time. Now strips EVERY standalone numeric token (not just
    4-digit years), so a match can only ever happen on a real,
    identifying word (a league acronym, "cup", a proper tournament
    name), never on a coincidental number alone.

    Real fix (July 2026, round 3) — also splits on underscores, not
    just hyphens/spaces, since Cito's real tournamentId field uses
    underscore separators (e.g. "lol-lpl_split_3_2026") — this function
    is now also called on that field (see _tournament_names_match),
    not just tournamentName."""
    if not name:
        return set()
    words = name.strip().lower().replace("-", " ").replace("_", " ").split()
    tokens = set()
    for w in words:
        if w.isdigit():
            continue  # a real, standalone number (year, round, split, stage) — never part of the tournament's core identity by itself
        if w in _TOURNAMENT_NAME_NOISE_WORDS:
            continue
        tokens.add(w)
    return tokens


def _tournament_names_match(tournament_name_substring, tournament_name, tournament_id=None):
    """Real, robust tournament-name match (July 2026) — replaces a pure
    substring check that fails whenever Polymarket's event_title and
    Cito's real tournamentName describe the same real tournament with
    genuinely different stage/qualifier wording. Real, confirmed case
    that motivated this: "KeSPA Cup Group Stage" (from Polymarket) vs
    Cito's real "KeSPA Cup 2026" share NO common substring at all
    despite being the exact same real tournament, silently returning
    (0, 0, 0) — genuinely no evidence — even when real games existed.
    Also confirmed on a second, real, different tournament: "LCS
    Regular Season" failing to match Cito's real LCS tournamentName the
    same way. Strips real, common noise words (stage/qualifier terms,
    standalone years) from both sides via
    _normalize_tournament_name_for_matching(), then matches if the
    remaining core tokens overlap at all — a real, deliberately
    permissive but honest heuristic (not a guaranteed-exact ID match,
    since neither data source actually shares one), which is a
    meaningfully better real signal than a strict substring check that
    was demonstrably failing on real, live data.

    Real fix (July 2026, round 3, per direct user report) — Cito's real
    tournamentName can be genuinely, unhelpfully generic with NO league
    identity in it at all — a real, confirmed case: LPL's real
    tournamentName is literally "Split 3 2026", nothing else, making it
    impossible for ANY tournamentName-only matching approach to ever
    connect it to Polymarket's "LPL Split 3 Group Nirvana" text, since
    the identifying word genuinely isn't there to find. Cito's real
    tournamentId field IS reliably structured with the league embedded
    (e.g. "lol-lpl_split_3_2026") — when provided, its tokens are
    folded into the real haystack too, giving a genuine second real
    source for the league identity when tournamentName alone can't
    provide one. tournament_id is optional and defaults to None so
    every existing real call site keeps working unchanged unless it's
    deliberately updated to pass it."""
    needle_tokens = _normalize_tournament_name_for_matching(tournament_name_substring)
    haystack_tokens = _normalize_tournament_name_for_matching(tournament_name)
    if tournament_id:
        haystack_tokens = haystack_tokens | _normalize_tournament_name_for_matching(tournament_id)
    if not needle_tokens or not haystack_tokens:
        return False
    return bool(needle_tokens & haystack_tokens)


def get_in_tournament_record(team_slug, tournament_name_substring, sorted_completed_matches, exclude_opponent_slug=None):
    """Real, direct scan of a team's own match history for real,
    completed matches within a SPECIFIC tournament — matched via
    _tournament_names_match() (a real, robust token-overlap comparison,
    not a strict substring check — see that function's own docstring
    for the full real reasoning and the confirmed real cases that
    motivated it) against each match's real tournamentName, since
    that's the only real, confirmed field available for this on Cito's
    team-matches endpoint (no clean tournamentId shared between
    Polymarket's market text and Cito's schedule). Returns (wins,
    losses, total) — real, honest series-level counts (using each
    match's own 'winner' field), not inferred from anything else. A
    team not appearing at all in this tournament yet returns (0, 0, 0)
    — genuinely no evidence, not a guess either way.

    Real fix (July 2026, per external review) — exclude_opponent_slug
    lets a caller exclude games against one specific opponent. Used by
    blend_with_in_tournament_form() below to prevent double-counting:
    if these two teams already played each other once within this
    same tournament, that specific game is already, separately
    captured by the head-to-head blend — counting it again here would
    give that one result more real pull on the final probability than
    either blend was individually designed to have."""
    if not tournament_name_substring:
        return 0, 0, 0
    wins = 0
    losses = 0
    total = 0
    for match in sorted_completed_matches:
        m_team1 = (match.get("team1") or {}).get("slug")
        m_team2 = (match.get("team2") or {}).get("slug")
        if team_slug not in (m_team1, m_team2):
            continue
        if exclude_opponent_slug and exclude_opponent_slug in (m_team1, m_team2):
            continue  # a real rematch within this tournament — already captured by head-to-head, skip here
        tournament_name = match.get("tournamentName") or ""
        tournament_id = match.get("tournamentId") or ""
        if not _tournament_names_match(tournament_name_substring, tournament_name, tournament_id):
            continue
        winner = match.get("winner")
        if winner == team_slug:
            wins += 1
            total += 1
        elif winner in (m_team1, m_team2):
            losses += 1
            total += 1
    return wins, losses, total


def diagnose_in_tournament_matches(team_slug, tournament_name_substring, sorted_completed_matches, exclude_opponent_slug=None):
    """Real diagnostic (July 2026, per direct user report — a team's
    in-tournament record looked internally inconsistent with real
    market context describing them as having "one of the league's
    strongest records," raising a real, legitimate concern that the
    broadened _tournament_names_match() token-overlap matching (fixed
    the same day, for a real, confirmed too-narrow bug) might now be
    matching TOO broadly for a common, short league acronym — pulling
    in real games from a genuinely different bracket, stage, or season
    that happens to share the same core token).

    Mirrors get_in_tournament_record()'s EXACT same real matching logic
    (same function, same filters, same order) but returns the actual,
    real matched match objects instead of just win/loss counts — so an
    admin can directly SEE which real tournamentName values got pulled
    in and visually confirm whether they genuinely all represent the
    same real tournament/split, or whether the matching swept in
    something it shouldn't have. Returns a list of dicts: {'opponent_
    slug', 'tournament_name', 'start_time', 'result' ('win'/'loss'/
    'unclear')} — deliberately NOT used by the real pricing pipeline
    itself (get_in_tournament_record stays the single source of truth
    for that), this is read-only, for-humans diagnostic output only."""
    if not tournament_name_substring:
        return []
    matched = []
    for match in sorted_completed_matches:
        m_team1 = (match.get("team1") or {}).get("slug")
        m_team2 = (match.get("team2") or {}).get("slug")
        if team_slug not in (m_team1, m_team2):
            continue
        if exclude_opponent_slug and exclude_opponent_slug in (m_team1, m_team2):
            continue
        tournament_name = match.get("tournamentName") or ""
        tournament_id = match.get("tournamentId") or ""
        if not _tournament_names_match(tournament_name_substring, tournament_name, tournament_id):
            continue
        winner = match.get("winner")
        opponent_slug = m_team2 if m_team1 == team_slug else m_team1
        if winner == team_slug:
            result = "win"
        elif winner == opponent_slug:
            result = "loss"
        else:
            result = "unclear"
        matched.append({
            "opponent_slug": opponent_slug,
            "tournament_name": tournament_name,
            "tournament_id": tournament_id,
            "start_time": match.get("startTime"),
            "result": result,
        })
    return matched


def blend_with_in_tournament_form(elo_prob_team1, team1_slug, team2_slug, tournament_name_substring, sorted_completed_matches, max_weight=MAX_IN_TOURNAMENT_FORM_WEIGHT, weight_per_game=IN_TOURNAMENT_FORM_WEIGHT_PER_GAME):
    """Real, conservative blend of the Elo-based series probability
    with each team's real, direct record within the SPECIFIC
    tournament this match is part of — real, current evidence that
    can catch things overall Elo can't (a team fielding substitutes,
    a team on a real hot/cold streak within one specific event).
    Combines both teams' in-tournament win rates into a single,
    relative signal: team1's implied strength = their own win rate
    scaled against the combined win rates of both teams (so if team1
    is 2-2 and team2 is 0-2, team1's real, relative in-tournament
    strength is clearly higher, not just 'both teams have some
    record'). Weight scales with real total games seen across both
    teams in this tournament, capped so a handful of real games can
    meaningfully shift the prediction without ever fully overriding
    the broader, much larger Elo history. Returns (blended_prob,
    detail_dict) — the detail dict is real, honest transparency about
    what in-tournament evidence (if any) existed, for display.

    Real fix (July 2026, per external review) — each team's record now
    excludes games against the OTHER team in this exact matchup, so a
    direct rematch within the tournament isn't counted by both this
    blend and the head-to-head blend at the same time."""
    t1_wins, t1_losses, t1_total = get_in_tournament_record(team1_slug, tournament_name_substring, sorted_completed_matches, exclude_opponent_slug=team2_slug)
    t2_wins, t2_losses, t2_total = get_in_tournament_record(team2_slug, tournament_name_substring, sorted_completed_matches, exclude_opponent_slug=team1_slug)
    detail = {
        "team1_wins": t1_wins, "team1_losses": t1_losses, "team1_total": t1_total,
        "team2_wins": t2_wins, "team2_losses": t2_losses, "team2_total": t2_total,
        "weight_applied": 0.0,
    }
    combined_games = t1_total + t2_total
    if combined_games == 0 or (t1_wins + t2_wins) == 0:
        return elo_prob_team1, detail  # no real in-tournament evidence at all — Elo alone, unchanged

    t1_win_rate = t1_wins / t1_total if t1_total else 0.0
    t2_win_rate = t2_wins / t2_total if t2_total else 0.0
    # A relative strength read — if both teams have identical win
    # rates (or neither has played), this correctly contributes
    # nothing new; the further apart they are, the stronger the real
    # signal that one team is playing meaningfully better right now.
    if (t1_win_rate + t2_win_rate) == 0:
        return elo_prob_team1, detail
    team1_relative_strength = t1_win_rate / (t1_win_rate + t2_win_rate)

    weight = min(max_weight, combined_games * weight_per_game)
    blended_prob = (1 - weight) * elo_prob_team1 + weight * team1_relative_strength
    detail["weight_applied"] = round(weight, 3)
    detail["team1_relative_strength"] = round(team1_relative_strength, 3)
    return blended_prob, detail


def combine_and_dedupe_matches(list_of_match_lists):
    """A real, global rating pool needs history from MANY teams, not
    just one — but cito_api.get_lol_team_matches() is per-team, and
    any given match between team A and team B appears once in team
    A's fetched history and once in team B's, with identical content.
    Feeding both copies into build_team_ratings_from_history() would
    double-count that game's Elo impact — a real, easy-to-miss bug this
    function exists specifically to prevent. Dedupes on 'matchId',
    matching the confirmed real field from Cito's schema."""
    seen_match_ids = set()
    combined = []
    for match_list in list_of_match_lists:
        for match in match_list:
            match_id = match.get("matchId")
            if match_id and match_id not in seen_match_ids:
                seen_match_ids.add(match_id)
                combined.append(match)
    return combined


def count_international_matches(sorted_completed_matches, team_region_map=None):
    """Real, per-reviewer confidence signal (July 2026): rather than
    changing a team's projection based on having zero cross-region
    international history (which the reviewer correctly flagged as
    manufacturing a correction from insufficient evidence), this
    tracks and returns a real, honest fact — {team_slug: count of
    real cross-region international games in their history} — so the
    pipeline can surface a genuine low-confidence flag for a team with
    zero international games, without pretending to know how that
    affects their true strength. A team with count=0 hasn't been
    proven weak OR strong internationally — it's genuinely unknown,
    and this function's job is only to report that honestly, not to
    guess at a correction."""
    team_region_map = team_region_map or {}
    counts = {}

    def _increment(slug):
        counts[slug] = counts.get(slug, 0) + 1

    for match in sorted_completed_matches:
        team1_slug = match.get("team1", {}).get("slug")
        team2_slug = match.get("team2", {}).get("slug")
        if not team1_slug or not team2_slug:
            continue
        # Ensure every team appears in the output even at zero, not just teams with real international games
        counts.setdefault(team1_slug, 0)
        counts.setdefault(team2_slug, 0)
        if not is_international_tournament(match.get("tournamentName")):
            continue
        region1 = team_region_map.get(team1_slug)
        region2 = team_region_map.get(team2_slug)
        if region1 and region2 and region1 != region2:
            _increment(team1_slug)
            _increment(team2_slug)

    return counts


DEFAULT_ROSTER_CONTINUITY_LOOKBACK_DAYS = 30  # real, moderate first choice — not backtested, may need real calibration later


def calculate_roster_continuity(roster_history_response, reference_date=None, lookback_days=DEFAULT_ROSTER_CONTINUITY_LOOKBACK_DAYS):
    """Real, honest roster continuity metric (July 2026) — found
    necessary via a real, concrete case: RED Canids' current roster
    showed 4 of 5 starters joining on the exact same real date (July
    15, 2026), just 10 days before a real, upcoming match, with their
    Elo rating still built entirely from games played before that
    roster change.

    Real bugs found and fixed via live testing against the FULL, exact
    real RED Canids dataset (28 real entries, July 2026) — two
    separate, genuine data-quality issues, not one:

    1. SAME-JOINDATE TIES: the same real player (confirmed example:
       'cadu') can have two entries with the IDENTICAL joinDate, one
       'current' and one 'former' with a real leaveDate — picking
       "most recent by joinDate" alone has no way to break this tie
       and arbitrarily kept whichever entry appeared first in the
       list. Fixed by preferring the entry with a leaveDate as the
       tiebreaker — a 'former' record with an explicit leaveDate is
       more informative than a stale 'current' one from the exact same
       date.

    2. MISSING 'FORMER' RECORDS ENTIRELY: a deeper, real gap — some
       players (confirmed real examples: Fuuu, frosty, zynts, STEPZ)
       remain marked 'current' with NO corresponding 'former' entry
       ever created for them at all, even though a newer player
       clearly replaced them (each of these four shares an exact ROLE
       with a newer, July 15-joined player: Fuuu/MID overlaps Nukenin,
       frosty/SUPPORT overlaps Manel, zynts/TOP overlaps jmz, STEPZ/
       JUNGLE overlaps smooth). Status alone cannot catch this since
       there's genuinely no 'former' record to signal it. Fixed using
       ROLE as an additional real signal: when multiple players are
       all marked 'current' for the exact same role, only the one with
       the latest joinDate is treated as genuinely current — the
       others are stale, superseded entries Cito never marked as such.

    Uses a real, set-based comparison of which currently-active real
    players were ALSO active lookback_days ago. A continuity of 1.0
    means the entire current roster was already there a month ago
    (real, stable roster, existing rating should be trusted normally).
    A continuity near 0 means the roster is almost entirely new since
    then (existing rating reflects players who may no longer even be
    on the team).

    Returns a real dict: {"continuity_pct": float 0-1, "current_roster_size":
    int, "retained_from_lookback": int, "new_since_lookback": int}.
    Returns continuity_pct=1.0 (the safe, honest default — no
    correction applied) if the roster data is missing/malformed, or if
    there's genuinely no current roster to compare (nothing to be
    cautious about if there's no real data)."""
    if reference_date is None:
        reference_date = datetime.now(timezone.utc)
    cutoff = reference_date - timedelta(days=lookback_days)

    roster_entries = (roster_history_response or {}).get("roster") or []

    def _parse_date(date_str):
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")) if date_str else None
        except (ValueError, TypeError):
            return None

    def _sort_key(entry):
        # Real fix #1: when joinDates tie, prefer the entry WITH a
        # leaveDate (a 'former' record) — it's more informative than a
        # stale 'current' entry from the exact same date.
        join_date = _parse_date(entry.get("joinDate")) or datetime.min.replace(tzinfo=timezone.utc)
        has_leave_date = 1 if entry.get("leaveDate") else 0
        return (join_date, has_leave_date)

    # Group every entry by real player ID, find each player's single
    # most recent stint (with the same-date tiebreak above).
    entries_by_player = {}
    for entry in roster_entries:
        if not isinstance(entry, dict):
            continue
        player_id = entry.get("lolPlayerId")
        if not player_id:
            continue
        entries_by_player.setdefault(player_id, []).append(entry)

    most_recent_stint_by_player = {
        player_id: max(entries, key=_sort_key)
        for player_id, entries in entries_by_player.items()
    }

    # Real fix #2: among players whose most recent stint says
    # 'current', group by role — only the latest joinDate per role is
    # genuinely current; any other 'current'-labeled player sharing
    # that same role is a stale entry Cito never marked 'former'.
    current_by_role = {}
    for player_id, entry in most_recent_stint_by_player.items():
        if entry.get("status") == "current" and entry.get("isActive"):
            role = entry.get("role")
            current_by_role.setdefault(role, []).append((player_id, entry))

    current_ids = set()
    for role, players in current_by_role.items():
        if role is None:
            # No real role info to disambiguate with — keep all
            # (a real, honest limitation, not a guess).
            current_ids.update(player_id for player_id, _ in players)
            continue
        latest_for_role = max(players, key=lambda p: _parse_date(p[1].get("joinDate")) or datetime.min.replace(tzinfo=timezone.utc))
        current_ids.add(latest_for_role[0])

    if not current_ids:
        return {"continuity_pct": 1.0, "current_roster_size": 0, "retained_from_lookback": 0, "new_since_lookback": 0}

    retained_ids = set()
    for player_id in current_ids:
        entry = most_recent_stint_by_player[player_id]
        join_date = _parse_date(entry.get("joinDate"))
        leave_date = _parse_date(entry.get("leaveDate"))
        # This player counts as "retained from lookback" if their real,
        # current stint covers the cutoff date — joined on or before
        # cutoff, and (still active, or left after cutoff).
        if join_date and join_date <= cutoff and (leave_date is None or leave_date > cutoff):
            retained_ids.add(player_id)

    retained_count = len(retained_ids)
    total_current = len(current_ids)
    continuity_pct = retained_count / total_current if total_current else 1.0
    return {
        "continuity_pct": round(continuity_pct, 3),
        "current_roster_size": total_current,
        "retained_from_lookback": retained_count,
        "new_since_lookback": total_current - retained_count,
    }


def apply_roster_continuity_discount(ev_pct, continuity_pct):
    """Real, simple, proportional discount — same mechanism already
    proven for market volume (a market nobody's traded doesn't deserve
    full trust; a roster that's mostly new doesn't either). Directly
    scales EV% by continuity_pct: full continuity (1.0) means no
    discount at all; a roster that's, say, 20% retained gets EV%
    discounted to 20% of its original value. Deliberately simple and
    transparent, not finely tuned — same honest first-attempt spirit
    as every other new adjustment today."""
    if ev_pct is None:
        return None
    return round(ev_pct * continuity_pct, 2)
