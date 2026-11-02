"""
ev_scanner_v1.py -- keeps the +EV board fresh. No projections: sharp books set the fair price, soft books get flagged.

What it does each cycle
  1. Lists upcoming games for each enabled sport (free endpoint, no credits).
  2. Decides which games are due for a scan: the closer to start time, the more often (see INTENSITY).
  3. Pulls every prop market for a due game in one request: sharps + soft books (10 books = 1 credit per market).
  4. Removes the sharps' vig, builds a fair price, and writes every soft-book price that beats it to the board.
  5. Tracks credits, keeps under a daily budget and a floor, and learns which markets the sharps never post
     (those are scanned rarely, saving credits).

Run it
    python3 ev_scanner_v1.py --plan                      # what is due right now and the estimated credits (free)
    python3 ev_scanner_v1.py --once --store memory       # one cycle, nothing written to Supabase
    python3 ev_scanner_v1.py --once                      # one cycle, writes to Supabase
    python3 ev_scanner_v1.py --loop                      # forever (the API server starts this in a background thread)

Environment: ODDS_API_KEY, SUPABASE_URL, SUPABASE_KEY, and optionally EV_SPORTS (nfl,nba,mlb), EV_BOOK_PROFILE (lean|wide),
EV_INTENSITY (lean|standard|heavy), EV_DAILY_BUDGET (credits per day), EV_CREDIT_FLOOR, EV_MIN_EV (percent).
"""
import argparse, collections, hashlib, json, os, sys, threading, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

import ev_engine_v3 as V

ET = ZoneInfo("America/New_York")
BASE = "https://api.the-odds-api.com/v4"

# ───────────────────────── configuration ─────────────────────────
# Every standard (two-sided) prop market the API offers. `_alternate` ladders are one-sided "X+" lines with no sharp
# reference, so they are left out. A market the sharps never post is detected automatically and scanned rarely.
SPORTS = {
    "nfl": {"key": "americanfootball_nfl", "label": "NFL", "markets": [
        "player_pass_yds", "player_pass_tds", "player_pass_attempts", "player_pass_completions", "player_pass_interceptions",
        "player_pass_longest_completion", "player_rush_yds", "player_rush_attempts", "player_rush_longest",
        "player_receptions", "player_reception_yds", "player_reception_longest", "player_rush_reception_yds",
        "player_pass_rush_yds", "player_pass_rush_reception_yds", "player_anytime_td", "player_rush_tds",
        "player_reception_tds", "player_tds_over", "player_1st_td", "player_last_td", "player_pass_rush_reception_tds",
        "player_kicking_points", "player_field_goals", "player_pats", "player_sacks", "player_solo_tackles",
        "player_tackles_assists", "player_assists", "player_defensive_interceptions", "player_pass_yds_q1"]},
    "nba": {"key": "basketball_nba", "label": "NBA", "markets": [
        "player_points", "player_rebounds", "player_assists", "player_threes", "player_blocks", "player_steals",
        "player_turnovers", "player_points_rebounds_assists", "player_points_rebounds", "player_points_assists",
        "player_rebounds_assists", "player_double_double", "player_triple_double"]},
    "mlb": {"key": "baseball_mlb", "label": "MLB", "markets": [
        "pitcher_strikeouts", "pitcher_outs", "pitcher_hits_allowed", "pitcher_earned_runs", "pitcher_walks",
        "batter_hits", "batter_total_bases", "batter_home_runs", "batter_rbis", "batter_runs_scored",
        "batter_hits_runs_rbis"]},
}

# Sharps are priced by Pinnacle, BetOnline and the exchanges. (LowVig, Kalshi and Betopenly posted no props in the
# coverage probe, Circa and Bookmaker are not in The Odds API.) 5 sharps + 5 soft = 10 books = ONE credit per market.
# Override without editing code:  EV_SHARP_BOOKS="pinnacle,betonlineag"  (a shorter list is cheaper, see books_for below).
SHARP_BOOKS = [b.strip() for b in os.environ.get("EV_SHARP_BOOKS", "pinnacle,betonlineag,novig,prophetx,polymarket").split(",") if b.strip()]
SOFT_BOOKS = {
    "lean": ["betmgm", "williamhill_us", "courtside", "draftkings", "fanduel"],
    "wide": ["betmgm", "williamhill_us", "courtside", "draftkings", "fanduel", "fanatics", "hardrockbet", "espnbet",
             "betrivers", "bovada", "ballybet", "betparx", "fliff"],
    # "mine": the books Austin picked (Caesars, Fanatics, FanDuel, DraftKings, Fliff, BetMGM, Courtside, Rebet, theScore Bet).
    # theScore Bet is the same feed as ESPN BET (key espnbet). Onyx Odds is not offered by The Odds API.
    "mine": ["betmgm", "williamhill_us", "courtside", "draftkings", "fanduel", "fanatics", "fliff", "rebet", "espnbet"],
}

# (hours to start from, to, minutes between scans). Props are pre-game only: nothing is scanned after start.
INTENSITY = {
    "lean":     [(0, 1, 45), (1, 6, 120), (6, 24, 360)],
    "standard": [(0, 1, 30), (1, 6, 90), (6, 24, 240), (24, 48, 720)],
    "heavy":    [(0, 1, 15), (1, 6, 45), (6, 24, 120), (24, 72, 360)],
}
MARKET_CHUNK = 10           # markets per request
DEAD_AFTER_SCANS = 6        # a market with zero usable fair prices after this many scans is "dead"
DEAD_RECHECK_HOURS = 72     # ...and is only re-checked this often


def cfg_from_env():
    return {
        "sports": [x.strip() for x in os.environ.get("EV_SPORTS", "nfl,nba,mlb").split(",") if x.strip()],
        "book_profile": os.environ.get("EV_BOOK_PROFILE", "lean"),
        "intensity": os.environ.get("EV_INTENSITY", "standard"),
        "daily_budget": int(os.environ.get("EV_DAILY_BUDGET", "2500")),
        "credit_floor": int(os.environ.get("EV_CREDIT_FLOOR", "3000")),
        "min_ev": float(os.environ.get("EV_MIN_EV", "2.0")) / 100,
        "max_odds": float(os.environ.get("EV_MAX_ODDS", "1200")),
    }


def books_for(profile):
    return list(dict.fromkeys(SHARP_BOOKS + SOFT_BOOKS[profile]))      # no book is requested twice


def groups_for(profile):
    return (len(books_for(profile)) + 9) // 10          # every 10 bookmakers count as one region


def parse_ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def interval_minutes(hours_to_start, intensity):
    for lo, hi, mins in INTENSITY[intensity]:
        if lo <= hours_to_start < hi:
            return mins
    return None            # outside every window: do not scan


def pick_id(r):
    raw = f"{r['event_id']}|{r['market']}|{V.norm(r['player'])}|{r['point']}|{r['side']}|{r['book']}"
    return hashlib.md5(raw.encode()).hexdigest()[:20]


# ───────────────────────── Odds API client ─────────────────────────
class OddsClient:
    def __init__(self, api_key, session=None):
        self.key, self.http = api_key, session or requests
        self.remaining = None
        self.last_cost = None
        self._events = {}            # sport_key -> (fetched_at, events); the events list is free but there is no need to hit it every minute

    def _get(self, path, params):
        params = {"apiKey": self.key, **params}
        for attempt in range(4):
            try:
                r = self.http.get(f"{BASE}{path}", params=params, timeout=40)
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            rem = r.headers.get("x-requests-remaining")
            if rem is not None:
                self.remaining = int(float(rem))
            last = r.headers.get("x-requests-last")
            self.last_cost = int(float(last)) if last is not None else None
            if r.status_code == 401:
                raise RuntimeError("Odds API rejected the key (401)")
            if r.status_code >= 400:
                return None
            return r.json()
        return None

    def events(self, sport_key, max_age=300):
        hit = self._events.get(sport_key)
        if hit and time.time() - hit[0] < max_age:
            return hit[1]
        data = self._get(f"/sports/{sport_key}/events", {})
        data = data if isinstance(data, list) else []
        self._events[sport_key] = (time.time(), data)
        return data

    def event_odds(self, sport_key, event_id, markets, books):
        return self._get(f"/sports/{sport_key}/events/{event_id}/odds",
                         {"bookmakers": ",".join(books), "markets": ",".join(markets), "oddsFormat": "american"})


# ───────────────────────── stores ─────────────────────────
class MemoryStore:
    """In-memory store for tests and dry runs."""
    def __init__(self):
        self.picks, self.log, self.scans, self.scan_log, self.mstats, self.lease = {}, {}, {}, [], {}, None

    def last_scan(self, event_id):
        return self.scans.get(event_id)

    def set_scan(self, event_id, sport, ts, commence):
        self.scans[event_id] = ts

    def replace_event_picks(self, sport, event_id, rows, ts):
        old = {k: v for k, v in self.picks.items() if v["event_id"] == event_id}
        new_ids = set()
        n_new = 0
        for r in rows:
            r = {**r, "sport": sport, "last_seen": ts.isoformat()}
            new_ids.add(r["id"])
            if r["id"] in old:
                r["first_seen"] = old[r["id"]]["first_seen"]
            else:
                r["first_seen"] = ts.isoformat()
                n_new += 1
                self.log[r["id"]] = {"id": r["id"], "sport": sport, "event_id": event_id, "market": r["market"], "player": r["player"],
                                     "point": r["point"], "side": r["side"], "book": r["book"], "odds_first": r["odds"],
                                     "fair_prob_first": r["fair_prob"], "fair_prob_last": r["fair_prob"], "commence": r["commence"],
                                     "first_seen": ts.isoformat()}
            self.picks[r["id"]] = r
        for k in set(old) - new_ids:
            del self.picks[k]
        return n_new

    def update_log_close(self, event_id, fmap, ts):
        n = 0
        for rec in self.log.values():
            if rec["event_id"] != event_id:
                continue
            key = (event_id, rec["market"], V.norm(rec["player"]), float(rec["point"]) if rec["point"] is not None else 0.0)
            if key in fmap:
                p = fmap[key][0]
                rec["fair_prob_last"] = p if rec["side"] in ("Over", "Yes") else 1 - p
                rec["last_seen"] = ts.isoformat()
                n += 1
        return n

    def purge_started(self, now):
        for k in [k for k, v in self.picks.items() if parse_ts(v["commence"]) <= now]:
            del self.picks[k]

    def add_scan_log(self, ts, sport, event_id, n_markets, credits, remaining, n_rows):
        self.scan_log.append({"ts": ts, "sport": sport, "event_id": event_id, "markets": n_markets, "credits": credits,
                              "remaining": remaining, "rows": n_rows})

    def credits_since(self, since):
        return sum((x["credits"] or 0) for x in self.scan_log if x["ts"] >= since)

    def market_stats(self):
        return self.mstats

    def add_market_stats(self, sport, stats, ts):
        for mk, st in stats.items():
            m = self.mstats.setdefault(mk, {"sport": sport, "scans": 0, "props": 0, "fair": 0, "last_scan": None})
            m["scans"] += 1
            m["props"] += st["props"]
            m["fair"] += st["fair"]
            m["last_scan"] = ts.isoformat()

    def acquire_lease(self, owner, seconds, now):
        if self.lease and self.lease["until"] > now and self.lease["owner"] != owner:
            return False
        self.lease = {"owner": owner, "until": now + timedelta(seconds=seconds)}
        return True


class SupabaseStore:
    """Tables are created by ev_tables_v1.sql."""
    def __init__(self, client):
        self.sb = client

    def last_scan(self, event_id):
        r = self.sb.table("ev_event_scans").select("last_scan").eq("event_id", event_id).limit(1).execute()
        return parse_ts(r.data[0]["last_scan"]) if r.data else None

    def set_scan(self, event_id, sport, ts, commence):
        self.sb.table("ev_event_scans").upsert({"event_id": event_id, "sport": sport, "last_scan": ts.isoformat(),
                                                "commence": commence}, on_conflict="event_id").execute()

    def replace_event_picks(self, sport, event_id, rows, ts):
        old = self.sb.table("ev_picks").select("id").eq("event_id", event_id).execute().data or []
        old_ids = {x["id"] for x in old}
        new_ids = {r["id"] for r in rows}
        fresh = [r for r in rows if r["id"] not in old_ids]
        payload = [{**r, "sport": sport, "last_seen": ts.isoformat()} for r in rows]
        # new rows get first_seen; existing rows keep theirs because the column is left out of their payload
        for p in payload:
            if p["id"] not in old_ids:
                p["first_seen"] = ts.isoformat()
        for chunk in _chunks([p for p in payload if p["id"] in old_ids], 200):
            self.sb.table("ev_picks").upsert(chunk, on_conflict="id").execute()
        for chunk in _chunks([p for p in payload if p["id"] not in old_ids], 200):
            self.sb.table("ev_picks").upsert(chunk, on_conflict="id").execute()
        gone = list(old_ids - new_ids)
        for chunk in _chunks(gone, 100):
            self.sb.table("ev_picks").delete().in_("id", chunk).execute()
        logs = [{"id": r["id"], "sport": sport, "event_id": event_id, "market": r["market"], "player": r["player"], "point": r["point"],
                 "side": r["side"], "book": r["book"], "odds_first": r["odds"], "fair_prob_first": r["fair_prob"],
                 "fair_prob_last": r["fair_prob"], "commence": r["commence"], "first_seen": ts.isoformat()} for r in fresh]
        for chunk in _chunks(logs, 200):
            self.sb.table("ev_pick_log").upsert(chunk, on_conflict="id", ignore_duplicates=True).execute()
        return len(fresh)

    def update_log_close(self, event_id, fmap, ts):
        recs = self.sb.table("ev_pick_log").select("id,market,player,point,side").eq("event_id", event_id).execute().data or []
        upd = []
        for rec in recs:
            key = (event_id, rec["market"], V.norm(rec["player"]), float(rec["point"]) if rec["point"] is not None else 0.0)
            if key in fmap:
                p = fmap[key][0]
                upd.append({"id": rec["id"], "fair_prob_last": p if rec["side"] in ("Over", "Yes") else 1 - p, "last_seen": ts.isoformat()})
        for chunk in _chunks(upd, 200):
            self.sb.table("ev_pick_log").upsert(chunk, on_conflict="id").execute()
        return len(upd)

    def purge_started(self, now):
        self.sb.table("ev_picks").delete().lte("commence", now.isoformat()).execute()

    def add_scan_log(self, ts, sport, event_id, n_markets, credits, remaining, n_rows):
        self.sb.table("ev_scan_log").insert({"ts": ts.isoformat(), "sport": sport, "event_id": event_id, "markets": n_markets,
                                              "credits": credits, "remaining": remaining, "rows": n_rows}).execute()

    def credits_since(self, since):
        r = self.sb.table("ev_scan_log").select("credits").gte("ts", since.isoformat()).execute().data or []
        return sum((x["credits"] or 0) for x in r)

    def market_stats(self):
        r = self.sb.table("ev_market_stats").select("*").execute().data or []
        return {x["market"]: x for x in r}

    def add_market_stats(self, sport, stats, ts):
        cur = self.market_stats()
        for mk, st in stats.items():
            c = cur.get(mk, {"scans": 0, "props": 0, "fair": 0})
            self.sb.table("ev_market_stats").upsert({"market": mk, "sport": sport, "scans": c["scans"] + 1, "props": c["props"] + st["props"],
                                                     "fair": c["fair"] + st["fair"], "last_scan": ts.isoformat()}, on_conflict="market").execute()

    def acquire_lease(self, owner, seconds, now):
        r = self.sb.table("ev_scan_state").select("*").eq("id", 1).execute().data
        if r:
            cur = r[0]
            if cur.get("lease_until") and parse_ts(cur["lease_until"]) > now and cur.get("owner") != owner:
                return False
        self.sb.table("ev_scan_state").upsert({"id": 1, "owner": owner, "lease_until": (now + timedelta(seconds=seconds)).isoformat()},
                                              on_conflict="id").execute()
        return True


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# ───────────────────────── scanning ─────────────────────────
def active_markets(sport, store, now):
    """Markets worth scanning now: everything except markets the sharps have never priced (re-checked every few days)."""
    stats = store.market_stats()
    out = []
    for mk in SPORTS[sport]["markets"]:
        st = stats.get(mk)
        dead = st and st["scans"] >= DEAD_AFTER_SCANS and st["fair"] == 0
        if dead:
            last = st.get("last_scan")
            if last and now - parse_ts(last) < timedelta(hours=DEAD_RECHECK_HOURS):
                continue
        out.append(mk)
    return out


def day_start_et(now):
    n = now.astimezone(ET)
    return n.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def due_events(client, store, cfg, now):
    due = []
    for sport in cfg["sports"]:
        for ev in client.events(SPORTS[sport]["key"]):
            hrs = (parse_ts(ev["commence_time"]) - now).total_seconds() / 3600
            if hrs <= 0:
                continue
            mins = interval_minutes(hrs, cfg["intensity"])
            if mins is None:
                continue
            last = store.last_scan(ev["id"])
            if last is None or (now - last) >= timedelta(minutes=mins):
                due.append((parse_ts(ev["commence_time"]), sport, ev))
    due.sort(key=lambda x: x[0])
    return due


def scan_event(client, store, cfg, sport, ev, now, log=print):
    markets = active_markets(sport, store, now)
    books = books_for(cfg["book_profile"])
    items, credits = [], 0
    for chunk in _chunks(markets, MARKET_CHUNK):
        data = client.event_odds(SPORTS[sport]["key"], ev["id"], chunk, books)
        credits += client.last_cost if client.last_cost is not None else len(chunk) * groups_for(cfg["book_profile"])
        if data:
            items.append({"event": {k: ev[k] for k in ("id", "home_team", "away_team", "commence_time")}, "data": data})
    quotes = V.build_quotes(items)
    rows, skipped, _all_ev, mstats = V.find_ev(quotes, min_ev=cfg["min_ev"], max_odds=cfg["max_odds"])
    for r in rows:
        r["id"] = pick_id(r)
        r["sport"] = sport
    # Market stats only count once the game's props are actually posted (otherwise early scans would mark every
    # market "dead"). Markets we asked for that came back with no props at all count as zero.
    if sum(st["props"] for st in mstats.values()) >= 20:
        for mk in markets:
            mstats.setdefault(mk, {"props": 0, "fair": 0})
        store.add_market_stats(sport, mstats, now)
    n_new = store.replace_event_picks(sport, ev["id"], rows, now)
    store.update_log_close(ev["id"], V.fair_map(quotes), now)
    store.set_scan(ev["id"], sport, now, ev["commence_time"])
    store.add_scan_log(now, sport, ev["id"], len(markets), credits, client.remaining, len(rows))
    log(f"  {SPORTS[sport]['label']} {ev['away_team']} @ {ev['home_team']}: {len(markets)} markets, {credits} credits, "
        f"{len(quotes)} props, {len(rows)} +EV ({n_new} new) | credits left {client.remaining}")
    return credits, len(rows)


def run_cycle(client, store, cfg, now=None, log=print):
    now = now or datetime.now(timezone.utc)
    store.purge_started(now)
    due = due_events(client, store, cfg, now)
    used_today = store.credits_since(day_start_et(now))
    spent = n_scanned = n_rows = 0
    for _, sport, ev in due:
        if used_today + spent >= cfg["daily_budget"]:
            log(f"  daily budget reached ({used_today + spent}/{cfg['daily_budget']}); {len(due) - n_scanned} games wait")
            break
        if client.remaining is not None and client.remaining < cfg["credit_floor"]:
            log(f"  credit floor reached ({client.remaining} < {cfg['credit_floor']}); stopping")
            break
        c, n = scan_event(client, store, cfg, sport, ev, now, log)
        spent += c
        n_rows += n
        n_scanned += 1
    return {"due": len(due), "scanned": n_scanned, "credits": spent, "rows": n_rows, "used_today": used_today + spent,
            "remaining": client.remaining}


def run_forever(client, store, cfg, stop=None, owner=None, log=print, sleep_seconds=60):
    owner = owner or f"{os.getpid()}"
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            now = datetime.now(timezone.utc)
            if store.acquire_lease(owner, sleep_seconds * 3, now):
                s = run_cycle(client, store, cfg, now, log)
                if s["scanned"]:
                    log(f"[ev-scanner] cycle: {s}")
        except Exception as e:                                   # never let the thread die
            log(f"[ev-scanner] cycle error: {e}")
        stop.wait(sleep_seconds)


# ───────────────────────── planning (free) ─────────────────────────
def estimate_event_credits(sport, cfg, n_markets=None):
    """Credits one game costs over its whole pre-game life under the chosen intensity."""
    n_markets = n_markets or len(SPORTS[sport]["markets"])
    scans = sum((hi - lo) * 60 / mins for lo, hi, mins in INTENSITY[cfg["intensity"]])
    return scans * n_markets * groups_for(cfg["book_profile"]), scans


def print_plan(client, store, cfg, now=None):
    now = now or datetime.now(timezone.utc)
    g = groups_for(cfg["book_profile"])
    print(f"Books: {len(books_for(cfg['book_profile']))} ({cfg['book_profile']}) -> {g} credit(s) per market per game | intensity: {cfg['intensity']}")
    for sport in cfg["sports"]:
        c, scans = estimate_event_credits(sport, cfg)
        print(f"  {SPORTS[sport]['label']}: {len(SPORTS[sport]['markets'])} markets, about {scans:.0f} scans/game -> up to {c:,.0f} credits/game "
              f"(less once markets without sharp prices are pruned)")
    due = due_events(client, store, cfg, now)
    print(f"\nDue right now: {len(due)} games")
    est = 0
    for t, sport, ev in due:
        c = len(active_markets(sport, store, now)) * g
        est += c
        print(f"  {SPORTS[sport]['label']} {ev['away_team']} @ {ev['home_team']}  starts {t.astimezone(ET):%a %b %d %I:%M %p} ET  ~{c} credits")
    print(f"Estimated credits for this cycle: {est}   | daily budget {cfg['daily_budget']}, floor {cfg['credit_floor']}, credits left: {client.remaining}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--store", default="supabase", choices=["supabase", "memory"])
    ap.add_argument("--api-key", default=os.environ.get("ODDS_API_KEY"))
    ap.add_argument("--sports", default=None)
    ap.add_argument("--intensity", default=None)
    ap.add_argument("--books", default=None, help="lean | wide")
    a = ap.parse_args()
    cfg = cfg_from_env()
    if a.sports:
        cfg["sports"] = [x.strip() for x in a.sports.split(",")]
    if a.intensity:
        cfg["intensity"] = a.intensity
    if a.books:
        cfg["book_profile"] = a.books
    if not a.api_key:
        sys.exit("Set ODDS_API_KEY or pass --api-key")
    client = OddsClient(a.api_key)
    if a.store == "memory" or a.plan:
        store = MemoryStore()
    else:
        from supabase import create_client
        store = SupabaseStore(create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]))
    if a.plan:
        print_plan(client, store, cfg)
    elif a.once:
        print(run_cycle(client, store, cfg))
        if a.store == "memory":
            for r in sorted(store.picks.values(), key=lambda r: -r["ev_pct"])[:25]:
                print(f"  {r['ev_pct']:5.1f}%  {r['book']:14s} {r['odds']:+5d} (fair {r['fair_odds']:+5d})  {r['player']} {r['pick']}  [{r['market']}]")
    elif a.loop:
        run_forever(client, store, cfg)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
