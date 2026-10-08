"""Deterministic MOCK history for backtests.

Extends `generate_market` (the latest `base_bars` sessions, unchanged and still matching the
golden fixtures) backwards with older sessions drawn from separate "HIST:" random streams,
and adds point-in-time quarterly fundamentals snapshots dated when results would have been
published. Everything here is synthetic and carries provenance "MOCK".
"""

import math
from dataclasses import replace
from datetime import date, timedelta

import numpy as np

from ..calendar import trading_days_back
from ..models import Bars, Fundamentals, MarketHistory
from .mock import DEFAULT_SEED, _SECTOR_PROFILE, generate_market, rng_for

BASE_MU = 0.00045  # matches generate_market
# Older history in three regimes so strategies are tested through a correction, not just a rally.
_REGIMES = ((0.40, 0.0007), (0.25, -0.0009), (0.35, 0.0006))  # (share of old sessions, daily drift)


def _stock_params(seed: int, symbol: str) -> tuple[float, float, float, float]:
    """Re-derive beta, idiosyncratic vol, quality and alpha exactly as generate_market draws them."""
    r = rng_for(seed, f"STOCK:{symbol}")
    beta = r.uniform(0.75, 1.25)
    idio = r.uniform(0.008, 0.02)
    q = float(r.normal(0, 1))
    alpha = 0.0002 * q + r.normal(0, 0.0003) - 0.0002
    return beta, idio, q, alpha


def _old_bars(dates: list[str], rets: np.ndarray, anchor: float, rng: np.random.Generator,
              base_volume: float | None) -> Bars:
    """Bars whose path ends exactly at `anchor` (the first open of the newer segment)."""
    growth = np.cumprod(1 + rets)
    close = np.round(anchor * growth / growth[-1], 2)
    prev = np.concatenate([[close[0] / (1 + rets[0])], close[:-1]])
    open_ = np.round(prev * (1 + rng.normal(0, 0.003, len(dates))), 2)
    high = np.round(np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, len(dates)))), 2)
    low = np.round(np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, len(dates)))), 2)
    if base_volume is None:
        volume = np.zeros(len(dates))
    else:
        volume = np.round(base_volume * np.exp(rng.normal(0, 0.35, len(dates))) * (1 + 8 * np.abs(rets)))
    return Bars(dates=dates, open=open_, high=high, low=low, close=close, volume=volume)


def _concat(a: Bars, b: Bars) -> Bars:
    return Bars(dates=a.dates + b.dates, open=np.concatenate([a.open, b.open]),
                high=np.concatenate([a.high, b.high]), low=np.concatenate([a.low, b.low]),
                close=np.concatenate([a.close, b.close]), volume=np.concatenate([a.volume, b.volume]))


def _publish_dates(first: str, last_exclusive: str) -> list[str]:
    """Results publication dates: quarter end + 45 days (+60 for the March year-end quarter)."""
    out = []
    for year in range(int(first[:4]) - 1, int(last_exclusive[:4]) + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            pub = date(year, month, day) + timedelta(days=60 if month == 3 else 45)
            if first <= pub.isoformat() < last_exclusive:
                out.append(pub.isoformat())
    return sorted(out)


def _close_on(b: Bars, d: str) -> float:
    idx = max(i for i, x in enumerate(b.dates) if x <= d)
    return float(b.close[idx])


def _snapshots(sym: str, final: Fundamentals, bars: Bars, q: float, seed: int,
               publish: list[str]) -> list[Fundamentals]:
    """Older point-in-time snapshots consistent with the final one (which stays untouched)."""
    r = rng_for(seed, f"HIST:FUND:{sym}")
    k_max = len(publish)
    # Quarterly EPS path: the final 12 quarters, extended back with the 3-year growth rate.
    growth = (final.eps_cagr_3y or 8.0) / 100
    if final.quarterly_eps:
        eps = list(final.quarterly_eps)
    else:  # TECHM-style gap: build a path for pricing but keep the gap visible in every snapshot
        ttm = _close_on(bars, final.as_of) / (final.pe or 20)
        eps = [ttm / 4] * 12
    for _ in range(k_max + 17):
        eps.insert(0, eps[3] / ((1 + growth) * (1 + r.normal(0, 0.05))))
    eps_arr = np.maximum(np.array(eps), 0.01)

    out: list[Fundamentals] = []
    for k, pub in enumerate(reversed(publish), start=1):  # k quarters before the final snapshot
        e = eps_arr[: len(eps_arr) - k]
        fy, fy_prev, fy_3 = e[-5:-1].sum(), e[-9:-5].sum(), e[-17:-13].sum()
        eps_growth = (fy / fy_prev - 1) * 100
        cagr = ((fy / fy_3) ** (1 / 3) - 1) * 100
        close = _close_on(bars, pub)
        pe = close / e[-4:].sum()
        drift = lambda v, s=0.03: None if v is None else v * (1 + r.normal(0, s))  # noqa: E731
        roe = drift(final.roe)
        last12 = e[-12:]
        out.append(replace(
            final,
            as_of=pub,
            market_cap_cr=None if final.market_cap_cr is None else round(final.market_cap_cr * close / _close_on(bars, final.as_of), 0),
            revenue_growth_yoy=round(0.6 * eps_growth + 4 + r.normal(0, 3), 2),
            profit_growth_yoy=round(eps_growth + r.normal(0, 1.5), 2),
            eps_growth_yoy=round(eps_growth, 2),
            eps_cagr_3y=round(cagr, 2),
            roe=None if roe is None else round(roe, 2),
            roce=None if final.roce is None else round(drift(final.roce), 2),
            operating_margin=None if final.operating_margin is None else round(drift(final.operating_margin), 2),
            net_margin=None if final.net_margin is None else round(drift(final.net_margin), 2),
            cfo_to_pat=None if final.cfo_to_pat is None else round(drift(final.cfo_to_pat, 0.08), 3),
            debt_to_equity=None if final.debt_to_equity is None else round(drift(final.debt_to_equity, 0.08), 3),
            interest_coverage=None if final.interest_coverage is None else round(drift(final.interest_coverage, 0.08), 2),
            pe=round(pe, 2),
            pb=None if roe is None else round(pe * roe / 100, 2),
            peg=round(pe / cagr, 3) if cagr != 0 else None,
            pe_median_5y=None if final.pe_median_5y is None else round(drift(final.pe_median_5y, 0.05), 2),
            positive_eps_quarters_8=None if final.positive_eps_quarters_8 is None
            else int(sum(last12[i] > last12[i - 4] for i in range(4, 12))),
            quarterly_eps=None if final.quarterly_eps is None else [round(float(x), 3) for x in last12],
        ))
    return sorted(out, key=lambda f: f.as_of) + [final]


def generate_history(as_of: str = "2026-10-05", history_bars: int = 1060, base_bars: int = 300,
                     seed: int = DEFAULT_SEED) -> MarketHistory:
    if history_bars < base_bars:
        raise ValueError("history_bars must be >= base_bars")
    base = generate_market(as_of, n_bars=base_bars, seed=seed)
    n_old = history_bars - base_bars
    first_base = base.nifty.dates[0]
    old_dates = trading_days_back((date.fromisoformat(first_base) - timedelta(days=1)).isoformat(), n_old) if n_old else []

    mu = np.concatenate([np.full(round(n_old * share), drift) for share, drift in _REGIMES])
    mu = np.resize(mu, n_old) if n_old else mu
    market_old = rng_for(seed, "HIST:MARKET").normal(mu, 0.0085, n_old)
    sector_old = {
        s: rng_for(seed, f"HIST:SECTOR:{s}").normal(p[0] / 100 / 252 - BASE_MU, p[1] / 100 / math.sqrt(252) * 0.5, n_old)
        for s, p in _SECTOR_PROFILE.items()
    }

    publish = _publish_dates(old_dates[0] if old_dates else first_base, as_of)
    bars: dict[str, Bars] = {}
    fundamentals: dict[str, list[Fundamentals]] = {}
    events = {}
    for s in base.stocks:
        sym = s.security.symbol
        beta, idio, q, alpha = _stock_params(seed, sym)
        r = rng_for(seed, f"HIST:STOCK:{sym}")
        shocks = np.where(r.random(n_old) < 0.004, r.normal(0, 0.06, n_old), 0.0)
        rets = beta * market_old + sector_old[s.security.sector] + alpha + r.normal(0, idio, n_old) + shocks
        full = _concat(_old_bars(old_dates, rets, float(s.bars.open[0]), r, float(np.median(s.bars.volume))), s.bars) \
            if n_old else s.bars
        bars[sym] = full
        fundamentals[sym] = _snapshots(sym, s.fundamentals, full, q, seed, publish) if s.fundamentals else []
        events[sym] = s.events

    ir = rng_for(seed, "HIST:INDICES")
    def extend(b: Bars, rets: np.ndarray) -> Bars:
        return _concat(_old_bars(old_dates, rets, float(b.open[0]), ir, None), b) if n_old else b

    nifty = extend(base.nifty, market_old)
    bank = extend(base.bank_nifty, 1.05 * market_old + sector_old["Banking"])
    if n_old:
        rv = np.array([np.std(market_old[max(0, i - 19): i + 1]) * math.sqrt(252) * 100 if i >= 19 else 14.0
                       for i in range(n_old)])
        vc = np.round(np.maximum(9.0, 4 + 0.95 * rv + ir.normal(0, 0.3, n_old)), 2)
        vix = _concat(Bars(dates=old_dates, open=vc.copy(), high=np.round(vc * 1.03, 2), low=np.round(vc * 0.97, 2),
                           close=vc, volume=np.zeros(n_old)), base.india_vix)
    else:
        vix = base.india_vix

    return MarketHistory(as_of=as_of, provenance="MOCK", securities=[s.security for s in base.stocks],
                         bars=bars, fundamentals=fundamentals, events=events,
                         nifty=nifty, bank_nifty=bank, india_vix=vix)
