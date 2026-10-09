"""Shareholding-pattern XBRL reader. Synthetic file shaped like INFY's 31-Mar-2026 filing."""

from datetime import datetime

import pytest

from dhandrishti.pit.adapters import nse_shp as S
from dhandrishti.pit.adapters.nse_xbrl import XbrlError
from dhandrishti.pit.availability import IST

NS = ('xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:in-bse-shp="http://www.bseindia.com/xbrl/shp/2025-10-31/in-bse-shp" '
      'xmlns:xbrldi="http://xbrl.org/2006/xbrldi"')


def shp(tmp_path, pledged="false", public_fii=100):
    def ctx(cid, member=None):
        seg = (f'<xbrli:segment><xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
               f'in-bse-shp:{member}</xbrldi:explicitMember></xbrli:segment>') if member else ""
        return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>{seg}'
                f'</xbrli:entity><xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period></xbrli:context>')
    cats = {"ShareholdingOfPromoterAndPromoterGroupMember": (150, 0.15), "PublicShareholdingMember": (800, 0.8),
            "SharesHeldByNonPromoterNonPublicShareholdersMember": (50, None), "ShareholdingPatternMember": (1000, 1),
            "InstitutionsForeignMember": (public_fii, 0.1), "InstitutionsDomesticMember": (500, 0.5),
            "GovernmentsMember": (0, 0), "NonInstitutionsMember": (200, 0.2)}
    body = ctx("MainI")
    for i, (m, (n, p)) in enumerate(cats.items()):
        body += ctx(f"C{i}", m) + f'<in-bse-shp:NumberOfFullyPaidUpEquityShares contextRef="C{i}" unitRef="shares" decimals="0">{n}</in-bse-shp:NumberOfFullyPaidUpEquityShares>'
        if p is not None:
            body += f'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="C{i}" unitRef="pure" decimals="4">{p}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>'
    for n, v in (("Symbol", "TESTCO"), ("DateOfReport", "2026-03-31"), (S.PLEDGE_FLAG, pledged)):
        body += f"<in-bse-shp:{n} contextRef=\"MainI\">{v}</in-bse-shp:{n}>"
    p = tmp_path / "SHP_1_16042026045034_WEB.xml"
    p.write_text(f'<?xml version="1.0" encoding="UTF-8"?><xbrli:xbrl {NS}>{body}</xbrli:xbrl>')
    return p


def test_reads_categories_as_percent_and_checks_identities(tmp_path):
    f = S.parse(shp(tmp_path))
    assert (f.symbol, str(f.as_on)) == ("TESTCO", "2026-03-31")
    assert f.pct["promoter"] == pytest.approx(15) and f.pct["fii"] == pytest.approx(10) and f.pct["dii"] == pytest.approx(50)
    assert all(st == "PASS" for _, st, _ in f.checks), f.checks
    t = datetime(2026, 4, 16, 16, 50, tzinfo=IST)
    obs = {o.metric: o for o in f.observations(t, "SHP_1_16042026045034_WEB.xml")}
    assert set(obs) == {"promoter_holding_pct", "fii_holding_pct", "dii_holding_pct", "promoter_pledged_pct"}
    assert obs["promoter_pledged_pct"].value == 0.0  # stated: no pledge
    o = obs["promoter_holding_pct"]
    assert (o.period_type, o.filing_type, o.available_at, o.unit) == ("INSTANT", "SHAREHOLDING_PATTERN", t, "PCT")


def test_category_mismatch_fails_and_unknown_pledge_warns(tmp_path):
    f = S.parse(shp(tmp_path, pledged="true", public_fii=90))
    st = {n: s for n, s, _ in f.checks}
    assert st["public = foreign + domestic institutions + government + non-institutions"] == "FAIL"
    assert st["promoter pledge stated"] == "WARN"
    assert "promoter_pledged_pct" not in {o.metric for o in f.observations(datetime(2026, 4, 16, tzinfo=IST), "x")}


def test_doctype_is_refused(tmp_path):
    p = shp(tmp_path)
    p.write_text(p.read_text().replace('?>', '?><!DOCTYPE x [<!ENTITY a "b">]>', 1))
    with pytest.raises(XbrlError, match="DOCTYPE"):
        S.parse(p)


def test_older_format_percent_scale_undefined_contexts_and_entity_symbol(tmp_path):
    """INFY 2023-2024 files (taxonomy 2022-09-30): percent not fraction, company facts on undefined contexts,
    symbol in the context identifier, 'Goverments' spelling and the broader pledge question."""
    p = shp(tmp_path)
    t = p.read_text()
    for frac, pct in (("0.15", "15"), ("0.8", "80"), (">1<", ">100<"), ("0.1", "10"), ("0.5", "50"), ("0.2", "20")):
        t = t.replace(f'decimals="4">{frac}<' if frac[0] != ">" else f'decimals="4"{frac}', 
                      f'decimals="4">{pct}<' if frac[0] != ">" else f'decimals="4"{pct}')
    t = t.replace("GovernmentsMember", "GovermentsMember")
    t = t.replace('scheme="s">1<', 'scheme="http://www.nseindia.com/NSESymbol">TESTCO<')
    t = t.replace('<in-bse-shp:Symbol contextRef="MainI">TESTCO</in-bse-shp:Symbol>', "")
    t = t.replace('contextRef="MainI">2026-03-31', 'contextRef="OneI">2026-03-31')
    t = t.replace(S.PLEDGE_FLAG, "WhetherAnySharesHeldByPromotersArePledgeOrOtherwiseEncumbered")
    p.write_text(t)
    f = S.parse(p)
    assert f.symbol == "TESTCO" and str(f.as_on) == "2026-03-31"
    assert f.pct["promoter"] == pytest.approx(15) and f.pct["total"] == pytest.approx(100)
    assert f.promoter_pledged is False
    assert all(st == "PASS" for _, st, _ in f.checks), f.checks
    assert any("not defined in the file (OneI)" in n for n in f.notes)


# ---------------------------------------------------------------- shareholding listing CSV

from dhandrishti.pit.adapters import nse_shp_listing as SL  # noqa: E402

LHEAD = ("﻿COMPANY,PROMOTER & PROMOTER GROUP (A),PUBLIC (B),SHARES HELD BY EMPLOYEE TRUSTS (C2),STATUS,AS ON DATE,"
         "SUBMISSION DATE,REVISION DATE,ACTION,BROADCAST DATE/TIME,EXCHANGE DISSEMINATION TIME,TIME TAKEN\n")


def listing(tmp_path, rows, name="CF-Shareholding-Pattern-equities-BAJAJ-AUTO-01-04-2023-to-09-10-2026.csv"):
    p = tmp_path / name
    p.write_text(LHEAD + "".join(rows), encoding="utf-8")
    return p


ROW = ('"Test Co Limited","14.38","85.38","0.23","-","31-MAR-2026","16-APR-2026","{rev}",'
       '"https://nsearchives.nseindia.com/corporate/xbrl/{file}","16-APR-2026 16:50:39","{dis}","00:00:04"\n')


def test_shareholding_listing_reads_times_and_symbol_from_file_name(tmp_path):
    rows = SL.parse(listing(tmp_path, [ROW.format(rev="", file="SHP_1_x_WEB.xml", dis="16-APR-2026 16:50:43")]))
    r = rows[0]
    assert r.symbol == "BAJAJ-AUTO" and str(r.as_on) == "2026-03-31" and r.promoter_pct == 14.38
    assert r.disseminated_at == datetime(2026, 4, 16, 16, 50, 43, tzinfo=IST) and r.xbrl_file == "SHP_1_x_WEB.xml"


@pytest.mark.parametrize("kw, message", [
    ({"rev": "", "file": "x.pdf", "dis": "16-APR-2026 16:50:43"}, "XBRL link"),
    ({"rev": "", "file": "SHP_1_x_WEB.xml", "dis": "16-APR-2026 16:00:00"}, "disseminated before submitted"),
    ({"rev": "20-APR-2026", "file": "SHP_1_x_WEB.xml", "dis": "16-APR-2026 16:50:43"}, "before its revision date"),
])
def test_shareholding_listing_rejects_bad_rows(tmp_path, kw, message):
    with pytest.raises(SL.ShpListingError, match=message):
        SL.parse(listing(tmp_path, [ROW.format(**kw)]))


def test_shareholding_listing_rejects_wrong_file_name(tmp_path):
    with pytest.raises(SL.ShpListingError, match="file name"):
        SL.parse(listing(tmp_path, [], name="shareholding.csv"))
