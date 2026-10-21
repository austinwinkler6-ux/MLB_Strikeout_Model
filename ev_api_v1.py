"""
ev_api_v1.py -- pure helpers behind the +EV endpoints (no Supabase, no FastAPI), so they can be tested on their own.
"""
from datetime import datetime, timezone


def _dec(american):
    return 1 + american / 100.0 if american > 0 else 1 + 100.0 / abs(american)


def _ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def confidence(row):
    """High: Pinnacle prices it, or 3+ sharp sources agree within 2 points. Low: one non-Pinnacle source only."""
    sharps = row.get("sharps") or {}
    spread = row.get("sharp_spread_pts") or 0
    if "pinnacle" in sharps or (len(sharps) >= 3 and spread <= 2.0):
        return "high"
    if len(sharps) >= 2:
        return "medium"
    return "low"


def shape_picks(rows, now=None, sport=None, market=None, book=None, min_ev=None, hide_low=False, limit=500):
    now = now or datetime.now(timezone.utc)
    out = []
    for r in rows:
        if sport and sport != "all" and r.get("sport") != sport:
            continue
        if market and r.get("market") != market:
            continue
        if book and r.get("book") != book:
            continue
        if min_ev is not None and (r.get("ev_pct") or 0) < min_ev:
            continue
        if _ts(r["commence"]) <= now:
            continue
        c = confidence(r)
        if hide_low and c == "low":
            continue
        last = _ts(r["last_seen"]) if r.get("last_seen") else None
        out.append({**r, "confidence": c,
                    "age_minutes": round((now - last).total_seconds() / 60) if last else None,
                    "minutes_to_start": round((_ts(r["commence"]) - now).total_seconds() / 60)})
    out.sort(key=lambda r: r["ev_pct"], reverse=True)
    return out[:limit]


def facets(rows):
    """Counts the page uses to build its filters."""
    f = {"sports": {}, "markets": {}, "books": {}}
    for r in rows:
        for k, key in (("sports", "sport"), ("markets", "market"), ("books", "book")):
            f[k][r[key]] = f[k].get(r[key], 0) + 1
    return f


def performance_summary(log_rows, now=None):
    """Closing-line value for every pick whose game has started. For each pick:
         ev_at_flag  = fair_prob_first * decimal_odds - 1      (what we thought when we flagged it)
         ev_at_close = fair_prob_last  * decimal_odds - 1      (what the sharp closing price says it was worth)
    If ev_at_close is clearly positive on average, the sharps moved toward our flagged price and the flags were real value."""
    now = now or datetime.now(timezone.utc)
    done = [r for r in log_rows if r.get("commence") and _ts(r["commence"]) <= now
            and r.get("fair_prob_first") is not None and r.get("fair_prob_last") is not None]

    def agg(rs):
        if not rs:
            return {"n": 0}
        first = [float(r["fair_prob_first"]) * _dec(r["odds_first"]) - 1 for r in rs]
        close = [float(r["fair_prob_last"]) * _dec(r["odds_first"]) - 1 for r in rs]
        pos = sum(1 for c in close if c > 0)
        return {"n": len(rs), "avg_ev_at_flag_pct": round(100 * sum(first) / len(first), 2),
                "avg_ev_at_close_pct": round(100 * sum(close) / len(close), 2), "pct_positive_at_close": round(100 * pos / len(rs), 1)}

    out = {"overall": agg(done), "by_sport": {}, "by_market": {}, "by_ev_at_flag": {}}
    for key, name in (("sport", "by_sport"), ("market", "by_market")):
        groups = {}
        for r in done:
            groups.setdefault(r.get(key), []).append(r)
        out[name] = {k: agg(v) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))}
    buckets = [("2-4%", 2, 4), ("4-7%", 4, 7), ("7-12%", 7, 12), ("12%+", 12, 1e9)]
    for label, lo, hi in buckets:
        rs = [r for r in done if lo <= 100 * (float(r["fair_prob_first"]) * _dec(r["odds_first"]) - 1) < hi]
        out["by_ev_at_flag"][label] = agg(rs)
    return out
