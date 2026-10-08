"""Paper trading: simulated portfolios driven by the DhanDrishti score, processed daily.

    uv run python -m dhandrishti.jobs.paper create --name "Monthly top 5" [--capital 100000] [--top-n 5]
        [--rebalance monthly] [--max-risk MEDIUM] [--stop-loss 10] [--rank-buffer 10] [--kill-switch 18]
        [--trailing-stop 15] [--min-history 252] [--regime-slots "BEARISH=0"]
    uv run python -m dhandrishti.jobs.paper run        # process every trading day not yet processed
    uv run python -m dhandrishti.jobs.paper list
    uv run python -m dhandrishti.jobs.paper resume <id>   # restart buying after a kill switch
    uv run python -m dhandrishti.jobs.paper close <id>

No real orders are ever placed. Fills use the next session's real open from the database.
"""

import argparse
import logging
import sys
from datetime import date, timedelta

import psycopg

from ..backtesting.engine import _period_key
from ..calendar import is_trading_day
from ..config import default_config
from ..db import connect
from ..db import paper_repository as repo
from ..db.migrate import migrate
from ..db.market_repository import load_history, load_market
from ..scoring import score_universe
from ..trading.paper import PaperParams, equity_of, new_state, plan_rebalance, process_day

log = logging.getLogger(__name__)


def next_trading_day(d: str) -> str:
    x = date.fromisoformat(d) + timedelta(days=1)
    while not is_trading_day(x.isoformat()):
        x += timedelta(days=1)
    return x.isoformat()


def is_signal_day(d: str, freq: str) -> bool:
    """Last session of the week/month/quarter (same rule as the backtester)."""
    return _period_key(d, freq) != _period_key(next_trading_day(d), freq)


def _prices(conn: psycopg.Connection, day: str) -> tuple[dict[str, float], dict[str, float]]:
    rows = conn.execute("SELECT symbol, open, close FROM daily_prices WHERE trade_date = %s", (day,)).fetchall()
    return {s: o for s, o, _ in rows}, {s: c for s, _, c in rows}


def _nifty(conn: psycopg.Connection, after: str) -> dict[str, float]:
    return {d.isoformat(): c for d, c in conn.execute("""
        SELECT trade_date, close FROM index_prices WHERE index_code = 'NIFTY 50' AND trade_date > %s
        ORDER BY trade_date""", (after,))}


def create(conn: psycopg.Connection, name: str, params: PaperParams, as_of: str | None = None) -> int:
    """Start a portfolio on the latest loaded session (`as_of` is for tests and replays only)."""
    cfg = default_config()
    if as_of is None:
        latest = conn.execute("SELECT max(trade_date) FROM daily_prices").fetchone()[0]
        if latest is None:
            raise LookupError("no prices in this database; run the pipeline first")
        as_of = latest.isoformat()
    market = load_market(conn, as_of, params.lookback_bars)
    result = score_universe(market, cfg)
    state = new_state(params)
    _, closes = _prices(conn, as_of)
    orders, events = plan_rebalance(state, as_of, result["stocks"], closes, "INITIAL",
                                    regime=result["regime"]["regime"])
    state.pending, state.last_processed = orders, as_of
    nifty_today = conn.execute("""SELECT close FROM index_prices WHERE index_code = 'NIFTY 50' AND trade_date = %s""",
                               (as_of,)).fetchone()
    with conn.transaction():
        pid = repo.create(conn, name, state, as_of, market.provenance)
        from ..trading.paper import DayResult
        day0 = DayResult(as_of, [], [], [], state.cash, 0.0, state.cash, 0.0, events)
        repo.save(conn, pid, state, [day0], {as_of: nifty_today[0] if nifty_today else None}, new_orders=orders)
    log.info("created paper portfolio %s (%s) as of %s with %d initial orders [%s]",
             pid, name, as_of, len(orders), market.provenance)
    for e in events:
        log.warning(e)
    return pid


def run(conn: psycopg.Connection) -> list[str]:
    """Process all unprocessed trading days for every open portfolio. Returns summary lines."""
    cfg = default_config()
    summaries = []
    latest = conn.execute("SELECT max(trade_date) FROM daily_prices").fetchone()[0]
    if latest is None:
        return ["no prices in this database"]
    latest = latest.isoformat()
    history = None
    for pid, name in repo.portfolios(conn):
        _, state = repo.load(conn, pid)
        nifty = _nifty(conn, state.last_processed)
        days = [d for d in nifty if d <= latest]
        if not days:
            summaries.append(f"#{pid} {name}: up to date ({state.last_processed})")
            continue
        results = []
        for day in days:
            opens, closes = _prices(conn, day)
            ranked = regime = None
            if state.status == "ACTIVE" and is_signal_day(day, state.params.rebalance):
                history = history or load_history(conn, latest)
                result = score_universe(history.market_at(day, state.params.lookback_bars), cfg)
                ranked, regime = result["stocks"], result["regime"]["regime"]
            results.append(process_day(state, day, opens, closes, ranked, regime))
        with conn.transaction():
            repo.save(conn, pid, state, results, nifty)
        start_equity = state.params.capital
        eq = equity_of(state)
        fills = sum(len(r.filled) for r in results)
        summaries.append(
            f"#{pid} {name}: {len(days)} day(s) to {days[-1]}, {fills} fill(s), equity ₹{eq:,.0f} "
            f"({(eq / start_equity - 1) * 100:+.2f}%), {len(state.positions)} holding(s), {state.status}")
        for r in results:
            for e in r.events:
                summaries.append(f"   {r.day}: {e}")
    return summaries


def parse_regime_slots(text: str | None) -> dict[str, int] | None:
    if not text:
        return None
    pairs = [part.split("=") for part in text.split(",") if part.strip()]
    return {k.strip().upper(): int(v) for k, v in pairs}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--name", required=True)
    c.add_argument("--capital", type=float, default=100_000)
    c.add_argument("--top-n", type=int, default=5)
    c.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly", "quarterly"])
    c.add_argument("--max-risk", default="MEDIUM")
    c.add_argument("--min-confidence", default=None)
    c.add_argument("--stop-loss", type=float, default=10.0, help="percent below entry; 0 disables")
    c.add_argument("--rank-buffer", type=int, default=10)
    c.add_argument("--kill-switch", type=float, default=18.0, help="percent drawdown from peak")
    c.add_argument("--trailing-stop", type=float, default=None, help="percent below the highest close since entry")
    c.add_argument("--min-history", type=int, default=None, help="skip stocks with fewer price bars")
    c.add_argument("--regime-slots", default=None,
                   help='max holdings per market regime, e.g. "BEARISH=0,CAUTIOUS=3"')
    sub.add_parser("run")
    sub.add_parser("list")
    for cmd in ("resume", "close"):
        s = sub.add_parser(cmd)
        s.add_argument("id", type=int)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with connect() as conn:
        migrate(conn)  # paper tables may be newer than this database
        conn.autocommit = True
        if args.cmd == "create":
            params = PaperParams(
                capital=args.capital, top_n=args.top_n, rebalance=args.rebalance,
                max_risk=None if args.max_risk.lower() == "none" else args.max_risk.upper(),
                min_confidence=args.min_confidence.upper() if args.min_confidence else None,
                stop_loss_pct=args.stop_loss or None, rank_buffer=args.rank_buffer, kill_switch_pct=args.kill_switch,
                trailing_stop_pct=args.trailing_stop, min_history_bars=args.min_history,
                regime_slots=parse_regime_slots(args.regime_slots))
            params.validate()
            pid = create(conn, args.name, params)
            print(f"Created paper portfolio #{pid} '{args.name}'. Initial orders fill at the next session's open "
                  f"when you run `pnpm paper:run` after that session's prices are loaded.")
        elif args.cmd == "run":
            print("\n".join(run(conn)))
        elif args.cmd == "list":
            for row in conn.execute("""
                    SELECT id, name, status, cash, start_date, last_processed FROM paper_portfolios ORDER BY id"""):
                print(f"#{row[0]} {row[1]}: {row[2]}, cash ₹{row[3]:,.0f}, since {row[4]}, processed to {row[5]}")
        elif args.cmd == "resume":
            _, state = repo.load(conn, args.id)
            repo.set_status(conn, args.id, "ACTIVE", peak=equity_of(state))  # new peak = today's equity
            print(f"Portfolio #{args.id} resumed; drawdown is measured from today's equity.")
        elif args.cmd == "close":
            repo.set_status(conn, args.id, "CLOSED")
            print(f"Portfolio #{args.id} closed (history kept).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
