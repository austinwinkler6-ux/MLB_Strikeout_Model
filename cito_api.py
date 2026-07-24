"""
cito_api.py — CitoAPI client for LoL esports team match history/results
(July 2026).

A genuinely new, standalone module — same "keep new, separable pieces
out of the single giant file" approach used for bet_math.py and
polymarket_api.py.

Real, confirmed facts this module is built on (via research, NOT yet
verified against a real, live response — see the honest note below):
  - Base URL: https://api.citoapi.com
  - Auth: requires an 'x-api-key' header — a real signup/key, unlike
    Polymarket's Gamma API or The Odds API's query-param auth.
  - Real, confirmed endpoint paths: /api/v1/lol/schedule/today,
    /api/v1/lol/live. A results/history-specific endpoint path was
    NOT independently confirmed from documentation search — this
    module's get_recent_results() is a reasonable guess at the
    likely path pattern, not a confirmed one.
  - Free tier: 500 calls/month, no cost — real signup required
    (citoapi.com), not usable without a real account.

HONEST, IMPORTANT LIMITATION: no live response schema has actually
been seen for the schedule/results endpoints specifically — only a
single documented example response for a live in-game match (kills,
gold, towers — not what's needed for a win-probability model, which
needs completed match results: who played, who won, how many games).
Do NOT trust any field names assumed below without running
get_cito_safety_check() first against a real key and inspecting the
real response — same discipline that caught real schema mistakes
earlier in this project (the NBA balldontlie rebuild).
"""

import requests

CITO_BASE_URL = "https://api.citoapi.com"


def _cito_headers(api_key):
    return {"x-api-key": api_key}


def get_lol_schedule_today(api_key, timeout=20):
    """Real, confirmed endpoint path per Cito's own documentation
    example. Returns today's LoL esports schedule. Raises on a real
    HTTP error — callers should wrap this in their own try/except,
    matching the established pattern elsewhere in this project."""
    response = requests.get(
        f"{CITO_BASE_URL}/api/v1/lol/schedule/today",
        headers=_cito_headers(api_key), timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_lol_live_matches(api_key, timeout=20):
    """Real, confirmed endpoint path. Returns currently active LoL
    esports matches and live state."""
    response = requests.get(
        f"{CITO_BASE_URL}/api/v1/lol/live",
        headers=_cito_headers(api_key), timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_lol_team_matches(api_key, team_slug, timeout=20):
    """UNCONFIRMED endpoint — a reasonable guess at the likely path
    pattern (matching the confirmed /lol/teams/{slug}/roster/history
    shape seen in documentation) for a team's match history, not a
    verified one. This is the endpoint most likely needed to build
    real Elo/power ratings (which team played which, who won), but it
    genuinely hasn't been seen working. Flagged loudly rather than
    presented as confirmed — get_cito_safety_check() tests this
    directly and will show a real 404 if this guess is wrong, rather
    than silently failing somewhere else later."""
    response = requests.get(
        f"{CITO_BASE_URL}/api/v1/lol/teams/{team_slug}/matches",
        headers=_cito_headers(api_key), timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_cito_safety_check(api_key):
    """Real, honest diagnostic — same pattern as NFL's live pipeline
    safety check and Polymarket's safety check. Does NOT assume any of
    the above endpoints actually work as guessed; calls each one for
    real and reports the genuine result (success + real response
    shape, or a real HTTP error) for each, so the actual schema can be
    inspected before any model gets built on top of assumed field
    names."""
    results = {}

    for label, fn, needs_team in [
        ("schedule_today", get_lol_schedule_today, False),
        ("live_matches", get_lol_live_matches, False),
    ]:
        try:
            data = fn(api_key)
            results[label] = {
                "ok": True,
                "type": type(data).__name__,
                "sample": data if not isinstance(data, list) else data[:2],
                "count": len(data) if isinstance(data, list) else None,
            }
        except Exception as e:
            results[label] = {"ok": False, "error": str(e)}

    # The team-matches endpoint needs a real team slug to test against
    # — using a genuinely well-known team as a reasonable guess for a
    # real slug, flagged as such since the exact slug format was never
    # confirmed either.
    try:
        data = get_lol_team_matches(api_key, "t1")
        results["team_matches_t1"] = {
            "ok": True, "type": type(data).__name__,
            "sample": data if not isinstance(data, list) else data[:2],
        }
    except Exception as e:
        results["team_matches_t1"] = {"ok": False, "error": str(e)}

    return results
