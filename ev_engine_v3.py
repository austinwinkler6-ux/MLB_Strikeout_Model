"""
ev_engine_v3.py -- "sharp vs soft" +EV finder. No projections, no model: the market sets the price.

  1. Collect every book's quote for each prop (same event, market, player, line).
  2. Take the SHARP books that post BOTH sides, remove their vig, and average them into one fair probability
     (sharper books count for more).
  3. Compare every other book's price to that fair probability:  EV% = fair_prob * decimal_odds - 1.
  4. Keep the props above a minimum EV, with guards against bad fair prices (sharps disagreeing, thin data, longshots).

Input is the raw JSON written by odds_sharp_coverage_probe_v1.py (a list of {sport, event, market, data}), where
`data` is The Odds API's per-event odds response. The same functions work on live responses.

Usage:
    python3 ev_engine_v3.py odds_probe_raw_v1.json
    python3 ev_engine_v3.py odds_probe_raw_v1.json --min-ev 3 --csv ev_picks.csv
    python3 ev_engine_v3.py odds_probe_raw_v1.json --highlight betmgm,williamhill_us,courtside
"""
import argparse, collections, csv, json, re, unicodedata

# How much each sharp book counts toward the fair price. Pinnacle sets the standard; LowVig copies Pinnacle's prices;
# exchanges are priced by bettors (counted a bit lower because the API gives no information on available size).
# Circa and Bookmaker are not available through The Odds API.
SHARP_WEIGHTS = {
    "pinnacle": 4.0, "lowvig": 2.0, "novig": 2.0, "prophetx": 2.0,
    "betonlineag": 1.5, "polymarket": 1.5, "kalshi": 1.5, "betopenly": 1.0,
}
YES_SIDE, NO_SIDE = {"over", "yes"}, {"under", "no"}


def norm(name):
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'`-]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def dec(american):
    return 1 + american / 100.0 if american > 0 else 1 + 100.0 / abs(american)


def implied(american):
    return 1.0 / dec(american)


def fair_odds_american(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def devig_pair(odds_a, odds_b):
    """Probability of side A with the vig removed, using the power method (finds k with pa^k + pb^k = 1).
    Handles favorites and longshots better than simply dividing by the total."""
    pa, pb = implied(odds_a), implied(odds_b)
    if pa + pb <= 1.0:                       # no vig (or a crossed market): plain normalization
        return pa / (pa + pb)
    lo, hi = 1.0, 10.0
    for _ in range(60):
        k = (lo + hi) / 2
        if pa ** k + pb ** k > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    return pa ** k


# ───────────────────────── parsing ─────────────────────────
def build_quotes(raw):
    """-> {(event_id, market, player_norm, point): {'meta': {...}, 'books': {book: {'A': price, 'B': price}}}}
    A = Over/Yes side, B = Under/No side."""
    out = {}
    for item in raw:
        ev, data = item["event"], item["data"]
        only = item.get("market")           # None -> parse every market in the response
        for bm in data.get("bookmakers", []):
            for m in bm.get("markets", []):
                mk = m.get("key")
                if not mk or (only and mk != only):
                    continue
                for o in m.get("outcomes", []):
                    nm, ds = str(o.get("name", "")), str(o.get("description", "") or "")
                    if nm.lower() in YES_SIDE | NO_SIDE:
                        side_txt, player = nm.lower(), ds
                    elif ds.lower() in YES_SIDE | NO_SIDE:
                        side_txt, player = ds.lower(), nm
                    else:
                        continue
                    if not player or o.get("price") is None:
                        continue
                    side = "A" if side_txt in YES_SIDE else "B"
                    point = o.get("point")
                    key = (ev["id"], mk, norm(player), float(point) if point is not None else 0.0)
                    slot = out.setdefault(key, {"meta": {"event": f"{ev['away_team']} @ {ev['home_team']}", "commence": ev["commence_time"],
                                                          "player": player, "market": mk, "point": point,
                                                          "yes_label": "Yes" if side_txt in ("yes", "no") else "Over",
                                                          "no_label": "No" if side_txt in ("yes", "no") else "Under"},
                                             "books": {}})
                    slot["books"].setdefault(bm["key"], {})[side] = float(o["price"])
    return out


# ───────────────────────── fair price ─────────────────────────
def fair_probability(books, weights=SHARP_WEIGHTS, min_sharps=1, max_spread=0.05, max_hold=0.15):
    """Weighted average of de-vigged two-sided sharp quotes. Returns (p_A, info) or (None, reason).
    A quote whose two sides add up to far more than 100% (hold above max_hold) is thin or a placeholder
    (for example an exchange showing a -25000 'No'), so it is dropped. The rest are weighted by how tight they are."""
    refs, junk = [], 0
    for b, w in weights.items():
        q = books.get(b)
        if q and "A" in q and "B" in q:
            hold = implied(q["A"]) + implied(q["B"]) - 1
            if hold > max_hold:
                junk += 1
                continue
            tight = min(1.0, 0.05 / max(hold, 0.01))
            refs.append((b, w * tight, devig_pair(q["A"], q["B"])))
    if not refs:
        return None, ("only wide/placeholder sharp quotes" if junk else "no two-sided sharp quote")
    has_pin = any(b == "pinnacle" for b, _, _ in refs)
    if len(refs) < min_sharps and not has_pin:
        return None, f"only {len(refs)} sharp source"
    ps = [p for _, _, p in refs]
    spread = max(ps) - min(ps)
    if spread > max_spread:
        return None, f"sharps disagree by {spread * 100:.1f} pts"
    p = sum(w * p for _, w, p in refs) / sum(w for _, w, _ in refs)
    return p, {"sharps": {b: round(pp, 4) for b, _, pp in refs}, "spread": spread}


def fair_map(quotes, weights=SHARP_WEIGHTS, min_sharps=1, max_spread=0.05, max_hold=0.15):
    """{(event_id, market, player_norm, point): (p_over_or_yes, n_sharps)} for every prop with a usable fair price.
    Used to record each flagged pick's closing fair price (closing-line value)."""
    out = {}
    for key, slot in quotes.items():
        p, info = fair_probability(slot["books"], weights, min_sharps, max_spread, max_hold)
        if p is not None:
            out[key] = (p, len(info["sharps"]))
    return out


def find_ev(quotes, min_ev=0.02, max_odds=1200, min_prob=0.03, max_prob=0.97, min_sharps=1, max_spread=0.05,
            weights=SHARP_WEIGHTS, single_source_min_ev=0.04, max_hold=0.15):
    """Returns (rows, skipped, all_ev, market_stats).
    rows: one dict per +EV (book, side) quote, each carrying `shop` = EVERY book that posts this prop (sharp books that
          went into the fair price, and all soft books): its price on the pick's side (`odds`), its price on the
          opposite side (`opp`), `sharp` (True for sharp books) and `ev_pct` (soft books only), best price first, so
          the page can show a full price comparison. market_stats: {market: {'props': n, 'fair': n}} for pruning dead markets."""
    rows, skipped = [], collections.Counter()
    all_ev = collections.defaultdict(list)       # every soft quote's EV, for sanity checking
    market_stats = collections.defaultdict(lambda: {"props": 0, "fair": 0})
    for key, slot in quotes.items():
        books = slot["books"]
        mk = key[1]
        market_stats[mk]["props"] += 1
        pA, info = fair_probability(books, weights, min_sharps, max_spread, max_hold)
        if pA is None:
            skipped[info.split(" by")[0] if info.startswith("sharps disagree") else info] += 1
            continue
        if not (min_prob <= pA <= max_prob):
            skipped["fair prob out of range"] += 1
            continue
        market_stats[mk]["fair"] += 1
        for side, p in (("A", pA), ("B", 1 - pA)):
            shop = []
            for b, q in books.items():
                if b in weights or side not in q:
                    continue
                ev = p * dec(q[side]) - 1
                all_ev[b].append(ev)
                shop.append({"book": b, "odds": int(q[side]), "ev_pct": round(ev * 100, 2)})
            shop.sort(key=lambda x: x["ev_pct"], reverse=True)
            other = "B" if side == "A" else "A"
            board = [{"book": e["book"], "odds": e["odds"], "ev_pct": e["ev_pct"], "sharp": False,
                      "opp": int(books[e["book"]][other]) if other in books[e["book"]] else None} for e in shop]
            for b in info["sharps"]:                    # sharp books that fed the fair price (junk quotes were already dropped)
                if side in books[b]:
                    board.append({"book": b, "odds": int(books[b][side]), "ev_pct": None, "sharp": True,
                                  "opp": int(books[b][other]) if other in books[b] else None})
            board.sort(key=lambda x: dec(x["odds"]), reverse=True)
            m = slot["meta"]
            single = len(info["sharps"]) == 1 and "pinnacle" not in info["sharps"]
            need = max(min_ev, single_source_min_ev if single else min_ev)
            for entry in shop:
                if entry["ev_pct"] / 100 < need or entry["odds"] > max_odds:
                    continue
                rows.append({
                    "event_id": key[0], "event": m["event"], "commence": m["commence"], "market": m["market"],
                    "player": m["player"], "point": m["point"], "side": "Over" if (side == "A" and m["yes_label"] == "Over") else
                    "Under" if (side == "B" and m["no_label"] == "Under") else ("Yes" if side == "A" else "No"),
                    "pick": f"{m['yes_label'] if side == 'A' else m['no_label']}" + (f" {m['point']}" if m["point"] is not None else ""),
                    "book": entry["book"], "odds": entry["odds"], "fair_prob": round(p, 4), "fair_odds": fair_odds_american(p),
                    "ev_pct": entry["ev_pct"], "n_sharps": len(info["sharps"]), "single_source": single,
                    "sharps": {k: round(v, 4) for k, v in info["sharps"].items()},
                    "sharp_spread_pts": round(info["spread"] * 100, 1),
                    "kelly_quarter_pct": round(max(0.0, (p * dec(entry["odds"]) - 1) / (dec(entry["odds"]) - 1)) * 25, 2),
                    "shop": board,
                })
    rows.sort(key=lambda r: r["ev_pct"], reverse=True)
    return rows, skipped, all_ev, dict(market_stats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("--min-ev", type=float, default=2.0, help="minimum EV%% to show")
    ap.add_argument("--max-odds", type=float, default=1200)
    ap.add_argument("--min-sharps", type=int, default=1, help="usable sharp quotes required (one non-Pinnacle source needs a bigger edge, see --single-min-ev)")
    ap.add_argument("--single-min-ev", type=float, default=4.0, help="minimum EV%% when only one non-Pinnacle sharp source sets the price")
    ap.add_argument("--max-spread", type=float, default=5.0, help="max disagreement between sharps, in probability points")
    ap.add_argument("--highlight", default="betmgm,williamhill_us,courtside", help="soft books to print first")
    ap.add_argument("--csv", default=None)
    a = ap.parse_args()

    raw = json.load(open(a.raw))
    quotes = build_quotes(raw)
    rows, skipped, all_ev, _stats = find_ev(quotes, min_ev=a.min_ev / 100, max_odds=a.max_odds, min_sharps=a.min_sharps,
                                    max_spread=a.max_spread / 100, single_source_min_ev=a.single_min_ev / 100)
    hl = [x.strip() for x in a.highlight.split(",") if x.strip()]
    print(f"props found: {len(quotes)} | with a usable fair price: {len(quotes) - sum(skipped.values())} | skipped: {dict(skipped)}")
    print(f"+EV bets (>= {a.min_ev}% EV): {len(rows)}\n")

    print("SANITY CHECK: average EV of every soft quote (should be negative, about minus each book's hold)")
    for b, v in sorted(all_ev.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        print(f"  {b:16s} n={len(v):4d}  mean EV {100 * sum(v) / len(v):+6.2f}%   share >= {a.min_ev}%: {100 * sum(1 for e in v if e >= a.min_ev / 100) / len(v):4.1f}%")

    def show(sub, title):
        if not sub:
            return
        print(f"\n{title}")
        print(f"  {'EV%':>5s}  {'book':14s} {'odds':>6s} {'fair':>6s}  {'player / pick':38s} {'market':20s} sharps")
        for r in sub[:40]:
            print(f"  {r['ev_pct']:5.1f}  {r['book']:14s} {r['odds']:+6d} {r['fair_odds']:+6d}  {(r['player'] + ' ' + r['pick']):38.38s} {r['market']:20.20s} {', '.join(f'{k}:{v * 100:.1f}%' for k, v in r['sharps'].items())}")
    show([r for r in rows if r["book"] in hl], f"+EV AT {', '.join(hl)}")
    show([r for r in rows if r["book"] not in hl], "+EV AT OTHER BOOKS")
    if a.csv and rows:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list([k for k in rows[0].keys() if k not in ("shop", "sharps")]))
            w.writeheader()
            w.writerows([{k: v for k, v in r.items() if k not in ('shop', 'sharps')} for r in rows])
        print(f"\nwrote {a.csv}")


if __name__ == "__main__":
    main()
