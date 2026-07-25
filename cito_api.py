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

# Real, confirmed set of invisible/zero-width Unicode characters found
# in real live data (July 2026) — 'Movistar KOI Fénix' had a real
# U+2060 WORD JOINER character before the name, which Python's
# .strip() does NOT remove (it only strips actual whitespace, not
# arbitrary Unicode formatting characters). This silently broke exact-
# match team-name lookups even though the visible name was otherwise
# perfectly correct. Includes the most common invisible characters
# known to appear in real-world text, not just the one specific
# character confirmed so far — a narrow fix for only U+2060 would risk
# missing the next real, different invisible character.
_INVISIBLE_UNICODE_CHARS = "\u2060\u200b\u200c\u200d\ufeff\u00a0"


def _normalize_team_name(name):
    """Real, shared normalization used everywhere a team name gets
    compared — strips real, confirmed invisible Unicode characters (in
    addition to normal whitespace) before lowercasing. Centralized
    here rather than duplicated across every function that touches a
    team name, so this fix applies consistently everywhere, not just
    in whichever single spot the bug happened to be noticed first."""
    if not name:
        return ""
    cleaned = name
    for char in _INVISIBLE_UNICODE_CHARS:
        cleaned = cleaned.replace(char, "")
    return cleaned.strip().lower()


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


def get_lol_schedule_upcoming(api_key, timeout=20):
    """Real, documented endpoint (found via Cito's own full docs page,
    July 2026): GET /api/v1/lol/schedule/upcoming — a wider window of
    upcoming matches than schedule/today, not limited to just the
    current day. Same real response shape as schedule/today (each
    match includes nested team1/team2 objects with slug/name/code),
    confirmed from live data earlier in this build.

    Real fix (July 2026): replaces fetching the ENTIRE global team
    database (GET /lol/teams, paginated) as the source for the
    name-to-slug map. That approach was technically more complete, but
    real live testing showed the global database is genuinely huge
    (pagination hit a rate limit at offset=1800, meaning 1800+ teams
    across every minor/amateur region worldwide) — burning through the
    free tier's monthly call quota in a single pipeline run just to
    resolve a handful of real, currently-relevant teams. Since
    Polymarket only lists markets for real, currently live/upcoming
    matches anyway, the set of teams that actually need to resolve is
    naturally small and already covered by a real upcoming-schedule
    fetch — a single call instead of dozens."""
    response = requests.get(
        f"{CITO_BASE_URL}/api/v1/lol/schedule/upcoming",
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


def build_team_name_to_slug_map(*schedule_responses):
    """Solves a real, necessary problem for connecting Polymarket to
    Cito: Polymarket identifies teams by full display name ('G2
    Esports', 'Movistar KOI') inside market outcome strings, while
    Cito identifies teams by slug ('g2', 'mkoi'). Accepts one or more
    real schedule responses (schedule/today, schedule/upcoming) and
    builds the map from their nested team1/team2 objects.

    Real fix (July 2026): an earlier version fetched Cito's ENTIRE
    global team database (GET /lol/teams, paginated) for
    completeness. Real live testing showed that database is genuinely
    huge — pagination hit a real rate limit at offset=1800, meaning
    1800+ teams across every minor/amateur region worldwide, burning
    through the free tier's monthly quota in a single pipeline run
    just to resolve a handful of currently-relevant teams. Since
    Polymarket only lists markets for real, live/upcoming matches, the
    set of teams that actually need to resolve is naturally covered by
    real schedule data (schedule/today + schedule/upcoming combined)
    at a fraction of the API cost.

    Real, separate bug also fixed here (kept from the previous
    version): 'name' and 'code' (this schedule shape's short-name
    field — NOT 'shortName', that was the global-teams-endpoint's
    naming) both feed into the same key space, and two different teams
    (e.g. a main roster and its academy squad) can genuinely share a
    short code. Tracks every distinct slug seen per key; any key
    mapping to more than one real, different slug is excluded from the
    final map entirely, rather than letting whichever team was
    processed last silently win — an unmatched team should block a
    prediction, not silently produce a wrong one."""
    key_to_slugs = {}
    for schedule_response in schedule_responses:
        if isinstance(schedule_response, dict):
            matches = schedule_response.get("data", [])
        elif isinstance(schedule_response, list):
            matches = schedule_response
        else:
            matches = []

        for match in matches:
            if not isinstance(match, dict):
                continue
            for team_key in ("team1", "team2"):
                team = match.get(team_key) or {}
                slug = team.get("slug")
                name = team.get("name")
                code = team.get("code")
                if slug and name:
                    key_to_slugs.setdefault(_normalize_team_name(name), set()).add(slug)
                if slug and code:
                    key_to_slugs.setdefault(_normalize_team_name(code), set()).add(slug)

    name_to_slug = {}
    for key, slugs in key_to_slugs.items():
        if len(slugs) == 1:
            name_to_slug[key] = next(iter(slugs))
        # len(slugs) > 1 means genuine ambiguity — deliberately excluded
    return name_to_slug


def build_team_name_to_slug_map_from_teams_list(teams_list_response):
    """Companion to build_team_name_to_slug_map(), built from the
    real, comprehensive GET /api/v1/lol/teams response instead of
    schedule data. Real, confirmed schema (verified against a live
    response, July 2026): {"teams": [{"slug", "name", "shortName",
    "region", "logoUrl", "isActive", "leagues", "rosterCount",
    "rosterStatus"}, ...]} — note this uses 'shortName', a genuinely
    different field name than the schedule endpoints' 'code'.

    This was the original approach, then abandoned when real testing
    on the free tier hit a rate limit at offset=1800 (the full
    database is genuinely huge — every minor/amateur team across every
    region). Restored as a real, deliberate fallback (not the default)
    now that a paid tier (50k calls/month, 30/min) makes the full fetch
    affordable again — used specifically for teams schedule data
    doesn't cover (e.g. major but currently-between-matches teams like
    T1, Cloud9, Team Liquid, confirmed missing from schedule/today +
    schedule/upcoming during real live testing), not as the default
    for every run. Same collision-safe two-pass logic as its schedule
    counterpart."""
    key_to_slugs = {}
    if isinstance(teams_list_response, dict):
        teams = teams_list_response.get("teams") or teams_list_response.get("data") or []
    elif isinstance(teams_list_response, list):
        teams = teams_list_response
    else:
        teams = []

    for team in teams:
        if not isinstance(team, dict):
            continue
        slug = team.get("slug")
        name = team.get("name")
        short_name = team.get("shortName")
        if slug and name:
            key_to_slugs.setdefault(_normalize_team_name(name), set()).add(slug)
        if slug and short_name:
            key_to_slugs.setdefault(_normalize_team_name(short_name), set()).add(slug)

    name_to_slug = {}
    for key, slugs in key_to_slugs.items():
        if len(slugs) == 1:
            name_to_slug[key] = next(iter(slugs))
    return name_to_slug


def build_team_region_map(teams_list_response):
    """Real extraction (July 2026) — {slug: region} from the same
    confirmed teams-list schema used by build_team_name_to_slug_map_
    from_teams_list(). Needed for lol_elo.py's cross-region
    international K-factor boost, which requires knowing whether two
    teams in an international match are actually from different
    regions (a same-region matchup at Worlds doesn't teach the model
    anything new about cross-region strength, per the real, precise
    refinement this feature was built around). A team with a missing/
    null region (confirmed to happen in real data — some entries have
    region: null) is simply excluded from the map, not given a guessed
    value — the boost logic already treats a missing region as 'don't
    apply the boost', the safe, honest default."""
    if isinstance(teams_list_response, dict):
        teams = teams_list_response.get("teams") or teams_list_response.get("data") or []
    elif isinstance(teams_list_response, list):
        teams = teams_list_response
    else:
        teams = []

    region_map = {}
    for team in teams:
        if not isinstance(team, dict):
            continue
        slug = team.get("slug")
        region = team.get("region")
        if slug and region:
            region_map[slug] = region.strip().lower()
    return region_map


def merge_name_to_slug_maps(*maps):
    """Safely combines multiple already-built name-to-slug maps (e.g.
    one from schedule data, one from the full teams list) into one.
    Applies the same collision-detection principle at the merge level:
    if a key exists in more than one input map with DIFFERENT slug
    values, that's a real, genuine conflict between two otherwise-
    trusted sources — excluded from the final map rather than letting
    whichever map happened to be passed last silently win. Keys that
    agree across maps, or that only appear in one map, merge in
    normally."""
    key_to_slugs = {}
    for m in maps:
        for key, slug in m.items():
            key_to_slugs.setdefault(key, set()).add(slug)

    merged = {}
    for key, slugs in key_to_slugs.items():
        if len(slugs) == 1:
            merged[key] = next(iter(slugs))
    return merged


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
    normalized = _normalize_team_name(polymarket_team_name)
    return name_to_slug_map.get(normalized)


# Real, known league identifiers that plausibly appear in Polymarket's
# own market text ("... (BO3) - LEC Regular Season", "... - LCS
# Regular Season"). Used only to disambiguate a GENUINE name collision
# (e.g. two different real teams both legitimately called "Cloud9" or
# "Team Liquid" across different regions) — never to override an
# already-unambiguous match.
KNOWN_LEAGUE_MARKERS = {
    'lec': ['lec'], 'lcs': ['lcs'], 'lck': ['lck'], 'lpl': ['lpl'],
    'lta': ['lta', 'lta_n', 'lta_s', 'lta north', 'lta south'],
    'nacl': ['nacl'], 'ljl': ['ljl'], 'pcs': ['pcs'], 'vcs': ['vcs'],
    'cblol': ['cblol'], 'msi': ['msi'], 'worlds': ['worlds'],
    # Real markers added (July 2026) — confirmed missing from live
    # diagnostic data, which showed real market text containing these
    # exact phrases with no matching marker to catch them.
    'roadoflegends': ['road of legends'],
    'primeleague': ['prime league'],
}


# Real, explicit, human-verified name-to-slug overrides — for cases
# where Polymarket's team name and Cito's real team name/shortName
# differ in a way too specific and one-off to justify a general (and
# riskier) matching rule, the same way the prefix and last-word
# fallbacks above generalize real, confirmed patterns. Each entry here
# is a fact a real person confirmed (not a string-similarity guess) —
# e.g. 'KT Rolster Challengers' (Polymarket's name) is known, from
# real domain knowledge of LCK's structure (each org fields a distinct
# main team AND a separate 'Challengers' developmental team), to be
# Cito's 'kt-challengers' entry ('kt Challengers'). A first attempt at
# this alias incorrectly pointed to 'kt-rolster-b' — corrected after
# the user's real domain knowledge caught the mistake before it
# shipped: 'kt-rolster-b' is some other, unrelated 'B team' concept in
# Cito's data, not the real LCK Challengers team.
# Add more entries here as specific, confirmed mismatches are found —
# each key should be the exact Polymarket team name, lowercased.
MANUAL_TEAM_ALIASES = {
    'kt rolster challengers': 'kt-challengers',
}


def build_team_candidates_map(*schedule_or_teams_list_responses):
    """A richer companion to build_team_name_to_slug_map() — instead
    of collapsing an ambiguous name to 'excluded', keeps every real
    candidate (slug + its real league AND region tags) for every
    name/code/shortName seen. Accepts a mix of schedule-shaped
    responses (nested team1/team2, with a 'leagueSlug' on the parent
    match) and the flat teams-list shape (team objects with 'leagues'
    and 'region' directly). This is the real data disambiguation
    needs — a plain name-to-slug map necessarily throws this away.

    Real addition (July 2026): now also tracks 'region' as a second,
    separate disambiguation signal alongside leagues. Real live data
    showed two different Cito entries both named 'Cloud9 Kia' — one
    tagged league 'lta_n', the other with NO league tag at all but a
    real 'region: LCS' field that directly matches real Polymarket
    market text ('LCS Regular Season'). Leagues alone couldn't
    disambiguate that case; region can."""
    candidates = {}  # key -> {slug: {"leagues": set(...), "regions": set(...)}}

    def _add(key, slug, league_slugs, region):
        if not key or not slug:
            return
        key = _normalize_team_name(key)
        entry = candidates.setdefault(key, {}).setdefault(slug, {"leagues": set(), "regions": set()})
        entry["leagues"].update(league_slugs)
        if region:
            entry["regions"].add(_normalize_team_name(region))

    for response in schedule_or_teams_list_responses:
        if isinstance(response, dict):
            if "teams" in response or (isinstance(response.get("data"), list) and response.get("data") and "slug" in response["data"][0] and "team1" not in response["data"][0]):
                # Flat teams-list shape
                teams = response.get("teams") or response.get("data") or []
                for team in teams:
                    if not isinstance(team, dict):
                        continue
                    slug = team.get("slug")
                    leagues = team.get("leagues") or []
                    league_slugs = {l.get("slug") for l in leagues if isinstance(l, dict) and l.get("slug")}
                    region = team.get("region")
                    for key in (team.get("name"), team.get("shortName")):
                        _add(key, slug, league_slugs, region)
            else:
                # Schedule shape — no region field available here
                matches = response.get("data", [])
                for match in matches:
                    if not isinstance(match, dict):
                        continue
                    league_slug = match.get("leagueSlug")
                    league_slugs = {league_slug} if league_slug else set()
                    for team_key in ("team1", "team2"):
                        team = match.get(team_key) or {}
                        slug = team.get("slug")
                        for key in (team.get("name"), team.get("code")):
                            _add(key, slug, league_slugs, None)
        elif isinstance(response, list):
            for match in response:
                if not isinstance(match, dict):
                    continue
                league_slug = match.get("leagueSlug")
                league_slugs = {league_slug} if league_slug else set()
                for team_key in ("team1", "team2"):
                    team = match.get(team_key) or {}
                    slug = team.get("slug")
                    for key in (team.get("name"), team.get("code")):
                        _add(key, slug, league_slugs, None)

    return candidates


def _find_prefix_candidates(polymarket_team_name, candidates_map):
    """Real, deliberately narrow fallback for when the exact name
    isn't found in candidates_map at all — not genuine ambiguity, but
    a real naming mismatch (Cito's real name is 'Cloud9 Kia', not
    plain 'Cloud9', the same pattern already confirmed with '100
    Thieves' being stored as just 'Thieves'). Only matches when the
    Polymarket name is a real PREFIX of a candidate key (or vice
    versa) — e.g. 'cloud9' is a genuine prefix of 'cloud9 kia'. This
    is deliberately much narrower than the substring-anywhere fallback
    removed earlier (which caused real wrong matches like 'T1' hitting
    't1-rookies') — a prefix relationship at the start of the string is
    a meaningfully stronger, safer signal than a substring appearing
    anywhere. Returns a merged {slug: {"leagues", "regions"}} dict
    combining every matching key's candidates."""
    normalized = _normalize_team_name(polymarket_team_name)
    merged = {}
    for key, slug_map in candidates_map.items():
        if key.startswith(normalized) or normalized.startswith(key):
            for slug, info in slug_map.items():
                entry = merged.setdefault(slug, {"leagues": set(), "regions": set()})
                entry["leagues"].update(info["leagues"])
                entry["regions"].update(info["regions"])
    return merged


def _find_last_word_candidates(polymarket_team_name, candidates_map):
    """Real, narrow fallback for the mirror-image pattern of the
    prefix fallback above: real live data showed 'Team WE' is stored
    in Cito as 'Xi'an Team WE' — here 'WE' is a SUFFIX/last word, not
    a prefix, so _find_prefix_candidates can't catch it (neither
    string is a prefix of the other). Both real candidate entries had
    shortName exactly 'WE', which exactly equals the last word of
    'Team WE'. Matches ONLY when the Polymarket name's last word,
    split on whitespace, EXACTLY equals an existing candidates_map key
    — deliberately exact and narrow (not 'contains'), since a bare
    2-3 letter shortName like 'WE' would produce real false positives
    under any looser matching rule."""
    words = _normalize_team_name(polymarket_team_name).split()
    if not words:
        return {}
    last_word = words[-1]
    return dict(candidates_map.get(last_word, {}))


def resolve_team_with_league_context(polymarket_team_name, candidates_map, market_text):
    """Real disambiguation, with three real passes, in priority order:
    1. A human-verified manual alias (MANUAL_TEAM_ALIASES) — a
       confirmed fact takes priority over any pattern-based guessing.
    2. If the exact name is genuinely ambiguous (multiple real slugs),
       or genuinely absent (a real naming mismatch, e.g. 'Cloud9' vs
       Cito's real 'Cloud9 Kia', or 'Team WE' vs 'Xi'an Team WE'), use
       real league AND region markers found in the actual Polymarket
       market text to narrow it down.
    3. Returns a slug ONLY if evidence narrows it to exactly one —
       never guesses. Keeps the same standing principle as the rest of
       this project: resolve with real evidence, or don't resolve at
       all."""
    normalized = _normalize_team_name(polymarket_team_name)

    if normalized in MANUAL_TEAM_ALIASES:
        return MANUAL_TEAM_ALIASES[normalized]

    candidate_slugs = candidates_map.get(normalized, {})

    if len(candidate_slugs) == 0:
        # Real naming mismatch fallbacks — prefix match (Cloud9 case),
        # then last-word exact match (Team WE case). Both deliberately
        # narrow, not broad substring matching.
        candidate_slugs = _find_prefix_candidates(polymarket_team_name, candidates_map)
    if len(candidate_slugs) == 0:
        candidate_slugs = _find_last_word_candidates(polymarket_team_name, candidates_map)

    if len(candidate_slugs) == 1:
        return next(iter(candidate_slugs))
    if len(candidate_slugs) == 0:
        return None

    market_text_lower = (market_text or "").lower()
    matched_markers = set()
    for marker_league, aliases in KNOWN_LEAGUE_MARKERS.items():
        if any(alias in market_text_lower for alias in aliases):
            matched_markers.add(marker_league)

    def _has_marker_match(tags):
        return any(marker in tag or tag in marker for tag in tags for marker in matched_markers)

    if matched_markers:
        # Try leagues first, then region, as two independent real signals
        by_league = [slug for slug, info in candidate_slugs.items() if _has_marker_match(info["leagues"])]
        if len(by_league) == 1:
            return by_league[0]
        by_region = [slug for slug, info in candidate_slugs.items() if _has_marker_match(info["regions"])]
        if len(by_region) == 1:
            return by_region[0]

    return None  # still ambiguous even with all available real context — don't guess


def search_teams_list_for_name(teams_list_response, search_term):
    """Real investigation tool, not used by the main pipeline — for
    a team that shows ZERO candidates (a real, different problem than
    genuine ambiguity: it means neither the schedule data nor the
    full teams list has anything under that exact name/shortName at
    all), this searches every team's real name/shortName/slug for a
    partial, case-insensitive match to the search term. Answers the
    real question directly: does this team exist in Cito's data under
    a different string than what Polymarket uses, or is it genuinely
    absent? Returns a list of {slug, name, shortName, region, leagues}
    for every real, partial match found."""
    if isinstance(teams_list_response, dict):
        teams = teams_list_response.get("teams") or teams_list_response.get("data") or []
    elif isinstance(teams_list_response, list):
        teams = teams_list_response
    else:
        teams = []

    term_lower = _normalize_team_name(search_term)
    matches = []
    for team in teams:
        if not isinstance(team, dict):
            continue
        name = (team.get("name") or "")
        short_name = (team.get("shortName") or "")
        slug = (team.get("slug") or "")
        if term_lower in name.lower() or term_lower in short_name.lower() or term_lower in slug.lower():
            matches.append({
                "slug": slug, "name": name, "shortName": short_name,
                "region": team.get("region"),
                "leagues": [l.get("slug") for l in (team.get("leagues") or []) if isinstance(l, dict)],
            })
    return matches


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
