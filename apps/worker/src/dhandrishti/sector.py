"""Sector engine (SPEC §6)."""

from collections import defaultdict
from dataclasses import asdict, dataclass

from .config import Config
from .models import StockInput
from .stats import median, weighted_normalized
from .technicals import Technicals


@dataclass
class SectorStrength:
    sector: str
    score: int
    normalized: float
    rank: int
    momentum: str
    breadth: str
    median_rs_nifty_3m: float | None
    median_rs_nifty_1m: float | None
    pct_above_sma50: float | None
    median_profit_growth: float | None
    median_ret_1d: float | None
    median_ret_1m: float | None
    members: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SectorContext:
    median_pe: float | None
    median_pb: float | None
    median_operating_margin: float | None


def sector_contexts(stocks: list[StockInput], fundamentals: dict | None = None) -> dict[str, SectorContext]:
    """Sector medians. `fundamentals` (symbol -> Fundamentals) overrides each stock's own, e.g. repriced."""
    groups: dict[str, list[StockInput]] = defaultdict(list)
    for s in stocks:
        groups[s.security.sector].append(s)
    out = {}
    for sector, members in groups.items():
        fs = [f for m in members
              if (f := (fundamentals.get(m.security.symbol) if fundamentals is not None else m.fundamentals)) is not None]
        out[sector] = SectorContext(
            median_pe=median(f.pe for f in fs if f.pe is not None and f.pe > 0),
            median_pb=median(f.pb for f in fs if f.pb is not None and f.pb > 0),
            median_operating_margin=median(f.operating_margin for f in fs),
        )
    return out


def sector_strengths(
    stocks: list[StockInput], tech: dict[str, Technicals], cfg: Config
) -> dict[str, SectorStrength]:
    groups: dict[str, list[StockInput]] = defaultdict(list)
    for s in stocks:
        groups[s.security.sector].append(s)

    rows: list[SectorStrength] = []
    for sector, members in groups.items():
        ts = [tech[m.security.symbol] for m in members]
        above = [t.close > t.sma50 for t in ts if t.sma50 is not None]
        raw = {
            "median_rs_nifty_3m": median(t.rs_nifty_3m for t in ts),
            "pct_above_sma50": (sum(above) / len(above)) if above else None,
            "median_rs_nifty_1m": median(t.rs_nifty_1m for t in ts),
            "median_profit_growth": median(
                m.fundamentals.profit_growth_yoy for m in members if m.fundamentals is not None
            ),
        }
        norm, _ = weighted_normalized(cfg["sector"]["metrics"], raw)
        norm = cfg["missing_data_neutral"] if norm is None else norm
        rs3 = raw["median_rs_nifty_3m"]
        pa = raw["pct_above_sma50"]
        rows.append(
            SectorStrength(
                sector=sector,
                score=round(norm * 100),
                normalized=norm,
                rank=0,
                momentum="Strong" if rs3 is not None and rs3 >= 3
                else "Weak" if rs3 is not None and rs3 <= -3 else "Neutral",
                breadth="Positive" if pa is not None and pa >= 0.6
                else "Negative" if pa is not None and pa <= 0.4 else "Mixed",
                median_rs_nifty_3m=rs3,
                median_rs_nifty_1m=raw["median_rs_nifty_1m"],
                pct_above_sma50=pa,
                median_profit_growth=raw["median_profit_growth"],
                median_ret_1d=median(t.ret_1d for t in ts),
                median_ret_1m=median(t.ret_1m for t in ts),
                members=sorted(m.security.symbol for m in members),
            )
        )
    rows.sort(key=lambda r: (-r.normalized, r.sector))
    for i, r in enumerate(rows, 1):
        r.rank = i
    return {r.sector: r for r in rows}
