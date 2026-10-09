"""The 20-stock pilot (chosen 2026-10-08 for data-quality validation, not for returns).

Spread across size, sector and reporting pattern, including awkward cases on purpose.
"""

PILOT: dict[str, str] = {
    "HDFCBANK": "Large private bank; bank P&L format; HDFC Ltd merger (July 2023) restates comparatives",
    "BANKBARODA": "PSU bank; bank format; government-owned reporting",
    "BAJFINANCE": "Large NBFC; financial-company format",
    "SBILIFE": "Insurer; revenue and profit concepts differ from industrials",
    "INFY": "Large IT; long, clean history; consolidated vs standalone differ",
    "PERSISTENT": "Mid-cap IT",
    "ITC": "FMCG conglomerate; hotels demerger (2025) changes comparatives",
    "MARICO": "Mid/large FMCG",
    "MARUTI": "Large auto; standalone close to consolidated",
    "ASHOKLEY": "Mid-cap auto; consolidated includes a large finance subsidiary",
    "SUNPHARMA": "Large pharma; large exceptional items in some years",
    "LAURUSLABS": "Mid-cap pharma; volatile earnings",
    "RELIANCE": "Conglomerate; very large consolidated group",
    "ONGC": "PSU energy; consolidated includes listed subsidiaries",
    "TATASTEEL": "Metal; overseas operations, losses and impairments",
    "BHEL": "PSU capital goods; loss years",
    "ULTRACEMCO": "Cement; acquisitions change comparatives",
    "DLF": "Real estate; lumpy revenue recognition",
    "IDEA": "Telecom; persistent losses, negative equity",
    "NYKAA": "Recent listing (2021); short history, thin early profits",
}
