"""
ev_refresh_v1.py -- "Refresh price" for ONE bet on the +EV board.

Pulls the live prices for just that bet's market in that game (1 credit with the lean book list), rebuilds the fair
price, and reports what the bet looks like right now. It does not touch the saved board; the scanner stays in charge
of that. Guard rails (all in-memory, so they reset if the server restarts):
  - results are shared for COOLDOWN_SECONDS per (game, market), so ten people refreshing the same bet cost 1 credit
  - each user gets USER_PER_HOUR refreshes an hour
  - manual refreshes stop at DAILY_CREDIT_CAP credits a day (Eastern time), and never go under the scanner's credit floor
"""
import threading, time
from datetime import datetime, timezone

import ev_engine_v3 as V
import ev_api_v1 as API
import ev_scanner_v1 as S

COOLDOWN_SECONDS = 45
USER_PER_HOUR = 30
DAILY_CREDIT_CAP = 400

_lock = threading.Lock()
_cache = {}            # (event_id, market) -> (monotonic time, quotes)
_user_hits = {}        # user_id -> [monotonic times]
_day = {"date": None, "credits": 0}


class RefreshLimit(Exception):
    pass


def _today_et(now):
    return S.day_start_et(now).date().isoformat()


def _check_limits(user_id, now, cap, floor, remaining):
    t = time.monotonic()
    hits = [x for x in _user_hits.get(user_id, []) if t - x < 3600]
    if len(hits) >= USER_PER_HOUR:
        raise RefreshLimit("You've refreshed a lot this hour. Try again in a few minutes.")
    d = _today_et(now)
    if _day["date"] != d:
        _day.update(date=d, credits=0)
    if _day["credits"] >= cap:
        raise RefreshLimit("Live refresh is at its limit for today. The board still updates on its own.")
    if remaining is not None and remaining < floor:
        raise RefreshLimit("Live refresh is paused while the data plan is low. The board still updates on its own.")
    hits.append(t)
    _user_hits[user_id] = hits


def _live_quotes(client, cfg, pick, now):
    """Quotes for this game+market, from the 45-second shared cache or a fresh 1-market request. -> (quotes, credits)"""
    key = (pick["event_id"], pick["market"])
    t = time.monotonic()
    hit = _cache.get(key)
    if hit and t - hit[0] < COOLDOWN_SECONDS:
        return hit[1], 0
    away, _, home = str(pick.get("event") or "").partition(" @ ")
    data = client.event_odds(S.SPORTS[pick["sport"]]["key"], pick["event_id"], [pick["market"]], S.books_for(cfg["book_profile"]))
    credits = client.last_cost if client.last_cost is not None else S.groups_for(cfg["book_profile"])
    if not data:
        return None, credits
    item = {"event": {"id": pick["event_id"], "home_team": home, "away_team": away, "commence_time": pick["commence"]},
            "data": data, "market": pick["market"]}
    quotes = V.build_quotes([item])
    _cache[key] = (t, quotes)
    return quotes, credits


def refresh_pick(client, cfg, pick, user_id="anon", store=None, now=None, cap=None):
    """-> dict for the page. status: ok | started | unavailable | line_moved | no_fair_price | book_removed"""
    now = now or datetime.now(timezone.utc)
    if S.parse_ts(pick["commence"]) <= now:
        return {"status": "started", "message": "This game has started. Pre-game prices are closed."}
    with _lock:
        _check_limits(user_id, now, cap if cap is not None else DAILY_CREDIT_CAP, cfg["credit_floor"], client.remaining)
        quotes, credits = _live_quotes(client, cfg, pick, now)
        _day["credits"] += credits
    if credits and store is not None:
        try:
            store.add_scan_log(now, pick["sport"], pick["event_id"], 1, credits, client.remaining, 0)
        except Exception:
            pass                                                   # a logging failure must never break the refresh
    if quotes is None:
        return {"status": "unavailable", "message": "Couldn't reach the odds feed. Try again in a moment."}

    target = (V.norm(pick["player"]), float(pick["point"]) if pick.get("point") is not None else 0.0)
    slot = [s for k, s in quotes.items() if k[1] == pick["market"] and (k[2], k[3]) == target]
    if not slot:
        return {"status": "line_moved", "checked_at": now.isoformat(), "credits": credits,
                "message": "This line is no longer posted, or it moved. Check the board for the new line."}

    rows, _sk, _all, _ms = V.find_ev(quotes, min_ev=-1.0, max_odds=1e9, min_prob=0.0, max_prob=1.0,
                                     single_source_min_ev=-1.0)
    same = [r for r in rows if r["market"] == pick["market"] and V.norm(r["player"]) == target[0]
            and (float(r["point"]) if r["point"] is not None else 0.0) == target[1] and r["side"] == pick["side"]]
    if not same:
        return {"status": "no_fair_price", "checked_at": now.isoformat(), "credits": credits,
                "message": "The sharp books aren't pricing this right now, so there's no fair price to compare against."}
    best = max(same, key=lambda r: r["ev_pct"])
    mine = next((r for r in same if r["book"] == pick["book"]), None)
    if mine is None:
        return {"status": "book_removed", "checked_at": now.isoformat(), "credits": credits,
                "message": f"{pick['book']} no longer posts this price.",
                "best_now": {"book": best["book"], "odds": best["odds"], "ev_pct": best["ev_pct"]},
                "fields": _fields(best, same[0]["shop"], now, keep_book=pick)}
    fields = _fields(mine, mine["shop"], now)
    return {"status": "ok", "checked_at": now.isoformat(), "credits": credits,
            "still_plus_ev": mine["ev_pct"] >= cfg["min_ev"] * 100,
            "before": {"odds": pick["odds"], "ev_pct": pick["ev_pct"], "fair_odds": pick["fair_odds"]},
            "best_now": {"book": best["book"], "odds": best["odds"], "ev_pct": best["ev_pct"]},
            "fields": fields}


def _fields(row, shop, now, keep_book=None):
    base = {"odds": row["odds"], "ev_pct": row["ev_pct"], "fair_prob": row["fair_prob"], "fair_odds": row["fair_odds"],
            "n_sharps": row["n_sharps"], "single_source": row["single_source"], "sharps": row["sharps"],
            "sharp_spread_pts": row["sharp_spread_pts"], "kelly_quarter_pct": row["kelly_quarter_pct"], "shop": shop,
            "age_minutes": 0}
    if keep_book is not None:                                       # the bet's own book is gone: keep showing the original bet,
        base.pop("odds"); base.pop("ev_pct"); base.pop("kelly_quarter_pct")     # but with current fair price and market board
    base["confidence"] = API.confidence({**row, "sharps": row["sharps"]})
    return base
