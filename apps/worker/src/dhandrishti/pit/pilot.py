"""The 20-company fundamentals pilot (data-quality validation, not return research).

Final list, 2026-10-12: the list proposed in docs/fundamentals-quality-design.md section 6, which replaces the
2026-10-08 choices SUNPHARMA, MARICO and NYKAA with ICICIBANK, WIPRO and DRREDDY. The three additions also furnish
their results to the US SEC (Form 6-K), so their figures can be checked against an official channel independent of
the NSE XBRL, as was done for INFY and HDFCBANK. Pharma and FMCG stay covered by DRREDDY/LAURUSLABS and ITC; the
recent-listing case (NYKAA) can return as a 21st company if short-history handling needs testing. All 20 are in the
scored NIFTY 200 universe. Readers exist for the Ind-AS and banking formats; SBILIFE (insurance) and possibly
BAJFINANCE (NBFC) will need their own mapping.
"""

PILOT: dict[str, str] = {
    "HDFCBANK": "Bank; HDFC Ltd merger; minority-interest tagging pattern; SEC filer",
    "ICICIBANK": "Large private bank with insurance subsidiaries; SEC filer",
    "BANKBARODA": "PSU bank; government-owned reporting",
    "BAJFINANCE": "Large NBFC; financial-company format",
    "SBILIFE": "Insurer; insurance taxonomy (reader mapping not built yet)",
    "INFY": "Large IT; buyback; SEC filer; reference company",
    "WIPRO": "Second IT company; bonus issues; SEC filer",
    "PERSISTENT": "Mid-cap IT",
    "DRREDDY": "Pharma; SEC filer",
    "LAURUSLABS": "Mid-cap pharma; volatile earnings",
    "ITC": "FMCG conglomerate; hotels demerger (2025) changes comparatives",
    "MARUTI": "Large auto; standalone close to consolidated",
    "ASHOKLEY": "Mid-cap auto; consolidated includes a large finance subsidiary",
    "RELIANCE": "Conglomerate; very large consolidated group; minority interests",
    "ONGC": "PSU energy; consolidated includes listed subsidiaries",
    "TATASTEEL": "Metal; overseas operations, losses and impairments",
    "BHEL": "PSU capital goods; weak profits",
    "ULTRACEMCO": "Cement; acquisitions change comparatives",
    "DLF": "Real estate; lumpy revenue recognition",
    "IDEA": "Telecom; persistent losses, negative equity",
}
