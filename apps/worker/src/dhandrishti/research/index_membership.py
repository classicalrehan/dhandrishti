"""Point-in-time NIFTY 200 membership from NSE Indices press releases (research only; reads text, writes nothing).

Source: the index-change press releases at www.niftyindices.com/press-release, saved manually as PDF and converted
with `pdftotext -layout`. Each notice states "effective from <date> (close of <date>)" and lists every affected index
in a numbered section ("12) Nifty 200", "l) Nifty 200", "6) NIFTY 200 Index", in 2015 "4) CNX 200 Index") with
"excluded" / "included" tables of company name and NSE symbol. A notice without such a section does not change
NIFTY 200. Strategy indices built on it ("Nifty200 Quality 30", ...) are different indices and are ignored.

Membership is rebuilt backwards from a known constituent list (today's NSE file): undoing each change, newest first.
Every undo is checked (an included stock must be present, an excluded one absent); failures are reported, never
silently corrected. A change takes effect at the open of its effective date; the day before, the old list applies.
Two cases need curated, source-checked data instead of the line parser:
- Revocation notices, whose "Index Name / Security / Symbol / Remarks" tables centre the index cell vertically across
  its rows (a row cannot be assigned to an index mechanically), and notices naming NIFTY 200 outside a numbered
  section ("excluded from the following indices" lists), and image-only PDFs (read by OCR). Their NIFTY 200 rows
  are transcribed in AMENDMENTS; parse_notice checks every transcribed row against the text, and rebuild reports
  any other such notice as unreviewed, so a new one cannot be missed silently.
- Symbol renames: membership is expressed in today's symbols (RENAMES maps old notice symbols to current ones).
Known gap: short-lived inclusions of demerged entities (if a notice does not list NIFTY 200 explicitly).
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

TARGET = {"nifty 200", "cnx 200"}                 # headings compared without a trailing "Index" (2015-2018 style)
HEADING = re.compile(r"^\s*(?:\d{1,2}|[a-z]{1,2})\s*[).]\s+(\S.*?)\s*:?\s*$", re.IGNORECASE)
ROW = re.compile(r"^\s*\d{1,3}\s+(\S.*?\S)\s{2,}(\S+)\s*$")
EFFECTIVE = re.compile(r"effective\s+(?:from|on)\s+([A-Z][a-z]+\s+\d{1,2},\s*\d{4})")
TABLE_HEADER = re.compile(r"^\s*Sr\.?\s*No", re.IGNORECASE)
RELEASED = re.compile(r"(?:Date:\s*|Mumbai,\s*)([A-Z][a-z]+\s+\d{1,2},\s*\d{4})")
MENTION = re.compile(r"\b(?:nifty|cnx)\s*200\b(?![ \t]*\w)", re.IGNORECASE)   # not "Nifty200 Quality 30"
REMARKS_HEADER = re.compile(r"Symbol\s+Remarks\s*$", re.MULTILINE)
REMARK_ACTION = {"Inclusion": ("IN", False), "Exclusion": ("OUT", False),
                 "Inclusion revoked": ("IN", True), "Exclusion revoked": ("OUT", True)}

# NIFTY 200 rows transcribed from the saved text: notice -> (effective date, rows), added to what the parser reads.
# Rows are (symbol, remark), or (symbol, remark, effective date) when it differs from the notice's own date.
# A reviewed notice with no NIFTY 200 rows maps to (None, ()).
AMENDMENTS: dict[str, tuple[date | None, tuple[tuple, ...]]] = {
    # IREDA inclusion (28-Feb-2024) revoked for impact cost; BSE included instead. Table row "5 Nifty 200".
    "ind_prs19032024": (date(2024, 3, 28), (("IREDA", "Inclusion revoked"), ("BSE", "Inclusion"))),
    # Vodafone Idea exclusion (23-Aug-2024) revoked; CENTRALBK inclusion revoked with it. Table row "8 Nifty 200".
    "ind_prs25092024": (date(2024, 9, 30), (("IDEA", "Exclusion revoked"), ("CENTRALBK", "Inclusion revoked"))),
    # Tata Motors DVR shares cancelled: "excluded from the following indices" list ("2 Nifty 200"), no replacement.
    "ind_prs23082024_1": (date(2024, 8, 30), (("TATAMTRDVR", "Exclusion"),)),
    # Image-only PDF (no text layer), read by OCR and checked against the page image: "10) NIFTY 200", 6 out, 6 in.
    "ind_prs23082021": (date(2021, 9, 30), tuple((s, "Exclusion") for s in (
        "ABBOTINDIA", "BBTC", "CESC", "GODREJAGRO", "IBULHSGFIN", "VGUARD")) + tuple((s, "Inclusion") for s in (
        "ASTRAL", "HINDCOPPER", "INDIANB", "IRFC", "NATIONALUM", "TATACOMM"))),
    "ind_prs23082021_1": (None, ()),             # image-only PDF; OCR: NIFTY SME EMERGE exclusions only
    # Yes Bank removed from all indices early (19-Mar-2020); ADANITRANS, due to join on 27-Mar (ind_prs18022020),
    # joined NIFTY 100 and NIFTY 200 on 19-Mar instead (parsed), so its 27-Mar inclusion did not happen.
    "ind_prs16032020": (date(2020, 3, 19), (("ADANITRANS", "Inclusion revoked", date(2020, 3, 27)),)),
    # Prose, not a table: "PVR Limited will be included in NIFTY 200 index" (with NIFTY Midcap 100, for Yes Bank).
    "ind_prs19032020": (date(2020, 3, 27), (("PVR", "Inclusion"),)),
    "ind_prs24092018": (None, ()),               # image-only PDF; OCR: NIFTY CPSE only
    "ind_prs23092024": (None, ()),               # Exicom / JNK India: Nifty Microcap 250 and Total Market only
    "ind_prs17032025": (None, ()),               # Raymond Lifestyle / Thirumalai: Nifty Microcap 250 only
}

# Old notice symbol -> today's symbol. Evidence: the notices switch name and symbol between two releases, and
# today's list carries the renamed company:
# - "GMR Airports Infrastructure Ltd." GMRINFRA up to ind_prs25092024; "GMR Airports Ltd." GMRAIRPORT from
#   ind_prs11122024 (today's list: ISIN INE776C01039).
# - "Zomato Ltd." ZOMATO up to ind_prs21022025; "Eternal Ltd." ETERNAL from ind_prs06062025 (ISIN INE758T01015).
# - "Adani Gas Ltd." ADANIGAS up to ind_prs11122020; "Adani Total Gas Ltd." ATGL from ind_prs08032022.
# - "Adani Transmission Ltd." ADANITRANS up to ind_prs06032023; "Adani Energy Solutions Ltd." ADANIENSOL from
#   ind_prs28022024.
# - "NIIT Technologies Ltd." NIITTECH up to ind_prs18022020; "Coforge Ltd." COFORGE from ind_prs20082020.
# Not in today's list (or renamed again), but needed to match changes across years:
# - "Reliance Nippon Life Asset Management Ltd." RNAM up to ind_prs16122019; "Nippon Life India Asset Management
#   Ltd." NAM-INDIA from ind_prs18022020.
# - "Indiabulls Ventures Ltd." IBVENTURES up to ind_prs28082019; "Dhani Services Ltd." DHANI from ind_prs10032021.
# Renamed twice: "Larsen & Toubro Infotech Ltd." LTI up to ind_prs16092022; "LTIMindtree Ltd." LTIM from
# ind_prs06122022 to ind_prs11122025; "LTM Ltd." LTM from ind_prs10062026 (today's list: ISIN INE214T01019).
RENAMES = {"GMRINFRA": "GMRAIRPORT", "ZOMATO": "ETERNAL", "ADANIGAS": "ATGL", "ADANITRANS": "ADANIENSOL",
           "NIITTECH": "COFORGE", "RNAM": "NAM-INDIA", "IBVENTURES": "DHANI", "LTI": "LTM", "LTIM": "LTM"}

# Effective days on which inclusions and exclusions legitimately differ in number (reported as notes, not problems).
SIZE_CHANGES = {
    date(2023, 9, 29): "TATAMTRDVR included without a matching exclusion (ind_prs17082023: 8 in, 7 out): 201 members",
    date(2024, 8, 30): "TATAMTRDVR excluded without replacement (ind_prs23082024_1, DVR shares cancelled): 200 members",
}


class NoticeError(ValueError):
    pass


def _date(s: str) -> date:
    return datetime.strptime(re.sub(r"\s+", " ", s.replace(",", ", ")).strip(), "%B %d, %Y").date()


@dataclass(frozen=True)
class Change:
    effective: date
    action: str          # "IN" | "OUT"
    symbol: str
    company: str
    notice: str


@dataclass
class Notice:
    name: str
    released: date | None
    effective: date | None
    changes: list[Change] = field(default_factory=list)
    revocations: list[Change] = field(default_factory=list)   # cancel an earlier announced change (same day)
    unreviewed: bool = False                                    # needs a transcription in AMENDMENTS


def parse_notice(text: str, name: str) -> Notice:
    """NIFTY 200 changes in one notice. A notice with a NIFTY 200 section but no effective date is an error."""
    eff = EFFECTIVE.search(text)
    rel = RELEASED.search(text)
    notice = Notice(name, _date(rel.group(1)) if rel else None, _date(eff.group(1)) if eff else None)
    in_target, mode = False, None
    for line in text.splitlines():
        if TABLE_HEADER.match(line):             # "Sr. No.  Company Name  Symbol" would otherwise look like "Sr." heading
            continue
        h = HEADING.match(line)
        if h and not ROW.match(line):
            in_target, mode = re.sub(r"\s+index$", "", h.group(1).strip().lower()) in TARGET, None
            continue
        if not in_target:
            continue
        low = line.lower()
        if "being excluded" in low:
            mode = "OUT"
        elif "being included" in low:
            mode = "IN"
        elif low.strip().startswith(("no inclusion", "no exclusion")):
            mode = None
        elif mode and (r := ROW.match(line)):
            if notice.effective is None:
                raise NoticeError(f"{name}: NIFTY 200 changes but no effective date")
            notice.changes.append(Change(notice.effective, mode, r.group(2), r.group(1), name))
    no_text = len(re.findall(r"[A-Za-z]{4,}", text)) < 50     # image-only PDF: pdftotext returns (almost) nothing
    other_format = REMARKS_HEADER.search(text) or (not notice.changes and MENTION.search(text))
    if notice.name in AMENDMENTS or no_text or other_format:
        _amend(notice, text)
    return notice


def _amend(notice: Notice, text: str) -> None:
    if notice.name not in AMENDMENTS:
        notice.unreviewed = True
        return
    eff, rows = AMENDMENTS[notice.name]
    if eff is not None and f"{eff:%B} {eff.day}, {eff.year}" not in re.sub(r"\s+", " ", text):
        raise NoticeError(f"{notice.name}: transcribed effective date {eff} not in the text")
    for symbol, remark, *on in rows:
        row = rf"\s{re.escape(symbol)}\s+{remark}\s*$" if REMARKS_HEADER.search(text) else rf"\b{re.escape(symbol)}\b"
        if not re.search(row, text, re.MULTILINE):
            raise NoticeError(f"{notice.name}: transcribed row {symbol} '{remark}' not in the text")
        action, revoked = REMARK_ACTION[remark]
        day = on[0] if on else eff
        (notice.revocations if revoked else notice.changes).append(Change(day, action, symbol, symbol, notice.name))


def load_notices(directory: Path) -> list[Notice]:
    return [parse_notice(p.read_text(encoding="utf-8", errors="replace"), p.stem) for p in sorted(directory.glob("*.txt"))]


@dataclass
class History:
    as_of: date                                  # date of the known (anchor) list
    complete_from: date                          # notices are known to be complete from this date on
    periods: list[tuple[date, frozenset[str]]]   # (first day the list applies, members), newest first
    problems: list[str]
    duplicates: int
    notes: list[str] = field(default_factory=list)

    def members_on(self, day: date) -> frozenset[str] | None:
        """Members at the open of `day`; None before `complete_from` (earlier changes are unknown)."""
        if day < self.complete_from:
            return None
        for start, members in self.periods:
            if day >= start:
                return members
        return None


def rebuild(anchor: set[str], anchor_date: date, notices: list[Notice], complete_from: date) -> History:
    """Walk back from `anchor` (membership on `anchor_date`), undoing each change effective after `complete_from`,
    newest first. `complete_from` must be a date from which every notice is in `notices` (the caller asserts it)."""
    def current(c: Change) -> Change:
        return Change(c.effective, c.action, RENAMES.get(c.symbol, c.symbol), c.company, c.notice)

    in_range = [n for n in notices if n.effective is None or complete_from < n.effective <= anchor_date]
    problems = [f"{n.name}: no text, or NIFTY 200 in a format the parser does not read (review, add to AMENDMENTS)"
                for n in in_range if n.unreviewed]
    revoked = {(c.effective, c.action, c.symbol): c for n in notices for c in map(current, n.revocations)}
    seen, changes, dups = set(), [], 0
    for n in notices:
        for c in map(current, n.changes):
            key = (c.effective, c.action, c.symbol)
            if key in revoked:
                revoked[key] = None              # matched: the announced change never happened
                continue
            if key in seen:
                dups += 1
                continue
            seen.add(key)
            if complete_from < c.effective <= anchor_date:
                changes.append(c)
    by_day: dict[date, list[Change]] = {}
    for c in changes:
        by_day.setdefault(c.effective, []).append(c)
    problems += [f"{c.notice}: revokes {c.action} {c.symbol} on {c.effective}, but no such change was announced"
                 for c in revoked.values() if c is not None and complete_from < c.effective <= anchor_date]
    state, notes = set(anchor), []
    periods: list[tuple[date, frozenset[str]]] = []
    for day in sorted(by_day, reverse=True):
        periods.append((day, frozenset(state)))
        ins = [c for c in by_day[day] if c.action == "IN"]
        outs = [c for c in by_day[day] if c.action == "OUT"]
        for c in ins:
            if c.symbol not in state:
                problems.append(f"{day}: {c.symbol} included by {c.notice} but not a member afterwards")
            state.discard(c.symbol)
        for c in outs:
            if c.symbol in state:
                problems.append(f"{day}: {c.symbol} excluded by {c.notice} but still a member afterwards")
            state.add(c.symbol)
        if len(ins) != len(outs):
            msg = f"{day}: {len(ins)} inclusions vs {len(outs)} exclusions (size changes)"
            if day in SIZE_CHANGES:
                notes.append(f"{msg}: {SIZE_CHANGES[day]}")
            else:
                problems.append(msg)
    periods.append((complete_from, frozenset(state)))
    return History(anchor_date, complete_from, periods, problems, dups, notes)
