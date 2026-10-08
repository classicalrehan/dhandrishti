"""Minimal, read-only Kite Connect REST client: market data and portfolio reads. No order endpoints.

Docs: https://kite.trade/docs/connect/v3/ . Historical candles are rate-limited to
3 requests/second, so calls are spaced accordingly.
"""

import csv
import gzip
import io
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from .session import KiteSession, checksum

API_ROOT = "https://api.kite.trade"
HISTORICAL_MIN_INTERVAL = 1 / 3  # seconds between historical requests (3 req/s)
DAY_CHUNK = 1500  # calendar days per historical request (kept well under Kite's per-request limits)


class KiteError(RuntimeError):
    def __init__(self, message: str, error_type: str | None = None, status: int | None = None):
        super().__init__(message)
        self.error_type, self.status = error_type, status


class KiteSessionExpired(KiteError):
    """403 TokenException: the access token expired (6 AM daily) or was invalidated."""


@dataclass(frozen=True)
class Instrument:
    instrument_token: int
    tradingsymbol: str
    name: str
    segment: str
    exchange: str
    instrument_type: str


@dataclass(frozen=True)
class Candle:
    date: str  # YYYY-MM-DD (IST trading date)
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class PortfolioItem:
    """One row of /portfolio/holdings (kind HOLDING) or /portfolio/positions net (kind POSITION)."""
    kind: str
    tradingsymbol: str
    exchange: str
    product: str
    isin: str | None
    qty: int  # holdings: settled + T1 (bought, not yet in demat); positions: net quantity
    t1_qty: int
    avg_price: float
    last_price: float
    close_price: float | None  # previous session close
    pnl: float


class KiteClient:
    def __init__(self, api_key: str, access_token: str | None = None,
                 transport: httpx.BaseTransport | None = None, sleep=time.sleep, clock=time.monotonic):
        headers = {"X-Kite-Version": "3"}
        if access_token:
            headers["Authorization"] = f"token {api_key}:{access_token}"
        self.api_key = api_key
        self._http = httpx.Client(base_url=API_ROOT, headers=headers, timeout=30.0, transport=transport)
        self._sleep, self._clock = sleep, clock
        self._last_hist = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_session(cls, session: KiteSession, **kw) -> "KiteClient":
        return cls(session.api_key, session.access_token, **kw)

    def close(self) -> None:
        self._http.close()

    # ---------------------------------------------------------------- errors

    @staticmethod
    def _raise_for(res: httpx.Response) -> None:
        if res.status_code < 400:
            return
        try:
            body = res.json()
            message, etype = body.get("message", res.text), body.get("error_type")
        except ValueError:
            message, etype = res.text[:200], None
        if res.status_code == 403 or etype == "TokenException":
            raise KiteSessionExpired(
                "Kite session expired or invalid (tokens expire at 6 AM daily). Run `pnpm kite:login`.",
                etype, res.status_code)
        raise KiteError(f"Kite API error {res.status_code} ({etype}): {message}", etype, res.status_code)

    # ---------------------------------------------------------------- endpoints

    def exchange_request_token(self, request_token: str, api_secret: str) -> KiteSession:
        res = self._http.post("/session/token", data={
            "api_key": self.api_key,
            "request_token": request_token,
            "checksum": checksum(self.api_key, request_token, api_secret),
        })
        self._raise_for(res)
        data = res.json()["data"]
        return KiteSession(api_key=self.api_key, access_token=data["access_token"],
                           user_id=data.get("user_id"), login_time=data.get("login_time"))

    def instruments(self, exchange: str = "NSE") -> list[Instrument]:
        """Instrument master for an exchange (gzipped CSV). Fetch once per day."""
        res = self._http.get(f"/instruments/{exchange}")
        self._raise_for(res)
        raw = res.content
        if raw[:2] == b"\x1f\x8b":  # gzip body without a Content-Encoding header
            raw = gzip.decompress(raw)
        rows = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        return [
            Instrument(int(r["instrument_token"]), r["tradingsymbol"], r.get("name", ""), r.get("segment", ""),
                       r.get("exchange", ""), r.get("instrument_type", ""))
            for r in rows
        ]

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_hist + HISTORICAL_MIN_INTERVAL - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last_hist = self._clock()

    def daily_candles(self, instrument_token: int, start: str, end: str) -> list[Candle]:
        """Day candles for [start, end] (inclusive), chunked and rate-limited."""
        out: dict[str, Candle] = {}
        cur, stop = date.fromisoformat(start), date.fromisoformat(end)
        while cur <= stop:
            chunk_end = min(stop, cur + timedelta(days=DAY_CHUNK))
            for attempt in range(3):
                self._throttle()
                res = self._http.get(f"/instruments/historical/{instrument_token}/day", params={
                    "from": f"{cur.isoformat()} 00:00:00", "to": f"{chunk_end.isoformat()} 23:59:59"})
                if res.status_code == 429 and attempt < 2:  # rate limited: back off and retry
                    self._sleep(1.0 * (attempt + 1))
                    continue
                self._raise_for(res)
                break
            data = res.json().get("data", {})
            candles = data.get("candles", data) if isinstance(data, dict) else data
            for c in candles:
                d = str(c[0])[:10]  # "2024-01-02T00:00:00+0530" -> trading date
                out[d] = Candle(d, float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5] or 0))
            cur = chunk_end + timedelta(days=1)
        return [out[d] for d in sorted(out)]

    # ---------------------------------------------------------------- portfolio (read-only)

    def _get_data(self, path: str):
        res = self._http.get(path)
        self._raise_for(res)
        return res.json().get("data")

    def holdings(self) -> list[PortfolioItem]:
        """Long-term (demat) holdings: https://kite.trade/docs/connect/v3/portfolio/#holdings"""
        out = []
        for h in self._get_data("/portfolio/holdings") or []:
            t1 = int(h.get("t1_quantity") or 0)
            out.append(PortfolioItem(
                "HOLDING", h["tradingsymbol"], h.get("exchange", ""), h.get("product") or "CNC", h.get("isin"),
                int(h.get("quantity") or 0) + t1, t1, float(h.get("average_price") or 0),
                float(h.get("last_price") or 0), _opt_float(h.get("close_price")), float(h.get("pnl") or 0)))
        return out

    def positions(self) -> list[PortfolioItem]:
        """Open net positions (intraday, F&O, today's delivery buys); zero-quantity rows are dropped."""
        data = self._get_data("/portfolio/positions") or {}
        return [
            PortfolioItem("POSITION", p["tradingsymbol"], p.get("exchange", ""), p.get("product") or "", None,
                          int(p.get("quantity") or 0), 0, float(p.get("average_price") or 0),
                          float(p.get("last_price") or 0), _opt_float(p.get("close_price")), float(p.get("pnl") or 0))
            for p in data.get("net", []) if int(p.get("quantity") or 0) != 0
        ]


def _opt_float(v) -> float | None:
    return float(v) if v not in (None, "", 0) else None
