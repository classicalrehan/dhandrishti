"""NSE results XBRL reader. Synthetic files in the format of INFY's 31-Mar-2026 filing; plus an end-to-end
check on the real pilot file when it is present locally (data/pilot is not committed)."""

import os
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from dhandrishti.db.migrate import migrate
from dhandrishti.pit import store
from dhandrishti.pit.adapters import nse_results_listing as L
from dhandrishti.pit.adapters import nse_xbrl as X
from dhandrishti.pit.availability import IST, decision_time

NS = ('xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/2026-01-31/in-capmkt" '
      'xmlns:xbrldi="http://xbrl.org/2006/xbrldi"')


def ctx(cid, start=None, end="2026-03-31", dim=False):
    period = f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>" if start \
        else f"<xbrli:instant>{end}</xbrli:instant>"
    seg = '<xbrli:segment><xbrldi:explicitMember dimension="in-capmkt:X">in-capmkt:Y</xbrldi:explicitMember></xbrli:segment>' if dim else ""
    return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>{seg}'
            f'</xbrli:entity><xbrli:period>{period}</xbrli:period></xbrli:context>')


def fact(name, cid, value, unit="INR"):
    u = f' unitRef="{unit}" decimals="-7"' if unit else ""
    return f"<in-capmkt:{name} contextRef=\"{cid}\"{u}>{value}</in-capmkt:{name}>"


def xbrl(tmp_path, name="INTEGRATED_FILING_INDAS_9_x_WEB.xml", symbol="TESTCO", nature="Consolidated", extra="",
         owners=True, doctype=""):
    cr = lambda v: str(int(v * 1e7))  # noqa: E731
    q = [("RevenueFromOperations", 1000), ("OtherIncome", 50), ("Income", 1050), ("Expenses", 850),
         ("ProfitBeforeExceptionalItemsAndTax", 200), ("ProfitBeforeTax", 200), ("TaxExpense", 50),
         ("ProfitLossForPeriod", 150), ("ProfitLossForPeriodFromContinuingOperations", 150), ("FinanceCosts", 10),
         ("DepreciationDepletionAndAmortisationExpense", 40), ("PaidUpValueOfEquityShareCapital", 10)]
    if owners:
        q.append(("ProfitOrLossAttributableToOwnersOfParent", 140))
    body = "".join(fact(n, "OneD", cr(v)) for n, v in q)
    body += fact("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "OneD", "14", "INRPerShare")
    body += fact("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "OneD", "13.9", "INRPerShare")
    body += fact("FaceValueOfEquityShareCapital", "OneD", "1", "INRPerShare")
    body += fact("RevenueFromOperations", "NineD", cr(2900))  # nine-month YTD: skipped
    body += fact("RevenueFromOperations", "Dim", cr(1))        # dimensional context: ignored
    body += "".join(fact(n, "OneI", cr(v)) for n, v in [("Assets", 5000), ("EquityAndLiabilities", 5000),
                    ("EquityAttributableToOwnersOfParent", 3000), ("BorrowingsCurrent", 100), ("BorrowingsNoncurrent", 200),
                    ("CashAndCashEquivalents", 400)])
    body += "".join(fact(n, "OneD", v, None) for n, v in [("Symbol", symbol), ("NatureOfReportStandaloneConsolidated", nature),
                    ("DateOfEndOfReportingPeriod", "2026-03-31"), ("DateOfEndOfBoardMeeting", "2026-04-23")])
    doc = (f'<?xml version="1.0" encoding="UTF-8"?>{doctype}<xbrli:xbrl {NS}>'
           + ctx("OneD", "2026-01-01") + ctx("NineD", "2025-07-01") + ctx("OneI") + ctx("Dim", "2026-01-01", dim=True)
           + body + extra + "</xbrli:xbrl>")
    p = tmp_path / name
    p.write_text(doc)
    return p


def filing(name="INTEGRATED_FILING_INDAS_9_x_WEB.xml", basis="CONSOLIDATED", taxonomy="INDAS", symbol="TESTCO"):
    t = datetime(2026, 4, 23, 21, 1, 54, tzinfo=IST)
    return L.ResultFiling(symbol=symbol, company="Test Co", period_end=datetime(2026, 3, 31).date(), period_type="Q",
                          relating_to="", basis=basis, audited=True, cumulative=False, accounting="", taxonomy=taxonomy,
                          xbrl_url="u/" + name, xbrl_file=name, received_at=t, disseminated_at=t)


def test_extracts_canonical_crore_values_with_the_listing_timestamp(tmp_path):
    pf = X.parse(xbrl(tmp_path), filing())
    got = {(o.metric, o.period_type): o.value for o in pf.observations}
    assert got[("revenue", "Q")] == 1000 and got[("net_profit", "Q")] == 140  # owners' share, not 150
    assert got[("total_borrowings", "INSTANT")] == 300 and got[("shares_outstanding", "INSTANT")] == 10
    assert got[("eps_diluted", "Q")] == 13.9
    assert ("revenue", "FY") not in got and all(o.period_type in ("Q", "INSTANT") for o in pf.observations)  # 9M skipped
    o = pf.observations[0]
    assert o.available_at == o.reported_at == datetime(2026, 4, 23, 21, 1, 54, tzinfo=IST)
    assert (o.availability_basis, o.value_vintage, o.basis) == ("EXCHANGE_TIMESTAMP", "AS_REPORTED", "CONSOLIDATED")
    assert any("skipped period" in n for n in pf.notes)
    assert all(status == "PASS" for _, status, _ in pf.checks), pf.checks


def test_consolidated_profit_without_owners_share_is_not_stored(tmp_path):
    pf = X.parse(xbrl(tmp_path, owners=False), filing())
    assert "net_profit" not in {o.metric for o in pf.observations}
    assert any("attributable to owners not tagged" in n for n in pf.notes)


def test_standalone_uses_profit_for_the_period(tmp_path):
    pf = X.parse(xbrl(tmp_path, nature="Standalone", owners=False), filing(basis="STANDALONE"))
    assert {o.metric: o.value for o in pf.observations if o.period_type == "Q"}["net_profit"] == 150


@pytest.mark.parametrize("kw, f_kw, message", [
    ({"symbol": "OTHER"}, {}, "symbol OTHER vs listing TESTCO"),
    ({"nature": "Standalone"}, {}, "basis Standalone"),
    ({}, {"name": "renamed.xml"}, "does not match listing file"),
    ({}, {"taxonomy": "INSURANCE"}, "not supported yet"),
    ({"doctype": '<!DOCTYPE x [<!ENTITY a "b">]>'}, {}, "DOCTYPE"),
])
def test_refusals(tmp_path, kw, f_kw, message):
    with pytest.raises(X.XbrlError, match=message):
        X.parse(xbrl(tmp_path, **kw), filing(**f_kw))


def test_consistency_check_catches_bad_arithmetic(tmp_path):
    p = xbrl(tmp_path)
    p.write_text(p.read_text().replace(">10500000000<", ">10600000000<"))  # Income 1050 -> 1060
    pf = X.parse(p, filing())
    assert dict((n, st) for n, st, _ in pf.checks)["income = revenue + other income"] == "FAIL"


def test_missing_balance_sheet_is_not_applicable_and_eps_gap_only_warns(tmp_path):
    p = xbrl(tmp_path)
    text = p.read_text()
    for el in ("Assets", "EquityAndLiabilities"):
        text = text.replace(f'<in-capmkt:{el} contextRef="OneI"', f'<in-capmkt:X{el} contextRef="OneI"').replace(
            f"</in-capmkt:{el}>", f"</in-capmkt:X{el}>")
    text = text.replace('unitRef="INRPerShare" decimals="-7">14<', 'unitRef="INRPerShare" decimals="-7">15<')  # EPS 15 vs 14
    p.write_text(text)
    st = {n: s for n, s, _ in X.parse(p, filing()).checks}
    assert st["assets = equity + liabilities"] == "N/A"
    assert st["EPS x period-end shares ≈ owners' profit (2%)"] == "WARN"


# ---------------------------------------------------------------- real pilot file, end to end (local only)

REPO = Path(__file__).resolve().parents[3]
REAL = REPO / "data/pilot/batch1-xbrl/INTEGRATED_FILING_INDAS_1658041_23042026090203_WEB.xml"
LISTINGS = REPO / "data/pilot/batch1"
ADMIN_URL = os.environ.get("DD_TEST_DATABASE_URL")


@pytest.mark.skipif(not (REAL.exists() and ADMIN_URL), reason="pilot file or test database not available")
def test_real_infy_filing_point_in_time_end_to_end():
    index = {f.xbrl_file: f for p in LISTINGS.glob("*.csv") for f in L.parse(p)}
    pf = X.parse(REAL, index[REAL.name])
    assert not any(status == "FAIL" for _, status, _ in pf.checks)
    name = f"dd_xbrl_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        with psycopg.connect(make_conninfo(ADMIN_URL, dbname=name), autocommit=True) as c:
            migrate(c)
            c.execute("INSERT INTO securities (symbol, name, sector, provenance, source) VALUES ('INFY','Infosys','IT','EOD','t')")
            r1 = store.append(c, pf.observations, X.SOURCE, REAL.name)
            r2 = store.append(c, pf.observations, X.SOURCE, REAL.name)
            assert r1.inserted == len(pf.observations) and r2.duplicates == len(pf.observations)
            seen = lambda d: {(o.metric, o.period_type): o.value for o in store.as_of(c, "INFY", decision_time(d))}  # noqa: E731
            assert seen("2026-04-23") == {}  # published 21:02, after that day's 15:30 decision
            after = seen("2026-04-24")
            assert after[("revenue", "Q")] == 38641 and after[("net_profit", "FY")] == 29211
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


# ---------------------------------------------------------------- banking taxonomy

def bank_xbrl(tmp_path, exceptional=0.0, name="INTEGRATED_FILING_BANKING_9_x_WEB.xml", nature="Consolidated",
              other_liabilities=200):
    """Shaped like HDFCBANK's 31-Mar-2025 filing. `exceptional` = minority interest reproduces its tagging error."""
    cr = lambda v: str(round(v * 1e7))  # noqa: E731
    minority = 5.0
    pbt = 100.0 - 20.0 + exceptional          # operating profit 100, provisions 20
    pat = pbt - 25.0
    owners = pat - minority
    q = [("InterestEarned", 300), ("OtherIncome", 100), ("Income", 400), ("InterestExpended", 200),
         ("ExpenditureExcludingProvisionsAndContingencies", 300), ("OperatingProfitBeforeProvisionAndContingencies", 100),
         ("ProvisionsOtherThanTaxAndContingencies", 20), ("ExceptionalItems", exceptional),
         ("ProfitLossFromOrdinaryActivitiesBeforeTax", pbt), ("TaxExpense", 25),
         ("ProfitLossFromOrdinaryActivitiesAfterTax", pat), ("ProfitLossForThePeriod", pat),
         ("ProfitLossOfMinorityInterest", minority), ("ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates", owners),
         ("PaidUpValueOfEquityShareCapital", 10), ("SegmentProfitBeforeTax", 80),
         ("OtherUnallocableExpenditureNetOffUnAllocableIncome", 0)]
    body = "".join(fact(n, "OneD", cr(v)) for n, v in q)
    true_owners = 80.0 - 25.0 - minority  # 50
    body += fact("BasicEarningsPerShareAfterExtraordinaryItems", "OneD", str(true_owners / 10), "INRPerShare")
    body += fact("DilutedEarningsPerShareAfterExtraordinaryItems", "OneD", str(true_owners / 10), "INRPerShare")
    body += fact("FaceValueOfEquityShareCapital", "OneD", "1", "INRPerShare")
    body += "".join(fact(n, "OneI", cr(v)) for n, v in [("Capital", 10), ("ReservesAndSurplus", 490), ("Deposits", 3000),
                    ("Borrowings", 500), ("OtherLiabilitiesAndProvisions", other_liabilities), ("CapitalAndLiabilities", 4200),
                    ("Assets", 4200), ("CashAndBalancesWithReserveBankOfIndia", 150),
                    ("BalancesWithBanksAndMoneyAtCallAndShortNotice", 50), ("Investments", 1000), ("Advances", 2900),
                    ("FixedAssets", 50), ("OtherAssets", 50), ("CashAndCashEquivalentsCashFlowStatement", 200)])
    body += "".join(fact(n, "OneD", v, None) for n, v in [("Symbol", "TESTCO"), ("NatureOfReportStandaloneConsolidated", nature),
                    ("DateOfEndOfReportingPeriod", "2026-03-31"), ("DateOfEndOfBoardMeeting", "2026-04-23")])
    p = tmp_path / name
    p.write_text(f'<?xml version="1.0" encoding="UTF-8"?><xbrli:xbrl {NS}>' + ctx("OneD", "2026-01-01") + ctx("OneI")
                 + body + "</xbrli:xbrl>")
    return p


def bank_filing(name="INTEGRATED_FILING_BANKING_9_x_WEB.xml"):
    return filing(name=name, taxonomy="BANKING")


def test_bank_mapping_uses_bank_concepts(tmp_path):
    pf = X.parse(bank_xbrl(tmp_path), bank_filing())
    got = {(o.metric, o.period_type): o.value for o in pf.observations}
    assert got[("revenue", "Q")] == 400 and got[("finance_costs", "Q")] == 200  # total income; interest expended
    assert got[("net_profit", "Q")] == 50 and got[("total_equity", "INSTANT")] == 500
    assert got[("total_borrowings", "INSTANT")] == 500 and got[("cash_and_equivalents", "INSTANT")] == 200  # no deposits
    assert ("profit_before_exceptional_items", "Q") not in got and ("depreciation", "Q") not in got
    assert all(st == "PASS" for _, st, _ in pf.checks), pf.checks


def test_minority_interest_tagged_as_exceptional_item_is_caught_by_cross_checks(tmp_path):
    """The HDFCBANK 31-Mar-2025 consolidated pattern: every addition balances, yet profit is understated."""
    pf = X.parse(bank_xbrl(tmp_path, exceptional=-5.0), bank_filing())
    st = {n: s for n, s, _ in pf.checks}
    assert st["PBT = operating profit - provisions + exceptional items"] == "PASS"
    assert st["PAT = PBT - tax"] == "PASS"
    assert st["segment profit before tax = PBT (cross-check)"] == "WARN"
    assert st["EPS x period-end shares ≈ owners' profit (2%)"] == "WARN"
    assert not any(s == "FAIL" for s in st.values())


def test_cli_holds_back_warned_files_unless_accepted(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from dhandrishti.jobs import pit_fundamentals as job
    xml = bank_xbrl(tmp_path, exceptional=-5.0)
    monkeypatch.setattr(job.listing, "parse", lambda p: [bank_filing()])
    (tmp_path / "listing.csv").write_text("x")
    calls = []
    monkeypatch.setattr(job.store, "append", lambda *a, **k: calls.append(a) or SimpleNamespace(
        batch_id=1, inserted=len(a[1]), versioned=0, duplicates=0))
    args = SimpleNamespace(files=[xml], listings=tmp_path, do_import=True, accept_warnings=False)
    assert job.xbrl_command(None, args) == 1 and calls == []
    assert "held back" in capsys.readouterr().err
    args.accept_warnings = True
    assert job.xbrl_command(None, args) == 0 and len(calls) == 1


def test_bank_balance_sheet_lines_must_sum_to_the_total(tmp_path):
    """The HDFCBANK consolidated 31-Mar-2026 pattern: totals agree, liability lines fall short."""
    st = {n: s for n, s, _ in X.parse(bank_xbrl(tmp_path, other_liabilities=20), bank_filing()).checks}
    assert st["assets = capital and liabilities"] == "PASS"
    assert st["liability lines sum to capital and liabilities"] == "FAIL"
    assert st["asset lines sum to assets"] == "PASS"



def test_stated_period_overrides_a_wrong_context_header(tmp_path):
    """INFY 31-Dec-2024 (old format): the nine-month context is labelled with the quarter's dates."""
    p = xbrl(tmp_path)
    text = p.read_text()
    # relabel the nine-month context with the quarter's dates, as the old-format file does
    text = text.replace("<xbrli:startDate>2025-07-01</xbrli:startDate>", "<xbrli:startDate>2026-01-01</xbrli:startDate>")
    text = text.replace("</xbrli:xbrl>", fact("DateOfStartOfReportingPeriod", "NineD", "2025-07-01", None)
                        + fact("DateOfEndOfReportingPeriod", "NineD", "2026-03-31", None) + "</xbrli:xbrl>")
    p.write_text(text)
    pf = X.parse(p, filing())
    assert {(o.metric, o.period_type): o.value for o in pf.observations}[("revenue", "Q")] == 1000  # not the 9M figure
    assert any("header says 2026-01-01..2026-03-31, filing states 2025-07-01..2026-03-31" in n for n in pf.notes)
