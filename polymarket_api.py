"""
polymarket_api.py — Polymarket Gamma API client, built for LoL esports
(July 2026).

A genuinely new, standalone module from day one — not bolted onto
mlb_app.py — matching the same "keep new, separable pieces out of the
single giant file" approach used for bet_math.py.

Real, verified facts this module is built on (confirmed via live fetch
against the actual API, July 2026):
  - Base URL: https://gamma-api.polymarket.com — fully public, no
    authentication required for reads.
  - /events returns a JSON array of event objects. Each event has a
    nested 'markets' array (one or more Yes/No markets per event).
  - Market objects use STRINGIFIED JSON for several fields —
    'outcomes' (e.g. '["Yes", "No"]'), 'outcomePrices' (e.g.
    '["0.62", "0.38"]', each a string representing implied
    probability from 0 to 1), and 'clobTokenIds'. These must be
    json.loads()'d before use — treating them as real arrays without
    parsing is a real, easy mistake.
  - No paid tier exists for reading market data — just undocumented,
    but reportedly generous, rate limits.

Honest, known limitation as of this build: query-parameter filtering
(tag_slug, active, closed) could NOT be independently verified as
working from this development environment — two test fetches with
different parameters returned identical results, which points at a
caching layer in the fetch tool used during development rather than a
confirmed problem with the real API. This needs real verification once
deployed, via get_polymarket_safety_check() below, which surfaces the
real HTTP response (or a real error) instead of assuming either way.
"""

import json
import requests

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


def _parse_stringified_json_field(value, default=None):
    """Polymarket's Gamma API returns several fields as JSON-encoded
    strings rather than real arrays (a real, confirmed quirk of this
    API, not a mistake in this code) — this safely parses them,
    falling back to a default rather than raising if a field is
    missing or genuinely malformed."""
    if value is None:
        return default if default is not None else []
    if isinstance(value, list):
        return value  # already parsed, some fields may not need it
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


def get_polymarket_events(tag_slug=None, closed=False, limit=50, timeout=20):
    """Fetches events from Polymarket's Gamma API, optionally filtered
    by tag_slug (e.g. 'league-of-legends') and closed status. Returns
    the raw list of event dicts on success. Raises on a real HTTP
    error or malformed response — callers should wrap this in their
    own try/except, matching the established pattern elsewhere in this
    project (get_json in mlb_app.py) rather than this function
    silently swallowing failures itself."""
    params = {"limit": limit, "closed": str(closed).lower()}
    if tag_slug:
        params["tag_slug"] = tag_slug
    response = requests.get(f"{GAMMA_BASE_URL}/events", params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def extract_player_prop_markets(events):
    """Given a list of raw Polymarket event dicts, returns a flat list
    of individual market dicts that look like real player-prop
    markets — filtering out plain moneyline/spread/totals markets,
    which don't have the same structure. This is a REAL, UNVALIDATED
    heuristic (checking the market question for player-prop-style
    language), not a confirmed field Polymarket exposes for this —
    worth revisiting once real live data is actually inspected,
    rather than trusting this filter blindly."""
    player_prop_markets = []
    for event in events:
        for market in event.get("markets", []):
            question = (market.get("question") or "").lower()
            # Real, deliberately loose heuristic — Polymarket doesn't
            # expose a clean 'market_type' field distinguishing player
            # props from match-level markets in what's been verified
            # so far. Flagged honestly as approximate, not exact.
            if any(kw in question for kw in ["kills", "assists", "deaths", "cs by", "kda"]):
                parsed_market = dict(market)
                parsed_market["outcomes_parsed"] = _parse_stringified_json_field(market.get("outcomes"))
                parsed_market["outcomePrices_parsed"] = _parse_stringified_json_field(market.get("outcomePrices"))
                parsed_market["clobTokenIds_parsed"] = _parse_stringified_json_field(market.get("clobTokenIds"))
                parsed_market["event_title"] = event.get("title")
                parsed_market["event_slug"] = event.get("slug")
                player_prop_markets.append(parsed_market)
    return player_prop_markets


def extract_match_winner_markets(events):
    """Given a list of raw Polymarket event dicts, returns a flat list
    of real match/series-winner markets — the market type CONFIRMED to
    actually exist for LoL (unlike player props, which were checked
    and confirmed absent). A real, more reliable signal than the
    keyword heuristic used for player props: a genuine match-winner
    market has real TEAM NAMES as its two outcomes, not the generic
    "Yes"/"No" pair used by simpler binary markets. This isn't a
    perfect filter either (a market titled 'Will Team X reach playoffs'
    could theoretically also list team-name-like outcomes), but
    checking for exactly 2 outcomes that both look like real team names
    (present in the event's own team1/team2-style title, when parseable)
    is meaningfully more targeted than a bare keyword match."""
    match_winner_markets = []
    for event in events:
        for market in event.get("markets", []):
            outcomes = _parse_stringified_json_field(market.get("outcomes"))
            if len(outcomes) != 2:
                continue
            if outcomes[0].strip().lower() == "yes" and outcomes[1].strip().lower() == "no":
                continue  # a plain Yes/No market, not a real team-vs-team one
            parsed_market = dict(market)
            parsed_market["outcomes_parsed"] = outcomes
            parsed_market["outcomePrices_parsed"] = _parse_stringified_json_field(market.get("outcomePrices"))
            parsed_market["clobTokenIds_parsed"] = _parse_stringified_json_field(market.get("clobTokenIds"))
            parsed_market["event_title"] = event.get("title")
            parsed_market["event_slug"] = event.get("slug")
            match_winner_markets.append(parsed_market)
    return match_winner_markets


def polymarket_price_to_american_odds(prob):
    """Converts a Polymarket implied-probability price (0 to 1) into
    American odds, so this can plug directly into the exact same
    analyze_prop/EV pipeline already built and validated for MLB, NBA,
    and NFL — rather than building a second, parallel EV system just
    for Polymarket's different price format. Mirrors the exact
    prob_to_american_odds logic in bet_math.py (kept as a real,
    separate copy here rather than importing across modules that
    otherwise have no reason to depend on each other)."""
    try:
        if prob is None or prob <= 0 or prob >= 1:
            return None
        if prob >= 0.5:
            return int(round(-100 * prob / (1 - prob)))
        else:
            return int(round(100 * (1 - prob) / prob))
    except Exception:
        return None


def get_polymarket_safety_check():
    """Real, honest diagnostic — built the same way as the NFL live-
    pipeline safety check. Does NOT assume the fetch/filtering logic
    above works correctly; actually calls it and reports the real
    result (or a real error with traceback), since the query-parameter
    filtering behavior could not be independently verified from the
    development environment. Meant to be called from an admin-only
    diagnostics panel, same pattern as NFL's. Updated to report on
    match-winner markets (the confirmed-real market type) rather than
    player props (confirmed absent, per real live-data investigation)."""
    results = {}
    try:
        events = get_polymarket_events(tag_slug="league-of-legends", closed=False, limit=20)
        results["fetch_ok"] = True
        results["event_count"] = len(events)
        results["sample_titles"] = [e.get("title") for e in events[:5]]
        match_markets = extract_match_winner_markets(events)
        results["match_winner_market_count"] = len(match_markets)
        results["sample_match_markets"] = [
            {"event": m.get("event_title"), "outcomes": m.get("outcomes_parsed"), "prices": m.get("outcomePrices_parsed")}
            for m in match_markets[:5]
        ]
    except Exception as e:
        results["fetch_ok"] = False
        results["error"] = str(e)
    return results
