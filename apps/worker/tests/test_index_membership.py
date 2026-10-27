"""NIFTY 200 point-in-time membership from NSE Indices notices (research/index_membership.py)."""

from datetime import date
from pathlib import Path

import pytest

from dhandrishti.research import index_membership as M

NOTICES = Path(__file__).resolve().parents[3] / "data" / "index-notices"
real = pytest.mark.skipif(not (NOTICES / "ind_prs22082025.txt").exists(), reason="saved notices not available")

SEMI_ANNUAL = """PRESS RELEASE
Mumbai, August 22, 2025
      Replacements in indices
      ... These changes shall become effective from September 30, 2025 (close of September 29, 2025).
      A. Replacements on account of semi-annual review of broad market indices:
      3) Nifty 100
      The following companies are being excluded:
         Sr. No.      Company Name                    Symbol
           1      Dabur India Ltd.                    DABUR
      12) Nifty 200
      The following companies are being excluded:
         Sr. No.      Company Name                    Symbol
           1      Apollo Tyres Ltd.                   APOLLOTYRE
           2      Bandhan Bank Ltd.                   BANDHANBNK
      The following companies are being included:
         Sr. No.      Company Name                    Symbol
           1      Blue Star Ltd.                      BLUESTARCO
 Sr. No.                    Company Name                Symbol
           2      GE Vernova T&D India Ltd.           GVT&D
      13) Nifty LargeMidcap 250
      The following companies are being included:
           1      Some Other Ltd.                     OTHER
      14) Nifty200 Quality 30
      The following company is being excluded:
           1      Decoy Ltd.                          DECOY
"""

LETTERED_2015 = """IISL
                                         Date: August 12, 2015
These changes shall become effective from September 28, 2015 (close of September 24, 2015).
l)    Nifty 200
The following company is being excluded:
   1     Old Co Ltd.                                OLDCO
The following company is being included:
   1     New Co Ltd.                                NEWCO
4)     CNX 200 Index
The following company is being excluded:
   1     Second Old Ltd.                            OLD2
No inclusion is being made in the index.
"""


def test_parses_only_the_nifty_200_section():
    n = M.parse_notice(SEMI_ANNUAL, "ind_prs22082025")
    assert (n.released, n.effective) == (date(2025, 8, 22), date(2025, 9, 30))
    got = {(c.action, c.symbol) for c in n.changes}
    assert got == {("OUT", "APOLLOTYRE"), ("OUT", "BANDHANBNK"), ("IN", "BLUESTARCO"), ("IN", "GVT&D")}  # page break ok
    assert all(c.symbol not in ("DABUR", "OTHER", "DECOY") for c in n.changes)  # other indices, strategy decoy


def test_lettered_and_cnx_headings_and_no_inclusion_lines():
    n = M.parse_notice(LETTERED_2015, "ind_prs12082015")
    assert n.released == date(2015, 8, 12) and n.effective == date(2015, 9, 28)
    assert [(c.action, c.symbol) for c in n.changes] == [("OUT", "OLDCO"), ("IN", "NEWCO"), ("OUT", "OLD2")]


def test_heading_with_index_suffix_2018_style():
    text = "Date: May 24, 2018\neffective from June 29, 2018\n6)         NIFTY 200 Index\n" \
           "The following companies are being excluded:\n       1       Arvind Ltd.        ARVIND\n" \
           "7)    NIFTY200 Quality 30 Index\nThe following company is being included:\n  1   Decoy Ltd.    DECOY\n"
    assert [(c.action, c.symbol) for c in M.parse_notice(text, "may2018").changes] == [("OUT", "ARVIND")]


def test_notice_without_nifty_200_changes_nothing_and_missing_date_is_an_error():
    assert M.parse_notice("PRESS RELEASE\neffective from May 12, 2026\n1) Nifty 500\n"
                          "The following company is being excluded:\n  1   X Ltd.     X\n", "n").changes == []
    with pytest.raises(M.NoticeError, match="no effective date"):
        M.parse_notice("1) Nifty 200\nThe following company is being excluded:\n  1   X Ltd.     XYZ\n", "bad")


def _notice(name, eff, ins=(), outs=()):
    n = M.Notice(name, None, eff)
    n.changes = [M.Change(eff, "IN", s, s, name) for s in ins] + [M.Change(eff, "OUT", s, s, name) for s in outs]
    return n


def test_rebuild_walks_back_with_effective_date_boundaries_and_counts_duplicates():
    today = {"A", "B", "NEW1", "NEW2"}
    feb = _notice("feb", date(2026, 3, 30), ins=["NEW2"], outs=["OLD2"])
    aug = _notice("aug", date(2025, 9, 30), ins=["NEW1"], outs=["OLD1"])
    aug_copy = _notice("aug_1", date(2025, 9, 30), ins=["NEW1"], outs=["OLD1"])     # same notice saved twice
    h = M.rebuild(today, date(2026, 10, 8), [feb, aug, aug_copy], complete_from=date(2025, 1, 1))
    assert h.problems == [] and h.duplicates == 2
    assert h.members_on(date(2026, 3, 30)) == today                                # open of effective day: new list
    assert h.members_on(date(2026, 3, 29)) == {"A", "B", "NEW1", "OLD2"}           # day before: old list
    assert h.members_on(date(2025, 9, 29)) == {"A", "B", "OLD1", "OLD2"}
    assert h.members_on(date(2025, 1, 1)) == {"A", "B", "OLD1", "OLD2"}
    assert h.members_on(date(2024, 12, 31)) is None                                # before coverage: unknown


def test_rebuild_reports_inconsistencies_instead_of_hiding_them():
    h = M.rebuild({"A", "B"}, date(2026, 10, 8),
                  [_notice("x", date(2026, 3, 30), ins=["GONE"], outs=["A"])], complete_from=date(2025, 1, 1))
    assert any("GONE included by x but not a member afterwards" in p for p in h.problems)
    assert any("A excluded by x but still a member afterwards" in p for p in h.problems)


REVOCATION = """PRESS RELEASE
Mumbai, September 25, 2024
     The Committee had announced exclusion of Vodafone Idea Ltd. (IDEA) with effect from September 30, 2024 ...
       Sr.
                Index Name             Security Name                Symbol               Remarks
       No.
                                Vodafone Idea Ltd.             IDEA                 Exclusion revoked
        1    Nifty 500
                                Prism Johnson Ltd.             PRSMJOHNSN           Exclusion
                                Vodafone Idea Ltd.             IDEA                 Exclusion revoked
        8    Nifty 200
                                Central Bank of India          CENTRALBK            Inclusion revoked
The above changes shall become effective from September 30, 2024 (close of September 27, 2024).
"""


def test_revocations_use_checked_transcriptions_and_unknown_formats_are_flagged(monkeypatch):
    eff = date(2024, 9, 30)
    monkeypatch.setitem(M.AMENDMENTS, "rev", (eff, (("IDEA", "Exclusion revoked"), ("CENTRALBK", "Inclusion revoked"))))
    n = M.parse_notice(REVOCATION, "rev")
    assert n.changes == [] and not n.unreviewed
    assert {(c.action, c.symbol) for c in n.revocations} == {("OUT", "IDEA"), ("IN", "CENTRALBK")}

    aug = _notice("aug", eff, ins=["CENTRALBK", "NEW"], outs=["IDEA", "OLD"])
    h = M.rebuild({"A", "IDEA", "NEW"}, date(2026, 10, 8), [aug, n], complete_from=date(2024, 1, 1))
    assert h.problems == [] and h.members_on(date(2024, 9, 29)) == {"A", "IDEA", "OLD"}   # IDEA never left

    assert M.parse_notice(REVOCATION, "not_transcribed").unreviewed                     # a new revocation notice
    h = M.rebuild({"A"}, date(2026, 10, 8), [M.parse_notice(REVOCATION, "not_transcribed")], date(2024, 1, 1))
    assert any("not_transcribed: no text, or NIFTY 200 in a format" in p for p in h.problems)
    list_format = "Mumbai, August 23, 2024\neffective from August 30, 2024\nexcluded from:\n  2      Nifty 200\n"
    assert M.parse_notice(list_format, "dvr").unreviewed                                 # index-list format too
    assert not M.parse_notice(list_format.replace("Nifty 200", "Nifty200 Quality 30") + "word " * 60, "q").unreviewed
    assert M.parse_notice("", "image_only").unreviewed                                  # no text layer: flagged

    monkeypatch.setitem(M.AMENDMENTS, "typo", (eff, (("IDEA", "Inclusion revoked"),)))  # not what the text says
    with pytest.raises(M.NoticeError, match="IDEA 'Inclusion revoked' not in the text"):
        M.parse_notice(REVOCATION, "typo")
    monkeypatch.setitem(M.AMENDMENTS, "early", (eff, (("IDEA", "Exclusion revoked", date(2024, 10, 25)),)))
    assert M.parse_notice(REVOCATION, "early").revocations[0].effective == date(2024, 10, 25)   # row's own date
    h = M.rebuild({"A"}, date(2026, 10, 8), [n], complete_from=date(2024, 1, 1))     # revokes nothing announced
    assert any("revokes IN CENTRALBK on 2024-09-30, but no such change" in p for p in h.problems)


def test_renamed_symbols_are_reported_in_todays_symbols_and_known_size_changes_are_notes(monkeypatch):
    monkeypatch.setitem(M.RENAMES, "OLDNAME", "NEWNAME")
    day = date(2024, 3, 28)
    monkeypatch.setitem(M.SIZE_CHANGES, day, "one extra security")
    h = M.rebuild({"A", "NEWNAME", "X"}, date(2026, 10, 8), [_notice("feb", day, ins=["OLDNAME", "X"], outs=["B"])],
                  complete_from=date(2024, 1, 1))
    assert h.problems == [] and h.members_on(date(2024, 3, 27)) == {"A", "B"}
    assert h.notes == ["2024-03-28: 2 inclusions vs 1 exclusions (size changes): one extra security"]


@real
def test_real_notices_2021_2026_are_consistent_with_todays_list():
    import csv
    root = Path(__file__).resolve().parents[3]
    today = {r["Symbol"] for r in csv.DictReader(open(root / "packages/quant-spec/universe/nifty200.csv",
                                                      encoding="utf-8-sig"))}
    notices = M.load_notices(NOTICES)
    with_changes = {n.name: len(n.changes) for n in notices if n.changes}
    assert with_changes.get("ind_prs21022025") == 22                              # lettered "l) Nifty 200"
    assert with_changes.get("ind_prs22082025") == 18 and with_changes.get("ind_prs23022026") == 22
    assert not [n.name for n in notices if n.unreviewed]
    assert with_changes.get("ind_prs24022022_1") == 28                            # Mar-2022 review, "NIFTY 200"
    assert with_changes.get("ind_prs23082021") == 12                              # image-only PDF, transcribed
    h = M.rebuild(today, date(2026, 10, 8), notices, complete_from=date(2021, 1, 1))
    assert h.problems == [] and len(h.notes) == 2
    sizes = {start: len(m) for start, m in h.periods}
    assert sizes.pop(date(2023, 9, 29)) == sizes.pop(date(2024, 3, 28)) == 201          # Tata Motors DVR counted
    assert set(sizes.values()) == {200}
    assert "BSE" in h.members_on(date(2024, 3, 28)) and "IREDA" not in h.members_on(date(2024, 3, 28))
    assert "IREDA" in h.members_on(date(2024, 9, 30)) and "GMRAIRPORT" in h.members_on(date(2024, 3, 28))
    assert "ETERNAL" in h.members_on(date(2022, 3, 31)) and "ETERNAL" not in h.members_on(date(2022, 3, 30))
