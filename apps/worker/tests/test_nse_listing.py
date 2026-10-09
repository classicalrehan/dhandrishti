"""NSE financial-results listing reader. Synthetic rows in the format of files downloaded 2026-10-08."""

from datetime import datetime

import pytest

from dhandrishti.jobs.pit_fundamentals import first_decision_day
from dhandrishti.pit.adapters import nse_results_listing as L
from dhandrishti.pit.availability import IST

HEAD = ("﻿COMPANY NAME,AUDITED / UNAUDITED,CUMULATIVE / NON-CUMULATIVE,CONSOLIDATED / NON-CONSOLIDATED,"
        "IND AS/ NON IND AS,PERIOD,PERIOD ENDED,RELATING TO,** XBRL,Exchange Received Time,"
        "Exchange Dissemination Time,Time Taken\n")
ROW = ('"Test Co Limited","Audited","Non-cumulative","{basis}","Ind-AS New","Quarterly","{end}","Fourth Quarter",'
       '"https://nsearchives.nseindia.com/corporate/xbrl/{file}","{rec}","{dis}","00:03:35"\n')


def listing(tmp_path, *rows, name="CF-FR-equities-BAJAJ-AUTO-01-04-2023-to-08-10-2026.csv"):
    p = tmp_path / name
    p.write_text(HEAD + "".join(ROW.format(**r) for r in rows), encoding="utf-8")
    return p


def row(basis="Consolidated", end="31-Mar-2024", file="INDAS_1_2_19042024112830.xml",
        rec="19-Apr-2024 11:28:31", dis="19-Apr-2024 11:32:06"):
    return dict(basis=basis, end=end, file=file, rec=rec, dis=dis)


def test_parses_symbol_bases_and_exact_times(tmp_path):
    fs = L.parse(listing(tmp_path, row(), row(basis="Non-Consolidated", file="INDAS_1_3_x.xml")))
    assert {f.symbol for f in fs} == {"BAJAJ-AUTO"}  # hyphenated symbol taken from the file name
    c = next(f for f in fs if f.basis == "CONSOLIDATED")
    assert c.disseminated_at == datetime(2024, 4, 19, 11, 32, 6, tzinfo=IST)
    assert c.received_at < c.disseminated_at and c.taxonomy == "INDAS" and c.audited and not c.cumulative
    assert c.period_type == "Q" and c.lag_days == 19 and not c.after_deadline
    assert {f.basis for f in fs} == {"CONSOLIDATED", "STANDALONE"}


def test_late_filing_is_flagged(tmp_path):
    f = L.parse(listing(tmp_path, row(end="31-Dec-2023", dis="20-Feb-2024 18:00:00", rec="20-Feb-2024 17:59:00")))[0]
    assert f.after_deadline  # 51 days after a December quarter; deadline is 45


@pytest.mark.parametrize("bad, message", [
    (row(basis="Mixed"), "basis"),
    (row(dis="19-Apr-2024 11:00:00"), "disseminated before received"),
    (row(end="30-Apr-2024"), "before the period ended"),
    (row(file="report.pdf"), "XBRL link"),
])
def test_bad_rows_are_rejected(tmp_path, bad, message):
    with pytest.raises(L.ListingError, match=message):
        L.parse(listing(tmp_path, bad))


def test_duplicate_files_and_wrong_headers_are_rejected(tmp_path):
    with pytest.raises(L.ListingError, match="duplicate"):
        L.parse(listing(tmp_path, row(), row()))
    p = tmp_path / "CF-FR-equities-X-01-04-2023-to-08-10-2026.csv"
    p.write_text("COMPANY,PERIOD\n")
    with pytest.raises(L.ListingError, match="unexpected header"):
        L.parse(p)
    with pytest.raises(L.ListingError, match="file name"):
        L.symbol_from_name(tmp_path / "results.csv")


def test_first_usable_decision_uses_real_sessions():
    sessions = {"2023-04-13", "2023-04-17", "2024-04-19", "2024-04-22"}  # 14-Apr-2023 was a holiday
    at = lambda s: datetime.fromisoformat(s).replace(tzinfo=IST)  # noqa: E731
    assert first_decision_day(at("2024-04-19 11:32"), sessions) == "2024-04-19"  # during market hours
    assert first_decision_day(at("2024-04-19 16:02"), sessions) == "2024-04-22"  # after the close: next session
    assert first_decision_day(at("2023-04-14 10:42"), sessions) == "2023-04-17"  # holiday


# ---------------------------------------------------------------- Integrated Filing – Financials format

IHEAD = ("﻿SYMBOL ,COMPANY NAME ,QUARTER END DATE ,TYPE OF SUBMISSION ,AUDITED / UNAUDITED ,"
         "CONSOLIDATED / STANDALONE ,DETAILS ,XBRL ,BROADCAST DATE/TIME ,REVISED DATE/TIME ,REVISION REMARKS ,"
         "EXCHANGE DISSEMINATION TIME ,TIME TAKEN \n")
IROW = ('"{sym}","Test Co Limited","31-MAR-2025","{sub}","Audited","{basis}",'
        '"https://nsearchives.nseindia.com/corporate/ixbrl/X_iXBRL_WEB.html",'
        '"https://nsearchives.nseindia.com/corporate/xbrl/{file}","17-Apr-2025 23:30:35","{rev}","{rem}",'
        '"17-Apr-2025 23:36:34","00:00:01"\n')


def integrated(tmp_path, *rows):
    p = tmp_path / "CF-Integrated-Filing-equities-Integrated Filing- Financials-TESTCO-08-Oct-2026.csv"
    p.write_text(IHEAD + "".join(IROW.format(**({"sym": "TESTCO", "sub": "Original", "basis": "Consolidated",
                                                  "file": "INTEGRATED_FILING_INDAS_1_17042025113633_WEB.xml",
                                                  "rev": "", "rem": ""} | r)) for r in rows), encoding="utf-8")
    return p


def test_integrated_format_is_detected_and_read(tmp_path):
    fs = L.parse(integrated(tmp_path, {}, {"basis": "Standalone", "file": "INTEGRATED_FILING_INDAS_2_x_WEB.xml"}))
    c = next(f for f in fs if f.basis == "CONSOLIDATED")
    assert c.symbol == "TESTCO" and c.period_type == "Q" and c.taxonomy == "INDAS"
    assert c.disseminated_at == datetime(2025, 4, 17, 23, 36, 34, tzinfo=IST)  # public time, not broadcast
    assert c.received_at == datetime(2025, 4, 17, 23, 30, 35, tzinfo=IST)
    assert c.source_page == "Integrated Filing - Financials" and c.submission == "Original"
    assert {f.basis for f in fs} == {"CONSOLIDATED", "STANDALONE"}


def test_revised_submission_is_never_public_before_the_revision(tmp_path):
    f = L.parse(integrated(tmp_path, {"sub": "Revised", "rev": "02-May-2025 10:00:00", "rem": "typo in EPS"}))[0]
    assert f.submission == "Revised" and f.revision_remarks == "typo in EPS"
    assert f.disseminated_at == datetime(2025, 5, 2, 10, 0, tzinfo=IST)
    with pytest.raises(L.ListingError, match="without REVISED"):
        L.parse(integrated(tmp_path, {"sub": "Revised"}))


def test_integrated_rows_for_another_symbol_are_rejected(tmp_path):
    with pytest.raises(L.ListingError, match="in a file for INFY"):
        L.parse(integrated(tmp_path, {}), symbol="INFY")
