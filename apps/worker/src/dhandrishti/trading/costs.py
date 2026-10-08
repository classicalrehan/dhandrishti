"""Zerodha equity-delivery charges (https://zerodha.com/charges/, checked 2026-10-06).

Every number lives in DELIVERY_CHARGES so a fee change is a one-line edit:
  Brokerage            ₹0
  STT                  0.1% of turnover, buy and sell
  NSE transaction      0.00307% of turnover
  SEBI                 ₹10 per crore of turnover
  Stamp duty           0.015% of turnover, buy side only
  GST                  18% on (brokerage + SEBI + transaction charges)
  DP charge            ₹15.34 per scrip per sell day, GST included, regardless of quantity
"""

from dataclasses import dataclass

DELIVERY_CHARGES = {
    "brokerage": 0.0,
    "stt": 0.001,
    "nse_txn": 0.0000307,
    "sebi": 10 / 1e7,
    "stamp_buy": 0.00015,
    "gst": 0.18,
    "dp_per_scrip_sell": 15.34,
}


@dataclass(frozen=True)
class Charges:
    stt: float
    transaction: float
    sebi: float
    stamp: float
    gst: float
    dp: float

    @property
    def total(self) -> float:
        return self.stt + self.transaction + self.sebi + self.stamp + self.gst + self.dp


def delivery_charges(side: str, value: float, c: dict = DELIVERY_CHARGES) -> Charges:
    """Charges for one delivery order of `value` rupees on `side` ("BUY" or "SELL")."""
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    txn = value * c["nse_txn"]
    sebi = value * c["sebi"]
    return Charges(
        stt=round(value * c["stt"], 2),
        transaction=round(txn, 2),
        sebi=round(sebi, 2),
        stamp=round(value * c["stamp_buy"], 2) if side == "BUY" else 0.0,
        gst=round((c["brokerage"] + sebi + txn) * c["gst"], 2),
        dp=c["dp_per_scrip_sell"] if side == "SELL" else 0.0,
    )
