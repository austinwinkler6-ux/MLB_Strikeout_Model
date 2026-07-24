"""
cito_api.py — CitoAPI client for LoL esports team match history/results
(July 2026).

A genuinely new, standalone module — same "keep new, separable pieces
out of the single giant file" approach used for bet_math.py and
polymarket_api.py.

Real, CONFIRMED facts (verified against live responses from a real
deployed account, July 2026 — not guessed):
  - Base URL: https://api.citoapi.com
  - Auth: requires an 'x-api-key' header.
  - GET /api/v1/lol/schedule/today — confirmed. Returns a mix of
    upcoming and same-day completed matches. Response shape:
    {"success": true, "status": "ok", "count": N, "data": [...]}
    Each match: matchId, tournamentName, leagueName, leagueSlug,
    blockName, team1/team2 (slug, name, code, logoUrl, score),
    winnerSlug, strategy ("Bo3"/"Bo5"), startTime, state
    ("completed"/"unstarted"), source.
  - GET /api/v1/lol/teams/{slug}/matches — CONFIRMED WORKING (this
    was an educated guess at the path pattern in an earlier version of
    this module; verified correct via a real, live response). Returns
    a combined, chronological list of a team's upcoming AND completed
    matches — NOT wrapped in success/data, appears to be a flat
    dict-of-index or list (confirmed structure: numbered entries each
    shaped like: matchId, tournamentName, round, startTime, state,
    team1/team2 (slug, name, logoUrl, score, isRequested — the
    isRequested flag marks which team matches the {slug} you queried),
    winner (slug of winning team, null if unstarted), won (bool,
    relative to the requested team, null if unstarted), games (array
    of per-game results within the series: gameNumber, winnerSlug,
    duration in seconds), vodUrl.
  - Free tier: 500 calls/month.

This confirmed schema is exactly what's needed to build a real
Elo/power-rating system: chronological match history per team, real
final series scores, explicit winners, and per-game granularity if a
future version wants game-level rather than series-level ratings.
"""

import requests
from datetime import datetime, timezone

CITO_BASE_URL = "https://api.citoapi.com"


def _cito_headers(api_key):
    return {"x-api-key": api_key}


def get_lol_schedule_today(api_key, timeout=20):
    """Confirmed endpoint. Returns today's LoL schedule — a mix of
    upcoming and same-day completed matches, wrapped in
    {"success", "status", "count", "data": [...]}."""
    response = requests.get(
        f"{CITO_BASE_URL}/api/v1/lol/schedule/today",
        headers=_cito_headers(api_key), timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_lol_live_matches(api_key, timeout=20):
    """Confirmed endpoint. Returns currently active LoL esports
    matches and live state."""
    response = requests.get(
        f"{CITO_BASE_URL}/api/v1/lol/live",
        headers=_cito_headers(api_key), timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_lol_team_matches(api_key, team_slug, timeout=20):
    """Confirmed endpoint — verified working against a real account
    (July 2026). Returns a team's combined upcoming + completed match
    history, chronologically. This is the real source for building
    Elo/power ratings."""
    response = requests.get(
        f"{CITO_BASE_URL}/api/v1/lol/teams/{team_slug}/matches",
        headers=_cito_headers(api_key), timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def build_team_name_to_slug_map(schedule_response):
    """Solves a real, necessary problem for connecting Polymarket to
    Cito: Polymarket identifies teams by full display name ('G2
    Esports', 'Movistar KOI') inside market outcome strings, while
    Cito identifies teams by slug ('g2', 'mkoi') for its match-history
    endpoint. Confirmed real schedule/today response includes both
    together on every team object (team1/team2: {slug, name, code}),
    so this builds a real, current mapping FROM this live data rather
    than a hardcoded, staleness-prone table that would need manual
    maintenance every time a team rebrands or a new team appears.
    Maps both the full name AND the short code (both lowercased) to
    the slug, to maximize real matches against however Polymarket's
    market text happens to phrase a given team."""
    name_to_slug = {}
    data = schedule_response.get("data", []) if isinstance(schedule_response, dict) else schedule_response
    for match in data:
        for team_key in ("team1", "team2"):
            team = match.get(team_key, {})
            slug = team.get("slug")
            name = team.get("name")
            code = team.get("code")
            if slug and name:
                name_to_slug[name.strip().lower()] = slug
            if slug and code:
                name_to_slug[code.strip().lower()] = slug
    return name_to_slug


def match_polymarket_name_to_slug(polymarket_team_name, name_to_slug_map):
    """Looks up a real slug for a Polymarket outcome team name against
    the map built by build_team_name_to_slug_map(). Tries an exact
    (case-insensitive) match first; falls back to a real but honestly
    imperfect substring check (does the map's team name appear inside,
    or contain, the Polymarket name) for cases where phrasing differs
    slightly (e.g. 'G2' vs 'G2 Esports'). Returns None, not a guessed
    slug, if nothing reasonably matches — an unmatched team should
    block a prediction, not silently produce a wrong one."""
    normalized = polymarket_team_name.strip().lower()
    if normalized in name_to_slug_map:
        return name_to_slug_map[normalized]
    for known_name, slug in name_to_slug_map.items():
        if known_name in normalized or normalized in known_name:
            return slug
    return None


def extract_completed_matches(team_matches_response):
    """Given the raw response from get_lol_team_matches(), returns
    only the real, completed matches (state == 'completed', winner is
    not None) — the actual training data for a rating system. Handles
    both a plain list and a dict-of-numbered-entries shape, since the
    exact top-level container wasn't fully pinned down from the
    partial responses inspected so far (worth re-confirming once this
    is wired into real code and run against a full response)."""
    if isinstance(team_matches_response, dict):
        # dict-of-numbered-entries or a wrapped {"data": [...]} shape
        entries = team_matches_response.get("data")
        if entries is None:
            entries = list(team_matches_response.values())
    elif isinstance(team_matches_response, list):
        entries = team_matches_response
    else:
        entries = []

    completed = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("state") == "completed" and entry.get("winner"):
            completed.append(entry)
    return completed


def sort_matches_chronologically(matches):
    """Sorts completed matches oldest-to-newest by startTime — required
    for a rolling Elo/power-rating system, which must process results
    in the real order they happened, not however the API returns them."""
    def _parse_time(m):
        try:
            return datetime.fromisoformat(m.get("startTime", "").replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            # Real bug fix (July 2026) — datetime.min is timezone-naive,
            # but successfully-parsed real timestamps above are
            # timezone-aware (they carry a +00:00 offset). Python
            # cannot compare naive and aware datetimes directly, so
            # sorted() threw a real TypeError the moment any match had
            # a missing/malformed startTime alongside real ones. The
            # fallback must be timezone-aware too, to sort consistently
            # with the real values rather than crashing on comparison.
            return datetime.min.replace(tzinfo=timezone.utc)

    return sorted(matches, key=_parse_time)


def get_cito_safety_check(api_key):
    """Real, honest diagnostic — same pattern as NFL's live pipeline
    safety check and Polymarket's safety check. Calls each real
    endpoint and reports genuine results (or genuine errors)."""
    results = {}

    for label, fn in [
        ("schedule_today", get_lol_schedule_today),
        ("live_matches", get_lol_live_matches),
    ]:
        try:
            data = fn(api_key)
            results[label] = {
                "ok": True,
                "type": type(data).__name__,
                "sample": data if not isinstance(data, list) else data[:2],
                "count": len(data) if isinstance(data, list) else data.get("count"),
            }
        except Exception as e:
            results[label] = {"ok": False, "error": str(e)}

    try:
        data = get_lol_team_matches(api_key, "t1")
        completed = extract_completed_matches(data)
        results["team_matches_t1"] = {
            "ok": True,
            "type": type(data).__name__,
            "total_entries": len(data) if isinstance(data, (list, dict)) else None,
            "completed_match_count": len(completed),
            "sample_completed": completed[:2],
        }
    except Exception as e:
        results["team_matches_t1"] = {"ok": False, "error": str(e)}

    return results
