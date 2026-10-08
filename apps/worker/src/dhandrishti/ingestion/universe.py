"""Mock universe definition: real NSE symbols, synthetic data only.

Index memberships here are illustrative and are not an authoritative constituent list.
"""

from ..models import Security

# (symbol, name, sector, is_financial)
_UNIVERSE: list[tuple[str, str, str, bool]] = [
    ("HDFCBANK", "HDFC Bank", "Banking", True),
    ("ICICIBANK", "ICICI Bank", "Banking", True),
    ("SBIN", "State Bank of India", "Banking", True),
    ("AXISBANK", "Axis Bank", "Banking", True),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Banking", True),
    ("INDUSINDBK", "IndusInd Bank", "Banking", True),
    ("BAJFINANCE", "Bajaj Finance", "Financial Services", True),
    ("BAJAJFINSV", "Bajaj Finserv", "Financial Services", True),
    ("SBILIFE", "SBI Life Insurance", "Financial Services", True),
    ("HDFCLIFE", "HDFC Life Insurance", "Financial Services", True),
    ("INFY", "Infosys", "IT", False),
    ("TCS", "Tata Consultancy Services", "IT", False),
    ("HCLTECH", "HCL Technologies", "IT", False),
    ("WIPRO", "Wipro", "IT", False),
    ("TECHM", "Tech Mahindra", "IT", False),
    ("RELIANCE", "Reliance Industries", "Energy", False),
    ("ONGC", "Oil & Natural Gas Corporation", "Energy", False),
    ("BPCL", "Bharat Petroleum", "Energy", False),
    ("MARUTI", "Maruti Suzuki", "Auto", False),
    ("M&M", "Mahindra & Mahindra", "Auto", False),
    ("EICHERMOT", "Eicher Motors", "Auto", False),
    ("BAJAJ-AUTO", "Bajaj Auto", "Auto", False),
    ("HINDUNILVR", "Hindustan Unilever", "FMCG", False),
    ("ITC", "ITC", "FMCG", False),
    ("NESTLEIND", "Nestle India", "FMCG", False),
    ("BRITANNIA", "Britannia Industries", "FMCG", False),
    ("SUNPHARMA", "Sun Pharmaceutical", "Pharma", False),
    ("DRREDDY", "Dr. Reddy's Laboratories", "Pharma", False),
    ("CIPLA", "Cipla", "Pharma", False),
    ("DIVISLAB", "Divi's Laboratories", "Pharma", False),
    ("TATASTEEL", "Tata Steel", "Metal", False),
    ("JSWSTEEL", "JSW Steel", "Metal", False),
    ("HINDALCO", "Hindalco Industries", "Metal", False),
    ("BHARTIARTL", "Bharti Airtel", "Telecom", False),
    ("LT", "Larsen & Toubro", "Infra", False),
    ("ADANIPORTS", "Adani Ports & SEZ", "Infra", False),
    ("ULTRACEMCO", "UltraTech Cement", "Cement", False),
    ("GRASIM", "Grasim Industries", "Cement", False),
    ("NTPC", "NTPC", "Power", False),
    ("POWERGRID", "Power Grid Corporation", "Power", False),
    ("TITAN", "Titan Company", "Consumer Durables", False),
    ("ASIANPAINT", "Asian Paints", "Consumer Durables", False),
    ("DLF", "DLF", "Realty", False),
    ("GODREJPROP", "Godrej Properties", "Realty", False),
]

MOCK_UNIVERSE: list[Security] = [
    Security(symbol=s, name=n, sector=sec, is_financial=fin) for s, n, sec, fin in _UNIVERSE
]
