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
import time
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


def get_lol_team_roster_history(api_key, team_slug, timeout=20):
    """Real, documented endpoint (found via Cito's full API list, July
    2026): GET /lol/teams/{slug}/roster/history — 'historical rosters
    and membership periods'. NOT YET VERIFIED against a real live
    response — a real, honest first step, not a confirmed-working
    integration like get_lol_team_matches() above.

    Investigated specifically to address roster continuity — a real,
    known gap in this Elo system (a team's rating is built entirely
    from past results, with no concept of WHO was actually playing in
    those games). Motivated by a concrete real case: a CBLOL Split 2
    season-opener where both teams could have entirely different
    rosters than whatever played their existing rated games from the
    prior split. This needs to be checked against live data (real
    schema, real date granularity, whether player-level identity is
    even exposed) before any real roster-aware rating logic can be
    designed around it — guessing at the shape here would repeat a
    mistake already made and corrected several times today."""
    response = requests.get(
        f"{CITO_BASE_URL}/api/v1/lol/teams/{team_slug}/roster/history",
        headers=_cito_headers(api_key), timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_lol_head_to_head(api_key, team_slug, opponent_slug, timeout=20):
    """Real, documented endpoint, CONFIRMED working via live testing
    (July 2026): GET /lol/teams/{slug}/h2h/{opponentSlug} — returns a
    real, structured head-to-head record: {"opponent": {...},
    "matches": {"total", "wins", "losses", "winRate"}, "games": {...},
    "recentMatches": [...]}. Confirmed via live testing to return
    MORE COMPLETE real data than reconstructing head-to-head from each
    team's own /matches history (10 real matches back to Jan 2025 for
    a real pair, vs only 4 found by reconstruction for the same pair)
    — a real, verified improvement, now the preferred head-to-head
    data source in this pipeline.

    HONEST, NAMED LIMITATION also confirmed via the same live test:
    even this endpoint was missing the same two real EWC matches
    (Karmine Corp vs Movistar KOI, May 14 and May 17, 2026) that the
    reconstruction approach was missing — this is a real, genuine gap
    in Cito's underlying data itself, not something either approach in
    our own code can work around. See get_lol_league_schedule() below
    for a real, different lead being investigated for this specific
    gap — EWC's own league entity shows a real _count.teams of 0,
    suggesting per-team endpoints may not properly surface all EWC
    matches regardless of which one is used."""
    response = requests.get(
        f"{CITO_BASE_URL}/api/v1/lol/teams/{team_slug}/h2h/{opponent_slug}",
        headers=_cito_headers(api_key), timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_lol_league_schedule(api_key, league_slug, timeout=20):
    """Real, documented endpoint (found via Cito's full API list, July
    2026): GET /lol/leagues/{leagueId}/schedule. NOT YET VERIFIED
    against a real live response.

    Investigated specifically as a real, different lead for the
    confirmed EWC data gap (two real matches, Karmine Corp vs Movistar
    KOI on May 14/17 2026, missing from both the per-team /matches
    endpoint AND the dedicated /h2h endpoint). A real, raw dump of
    EWC's own league entity (via /lol/leagues) showed
    '_count': {'tournaments': 1, 'teams': 0} — zero teams linked to
    the league entity — which could mean any endpoint that resolves
    matches THROUGH a team-to-league association (as both /matches and
    /h2h likely do) may systematically miss real EWC matches, while a
    real, direct league-level schedule query might not depend on that
    same broken/empty linkage. This is a real hypothesis to verify
    against live data, not a confirmed fix."""
    response = requests.get(
        f"{CITO_BASE_URL}/api/v1/lol/leagues/{league_slug}/schedule",
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
    for page_num in range(max_pages):
        # Real fix (July 2026, round 2) — the first version of this
        # delay (2.0s/page) was correct in spirit but too heavy-handed
        # for what's genuinely a rare fallback path (only fires when
        # the cheap schedule-based team map leaves real teams
        # unresolved). A lighter delay here still gives real protection
        # (max_pages=20 pages -> ~6s worst case, not ~40s) without being
        # the dominant source of a slow real run — the mlb_app.py side
        # of this pipeline now uses an adaptive, rolling-window limiter
        # instead of a flat per-call delay for the same reason.
        if page_num > 0:
            time.sleep(0.3)
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


def build_match_time_map(*schedule_responses):
    """Real fix (July 2026) — Cito's schedule/today and schedule/
    upcoming responses include a real, confirmed 'startTime' field on
    each match (e.g. '2026-07-24T09:00:00.000Z') that genuinely varies
    per real match — unlike Polymarket's own date fields, which were
    investigated and confirmed to represent market-creation time, not
    real game time (see polymarket_api.py's _extract_match_date
    docstring for the full account of that investigation). Since
    schedule data is already fetched during team resolution anyway,
    this builds a real {frozenset({team1_slug, team2_slug}):
    startTime} lookup from it — a frozenset key since team1/team2
    ordering may differ between Cito's schedule and Polymarket's
    outcome ordering, and match identity here is really "these two
    teams playing," not which one is listed first. Returns the most
    recently-seen startTime if a same team pair appears more than once
    across combined schedule_today + schedule_upcoming (a genuine,
    if rare, real possibility — e.g. a rematch)."""
    time_map = {}
    for response in schedule_responses:
        if isinstance(response, dict):
            matches = response.get("data", [])
        elif isinstance(response, list):
            matches = response
        else:
            matches = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            team1_slug = (match.get("team1") or {}).get("slug")
            team2_slug = (match.get("team2") or {}).get("slug")
            start_time = match.get("startTime")
            if team1_slug and team2_slug and start_time:
                key = frozenset({team1_slug, team2_slug})
                time_map[key] = start_time
    return time_map


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
    will resolve than before; that's the correct, honest tradeoff.

    Real fix (July 2026, round 2, per direct user investigation) —
    MANUAL_TEAM_ALIASES is now checked FIRST, before the automatic map
    lookup, not just as a fallback inside resolve_team_with_league_
    context() for names the automatic lookup fails on entirely. Found
    necessary via a real, confirmed case: Cito has THREE separate
    duplicate real entries for ThunderTalk Gaming, and the automatic
    exact-match lookup was finding a real, valid-LOOKING match every
    time — just the wrong one (a real, dead duplicate with zero match
    data), since that duplicate's specific name formatting happened to
    match Polymarket's own convention exactly. Since the automatic
    lookup "succeeded" (found SOMETHING), the code never reached the
    fallback path where a human-verified manual override lives. A
    confirmed, human-verified fact should always take priority over
    automatic matching, even when that automatic matching finds a
    real, valid-looking (but wrong) result — not just when it fails
    outright."""
    normalized = _normalize_team_name(polymarket_team_name)
    if normalized in MANUAL_TEAM_ALIASES:
        return MANUAL_TEAM_ALIASES[normalized]
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
    # Real, confirmed fix (July 2026, per direct user investigation) —
    # Cito has THREE separate real entries for the same real team:
    # 'tt' (real, active, name "THUNDER TALK GAMING", tagged with the
    # real league 'lpl', 40 real completed matches, most recent just 2
    # days old), 'thunder-talk-gaming' (same duplicate problem), and
    # 'thundertalk-gaming' (name "ThunderTalk Gaming" — no internal
    # space, ZERO real match data). Polymarket's own team-name text
    # happens to match 'thundertalk-gaming''s specific no-space
    # formatting exactly, so ordinary name-based resolution silently
    # picked the dead duplicate over the real, active team every time
    # — confirmed directly via the admin coverage tool (0 total
    # entries for the dead one, 50 total / 40 completed for 'tt').
    'thundertalk gaming': 'tt',
    # Real, confirmed fix (August 2026, per direct user investigation)
    # — same real duplicate-entry pattern as ThunderTalk above. Cito
    # has 'docta-esports' (real, but ZERO match data — confirmed via
    # the admin coverage tool) and 'docta-esports-club' (the real,
    # active team — confirmed to have real, complete match history).
    # Ordinary name-based resolution was picking the dead duplicate.
    'docta esports': 'docta-esports-club',
}

# Real, curated allowlist (August 2026, per direct user investigation)
# — a real, deliberate alternative to fetching Cito's ENTIRE team
# database (1800+ teams) to look up each team's official league tag.
# That approach was already tried once for a different real problem
# (see build_team_name_to_slug_map's own docstring above) and found to
# burn through the free tier's monthly API quota fast — not worth
# repeating for this.
#
# normalize_requested_team_slug() below can already detect a
# Challengers-tier request when the slug itself literally contains
# the word "challenger" (e.g. "dplus-kia-challengers"). This set
# covers the real, confirmed cases where the real, official Challengers
# slug is an ABBREVIATION that doesn't self-identify that way at all
# (e.g. "dns" for DN SOOPers Challengers) — added one at a time, only
# once actually confirmed via the admin diagnostic tools, at zero
# ongoing API cost.
# Real, curated redirect (August 2026, per direct user investigation,
# using the auto-investigate admin tool's own real findings) — a
# different mechanism than MANUAL_TEAM_ALIASES above. That dict is
# keyed by the real, normalized POLYMARKET team name (since that's
# what match_polymarket_name_to_slug() actually receives to look up).
# This one is keyed by the real, WRONG Cito slug that resolution
# already, confirmedly produces — found directly via the admin "Auto-
# Investigate" tool's own real cross-check against Cito's full team
# database, without needing to know or guess the exact real Polymarket
# text for each team. Applied as a direct, real post-resolution
# override: "whenever resolution produces this specific real wrong
# slug, use this real correct one instead" — regardless of which real
# Polymarket text originally produced it.
KNOWN_WRONG_SLUG_REDIRECTS = {
    'brod-n-friends': 'brod--friends',       # confirmed August 2026 — same real team, real slug just formatted differently ("Brod & Friends")
    'esprit-shnen': 'e-shonen',               # confirmed August 2026 — same real team ("Esprit Shonen"), a real, missing-vowel typo in the original resolved slug
    '3bl-esports': 'ebl-esports',             # confirmed August 2026 — same real team ("3BL GALAXY ESPORTS"), Cito's own real slug just doesn't start with "3"
    'croatian-flair-x-rlx': 'croatian-flair', # LIKELY the same real roster under a real sponsor-tag name variant ("x RLX") — flagged as the real, more likely of two real candidates, not as fully certain as the three above; worth a real, direct sanity check once live.
}

MANUAL_CHALLENGERS_SLUGS = {
    'dns',  # DN SOOPers Challengers — confirmed August 2026: shares Cito's real, single "kwangdong-freecs" slug with their main roster for isRequested purposes, but their real, distinct tournament (lol-lck_cl_split_2_2026) IS present in the data once correctly tier-filtered.
}

# Real, curated allowlist (August 2026, per direct user investigation)
# — a real, HARDER version of the same real problem MANUAL_CHALLENGERS_
# SLUGS solves. For DNS, the requested slug ("dns") and Cito's real,
# underlying slug ("kwangdong-freecs") are two genuinely different
# strings — tagging "dns" as Challengers-only has zero effect on
# anything that queries "kwangdong-freecs" directly. HANJIN BRION is
# real, confirmed to be different: "bro" is the ONLY real slug that
# exists for them at all — both their real main roster AND their real
# Challengers roster get requested through the exact same string, with
# real games from BOTH tiers returned either way (confirmed August
# 2026: querying "bro" returned 28 real main-tier games and 9 real
# Challengers-tier games together). Tagging "bro" itself as
# Challengers-only in MANUAL_CHALLENGERS_SLUGS would incorrectly
# affect every real query for their main roster too — there's no
# distinguishing string to hang a real, safe rule on at the slug level
# alone.
#
# Real teams here get a SYNTHETIC, disambiguated identifier
# (build_disambiguated_slug) used internally throughout this pipeline
# whenever a SPECIFIC real matchup being priced is confirmed (via that
# matchup's own real market text) to involve this team's Challengers
# side specifically — letting the exact same real slug correctly
# represent two different real real rosters depending on which real
# matchup is actually being priced, rather than a single, real,
# globally-ambiguous rating.
AMBIGUOUS_SINGLE_SLUG_TEAMS = {
    'bro',  # HANJIN BRION — confirmed August 2026: the ONLY real slug for both their main roster and their Challengers roster, no separate identifier exists at all.
}

DISAMBIGUATED_CHALLENGERS_SUFFIX = "::cl"


def build_disambiguated_slug(real_slug):
    """Real, synthetic internal identifier (August 2026) — used ONLY
    within this pipeline's own real Elo/tournament-form/head-to-head
    bookkeeping, never sent to Cito's real API (real fetches always
    strip this back to the real, underlying slug first — see
    resolve_fetchable_slug below). Lets a real, single, ambiguous Cito
    slug like "bro" correctly represent two different real rosters
    depending on which real matchup is actually being priced, instead
    of one real, globally-blended rating covering both tiers at once."""
    return f"{real_slug}{DISAMBIGUATED_CHALLENGERS_SUFFIX}"


def is_disambiguated_challengers_slug(slug):
    """Real, direct check for whether a real slug string is one of
    this pipeline's own synthetic identifiers (see
    build_disambiguated_slug above), not a real, genuine Cito slug."""
    return bool(slug) and slug.endswith(DISAMBIGUATED_CHALLENGERS_SUFFIX)


def resolve_fetchable_slug(slug):
    """Strips a real, synthetic disambiguation suffix (if present),
    returning the real, underlying slug Cito's own API actually
    recognizes. A real, genuine Cito slug (no suffix) passes through
    completely unchanged."""
    if is_disambiguated_challengers_slug(slug):
        return slug[:-len(DISAMBIGUATED_CHALLENGERS_SUFFIX)]
    return slug


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


def slugs_textually_related(a, b):
    """Real, shared safety check (August 2026, per direct user
    investigation) — used by both normalize_requested_team_slug()
    below and the real, global alias-map detection logic in
    mlb_app.py's _fetch_lol_team_histories(), so the SAME real rule
    applies whether a slug mismatch gets caught on the first pass or
    the second, global pass. Two real slugs are considered the same
    real team only when one is a real substring of the other once
    hyphens/underscores are stripped (e.g. "pain"/"pain-gaming",
    "docta-esports"/"docta-esports-club") — genuinely unrelated real
    strings (e.g. "dns"/"kwangdong-freecs") are NOT treated as the
    same team, since that pattern turned out to be real, confirmed
    evidence of two DIFFERENT real rosters, not an aliasing quirk."""
    if not a or not b:
        return False
    a_clean = a.replace("-", "").replace("_", "")
    b_clean = b.replace("-", "").replace("_", "")
    return a_clean in b_clean or b_clean in a_clean


def normalize_requested_team_slug(completed_matches, requested_slug):
    """Real fix (July 2026, per direct user report — a real,
    established team, paiN Gaming, showing ZERO processed games in the
    real Elo/tournament-form pipeline despite genuinely having 38 real
    completed matches). Found a real, deep slug inconsistency: Cito's
    schedule-based team resolution can return a real, valid slug (e.g.
    "pain-gaming") that Cito's own GET /teams/{slug}/matches endpoint
    happily accepts as an alias and correctly returns that team's real
    matches for — but the match objects THEMSELVES still label that
    same team using its OTHER real, canonical slug internally (e.g.
    "pain", confirmed via a real, live match object where team2.slug
    was "pain" while team2.isRequested was true, for a request made
    with slug "pain-gaming"). Since every downstream real function
    (build_team_ratings_from_history, get_in_tournament_record,
    get_head_to_head_record, etc.) compares OUR resolved slug directly
    against each match's own team1.slug/team2.slug, this silent
    mismatch meant this team's entire real, substantial match history
    was NEVER actually processed anywhere — every slug comparison
    simply never matched, leaving real teams stuck at the default 1500
    Elo rating despite having genuine, plentiful data all along.

    Fixes this at the real source, right after fetching a team's own
    match history: Cito's real 'isRequested' flag on each match's
    team1/team2 objects marks exactly which side corresponds to the
    slug that was actually queried, regardless of which of a team's
    real, valid slug aliases was used to make the request. This
    overwrites THAT side's slug to match the real slug we resolved and
    are using consistently everywhere else in this pipeline, so every
    downstream comparison works correctly from this point forward.

    Real fix (round 2, same real investigation) — the top-level series
    'winner' field and each individual game's 'winnerSlug' ALSO
    reference a team by its real, OLD, un-normalized slug. Fixing only
    team1.slug/team2.slug and leaving these untouched would have been
    a real, serious, and worse bug in disguise: every match/game this
    team actually WON would still show its real winner as the OLD slug
    (e.g. "pain"), which no longer equals ANYTHING in the normalized
    match (team1_slug and team2_slug are now "pain-gaming" and the
    opponent's real slug) — silently dropping every real WIN from Elo/
    tournament-form processing while still correctly counting every
    real LOSS (since a loss's winner is the opponent's real, unchanged
    slug). That's a real, directional bias, not a random data-quality
    gap — now fixed by normalizing 'winner' and every game's
    'winnerSlug' alongside team1/team2.slug, all in the same pass.

    Real fix (round 3, August 2026, per direct user investigation — a
    real, serious, different bug this same mechanism was found to
    CAUSE, not just fix). A real, confirmed case: requesting slug
    "dns" (DN SOOPers CHALLENGERS, a real, distinct, lower-tier roster)
    returned a real match with isRequested=true on team1.slug =
    "kwangdong-freecs" — but that real match's own tournamentId was
    "lol-lck_split_3_2026", the MAIN LCK split, not Challengers. "dns"
    and "kwangdong-freecs" share NO textual relationship at all (unlike
    "pain"/"pain-gaming", which obviously refer to the same real team).
    Blindly relabeling here — as this function used to do
    unconditionally — would silently feed a Challengers team's Elo/
    tournament-form real MAIN-ROSTER results, a real, serious data-
    contamination bug this same "fix" was directly responsible for.

    Real fix (round 4, August 2026, same real investigation, follow-up
    finding) — round 3's fix correctly blocked the real contamination,
    but a real, direct follow-up check (a genuine "lol-lck_cl_split_
    2_2026" match for slug "dplus-kia-challengers") revealed it ALSO
    blocked real, legitimate Challengers games too: Cito doesn't have
    a real, separate team record for Dplus KIA's Challengers roster at
    all — "dk" (their real, shared, main-roster slug) is isRequested
    on BOTH the real main-tier AND real Challengers-tier games alike.
    "dk" isn't textually related to "dplus-kia-challengers" either
    way, so round 3's check excluded everything from this team, not
    just the contamination.

    Now checks the real, actual TOURNAMENT TIER directly (using the
    same "challenger" keyword both the requested slug and each match's
    real tournamentId can self-identify with) instead of relying on
    the slug relationship alone. When a REQUESTED slug self-identifies
    as Challengers (contains "challenger", e.g. "dplus-kia-challengers",
    "kt-challengers"), any match whose real tournamentId does NOT
    ALSO self-identify as Challengers tier is excluded outright,
    regardless of isRequested — closing the real contamination even
    though the underlying shared slug ("dk") looks the same either
    way. Conversely, once BOTH sides confirm the same real tier, the
    isRequested relabeling is trusted even when the underlying slugs
    are textually unrelated (like "dk"), since the real, independent
    tier match is stronger evidence than a textual slug comparison
    alone.

    Real fix (round 5, August 2026, same real investigation) —
    round 4's self-identification check only worked for requested
    slugs that literally contain the word "challenger" — an
    abbreviated slug like "dns" (DN SOOPers Challengers) doesn't
    self-identify that way at all. Rather than fetching Cito's entire
    real team database (1800+ teams — already tried once for a
    different real problem and found to burn through the free tier's
    monthly API quota fast, see build_team_name_to_slug_map's own
    docstring), this checks a small, real, curated allowlist
    (MANUAL_CHALLENGERS_SLUGS) instead — added one real, confirmed
    case at a time via the admin diagnostic tools, at zero ongoing API
    cost, same real pattern as MANUAL_TEAM_ALIASES above.

    Real fix (round 6, August 2026, same real investigation, per
    direct user report — "so what was different between DNS and
    BRO?"). Found a real, harder version of the same real problem:
    HANJIN BRION has NO real, separate slug for their Challengers
    roster at all — "bro" is the ONLY real slug that exists, used for
    querying BOTH tiers, with real games from both tiers returned
    either way. Neither round 4 (self-identifying slug text) nor
    round 5 (a curated allowlist) can safely apply here — tagging
    "bro" itself as Challengers-only would incorrectly affect every
    real request for their main roster too, since it's the exact same
    string either way.

    Now also recognizes a real, synthetic, internal-only identifier
    (see build_disambiguated_slug/is_disambiguated_challengers_slug in
    this same module) that the caller builds PER REAL MATCHUP being
    priced, using that specific matchup's own real market context to
    decide which real roster is actually meant — letting the exact
    same real Cito slug ("bro") correctly represent two different real
    rosters depending on which real matchup is being priced, rather
    than one real, globally-blended rating. Also adds the REVERSE,
    symmetric filter: when a KNOWN-ambiguous real slug (see
    AMBIGUOUS_SINGLE_SLUG_TEAMS) is requested WITHOUT disambiguation
    (i.e. the plain "bro", meaning the real main roster), real
    Challengers-tagged matches are now excluded from THAT identity too
    — closing the same real contamination risk in the other direction,
    not just protecting the Challengers side.

    Returns a NEW list of shallow-copied match dicts (with shallow-
    copied team1/team2 sub-dicts and a shallow-copied games list/dicts
    where changed) — deliberately never mutates the original response
    in place, since that's real, shared, cached data (via Streamlit's
    @st.cache_data) that other real callers may still reference."""
    requested_slug_lower = (requested_slug or "").lower()
    requested_is_challengers = (
        "challenger" in requested_slug_lower
        or requested_slug_lower in MANUAL_CHALLENGERS_SLUGS
        or is_disambiguated_challengers_slug(requested_slug)
    )
    requested_is_ambiguous_main = (
        resolve_fetchable_slug(requested_slug_lower) in AMBIGUOUS_SINGLE_SLUG_TEAMS
        and not is_disambiguated_challengers_slug(requested_slug)
    )

    normalized = []
    for match in completed_matches:
        if not isinstance(match, dict):
            normalized.append(match)
            continue

        tournament_id_lower = (match.get("tournamentId") or "").lower()
        tournament_is_challengers = "challenger" in tournament_id_lower or "_cl_" in tournament_id_lower or tournament_id_lower.endswith("_cl")

        if requested_is_challengers and not tournament_is_challengers:
            # Real, direct tier mismatch — we specifically asked for
            # the Challengers side; a non-Challengers tournament here
            # is real, main-roster contamination, regardless of what
            # isRequested says.
            continue
        if requested_is_ambiguous_main and tournament_is_challengers:
            # Real, symmetric tier mismatch — a known-ambiguous real
            # slug requested WITHOUT disambiguation means the real
            # main roster; a real Challengers-tagged match here is
            # contamination in the OTHER direction.
            continue

        tier_confirmed = requested_is_challengers and tournament_is_challengers
        # Real fix (round 7, August 2026, per direct user report — "so
        # many of these lol teams just dont work... you are the code,
        # there has to be a fix for this"). Found the real, root cause:
        # round 3's textual-relatedness safety check was built
        # SPECIFICALLY in response to the DN SOOPers Challengers bug —
        # a real, NARROW case where a single Cito slug genuinely
        # represents two DIFFERENT real rosters (main + Challengers).
        # That check was a blanket rule applied to EVERY real team,
        # not just the ones actually proven to have that problem —
        # which meant a real, ordinary team where Cito's schedule data
        # and match-history data simply use two unrelated internal
        # slugs for the SAME real roster (no tier ambiguity involved
        # at all) was ALSO getting its real match data silently
        # excluded, since "unrelated-looking slug" was being treated
        # as suspicious regardless of WHY it looked unrelated.
        # Cito's own isRequested flag already means, by definition,
        # "this side IS the real team whose slug you queried" — that's
        # a real, trustworthy signal on its own for the general case.
        # The textual-relatedness/tier check is now ONLY applied to
        # teams we've SPECIFICALLY confirmed are genuinely ambiguous
        # (Challengers-tagged requests, or a known AMBIGUOUS_SINGLE_
        # SLUG_TEAMS entry) — every other, ordinary team's real
        # isRequested relabeling is now trusted directly, no textual
        # comparison required at all.
        is_known_risky_team = requested_is_challengers or requested_is_ambiguous_main

        new_match = dict(match)
        old_slug = None
        unrelated_mismatch = False
        for side_key in ("team1", "team2"):
            side = new_match.get(side_key)
            if isinstance(side, dict) and side.get("isRequested") and side.get("slug") != requested_slug:
                real_old_slug = side.get("slug")
                if is_known_risky_team and not tier_confirmed and not slugs_textually_related(real_old_slug, requested_slug):
                    # Real, serious mismatch — likely a genuinely
                    # different real team, not an alias. Exclude this
                    # match entirely rather than risk corrupting either
                    # team's real history.
                    unrelated_mismatch = True
                    break
                old_slug = real_old_slug
                new_side = dict(side)
                new_side["slug"] = requested_slug
                new_match[side_key] = new_side
        if unrelated_mismatch:
            continue
        if old_slug:
            if new_match.get("winner") == old_slug:
                new_match["winner"] = requested_slug
            games = new_match.get("games")
            if games:
                new_games = []
                for game in games:
                    if isinstance(game, dict) and game.get("winnerSlug") == old_slug:
                        new_game = dict(game)
                        new_game["winnerSlug"] = requested_slug
                        new_games.append(new_game)
                    else:
                        new_games.append(game)
                new_match["games"] = new_games
        normalized.append(new_match)
    return normalized


def apply_slug_alias_map(matches, alias_map):
    """Real, second-pass fix (July 2026, same real investigation as
    normalize_requested_team_slug() above). That function correctly
    fixes a team's OWN slug within THAT team's own individually-
    fetched match history — but the SAME real match also appears in
    the OPPONENT's own separately-fetched history, and in THAT copy
    only the opponent's own side gets normalized, leaving the first
    team's slug un-normalized in that specific copy. Since combining
    real per-team histories dedupes by matchId and keeps whichever
    real copy of a shared match it happens to encounter first (real,
    genuinely order-dependent — not something safe to rely on), a
    match could still show the OLD, un-normalized slug depending on
    real fetch order, even after the first, per-team normalization
    pass. This applies a real, COMPLETE alias_map (built by the caller
    from every team's own real isRequested-based old-slug detection
    during their own individual fetches) ONE MORE TIME across the
    FULLY COMBINED, deduplicated history — team1.slug, team2.slug,
    winner, and every game's winnerSlug — guaranteeing a real,
    consistent result regardless of which specific copy of a shared
    match happened to win the dedup. A real, empty alias_map (the
    common case — most teams' real, resolved slug matches their real,
    internal match-history slug with no alias at all) is a safe,
    fast no-op."""
    if not alias_map:
        return matches
    normalized = []
    for match in matches:
        if not isinstance(match, dict):
            normalized.append(match)
            continue
        new_match = dict(match)
        for side_key in ("team1", "team2"):
            side = new_match.get(side_key)
            if isinstance(side, dict) and side.get("slug") in alias_map:
                new_side = dict(side)
                new_side["slug"] = alias_map[side["slug"]]
                new_match[side_key] = new_side
        if new_match.get("winner") in alias_map:
            new_match["winner"] = alias_map[new_match["winner"]]
        games = new_match.get("games")
        if games:
            new_games = []
            for game in games:
                if isinstance(game, dict) and game.get("winnerSlug") in alias_map:
                    new_game = dict(game)
                    new_game["winnerSlug"] = alias_map[game["winnerSlug"]]
                    new_games.append(new_game)
                else:
                    new_games.append(game)
            new_match["games"] = new_games
        normalized.append(new_match)
    return normalized


def infer_missing_game_winners(completed_matches):
    """Real fix (July 2026) for a genuine data-quality bug found via
    live investigation: a real completed match (G2 2-1 over Movistar
    KOI, confirmed via the real match object) had its series score and
    Game 1's winner recorded correctly, but Games 2 and 3 both showed
    winnerSlug: null — completely missing. Since build_team_ratings_
    from_history() processes games individually and silently skips any
    game with a missing winner, this match was only counting as a KOI
    win in the rating system — the two games G2 actually won to clinch
    the series were invisible to Elo, systematically dragging down
    ratings for teams that win series with some individual game data
    missing.

    This is often genuinely, safely inferable: given the real final
    series score (each team's confirmed win count) and whichever
    individual games ARE recorded, simple arithmetic can determine the
    remaining unknown games' winners — but ONLY when unambiguous: if
    all of a match's unknown games must belong to the same team to
    reach the known final score (the other team has already reached
    its win quota from known games alone), they're safely filled in.
    If the math allows more than one real possibility (e.g. two teams
    each still need exactly one more win, with two unknown games
    remaining — genuinely ambiguous which unknown game belongs to
    which team), this is left alone, not guessed — matching this
    project's standing principle that an unresolved case should stay
    unresolved rather than risk being silently wrong.

    Returns a new list (does not mutate the input) with inferred
    winners filled in where safe."""
    fixed_matches = []
    for match in completed_matches:
        if not isinstance(match, dict):
            fixed_matches.append(match)
            continue

        games = match.get("games") or []
        team1 = match.get("team1") or {}
        team2 = match.get("team2") or {}
        team1_slug = team1.get("slug")
        team2_slug = team2.get("slug")
        team1_score = team1.get("score")
        team2_score = team2.get("score")

        # Only attempt inference when we have real, confirmed data to
        # work from — both team slugs, both real final scores, and at
        # least one game with a genuinely missing winner.
        unknown_games = [g for g in games if isinstance(g, dict) and g.get("winnerSlug") is None]
        if not team1_slug or not team2_slug or team1_score is None or team2_score is None or not unknown_games:
            fixed_matches.append(match)
            continue

        known_team1_wins = sum(1 for g in games if isinstance(g, dict) and g.get("winnerSlug") == team1_slug)
        known_team2_wins = sum(1 for g in games if isinstance(g, dict) and g.get("winnerSlug") == team2_slug)
        team1_needed = team1_score - known_team1_wins
        team2_needed = team2_score - known_team2_wins

        # Safe, unambiguous inference: ALL remaining unknown games must
        # belong to one specific team (the other team has already hit
        # its real, known win quota) — not a case where both teams
        # still need wins among multiple unknown games, which would be
        # a real guess, not a real inference.
        inferred_winner = None
        if team1_needed == len(unknown_games) and team2_needed == 0:
            inferred_winner = team1_slug
        elif team2_needed == len(unknown_games) and team1_needed == 0:
            inferred_winner = team2_slug

        if inferred_winner is None:
            fixed_matches.append(match)  # genuinely ambiguous — leave alone, don't guess
            continue

        new_games = []
        for g in games:
            if isinstance(g, dict) and g.get("winnerSlug") is None:
                new_g = dict(g)
                new_g["winnerSlug"] = inferred_winner
                new_g["winnerSlug_inferred"] = True  # real, honest marker that this was inferred, not directly reported
                new_games.append(new_g)
            else:
                new_games.append(g)
        fixed_match = dict(match)
        fixed_match["games"] = new_games
        fixed_matches.append(fixed_match)

    return fixed_matches


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
