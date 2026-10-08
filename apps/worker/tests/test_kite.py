"""Kite Connect integration, tested against a fake Kite API (httpx.MockTransport)."""

import gzip
import hashlib
import os
import socket
import stat
import threading
import time
from datetime import date, timedelta

import httpx
import pytest

from dhandrishti.jobs.kite_login import wait_for_request_token
from dhandrishti.providers.kite.client import KiteClient, KiteError, KiteSessionExpired
from dhandrishti.providers.kite.provider import KiteMarketData, Unavailable, suspicious_moves
from dhandrishti.providers.kite.session import KiteSession, checksum, load_session, login_url, save_session

INSTRUMENTS_CSV = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,"
    "instrument_type,segment,exchange\n"
    "341249,1333,HDFCBANK,HDFC BANK,0,,0,0.05,1,EQ,NSE,NSE\n"
    "1270529,4963,ICICIBANK,ICICI BANK,0,,0,0.05,1,EQ,NSE,NSE\n"
    "256265,1001,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE\n"
    "260105,1016,NIFTY BANK,NIFTY BANK,0,,0,0,0,EQ,INDICES,NSE\n"
    "264969,1035,INDIA VIX,INDIA VIX,0,,0,0,0,EQ,INDICES,NSE\n"
)


def candles_between(start: str, end: str, base: float = 100.0, jump: str | None = None):
    out, d, price = [], date.fromisoformat(start), base
    while d <= date.fromisoformat(end):
        if d.weekday() < 5:
            if jump and d.isoformat() == jump:
                price *= 0.5  # e.g. an unadjusted 2:1 split
            price *= 1.001
            out.append([f"{d.isoformat()}T00:00:00+0530", price, price * 1.01, price * 0.99, price, 1000])
        d += timedelta(days=1)
    return out


class FakeKite:
    def __init__(self, expired: bool = False, rate_limit_once: bool = False, jump: dict | None = None):
        self.requests: list[httpx.Request] = []
        self.expired, self.rate_limit_once, self.jump = expired, rate_limit_once, jump or {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        path = req.url.path
        if self.expired:
            return httpx.Response(403, json={"status": "error", "message": "Incorrect `api_key` or `access_token`.",
                                             "error_type": "TokenException"})
        if path == "/session/token":
            return httpx.Response(200, json={"status": "success", "data": {
                "access_token": "acc123", "user_id": "AB1234", "login_time": "2026-10-06 09:00:00"}})
        if path == "/instruments/NSE":
            return httpx.Response(200, content=gzip.compress(INSTRUMENTS_CSV.encode()))
        if path.startswith("/instruments/historical/"):
            if self.rate_limit_once:
                self.rate_limit_once = False
                return httpx.Response(429, json={"status": "error", "message": "Too many requests",
                                                 "error_type": "NetworkException"})
            token = int(path.split("/")[3])
            start, end = req.url.params["from"][:10], req.url.params["to"][:10]
            return httpx.Response(200, json={"status": "success", "data": {
                "candles": candles_between(start, end, jump=self.jump.get(token))}})
        return httpx.Response(404, json={"status": "error", "message": "not found", "error_type": "GeneralException"})


def client(fake: FakeKite, **kw) -> KiteClient:
    return KiteClient("key", "acc123", transport=httpx.MockTransport(fake), sleep=lambda s: None, **kw)


# ------------------------------------------------------------------ session

def test_checksum_and_login_url():
    assert checksum("key", "tok", "sec") == hashlib.sha256(b"keytoksec").hexdigest()
    assert login_url("key") == "https://kite.zerodha.com/connect/login?v=3&api_key=key"


def test_token_exchange_posts_checksum_and_never_sends_the_secret_raw():
    fake = FakeKite()
    c = KiteClient("key", transport=httpx.MockTransport(fake))
    session = c.exchange_request_token("tok", "sec")
    assert session == KiteSession("key", "acc123", "AB1234", "2026-10-06 09:00:00")
    body = fake.requests[0].content.decode()
    assert f"checksum={checksum('key', 'tok', 'sec')}" in body and "sec&" not in body and "=sec" not in body
    assert fake.requests[0].headers["X-Kite-Version"] == "3"


def test_session_file_is_private(tmp_path):
    path = save_session(KiteSession("key", "acc123", "AB1234", None), tmp_path / "s.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert load_session(path).access_token == "acc123"
    with pytest.raises(FileNotFoundError, match="kite:login"):
        load_session(tmp_path / "missing.json")


# ------------------------------------------------------------------ client

def test_requests_are_signed():
    fake = FakeKite()
    client(fake).instruments()
    assert fake.requests[0].headers["Authorization"] == "token key:acc123"


def test_instruments_parse_gzipped_csv():
    ins = client(FakeKite()).instruments()
    assert {i.tradingsymbol for i in ins if i.segment == "INDICES"} == {"NIFTY 50", "NIFTY BANK", "INDIA VIX"}


def test_daily_candles_chunk_dedupe_and_throttle():
    fake = FakeKite()
    sleeps: list[float] = []
    t = [0.0]
    c = KiteClient("key", "acc123", transport=httpx.MockTransport(fake), sleep=lambda s: sleeps.append(s),
                   clock=lambda: t[0])
    candles = c.daily_candles(341249, "2020-01-01", "2026-10-05")
    hist = [r for r in fake.requests if "historical" in r.url.path]
    assert len(hist) == 2  # > 1500 days -> two chunks
    assert hist[0].url.params["from"] == "2020-01-01 00:00:00"
    assert [x.date for x in candles] == sorted({x.date for x in candles})
    assert candles[0].date >= "2020-01-01" and candles[-1].date <= "2026-10-05"
    assert sleeps and all(s <= 1 / 3 + 1e-9 for s in sleeps)  # spaced for 3 req/s


def test_rate_limited_request_is_retried():
    fake = FakeKite(rate_limit_once=True)
    assert len(client(fake).daily_candles(341249, "2026-09-01", "2026-09-30")) > 15


def test_expired_session_gives_a_clear_instruction():
    with pytest.raises(KiteSessionExpired, match="kite:login"):
        client(FakeKite(expired=True)).instruments()


def test_other_errors_raise_kite_error():
    with pytest.raises(KiteError, match="404") as exc:
        client(FakeKite())._raise_for(httpx.Response(404, json={"message": "nope", "error_type": "GeneralException"}))
    assert not isinstance(exc.value, KiteSessionExpired)


# ------------------------------------------------------------------ provider

def test_provider_maps_universe_and_reports_missing_symbols():
    p = KiteMarketData(client(FakeKite()))
    secs = p.list_securities()
    assert {s.symbol for s in secs} == {"HDFCBANK", "ICICIBANK"}
    assert any("Not found in Kite" in w and "RELIANCE" in w for w in p.warnings)
    bars = p.daily_bars(["HDFCBANK", "RELIANCE"], "2026-09-01", "2026-10-05")
    assert list(bars) == ["HDFCBANK"]
    idx = p.index_bars(["NIFTY 50", "NIFTY BANK", "INDIA VIX"], "2026-09-01", "2026-10-05")
    assert set(idx) == {"NIFTY 50", "NIFTY BANK", "INDIA VIX"}
    assert p.provenance == "EOD"


def test_unadjusted_split_is_flagged():
    p = KiteMarketData(client(FakeKite(jump={341249: "2026-09-15"})))
    p.daily_bars(["HDFCBANK"], "2026-09-01", "2026-10-05")
    assert any("HDFCBANK 2026-09-15" in w and "split" in w for w in p.warnings)


def test_unavailable_provider_never_invents_data():
    u = Unavailable("none")
    assert u.fundamentals(["HDFCBANK"], "2026-10-05") == {} and u.fundamentals_history(["X"], "a", "b") == {}
    assert u.events(["X"], "a", "b") == [] and u.news(["X"], "a") == []


# ------------------------------------------------------------------ login callback

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _redirect(port: int, query: str) -> None:
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{port}/kite/callback?{query}", timeout=2)
            return
        except httpx.ConnectError:
            time.sleep(0.05)


def test_callback_server_captures_the_request_token():
    port = _free_port()
    threading.Thread(target=_redirect, args=(port, "request_token=rt1&status=success&state=s1"), daemon=True).start()
    assert wait_for_request_token(port, "s1", timeout=10) == "rt1"


def test_callback_server_rejects_a_forged_state():
    port = _free_port()
    threading.Thread(target=_redirect, args=(port, "request_token=evil&status=success&state=nope"), daemon=True).start()
    with pytest.raises(RuntimeError, match="state mismatch"):
        wait_for_request_token(port, "s1", timeout=10)


def test_login_remembers_the_api_key_but_never_the_secret(tmp_path, monkeypatch):
    import dhandrishti.jobs.kite_login as kl
    path = save_session(KiteSession("ytkey123", "acc", "AB1234", None), tmp_path / "s.json")
    monkeypatch.setattr(kl, "load_session", lambda: load_session(path))
    assert kl.remembered_api_key() == "ytkey123"
    assert "secret" not in path.read_text()


def test_daily_job_reports_an_expired_session_without_a_traceback(monkeypatch):
    import subprocess
    import sys
    env = dict(os.environ, DD_KITE_SESSION_FILE="/nonexistent/kite_session.json",
               DD_DATABASE_URL="postgresql://invalid@127.0.0.1:1/x")
    r = subprocess.run([sys.executable, "-m", "dhandrishti.jobs.ingest", "--source", "kite"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 1
    assert "kite:login" in r.stderr and "Traceback" not in r.stderr


def test_impossible_candles_are_dropped():
    from dhandrishti.providers.kite.client import Candle
    from dhandrishti.providers.kite.provider import _bars
    b = _bars([Candle("2018-01-01", 0, 0, 0, 0, 100), Candle("2020-10-12", 107.45, 110, 85, 86, 10),
               Candle("2020-10-13", 86, 80, 90, 90.7, 10)])  # last: high below low
    assert b.dates == ["2020-10-12"]
