"""The real (Kite) universe: NIFTY 200 from NSE's official list, plus held stocks."""

import numpy as np
import pytest

from dhandrishti.ingestion.nse_universe import NIFTY200, SECTORS, load_list, real_universe
from dhandrishti.ingestion.universe import MOCK_UNIVERSE
from dhandrishti.models import Bars, MarketHistory, Security, is_stale


def test_nifty200_list_is_complete_and_unique():
    u = real_universe()
    assert len(u) == 200 == len({s.symbol for s in u})
    assert all(s.indices == ("NIFTY 200",) and s.industry in SECTORS for s in u)


def test_sectors_banks_and_financial_flag():
    d = {s.symbol: s for s in real_universe()}
    assert d["HDFCBANK"].sector == "Banking" and d["BANKBARODA"].sector == "Banking"
    assert d["BAJFINANCE"].sector == "Financial Services" and d["BAJFINANCE"].is_financial
    assert d["SBILIFE"].is_financial and d["SBILIFE"].sector == "Financial Services"
    assert d["INFY"].sector == "IT" and not d["INFY"].is_financial
    assert d["HDFCBANK"].name == "HDFC Bank"  # " Ltd." suffix dropped


def test_the_old_mock_universe_is_inside_the_nifty200():
    assert {s.symbol for s in MOCK_UNIVERSE} <= {s.symbol for s in real_universe()}


def test_held_stocks_outside_the_index_are_added_but_etfs_are_not():
    u = real_universe(["MANAPPURAM", "HDFCGOLD", "NOT_A_STOCK", "ITC"])
    syms = [s.symbol for s in u]
    assert len(u) == 201 and syms[-1] == "MANAPPURAM" and "HDFCGOLD" not in syms
    assert u[-1].indices == () and u[-1].sector == "Financial Services"


def test_unknown_nse_industry_fails_loudly(tmp_path):
    p = tmp_path / "list.csv"
    p.write_text("Company Name,Industry,Symbol,Series,ISIN Code\nX Ltd.,Space Mining,XSPACE,EQ,INE000000000\n")
    with pytest.raises(ValueError, match="Space Mining"):
        load_list(p)


def test_stale_prices_are_not_scored():
    assert not is_stale("2026-10-01", "2026-10-08") and is_stale("2026-09-20", "2026-10-08")
    dates = ["2026-09-01", "2026-09-02"]
    b = Bars(dates=dates, open=np.ones(2), high=np.ones(2), low=np.ones(2), close=np.ones(2), volume=np.ones(2))
    h = MarketHistory(as_of="2026-10-08", securities=[Security("OLD", "Old", "IT", False)], bars={"OLD": b}, fundamentals={},
                      events={}, nifty=b, bank_nifty=b, india_vix=b, provenance="EOD")
    assert [s.security.symbol for s in h.market_at("2026-09-03").stocks] == ["OLD"]
    assert h.market_at("2026-10-08").stocks == []
