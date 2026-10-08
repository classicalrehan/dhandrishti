"""Paper-trading engine: simulated trades that follow the same rules real trading would.

Day D (processed after D's close, once D's EOD candles exist):
  1. Fill orders created on an earlier day at D's OPEN, sells first (frees cash), then buys.
  2. Mark positions to D's CLOSE; update peak equity and drawdown.
  3. Kill switch: drawdown beyond the limit -> sell everything next open, stop buying (HALTED).
  4. Stop-losses: a close at or below entry x (1 - stop%), or below the highest close since entry
     x (1 - trailing%) -> sell next open.
  5. Rebalance (on signal days, or at creation): keep holdings still ranked within
     `rank_buffer`, fill empty slots with the best-ranked eligible stocks not held. With
     `regime_slots`, the market regime on the signal day caps the number of holdings (the rest is
     held as cash), e.g. {"BEARISH": 0} sits out bear markets.
New orders are created on D and can only fill on a later day: no look-ahead.

Realism: whole shares; Zerodha delivery charges (trading.costs); a buy shrinks to what cash
can pay for at the actual open (gaps happen); missing prices delay a fill (up to 3 sessions).
Existing holdings are not resized at rebalance (fewer trades, lower charges).
"""

import math
from dataclasses import asdict, dataclass, field

from .costs import delivery_charges

RISK_ORDER = ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")
REGIMES = ("BULLISH", "NEUTRAL", "CAUTIOUS", "BEARISH")
CONFIDENCE_ORDER = ("LOW", "MEDIUM", "HIGH")
BUY_CHARGE_HEADROOM = 1.0015  # STT + stamp + fees on a buy are ~0.12%; keep a little spare
MAX_FILL_ATTEMPTS = 3


@dataclass(frozen=True)
class PaperParams:
    capital: float = 100_000.0
    top_n: int = 5
    rebalance: str = "monthly"  # weekly | monthly | quarterly
    max_risk: str | None = "MEDIUM"
    min_confidence: str | None = None
    stop_loss_pct: float | None = 10.0
    rank_buffer: int | None = 10  # keep a holding while its rank stays within this
    kill_switch_pct: float = 18.0
    lookback_bars: int = 300
    # Optional rules (off by default, so existing portfolios behave exactly as before):
    regime_slots: dict[str, int] | None = None  # max holdings per regime, e.g. {"BEARISH": 0, "CAUTIOUS": 3}
    min_history_bars: int | None = None  # skip stocks with less price history (recent listings)
    trailing_stop_pct: float | None = None  # sell on a close this far below the highest close since entry

    def validate(self) -> None:
        if self.capital <= 0 or self.top_n < 1:
            raise ValueError("capital and top_n must be positive")
        if self.rebalance not in ("weekly", "monthly", "quarterly"):
            raise ValueError("rebalance must be weekly, monthly or quarterly")
        if self.max_risk is not None and self.max_risk not in RISK_ORDER:
            raise ValueError(f"max_risk must be one of {RISK_ORDER}")
        if self.min_confidence is not None and self.min_confidence not in CONFIDENCE_ORDER:
            raise ValueError(f"min_confidence must be one of {CONFIDENCE_ORDER}")
        if self.stop_loss_pct is not None and not 0 < self.stop_loss_pct < 100:
            raise ValueError("stop_loss_pct must be between 0 and 100")
        if self.rank_buffer is not None and self.rank_buffer < self.top_n:
            raise ValueError("rank_buffer must be >= top_n")
        if not 0 < self.kill_switch_pct < 100:
            raise ValueError("kill_switch_pct must be between 0 and 100")
        if self.trailing_stop_pct is not None and not 0 < self.trailing_stop_pct < 100:
            raise ValueError("trailing_stop_pct must be between 0 and 100")
        if self.min_history_bars is not None and not 0 < self.min_history_bars <= self.lookback_bars:
            raise ValueError("min_history_bars must be between 1 and lookback_bars")
        for regime, n in (self.regime_slots or {}).items():
            if regime not in REGIMES or not 0 <= n <= self.top_n:
                raise ValueError(f"regime_slots: {regime!r} must be one of {REGIMES} with 0..top_n holdings")

    def slots(self, regime: str | None) -> int:
        """Holdings allowed under `regime` (top_n when no rule applies)."""
        return min(self.top_n, (self.regime_slots or {}).get(regime, self.top_n)) if regime else self.top_n


@dataclass
class Position:
    symbol: str
    qty: int
    avg_price: float
    entry_date: str
    last_close: float
    high_close: float | None = None  # highest close since entry (trailing stop)


@dataclass
class Order:
    created_on: str
    side: str  # BUY | SELL
    symbol: str
    qty: int
    reason: str  # INITIAL | REBALANCE | STOP_LOSS | KILL_SWITCH
    status: str = "PENDING"  # PENDING | FILLED | CANCELLED
    fill_date: str | None = None
    fill_price: float | None = None
    charges: float = 0.0
    note: str | None = None
    attempts: int = 0
    id: int | None = None


@dataclass
class PaperState:
    params: PaperParams
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    pending: list[Order] = field(default_factory=list)
    peak_equity: float = 0.0
    status: str = "ACTIVE"  # ACTIVE | HALTED | CLOSED
    halt_reason: str | None = None
    last_processed: str | None = None


@dataclass
class DayResult:
    day: str
    filled: list[Order]
    cancelled: list[Order]
    created: list[Order]
    cash: float
    holdings_value: float
    equity: float
    drawdown_pct: float
    events: list[str]

    def daily_row(self) -> dict:
        return {"trade_date": self.day, "cash": round(self.cash, 2), "holdings_value": round(self.holdings_value, 2),
                "equity": round(self.equity, 2), "drawdown_pct": round(self.drawdown_pct, 4)}


def equity_of(state: PaperState) -> float:
    return state.cash + sum(p.qty * p.last_close for p in state.positions.values())


def _fill(state: PaperState, o: Order, day: str, opens: dict[str, float]) -> str:
    """Try to fill one order at today's open. Returns FILLED, CANCELLED or PENDING."""
    price = opens.get(o.symbol)
    if price is None:
        o.attempts += 1
        if o.attempts >= MAX_FILL_ATTEMPTS:
            o.status, o.note = "CANCELLED", "no price for 3 sessions"
            return "CANCELLED"
        return "PENDING"
    if o.side == "SELL":
        pos = state.positions.get(o.symbol)
        if pos is None:
            o.status, o.note = "CANCELLED", "no position to sell"
            return "CANCELLED"
        o.qty = min(o.qty, pos.qty)
        ch = delivery_charges("SELL", o.qty * price).total
        state.cash += o.qty * price - ch
        pos.qty -= o.qty
        if pos.qty == 0:
            del state.positions[o.symbol]
    else:
        affordable = math.floor(state.cash / (price * BUY_CHARGE_HEADROOM))
        if affordable < o.qty:
            o.note = f"reduced from {o.qty}: open gapped above the plan"
            o.qty = affordable
        if o.qty <= 0:
            o.status, o.note = "CANCELLED", "insufficient cash at the open"
            return "CANCELLED"
        ch = delivery_charges("BUY", o.qty * price).total
        state.cash -= o.qty * price + ch
        pos = state.positions.get(o.symbol)
        if pos:
            pos.avg_price = (pos.avg_price * pos.qty + price * o.qty) / (pos.qty + o.qty)
            pos.qty += o.qty
        else:
            state.positions[o.symbol] = Position(o.symbol, o.qty, price, day, price)
    o.status, o.fill_date, o.fill_price, o.charges = "FILLED", day, price, ch
    return "FILLED"


def _eligible(ranked: list[dict], p: PaperParams) -> list[dict]:
    risk_cap = RISK_ORDER.index(p.max_risk) if p.max_risk else len(RISK_ORDER) - 1
    conf_min = CONFIDENCE_ORDER.index(p.min_confidence) if p.min_confidence else 0
    return [s for s in ranked
            if RISK_ORDER.index(s["risk_level"]) <= risk_cap and CONFIDENCE_ORDER.index(s["confidence"]) >= conf_min
            and (not p.min_history_bars or s["technicals"].get("bars", 0) >= p.min_history_bars)]


def plan_rebalance(state: PaperState, day: str, ranked: list[dict], closes: dict[str, float],
                   reason: str = "REBALANCE", regime: str | None = None) -> tuple[list[Order], list[str]]:
    p = state.params
    top_n = p.slots(regime)
    eligible = _eligible(ranked, p)
    rank_of = {s["symbol"]: i + 1 for i, s in enumerate(eligible)}  # rank among eligible stocks
    selling = {o.symbol for o in state.pending if o.side == "SELL"}
    buffer = p.rank_buffer or p.top_n
    keep = [s for s in sorted(state.positions)
            if s not in selling and rank_of.get(s, math.inf) <= buffer]
    keep = sorted(keep, key=lambda s: rank_of[s])[:top_n]
    slots = top_n - len(keep)
    new = [s["symbol"] for s in eligible if s["symbol"] not in state.positions and s["symbol"] in closes][:slots]

    orders, events = [], []
    sells = [s for s in sorted(state.positions) if s not in keep and s not in selling]
    for sym in sells:
        why = ("no longer eligible" if sym not in rank_of
               else f"rank {rank_of[sym]} outside top {buffer}" if rank_of[sym] > buffer
               else f"{regime.lower()} market: holding {top_n} of {p.top_n}" if regime and top_n < p.top_n
               else f"rank {rank_of[sym]}: more holdings than the {top_n} allowed")
        orders.append(Order(day, "SELL", sym, state.positions[sym].qty, reason, note=why))
    if new:
        # Cash expected after today's sells (at today's close, net of ~0.12% charges).
        est_cash = state.cash + sum(state.positions[s].qty * closes.get(s, state.positions[s].last_close) * 0.9988
                                    for s in sells)
        est_cash -= sum(o.qty * closes.get(o.symbol, 0) for o in state.pending if o.side == "BUY")
        # Each new holding gets an equal share of equity, so a smaller regime allowance leaves cash idle.
        equity = state.cash + sum(pos.qty * closes.get(s, pos.last_close) for s, pos in state.positions.items())
        per = min(est_cash / len(new), equity / p.top_n) if p.regime_slots else est_cash / len(new)
        for sym in new:
            qty = math.floor(per / (closes[sym] * BUY_CHARGE_HEADROOM))
            if qty > 0:
                orders.append(Order(day, "BUY", sym, qty, reason, note=f"rank {rank_of[sym]}"))
            else:
                events.append(f"skipped {sym}: one share (₹{closes[sym]:,.0f}) exceeds the ₹{per:,.0f} slot")
    return orders, events


def process_day(state: PaperState, day: str, opens: dict[str, float], closes: dict[str, float],
                ranked: list[dict] | None, regime: str | None = None) -> DayResult:
    """Advance the paper portfolio through one trading day. `ranked` (and the market `regime`) are
    given on signal days."""
    if state.last_processed is not None and day <= state.last_processed:
        raise ValueError(f"{day} already processed (last {state.last_processed})")
    events: list[str] = []
    filled, cancelled, still = [], [], []

    # 1. Fills at the open: sells first, then buys.
    for o in sorted(state.pending, key=lambda o: (o.side != "SELL", o.symbol)):
        if o.created_on >= day:
            still.append(o)
            continue
        outcome = _fill(state, o, day, opens)
        (filled if outcome == "FILLED" else cancelled if outcome == "CANCELLED" else still).append(o)
    state.pending = still

    # 2. Mark to market.
    for sym, pos in state.positions.items():
        if sym in closes:
            pos.last_close = closes[sym]
            pos.high_close = max(pos.high_close or pos.avg_price, closes[sym])
    equity = equity_of(state)
    state.peak_equity = max(state.peak_equity, equity)
    dd = (equity / state.peak_equity - 1) * 100 if state.peak_equity else 0.0

    created: list[Order] = []
    p = state.params
    # 3. Kill switch.
    if state.status == "ACTIVE" and dd <= -p.kill_switch_pct:
        state.status = "HALTED"
        state.halt_reason = f"drawdown {dd:.1f}% hit the {p.kill_switch_pct:.0f}% kill switch on {day}"
        events.append(state.halt_reason)
        for o in state.pending:
            if o.side == "BUY":
                o.status, o.note = "CANCELLED", "kill switch"
                cancelled.append(o)
        state.pending = [o for o in state.pending if o.side == "SELL"]
        pending_sells = {o.symbol for o in state.pending}
        created += [Order(day, "SELL", s, pos.qty, "KILL_SWITCH") for s, pos in sorted(state.positions.items())
                    if s not in pending_sells]
    elif state.status == "ACTIVE":
        # 4. Stop-losses.
        if p.stop_loss_pct:
            pending_sells = {o.symbol for o in state.pending if o.side == "SELL"}
            for s, pos in sorted(state.positions.items()):
                if s not in pending_sells and pos.last_close <= pos.avg_price * (1 - p.stop_loss_pct / 100):
                    created.append(Order(day, "SELL", s, pos.qty, "STOP_LOSS",
                                         note=f"close ₹{pos.last_close:,.2f} ≤ {p.stop_loss_pct:g}% below entry ₹{pos.avg_price:,.2f}"))
        if p.trailing_stop_pct:
            pending_sells = {o.symbol for o in state.pending + created if o.side == "SELL"}
            for s, pos in sorted(state.positions.items()):
                high = pos.high_close or pos.avg_price
                if s not in pending_sells and pos.last_close <= high * (1 - p.trailing_stop_pct / 100):
                    created.append(Order(day, "SELL", s, pos.qty, "STOP_LOSS",
                                         note=f"close ₹{pos.last_close:,.2f} ≤ {p.trailing_stop_pct:g}% below its high ₹{high:,.2f}"))
        # 5. Rebalance.
        if ranked is not None:
            state.pending.extend(created)
            orders, ev = plan_rebalance(state, day, ranked, closes, regime=regime)
            state.pending = [o for o in state.pending if o not in created]
            created += orders
            events += ev

    state.pending.extend(created)
    state.last_processed = day
    return DayResult(day, filled, cancelled, created, state.cash, equity - state.cash, equity, dd, events)


def new_state(params: PaperParams) -> PaperState:
    params.validate()
    return PaperState(params=params, cash=params.capital, peak_equity=params.capital)


def params_dict(p: PaperParams) -> dict:
    return asdict(p)
