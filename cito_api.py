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


def get_lol_teams_list(api_key, timeout=20, max_pages=20):
    """Real, documented endpoint (found via Cito's own full docs page,
    July 2026): GET /api/v1/lol/teams — 'List Teams: Professional LoL
    teams'. This is the real, authoritative source for team slugs,
    replacing the earlier approach of deriving a name-to-slug map only
    from whichever teams happened to appear on a single day's schedule.

    Real bug found and fixed (July 2026): a first version of this
    function made a single, unpaginated call and used whatever came
    back directly. Real live data showed the response is sorted
    alphabetically/numerically (100t, 19-esports, 2-massive, 300,
    3bl-esports, ...) and total team count across all regions/tiers is
    almost certainly larger than one page — meaning teams that sort
    later in the alphabet (G2 Esports, Karmine Corp, Movistar KOI,
    Team Vitality — exactly the real LEC teams this pipeline needs)
    were silently never reached, causing every matchup to fail to
    resolve. This now pages through using limit/offset (the general
    pagination pattern the docs describe for this API) until the
    response reports no more results or max_pages is hit, then
    combines every page's teams into one full list. Handles a few
    plausible 'more data available' signals defensively (hasMore,
    or a returned page smaller than the requested limit), since the
    exact field name for this specific endpoint hasn't been directly
    confirmed."""
    all_teams = []
    limit = 100
    offset = 0
    for _ in range(max_pages):
        response = requests.get(
            f"{CITO_BASE_URL}/api/v1/lol/teams",
            headers=_cito_headers(api_key), params={"limit": limit, "offset": offset}, timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        page_teams = data.get("teams") or data.get("data") or (data if isinstance(data, list) else [])
        if not page_teams:
            break
        all_teams.extend(page_teams)
        has_more = data.get("hasMore") if isinstance(data, dict) else None
        if has_more is False:
            break
        if has_more is None and len(page_teams) < limit:
            break  # a page smaller than requested strongly implies this was the last one
        offset += limit
    return {"teams": all_teams, "total_fetched": len(all_teams)}


def build_team_name_to_slug_map(teams_list_response):
    """Solves a real, necessary problem for connecting Polymarket to
    Cito: Polymarket identifies teams by full display name ('G2
    Esports', 'Movistar KOI') inside market outcome strings, while
    Cito identifies teams by slug ('g2', 'mkoi'). Built against the
    real, documented GET /api/v1/lol/teams endpoint ('List Teams:
    Professional LoL teams') — the authoritative full team list,
    rather than the earlier approach of only building this map from
    whichever teams happened to appear on one specific day's schedule.

    CONFIRMED real schema (verified against a live response, July
    2026): {"teams": [{"slug", "name", "shortName", "region",
    "logoUrl", "isActive", "leagues", "rosterCount", "rosterStatus"},
    ...]}.

    Real bug found and fixed (July 2026), separate from the earlier
    substring-fallback removal: 'name' and 'shortName' both feed into
    the same dict key space here. Real live data showed T1's main
    roster still resolving to 't1-rookies' even after removing the
    fuzzy substring match — because T1's academy/rookie squad
    apparently ALSO uses 'T1' as its shortName, so one team's entry was
    silently overwriting the other's regardless of processing order,
    with exact-match lookups powerless to detect it (both sides of the
    lookup were "exact"). Now tracks every distinct slug seen per key;
    if a key (name or shortName) ever maps to more than one real,
    different slug, that key is excluded from the final map entirely
    rather than letting whichever team was processed last silently
    win. An excluded/ambiguous team will fail to resolve and get
    skipped upstream — the correct, honest outcome when genuine
    ambiguity exists, consistent with this project's standing
    principle that an unmatched team should block a prediction, not
    silently produce a wrong one."""
    name_to_slug = {}
    if isinstance(teams_list_response, dict):
        teams = teams_list_response.get("teams") or teams_list_response.get("data") or []
    elif isinstance(teams_list_response, list):
        teams = teams_list_response
    else:
        teams = []

    # First pass: collect every distinct slug seen for each key
    key_to_slugs = {}
    for team in teams:
        if not isinstance(team, dict):
            continue
        slug = team.get("slug")
        name = team.get("name")
        short_name = team.get("shortName")
        if slug and name:
            key_to_slugs.setdefault(name.strip().lower(), set()).add(slug)
        if slug and short_name:
            key_to_slugs.setdefault(short_name.strip().lower(), set()).add(slug)

    # Second pass: only keep keys with exactly one, unambiguous slug
    for key, slugs in key_to_slugs.items():
        if len(slugs) == 1:
            name_to_slug[key] = next(iter(slugs))
        # len(slugs) > 1 means genuine ambiguity — deliberately excluded

    return name_to_slug


def match_polymarket_name_to_slug(polymarket_team_name, name_to_slug_map):
    """Looks up a real slug for a Polymarket outcome team name against
    the map built by build_team_name_to_slug_map(). EXACT match only
    (case-insensitive after stripping whitespace).

    Real bug found and fixed (July 2026): an earlier version of this
    function also fell back to a loose substring check ("does one
    string contain the other") when an exact match failed. That was
    tested only against a small, 2-team sample and looked safe — but
    against the REAL, full team database (hundreds of teams across all
    regions/tiers), it produced genuinely wrong, silent mismatches:
    'T1' matched to 't1-rookies' (T1's academy team, not the real main
    roster), 'Team Liquid' and 'Cloud9' matched to completely unrelated
    teams. Dict iteration order meant whichever false match happened to
    be found first silently won, with no way to tell a right match from
    a wrong one downstream. Removed entirely — an unmatched team now
    correctly returns None and gets skipped, rather than risking a
    wrong, undetectable prediction. This does mean fewer real matchups
    will resolve than before; that's the correct, honest tradeoff."""
    normalized = polymarket_team_name.strip().lower()
    return name_to_slug_map.get(normalized)


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


def diagnose_team_match_coverage(team_matches_response):
    """Real diagnostic (July 2026) — built specifically to answer 'why
    are real matches missing from the ratings?' rather than guessing
    between the likely causes. Reports:
    - total entries actually returned by Cito for this team
    - how many are 'completed' at all
    - how many of THOSE completed matches have a real, non-empty
      'games' array (build_team_ratings_from_history() silently skips
      any completed match missing this — a real, possible source of
      data loss separate from Cito simply not returning enough
      matches in the first place)
    - the real date range covered by the completed matches, to reveal
      whether this is a pagination/limit issue (a suspiciously narrow
      window) rather than a per-match data-completeness issue."""
    if isinstance(team_matches_response, dict):
        entries = team_matches_response.get("data")
        if entries is None:
            entries = list(team_matches_response.values())
    elif isinstance(team_matches_response, list):
        entries = team_matches_response
    else:
        entries = []

    total = len(entries)
    completed = [e for e in entries if isinstance(e, dict) and e.get("state") == "completed" and e.get("winner")]
    completed_with_games = [e for e in completed if e.get("games")]
    completed_missing_games = [e for e in completed if not e.get("games")]

    start_times = [e.get("startTime") for e in completed if e.get("startTime")]
    date_range = {"oldest": min(start_times), "newest": max(start_times)} if start_times else None

    return {
        "total_entries_returned": total,
        "completed_count": len(completed),
        "completed_with_usable_games_data": len(completed_with_games),
        "completed_missing_games_data": len(completed_missing_games),
        "sample_missing_games_matches": [
            {"matchId": e.get("matchId"), "startTime": e.get("startTime"), "winner": e.get("winner")}
            for e in completed_missing_games[:5]
        ],
        "date_range_of_completed_matches": date_range,
    }


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
        ("teams_list", get_lol_teams_list),
    ]:
        try:
            data = fn(api_key)
            if label == "teams_list":
                teams = data.get("teams", [])
                results[label] = {
                    "ok": True, "type": "dict",
                    "total_fetched": data.get("total_fetched"),
                    "sample_first_5": teams[:5],
                    "sample_last_5": teams[-5:] if len(teams) >= 5 else teams,
                }
            else:
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
