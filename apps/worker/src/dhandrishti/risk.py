"""Risk engine (SPEC §7). Produces explicit flags with penalty points and a level."""

from dataclasses import asdict, dataclass
from datetime import date, timedelta

from .config import Config
from .fundamentals import earnings_deteriorating
from .models import StockInput
from .technicals import Technicals


@dataclass
class RiskFlag:
    code: str
    severity: str  # ELEVATED | EXTREME | INFO
    points: float
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def risk_level(points: float, cfg: Config) -> str:
    for entry in cfg["risk_levels"]:
        if entry["max_points"] is None or points <= entry["max_points"]:
            return entry["level"]
    raise ValueError("risk_levels must end with an unbounded entry")


def assess_risk(
    stock: StockInput, t: Technicals, pe_vs_sector: float | None, as_of: str, cfg: Config
) -> list[RiskFlag]:
    rf = cfg["risk_flags"]
    pts = rf["points"]
    f = stock.fundamentals
    flags: list[RiskFlag] = []

    def tiered(code: str, value: float | None, th: dict, above: bool, fmt: str) -> None:
        if value is None:
            return
        breach = (lambda lim: value > lim) if above else (lambda lim: value < lim)
        if "extreme" in th and breach(th["extreme"]):
            flags.append(RiskFlag(code, "EXTREME", pts["extreme"], fmt.format(value)))
        elif "elevated" in th and breach(th["elevated"]):
            flags.append(RiskFlag(code, "ELEVATED", pts["elevated"], fmt.format(value)))

    tiered("EXTREME_VOLATILITY", t.volatility_60d, rf["volatility_60d"], True,
           "Annualised 60-day volatility of {:.1f}%")
    tiered("LARGE_DRAWDOWN", t.max_drawdown_1y, rf["max_drawdown_1y"], False,
           "1-year max drawdown of {:.1f}%")

    if t.avg_traded_value_cr is not None and t.avg_traded_value_cr < cfg["min_avg_traded_value_cr"]:
        flags.append(RiskFlag("LOW_LIQUIDITY", "EXTREME", pts["extreme"],
                              f"Average traded value ₹{t.avg_traded_value_cr:.1f} Cr/day"))

    if pe_vs_sector is not None and pe_vs_sector > rf["pe_vs_sector"]["extreme"]:
        msg = ("Loss-making: PE not meaningful" if pe_vs_sector == float("inf")
               else f"PE is {pe_vs_sector:.1f}x the sector median")
        flags.append(RiskFlag("EXCESSIVE_VALUATION", "ELEVATED", pts["elevated"], msg))

    if f is not None and not stock.security.is_financial:
        de, ic = f.debt_to_equity, f.interest_coverage
        th = rf["debt_to_equity"]
        if de is not None and de > th["extreme"]:
            flags.append(RiskFlag("DEBT_CONCERN", "EXTREME", pts["extreme"], f"Debt/Equity of {de:.2f}x"))
        elif de is not None and de > th["elevated"]:
            flags.append(RiskFlag("DEBT_CONCERN", "ELEVATED", pts["elevated"], f"Debt/Equity of {de:.2f}x"))
        elif ic is not None and ic < rf["interest_coverage"]["elevated"]:
            flags.append(RiskFlag("DEBT_CONCERN", "ELEVATED", pts["elevated"],
                                  f"Interest coverage of {ic:.1f}x"))

    if f is not None and earnings_deteriorating(f.quarterly_eps):
        flags.append(RiskFlag("EARNINGS_DETERIORATION", "EXTREME", pts["extreme"],
                              "EPS fell year-on-year in each of the last two quarters"))

    if f is not None:
        tiered("PROMOTER_PLEDGE", f.promoter_pledge, rf["promoter_pledge"], True,
               "{:.1f}% of promoter holding pledged")

    tiered("UNUSUAL_VOLUME", t.relative_volume, rf["relative_volume"], True,
           "Volume {:.1f}x the 20-day average")
    if t.gap_moves_60d >= rf["gap_moves_60d"]["elevated"]:
        flags.append(RiskFlag("LARGE_GAP_MOVES", "ELEVATED", pts["elevated"],
                              f"{t.gap_moves_60d} gap moves above 4% in 60 sessions"))
    tiered("OVEREXTENDED", t.dist_from_sma200, rf["dist_from_sma200"], True,
           "Price {:.1f}% above its 200 DMA")

    start = date.fromisoformat(as_of)
    end = start + timedelta(days=rf["event_window_days"])
    for ev in sorted(stock.events, key=lambda e: (e.date, e.type)):
        d = date.fromisoformat(ev.date)
        if not (start < d <= end):
            continue
        if ev.type == "EARNINGS":
            flags.append(RiskFlag("UPCOMING_EARNINGS", "INFO", 0, f"Results expected on {ev.date}"))
        elif ev.type in ("DIVIDEND", "SPLIT", "BONUS"):
            flags.append(RiskFlag("CORPORATE_ACTION", "INFO", 0, f"{ev.title} on {ev.date}"))
    return flags
