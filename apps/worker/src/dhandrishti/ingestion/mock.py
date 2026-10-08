"""Deterministic MOCK market data generator.

Everything produced here is synthetic. The output always carries
provenance "MOCK" and must never be shown as live market information.

Determinism: every random stream is a numpy PCG64 generator seeded from
crc32("<seed>:<stream name>"), so adding a symbol does not perturb the others.
Golden fixtures store the generated *inputs*, so engine tests do not depend on
numpy's RNG stream staying stable across versions.
"""

import math
import zlib
from datetime import date, timedelta

import numpy as np

from ..calendar import trading_days_back
from ..models import Bars, Event, Fundamentals, MarketInput, Security, StockInput
from .universe import MOCK_UNIVERSE

DEFAULT_SEED = 20261005

# sector: (annual drift %, annual sector vol %, roe, op margin, pe, d/e, growth %, div yield %)
_SECTOR_PROFILE: dict[str, tuple[float, float, float, float | None, float, float | None, float, float]] = {
    "Banking": (16, 14, 15, None, 17, None, 16, 1.0),
    "Financial Services": (14, 16, 16, None, 28, None, 18, 0.5),
    "IT": (8, 15, 26, 22, 26, 0.1, 9, 2.5),
    "Energy": (10, 15, 12, 15, 13, 0.6, 7, 2.2),
    "Auto": (18, 16, 18, 13, 26, 0.3, 14, 1.0),
    "FMCG": (6, 10, 30, 21, 48, 0.1, 9, 1.8),
    "Pharma": (12, 13, 17, 24, 32, 0.15, 13, 0.8),
    "Metal": (-4, 22, 13, 16, 12, 0.8, 3, 2.5),
    "Telecom": (20, 14, 18, 50, 55, 1.6, 25, 0.4),
    "Infra": (14, 15, 15, 12, 30, 0.9, 15, 0.8),
    "Cement": (9, 14, 12, 18, 35, 0.4, 10, 0.6),
    "Power": (11, 13, 13, 30, 17, 1.4, 9, 2.8),
    "Consumer Durables": (3, 13, 25, 16, 65, 0.1, 12, 0.6),
    "Realty": (-6, 26, 9, 30, 45, 0.5, 15, 0.3),
}


def rng_for(seed: int, stream: str) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(zlib.crc32(f"{seed}:{stream}".encode())))


def _bars_from_returns(dates: list[str], start: float, rets: np.ndarray, rng: np.random.Generator,
                       base_shares: float | None, gaps: np.ndarray | None = None) -> Bars:
    n = len(dates)
    close = np.round(start * np.cumprod(1 + rets), 2)
    prev = np.concatenate([[start], close[:-1]])
    gap = rng.normal(0, 0.003, n)
    if gaps is not None:
        gap = np.where(gaps != 0, gaps * 0.8, gap)
    open_ = np.round(prev * (1 + gap), 2)
    wick_hi = np.abs(rng.normal(0, 0.006, n))
    wick_lo = np.abs(rng.normal(0, 0.006, n))
    high = np.round(np.maximum(open_, close) * (1 + wick_hi), 2)
    low = np.round(np.minimum(open_, close) * (1 - wick_lo), 2)
    if base_shares is None:
        volume = np.zeros(n)
    else:
        noise = np.exp(rng.normal(0, 0.35, n))
        volume = np.round(base_shares * noise * (1 + 8 * np.abs(rets)))
    return Bars(dates=dates, open=open_, high=high, low=low, close=close, volume=volume)


def _fundamentals(sym: str, sector: str, fin: bool, close: float, q: float,
                  rng: np.random.Generator, as_of: str) -> Fundamentals:
    _, _, roe_m, opm_m, pe_m, de_m, g_m, dy_m = _SECTOR_PROFILE[sector]
    growth = g_m + 6 * q + rng.normal(0, 6)  # % per year
    shape = np.array([(1 + growth / 100) ** (t / 4) for t in range(17)]) * (1 + rng.normal(0, 0.06, 17))
    shape = np.maximum(shape, 0.05)
    target_pe = pe_m * math.exp(0.15 * q + rng.normal(0, 0.25))
    k = close / (target_pe * shape[-4:].sum())
    eps = shape * k
    fy, fy_prev, fy_3 = eps[-5:-1].sum(), eps[-9:-5].sum(), eps[-17:-13].sum()
    eps_growth = (fy / fy_prev - 1) * 100
    cagr = ((fy / fy_3) ** (1 / 3) - 1) * 100
    pe = close / eps[-4:].sum()
    roe = float(np.clip(roe_m + 4 * q + rng.normal(0, 2.5), 2, 45))
    opm = None if opm_m is None else float(opm_m + 3 * q + rng.normal(0, 3))
    npm = (opm * 0.55 if opm is not None else 18 + 3 * q) + rng.normal(0, 1.5)
    de = None if de_m is None else float(de_m * math.exp(-0.2 * q + rng.normal(0, 0.4)))
    mcap = float(math.exp(rng.normal(math.log(150_000), 0.9)))
    last8 = eps[-12:]
    pledge = float(rng.uniform(5, 35)) if rng.random() < 0.12 else 0.0

    f = Fundamentals(
        as_of=as_of,
        market_cap_cr=round(mcap, 0),
        revenue_growth_yoy=round(0.6 * eps_growth + 4 + rng.normal(0, 3), 2),
        profit_growth_yoy=round(eps_growth + rng.normal(0, 1.5), 2),
        eps_growth_yoy=round(eps_growth, 2),
        eps_cagr_3y=round(cagr, 2),
        roe=round(roe, 2),
        roce=None if fin else round(roe + rng.normal(2, 3), 2),
        operating_margin=None if opm is None else round(opm, 2),
        net_margin=round(float(npm), 2),
        free_cash_flow_cr=None if fin else round(mcap * rng.normal(0.02 + 0.01 * q, 0.02), 0),
        cfo_to_pat=round(float(np.clip(0.9 + 0.12 * q + rng.normal(0, 0.15), 0.2, 1.6)), 3),
        debt_to_equity=None if de is None else round(de, 3),
        interest_coverage=None if de is None else round(
            float(np.clip(12 / (de + 0.1) * math.exp(rng.normal(0, 0.3)), 0.8, 80)), 2),
        pe=round(pe, 2),
        pb=round(pe * roe / 100, 2),
        peg=round(pe / cagr, 3) if cagr != 0 else None,
        dividend_yield=round(float(np.clip(dy_m * math.exp(rng.normal(0, 0.4)), 0, 6)), 2),
        promoter_holding=round(float(rng.uniform(30, 75)), 2),
        promoter_pledge=round(pledge, 2),
        institutional_holding=round(float(rng.uniform(15, 55)), 2),
        pe_median_5y=round(pe * math.exp(rng.normal(-0.05, 0.18)), 2),
        positive_eps_quarters_8=int(sum(last8[i] > last8[i - 4] for i in range(4, 12))) if len(last8) == 12 else None,
        quarterly_eps=[round(float(x), 3) for x in eps[-12:]],
    )
    # Deliberate gaps so the "Data unavailable" path is always exercised.
    if sym == "GODREJPROP":
        f.cfo_to_pat = None
        f.pe_median_5y = None
        f.interest_coverage = None
    if sym == "TECHM":
        f.quarterly_eps = None
        f.positive_eps_quarters_8 = None
    return f


def generate_market(as_of: str = "2026-10-05", n_bars: int = 300, seed: int = DEFAULT_SEED,
                    universe: list[Security] | None = None) -> MarketInput:
    universe = universe or MOCK_UNIVERSE
    dates = trading_days_back(as_of, n_bars)
    n = len(dates)

    mr = rng_for(seed, "MARKET")
    base_mu = 0.00045  # ≈12% a year
    mu = np.full(n, base_mu)
    mu[-63:] += 0.0002  # mildly stronger recent quarter
    market = mr.normal(mu, 0.0085)

    sector_ret: dict[str, np.ndarray] = {}
    for sector, prof in _SECTOR_PROFILE.items():
        sr = rng_for(seed, f"SECTOR:{sector}")
        sector_ret[sector] = sr.normal(prof[0] / 100 / 252 - base_mu, prof[1] / 100 / math.sqrt(252) * 0.5, n)

    stocks: list[StockInput] = []
    for sec in universe:
        r = rng_for(seed, f"STOCK:{sec.symbol}")
        beta = r.uniform(0.75, 1.25)
        idio = r.uniform(0.008, 0.02)
        q = float(r.normal(0, 1))
        alpha = 0.0002 * q + r.normal(0, 0.0003) - 0.0002
        shocks = np.where(r.random(n) < 0.004, r.normal(0, 0.06, n), 0.0)
        rets = beta * market + sector_ret[sec.sector] + alpha + r.normal(0, idio, n) + shocks
        start = float(r.uniform(150, 4000))
        value_cr = float(math.exp(r.normal(math.log(400), 0.8)))
        bars = _bars_from_returns(dates, start, rets, r, value_cr * 1e7 / start, gaps=shocks)
        fund = _fundamentals(sec.symbol, sec.sector, sec.is_financial, float(bars.close[-1]), q, r, as_of)
        d0 = date.fromisoformat(as_of)
        events = [Event(date=(d0 + timedelta(days=int(r.integers(3, 46)))).isoformat(),
                        type="EARNINGS", title="Quarterly results", symbol=sec.symbol)]
        if r.random() < 1 / 6:
            events.append(Event(date=(d0 + timedelta(days=int(r.integers(2, 30)))).isoformat(),
                                type="DIVIDEND", title="Interim dividend (record date)", symbol=sec.symbol))
        stocks.append(StockInput(security=sec, bars=bars, fundamentals=fund, events=events))

    ir = rng_for(seed, "INDICES")
    nifty = _bars_from_returns(dates, 23_500.0, market, ir, None)
    bank = _bars_from_returns(dates, 51_000.0, 1.05 * market + sector_ret["Banking"], ir, None)
    rv = np.array([np.std(market[max(0, i - 19): i + 1]) * math.sqrt(252) * 100 if i >= 19 else 14.0
                   for i in range(n)])
    vix_close = np.round(np.maximum(9.0, 4 + 0.95 * rv + ir.normal(0, 0.3, n)), 2)
    vix = Bars(dates=dates, open=vix_close.copy(), high=np.round(vix_close * 1.03, 2),
               low=np.round(vix_close * 0.97, 2), close=vix_close, volume=np.zeros(n))

    return MarketInput(as_of=as_of, provenance="MOCK", stocks=stocks,
                       nifty=nifty, bank_nifty=bank, india_vix=vix)
