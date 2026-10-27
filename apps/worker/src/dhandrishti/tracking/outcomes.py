"""Forward outcomes of recorded scoring runs (docs/recommendation-tracking.md).

Method outcome-v1, for each scored stock of a run and each horizon h (trading sessions):
  calendar  NIFTY 50 sessions stored in index_prices
  entry     open of the first session after as_of; if the stock has no bar that day, the next of up to
            3 sessions (suspensions), as paper trading delays fills
  exit      open of the session h sessions after the planned entry; up to 3 sessions later if missing.
            A late entry does not move the exit, so the holding can be a few sessions shorter
  returns   price only (dividends excluded), fractional shares on a fixed notional
  costs     Zerodha delivery charges from trading.costs (the same function paper trading pays) plus a
            stated slippage assumption per side; net is also given with no slippage and at 10/25 bps
  benchmark NIFTY 50 price index, open to open on the stock's own entry and exit sessions (no costs), and
            the equal-weight mean net return of every COMPLETE outcome of the same run and horizon
  MAE       lowest low between entry and exit (and the exit open) relative to the entry price
A run and horizon are evaluated only when the calendar holds the planned exit plus the 3 grace sessions,
and then for every stock at once. Earlier than that the outcome is PENDING and nothing is stored.
Outcomes are never read by scoring, paper trading or backtests.
"""

import bisect
import statistics
from dataclasses import dataclass, field

import psycopg
from psycopg.types.json import Jsonb

from ..trading.costs import DELIVERY_CHARGES, delivery_charges
from .manifest import sha

HORIZONS = (20, 60, 120, 252)

METHOD_V1 = {
    "version": "outcome-v1",
    "calendar": "NIFTY 50 sessions in index_prices",
    "entry": "open of the first session after as_of; up to 3 later sessions if the stock has no bar",
    "exit": "open of planned entry + horizon sessions; up to 3 later sessions if missing",
    "max_delay_sessions": 3,
    "notional_inr": 20000.0,
    "base_slippage_bps": 3.0,
    "sensitivity_slippage_bps": [10.0, 25.0],
    "shares": "fractional",
    "charges": DELIVERY_CHARGES,
    "charges_source": "trading.costs.delivery_charges: Zerodha equity delivery, checked 2026-10-06",
    "returns": "price only, dividends excluded; benchmark NIFTY 50 price index without costs",
    "suspect_move": 0.35,
}
METHOD_V1_DESCRIPTION = (
    "Open-to-open from the session after the signal; Rs 20,000 notional, fractional shares; Zerodha delivery "
    "charges (STT 0.1% each side, stamp 0.015% buy, NSE 0.00307%, SEBI Rs 10/cr, GST 18% on fees, DP Rs 15.34 "
    "per sell); slippage 3 bps per side is an assumption, not a measured cost (sensitivity at 0, 10, 25 bps).")


def register(conn: psycopg.Connection, method: dict = METHOD_V1, description: str = METHOD_V1_DESCRIPTION) -> str:
    digest = sha(method)
    conn.execute("""INSERT INTO outcome_methods (version, params, params_sha256, description) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (version) DO NOTHING""", (method["version"], Jsonb(method), digest, description))
    stored = conn.execute("SELECT params_sha256 FROM outcome_methods WHERE version = %s",
                          (method["version"],)).fetchone()[0]
    if stored != digest:
        raise RuntimeError(f"outcome method {method['version']} differs from the stored copy (charges changed?); "
                           "bump its version")
    return method["version"]


def net_return(entry: float, exit_: float, notional: float, slippage_bps: float,
               charges: dict = DELIVERY_CHARGES) -> tuple[float, float]:
    """(net return, charges in rupees) for buying `notional` at `entry` and selling at `exit_`."""
    s = slippage_bps / 1e4
    buy = delivery_charges("BUY", notional, charges).total
    shares = notional / (entry * (1 + s))
    proceeds = shares * exit_ * (1 - s)
    sell = delivery_charges("SELL", proceeds, charges).total
    return (proceeds - sell) / (notional + buy) - 1, buy + sell


@dataclass
class Evaluation:
    run_id: int
    horizon: int
    evaluation_hash: str
    rows: list[dict] = field(default_factory=list)


def _calendar(conn: psycopg.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT trade_date::text FROM index_prices WHERE index_code = 'NIFTY 50' ORDER BY trade_date")]


def evaluate(conn: psycopg.Connection, run_id: int, horizon: int, method: dict = METHOD_V1,
             calendar: list[str] | None = None) -> Evaluation | None:
    """Outcomes for every stock of a run at one horizon, or None while the horizon is still PENDING."""
    cal = calendar if calendar is not None else _calendar(conn)
    as_of = conn.execute("SELECT as_of::text FROM recommendation_runs WHERE run_id = %s", (run_id,)).fetchone()[0]
    delay = method["max_delay_sessions"]
    e = bisect.bisect_right(cal, as_of)          # planned entry: first session after as_of
    x = e + horizon                               # planned exit
    if x + delay >= len(cal):
        return None
    lo, hi = cal[max(e - 1, 0)], cal[x + delay]
    window = cal[max(e - 1, 0): x + delay + 1]
    symbols = [r[0] for r in conn.execute("SELECT symbol FROM recommendation_scores WHERE run_id = %s ORDER BY symbol",
                                          (run_id,))]
    bars: dict[str, dict[str, tuple]] = {s: {} for s in symbols}
    for sym, d, o, h, low, c in conn.execute("""
            SELECT symbol, trade_date::text, open, high, low, close FROM daily_prices
            WHERE symbol = ANY(%s) AND trade_date BETWEEN %s AND %s ORDER BY symbol, trade_date""",
                                             (symbols, lo, hi)):
        bars[sym][d] = (o, h, low, c)
    nifty = {d: o for d, o in conn.execute("""
        SELECT trade_date::text, open FROM index_prices WHERE index_code = 'NIFTY 50'
        AND trade_date BETWEEN %s AND %s""", (lo, hi))}

    def first_open(b: dict, start: int) -> int | None:
        return next((k for k in range(start, start + delay + 1) if cal[k] in b and b[cal[k]][0] > 0), None)

    price_hashes = {s: sha({d: list(bars[s][d]) for d in window if d in bars[s]}) for s in symbols}
    ev = Evaluation(run_id, horizon, sha({"method": sha(method), "horizon": horizon, "calendar": window,
                                          "nifty": {d: nifty.get(d) for d in window}, "stocks": price_hashes}))
    notional, base = method["notional_inr"], method["base_slippage_bps"]
    for sym in symbols:
        b = bars[sym]
        row = {"symbol": sym, "price_data_hash": price_hashes[sym], "status": None, "entry_date": None,
               "entry_price": None, "exit_date": None, "exit_price": None, "sessions_held": None,
               "gross_return": None, "net_return": None, "net_return_no_slippage": None,
               "slippage_sensitivity": None, "charges_inr": None, "nifty_return": None, "max_adverse_excursion": None,
               "mae_reliable": None, "detail": None}
        ek = first_open(b, e)
        if ek is None:
            row.update(status="NO_ENTRY_PRICE", detail=f"no open price from {cal[e]} to {cal[e + delay]}")
            ev.rows.append(row)
            continue
        xk = first_open(b, x)
        row.update(entry_date=cal[ek], entry_price=b[cal[ek]][0])
        if xk is None:
            known = [d for d in window if d in b]
            row.update(status="NO_EXIT_PRICE", detail=f"no open price from {cal[x]} to {cal[x + delay]}; "
                                                      f"last bar {known[-1] if known else 'none'}")
            ev.rows.append(row)
            continue
        entry, exit_ = b[cal[ek]][0], b[cal[xk]][0]
        gross = exit_ / entry - 1
        net, charges = net_return(entry, exit_, notional, base)
        net0, _ = net_return(entry, exit_, notional, 0.0)
        sens = {f"{bps:g}": net_return(entry, exit_, notional, bps)[0] for bps in method["sensitivity_slippage_bps"]}
        held = [cal[k] for k in range(ek, xk)]
        lows = [b[d][2] for d in held if d in b]
        missing = len(lows) < len(held)
        closes = [b[d][3] for d in cal[max(e - 1, 0): xk + 1] if d in b]
        suspect = any(abs(c1 / c0 - 1) > method["suspect_move"] for c0, c1 in zip(closes, closes[1:]) if c0 > 0)
        mae = min(lows + [exit_]) / entry - 1
        n0, n1 = nifty.get(cal[ek]), nifty.get(cal[xk])
        nifty_ret = n1 / n0 - 1 if n0 and n1 else None
        notes = []
        if ek > e:
            notes.append(f"entry {ek - e} session(s) late")
        if xk > x:
            notes.append(f"exit {xk - x} session(s) late")
        if missing:
            notes.append(f"{len(held) - len(lows)} session(s) without a bar")
        status = ("SUSPECT_PRICE_JUMP" if suspect else "BENCHMARK_MISSING" if nifty_ret is None else "COMPLETE")
        if suspect:
            notes.append(f"close-to-close move above {method['suspect_move']:.0%} (unadjusted split/bonus?)")
        row.update(status=status, exit_date=cal[xk], exit_price=exit_, sessions_held=xk - ek, gross_return=gross,
                   net_return=net, net_return_no_slippage=net0, slippage_sensitivity=sens, charges_inr=charges,
                   nifty_return=nifty_ret, max_adverse_excursion=mae, mae_reliable=not (missing or suspect),
                   detail="; ".join(notes) or None)
        ev.rows.append(row)

    complete = [r["net_return"] for r in ev.rows if r["status"] == "COMPLETE"]
    universe = statistics.fmean(complete) if complete else None
    for r in ev.rows:
        r["universe_return"] = universe if r["net_return"] is not None else None
        r["excess_vs_universe"] = (r["net_return"] - universe
                                   if r["net_return"] is not None and universe is not None else None)
        r["excess_vs_nifty"] = (r["net_return"] - r["nifty_return"]
                                if r["net_return"] is not None and r["nifty_return"] is not None else None)
    return ev


def _store(conn: psycopg.Connection, ev: Evaluation, version: str) -> int:
    cols = ("status", "entry_date", "entry_price", "exit_date", "exit_price", "sessions_held", "gross_return",
            "net_return", "net_return_no_slippage", "slippage_sensitivity", "charges_inr", "nifty_return",
            "excess_vs_nifty", "universe_return", "excess_vs_universe", "max_adverse_excursion", "mae_reliable",
            "detail")
    rows = [(ev.run_id, r["symbol"], ev.horizon, version, ev.evaluation_hash, r["price_data_hash"],
             *[Jsonb(r[c]) if c == "slippage_sensitivity" and r[c] is not None else r[c] for c in cols])
            for r in ev.rows]
    with conn.cursor() as cur:
        cur.executemany(f"""
            INSERT INTO recommendation_outcomes (run_id, symbol, horizon, method_version, evaluation_hash,
              price_data_hash, {', '.join(cols)})
            VALUES ({', '.join(['%s'] * (6 + len(cols)))})""", rows)
    return len(rows)


@dataclass
class UpdateReport:
    evaluated: int = 0       # (run, horizon) pairs newly stored
    unchanged: int = 0       # already stored with the same prices
    revised: int = 0         # stored again because the prices used changed
    pending: int = 0
    rows: int = 0


def update(conn: psycopg.Connection, method: dict = METHOD_V1, horizons=HORIZONS) -> UpdateReport:
    """Evaluate every recorded run at every matured horizon. Insert-only and idempotent."""
    rep = UpdateReport()
    cal = _calendar(conn)
    with conn.transaction():
        version = register(conn, method)
    for (run_id,) in conn.execute("SELECT run_id FROM recommendation_runs ORDER BY run_id").fetchall():
        for h in horizons:
            ev = evaluate(conn, run_id, h, method, cal)
            if ev is None:
                rep.pending += 1
                continue
            seen = conn.execute("""SELECT bool_or(evaluation_hash = %s), count(*) > 0 FROM recommendation_outcomes
                                   WHERE run_id = %s AND horizon = %s AND method_version = %s""",
                                (ev.evaluation_hash, run_id, h, version)).fetchone()
            if seen[0]:
                rep.unchanged += 1
                continue
            with conn.transaction():
                rep.rows += _store(conn, ev, version)
            if seen[1]:
                rep.revised += 1
            else:
                rep.evaluated += 1
    return rep
