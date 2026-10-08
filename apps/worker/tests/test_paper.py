import pytest

from dhandrishti.trading.costs import delivery_charges
from dhandrishti.trading.paper import PaperParams, new_state, plan_rebalance, process_day


def ranked(*symbols, risk="LOW", conf="HIGH"):
    return [{"symbol": s, "rank": i + 1, "risk_level": risk, "confidence": conf} for i, s in enumerate(symbols)]


# ------------------------------------------------------------------ charges

def test_zerodha_delivery_charges_match_the_published_schedule():
    buy = delivery_charges("BUY", 100_000)
    assert buy.stt == 100.0 and buy.stamp == 15.0 and buy.dp == 0
    # SEBI: ₹10 per crore -> ₹0.10 on ₹1 lakh. GST: 18% of (transaction + SEBI).
    assert buy.transaction == pytest.approx(3.07) and buy.sebi == pytest.approx(0.10)
    assert buy.gst == pytest.approx(0.18 * (3.07 + 0.10), abs=0.01)
    sell = delivery_charges("SELL", 100_000)
    assert sell.stamp == 0 and sell.dp == 15.34 and sell.stt == 100.0
    assert sell.total == pytest.approx(100 + 3.07 + 0.10 + 0.57 + 15.34, abs=0.02)
    with pytest.raises(ValueError):
        delivery_charges("SHORT", 1)


# ------------------------------------------------------------------ engine

def make(**kw):
    base = {"capital": 100_000, "top_n": 2, "rank_buffer": 3, "stop_loss_pct": 10, "kill_switch_pct": 18}
    return new_state(PaperParams(**(base | kw)))


def test_initial_orders_are_whole_shares_and_fill_next_open_not_same_day():
    s = make()
    orders, _ = plan_rebalance(s, "2026-10-06", ranked("A", "B", "C"), {"A": 1000.0, "B": 3000.0, "C": 50.0}, "INITIAL")
    assert [(o.symbol, o.qty) for o in orders] == [("A", 49), ("B", 16)]  # ₹50k each, whole shares
    s.pending, s.last_processed = orders, "2026-10-06"
    r = process_day(s, "2026-10-07", {"A": 1010.0, "B": 2990.0}, {"A": 1020.0, "B": 3000.0}, None)
    assert {o.symbol: o.fill_price for o in r.filled} == {"A": 1010.0, "B": 2990.0}  # next open, not signal close
    assert s.positions["A"].qty == 49 and s.cash < 100_000 - 49 * 1010 - 16 * 2990  # charges paid
    assert r.equity == pytest.approx(s.cash + 49 * 1020 + 16 * 3000)


def test_expensive_stock_is_skipped_with_a_reason():
    s = new_state(PaperParams(capital=10_000, top_n=2, rank_buffer=2))
    orders, events = plan_rebalance(s, "d", ranked("MRF", "ITC"), {"MRF": 120_000.0, "ITC": 400.0}, "INITIAL")
    assert [o.symbol for o in orders] == ["ITC"]
    assert "skipped MRF" in events[0]


def test_gap_up_shrinks_the_buy_to_available_cash():
    s = new_state(PaperParams(capital=10_000, top_n=1, rank_buffer=1))
    s.pending, _ = plan_rebalance(s, "d0", ranked("A"), {"A": 100.0}, "INITIAL")
    s.last_processed = "d0"
    r = process_day(s, "d1", {"A": 130.0}, {"A": 130.0}, None)
    assert r.filled[0].qty < 99 and "reduced" in r.filled[0].note
    assert s.cash >= 0


def test_stop_loss_triggers_on_close_and_sells_next_open():
    s = make()
    s.pending, _ = plan_rebalance(s, "d0", ranked("A", "B"), {"A": 100.0, "B": 100.0}, "INITIAL")
    s.last_processed = "d0"
    process_day(s, "d1", {"A": 100.0, "B": 100.0}, {"A": 100.0, "B": 100.0}, None)
    r = process_day(s, "d2", {"A": 95.0, "B": 100.0}, {"A": 89.0, "B": 101.0}, None)  # A closes 11% below entry
    assert [(o.symbol, o.side, o.reason) for o in r.created] == [("A", "SELL", "STOP_LOSS")]
    r3 = process_day(s, "d3", {"A": 88.0, "B": 101.0}, {"A": 90.0, "B": 101.0}, None)
    assert r3.filled[0].fill_price == 88.0 and "A" not in s.positions


def test_kill_switch_sells_everything_and_halts():
    s = make()
    s.pending, _ = plan_rebalance(s, "d0", ranked("A", "B"), {"A": 100.0, "B": 100.0}, "INITIAL")
    s.last_processed = "d0"
    process_day(s, "d1", {"A": 100.0, "B": 100.0}, {"A": 100.0, "B": 100.0}, None)
    r = process_day(s, "d2", {"A": 80.0, "B": 80.0}, {"A": 75.0, "B": 75.0}, ranked("C", "D"))
    assert s.status == "HALTED" and "kill switch" in s.halt_reason
    assert {(o.symbol, o.reason) for o in r.created} == {("A", "KILL_SWITCH"), ("B", "KILL_SWITCH")}
    process_day(s, "d3", {"A": 74.0, "B": 74.0}, {"A": 74.0, "B": 74.0}, ranked("C", "D"))
    assert s.positions == {} and not any(o.side == "BUY" for o in s.pending)  # no new buying while halted


def test_rank_buffer_keeps_holdings_and_limits_turnover():
    s = make()  # top 2, buffer 3
    s.pending, _ = plan_rebalance(s, "d0", ranked("A", "B"), {"A": 100.0, "B": 100.0}, "INITIAL")
    s.last_processed = "d0"
    process_day(s, "d1", {"A": 100.0, "B": 100.0}, {"A": 100.0, "B": 100.0}, None)
    # B slips to rank 3 (inside the buffer): kept. A drops to rank 5: replaced by the best new stock.
    r = process_day(s, "d2", {"A": 100.0, "B": 100.0}, {"A": 100.0, "B": 100.0, "C": 50.0, "D": 50.0, "E": 50.0},
                    ranked("C", "D", "B", "E", "A"))
    assert sorted((o.side, o.symbol) for o in r.created) == [("BUY", "C"), ("SELL", "A")]


def test_ineligible_holding_is_sold():
    s = make(max_risk="MEDIUM")
    s.pending, _ = plan_rebalance(s, "d0", ranked("A", "B"), {"A": 100.0, "B": 100.0}, "INITIAL")
    s.last_processed = "d0"
    process_day(s, "d1", {"A": 100.0, "B": 100.0}, {"A": 100.0, "B": 100.0}, None)
    rk = ranked("A", "B", "C")
    rk[0]["risk_level"] = "VERY_HIGH"  # A stays #1 by score but breaches the risk filter
    r = process_day(s, "d2", {"A": 100.0, "B": 100.0}, {"A": 100.0, "B": 100.0, "C": 100.0}, rk)
    assert ("SELL", "A") in {(o.side, o.symbol) for o in r.created}
    assert next(o for o in r.created if o.symbol == "A").note == "no longer eligible"


def test_missing_price_delays_then_cancels():
    s = make()
    s.pending, _ = plan_rebalance(s, "d0", ranked("A"), {"A": 100.0}, "INITIAL")
    s.last_processed = "d0"
    for d in ("d1", "d2"):
        process_day(s, d, {}, {}, None)
        assert s.pending[0].status == "PENDING"
    r = process_day(s, "d3", {}, {}, None)
    assert r.cancelled[0].note == "no price for 3 sessions" and s.pending == []


def test_days_must_move_forward():
    s = make()
    s.last_processed = "2026-10-07"
    with pytest.raises(ValueError, match="already processed"):
        process_day(s, "2026-10-06", {}, {}, None)


def test_invalid_params():
    for bad in (dict(rank_buffer=1, top_n=2), dict(stop_loss_pct=150), dict(rebalance="daily"), dict(max_risk="X")):
        with pytest.raises(ValueError):
            PaperParams(**bad).validate()


# ------------------------------------------------------------------ optional rules (2026-10 rule study)

def owned(s, day, prices):
    """Fill pending orders at `prices` on `day`."""
    return process_day(s, day, prices, prices, None)


def test_regime_slots_hold_cash_in_a_bear_market_and_reinvest_later():
    s = make(regime_slots={"BEARISH": 0, "CAUTIOUS": 1})
    px = {"A": 100.0, "B": 100.0, "C": 100.0}
    orders, _ = plan_rebalance(s, "d0", ranked("A", "B", "C"), px, "INITIAL", regime="BEARISH")
    assert orders == []  # bearish: stay in cash
    s.pending, _ = plan_rebalance(s, "d0", ranked("A", "B", "C"), px, "INITIAL", regime="CAUTIOUS")
    assert [o.symbol for o in s.pending] == ["A"]
    assert s.pending[0].qty * 100 <= 50_000  # one of two slots: half the money, the rest stays cash
    s.last_processed = "d0"
    owned(s, "d1", px)
    r = process_day(s, "d2", px, px, ranked("A", "B", "C"), regime="BEARISH")
    assert [(o.side, o.symbol) for o in r.created] == [("SELL", "A")]
    assert "bearish market" in r.created[0].note
    owned(s, "d3", px)
    r = process_day(s, "d4", px, px, ranked("A", "B", "C"), regime="BULLISH")
    assert sorted(o.symbol for o in r.created if o.side == "BUY") == ["A", "B"]


def test_no_regime_rule_means_regime_is_ignored():
    s = make()
    orders, _ = plan_rebalance(s, "d0", ranked("A", "B"), {"A": 100.0, "B": 100.0}, "INITIAL", regime="BEARISH")
    assert len(orders) == 2


def test_trailing_stop_follows_the_highest_close():
    s = make(trailing_stop_pct=10, stop_loss_pct=None)
    s.pending, _ = plan_rebalance(s, "d0", ranked("A"), {"A": 100.0}, "INITIAL")
    s.last_processed = "d0"
    owned(s, "d1", {"A": 100.0})
    assert not process_day(s, "d2", {"A": 150.0}, {"A": 150.0}, None).created
    assert not process_day(s, "d3", {"A": 140.0}, {"A": 136.0}, None).created  # 9.3% off the high
    r = process_day(s, "d4", {"A": 135.0}, {"A": 134.0}, None)  # 10.7% off the ₹150 high, still +34% on entry
    assert [(o.side, o.reason) for o in r.created] == [("SELL", "STOP_LOSS")] and "high" in r.created[0].note


def test_min_history_skips_recent_listings():
    rows = ranked("NEWIPO", "OLDCO")
    rows[0]["technicals"], rows[1]["technicals"] = {"bars": 120}, {"bars": 300}
    s = new_state(PaperParams(capital=100_000, top_n=1, rank_buffer=1, min_history_bars=252))
    orders, _ = plan_rebalance(s, "d0", rows, {"NEWIPO": 10.0, "OLDCO": 10.0}, "INITIAL")
    assert [o.symbol for o in orders] == ["OLDCO"]


@pytest.mark.parametrize("kw", [{"trailing_stop_pct": 0}, {"min_history_bars": 400},
                                {"regime_slots": {"BEARISH": 5}}, {"regime_slots": {"PANIC": 0}}])
def test_invalid_rule_settings_are_rejected(kw):
    with pytest.raises(ValueError):
        PaperParams(top_n=2, rank_buffer=2, **kw).validate()
