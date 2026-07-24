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
"""

from math import comb

DEFAULT_STARTING_RATING = 1500
DEFAULT_K_FACTOR = 32


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


def build_team_ratings_from_history(sorted_completed_matches, starting_rating=DEFAULT_STARTING_RATING, k_factor=DEFAULT_K_FACTOR):
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
    substitute that would mix two different granularities together."""
    ratings = {}

    def _get_rating(slug):
        return ratings.setdefault(slug, starting_rating)

    for match in sorted_completed_matches:
        team1_slug = match.get("team1", {}).get("slug")
        team2_slug = match.get("team2", {}).get("slug")
        games = match.get("games") or []
        if not team1_slug or not team2_slug or not games:
            continue
        for game in games:
            winner_slug = game.get("winnerSlug")
            if winner_slug not in (team1_slug, team2_slug):
                continue  # malformed/unexpected data — skip rather than guess
            r1 = _get_rating(team1_slug)
            r2 = _get_rating(team2_slug)
            team1_won = (winner_slug == team1_slug)
            new_r1, new_r2 = update_elo_ratings(r1, r2, team1_won, k_factor)
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
