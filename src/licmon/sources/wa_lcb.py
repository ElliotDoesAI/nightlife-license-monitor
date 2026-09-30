"""Washington LCB license-actions connector.

Source report: "New License Applications, Approvals and Discontinuances",
statewide, past 30 days::

    https://licensinginfo.lcb.wa.gov/EntireStateWeb.asp

The report is a single large HTML page (latin-1/windows-1252) with three
sections -- new applications, recently approved licenses, discontinued
licenses. Each record is one ``<tbody>`` of label/value rows. Only the
stdlib is used for parsing.

Venue history comes from the report's own Application Type only. The LCB
licensee list (https://lcb.wa.gov/taxreporting/licensee-list, checked
2026-09-30) covers manufacturers, distributors, spirits retailers and
public houses, not taverns, restaurants or nightclubs, and data.wa.gov's
"Liquor Renewal" set (9dee-kzm5) is a partial renewal notice list last
updated April 2026. Neither is a full list of existing licenses, so no
address check: ASSUMPTION is "New owner", ADDED/CHANGE OF CLASS/IN LIEU is
"Adding a permit", everything else (NEW APPLICATION, CHANGE OF LOCATION,
ADDED/CHANGE OF TRADENAME) stays Unknown.
"""

from __future__ import annotations

import html
import re
from typing import Iterable

from .. import history, stage
from ..http import Http
from ..models import Record, Snapshot, parse_date
from .base import Source

#: Report URL (also used as every record's ``source_url``).
URL = "https://licensinginfo.lcb.wa.gov/EntireStateWeb.asp"

_APPLICATION = "APPLICATION"
_APPROVED = "APPROVED"
_DISCONTINUED = "DISCONTINUED"

_STAGE_RANK = {_APPLICATION: 0, _APPROVED: 1, _DISCONTINUED: 2}

# Section headers as they appear in the report (<th> cells, &nbsp; included).
_HEADERS = (
    (re.compile(r"STATEWIDE(?:&nbsp;|\s)+NEW LICENSE APPLICATIONS"), _APPLICATION),
    (re.compile(r"STATEWIDE(?:&nbsp;|\s)+RECENTLY APPROVED LICENSES"), _APPROVED),
    (re.compile(r"STATEWIDE(?:&nbsp;|\s)+DISCONTINUED LICENSES"), _DISCONTINUED),
)

_TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr\s*>", re.S | re.I)
_TD_RE = re.compile(r"<td\b[^>]*>(.*?)</td\s*>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")
_BAR_RE = re.compile(r"\bBAR\b")
_COA_RE = re.compile(r"\bCOA\b")
_STATE_ZIP_RE = re.compile(r"^\s*([A-Za-z]{2})?\s*(\d{5}(?:\s*-\s*\d{4})?)?\s*$")
_TRAILING_STATE_ZIP_RE = re.compile(
    r"^(.*?)\b([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)\s*$"
)

# Priority order (best first): nightlife > on_premise > hospitality_mfg >
# catering_event > hotel > off_premise > wholesale_mfg > temporary > other.
PRIORITY = (
    "nightlife",
    "on_premise",
    "hospitality_mfg",
    "catering_event",
    "hotel",
    "off_premise",
    "wholesale_mfg",
    "temporary",
    "other",
)


# Approvals list privilege *codes* instead of names. Only codes whose names
# are published on the official licensee-list page
# (https://lcb.wa.gov/taxreporting/licensee-list, checked 2026-09-29) are
# mapped. Retail codes such as 450 or 424 have no official public label we
# could verify, so they stay "other" rather than being guessed.
PRIVILEGE_CODES = {
    "470": "hospitality_mfg",  # Washington Public House
    "326": "hospitality_mfg",  # Domestic & Microbreweries
    "327": "hospitality_mfg",  # Domestic Winery
    "325": "hospitality_mfg",  # Distill/Rectify
    "329": "hospitality_mfg",  # Fruit and/or Wine Distillery
    "351": "hospitality_mfg",  # Craft Distillery
    "482": "off_premise",  # Spirits Retailer
    "483": "off_premise",  # CLS Spirits Retailer
    "484": "off_premise",  # SLS Spirits Retailer
    "320": "wholesale_mfg", "320A": "wholesale_mfg", "321": "wholesale_mfg",
    "334": "wholesale_mfg", "336": "wholesale_mfg", "340": "wholesale_mfg",
    "341": "wholesale_mfg", "342": "wholesale_mfg", "343": "wholesale_mfg",
    "346": "wholesale_mfg", "347": "wholesale_mfg", "348B": "wholesale_mfg",
    "348W": "wholesale_mfg", "354": "wholesale_mfg", "355": "wholesale_mfg",
    "356": "wholesale_mfg", "357": "wholesale_mfg",
}


#: Application Type -> venue history (see the module docstring).
HISTORY_BY_TYPE = {
    "ASSUMPTION": history.NEW_OWNER,
    "ADDED/CHANGE OF CLASS/IN LIEU": history.ADDING_PERMIT,
}


# License-type wording -> qualify.NIGHTLIFE_LICENSE_POINTS keys. Seen in the
# report (probe, 2026-09-29): "NIGHTCLUB", "SPORTS ENTERTAINMENT FACILITY",
# "BEER/WINE THEATER", "NON-PROFIT ARTS ORGANIZATION".
_NIGHTLIFE_TYPES = (
    (re.compile(r"NIGHTCLUB|NIGHT CLUB|CABARET"), "nightclub_cabaret"),
    (re.compile(r"SPORTS ENTERTAINMENT|SPORTS/ENTERTAINMENT"), "sports_venue"),
    (re.compile(r"THEATER|THEATRE|NON-PROFIT ARTS"), "theater"),
)


def _part_category(part: str) -> str:
    """Classify one ';'-separated license-type fragment."""
    if part in PRIVILEGE_CODES:
        return PRIVILEGE_CODES[part]
    if "CANNABIS" in part or "MARIJUANA" in part:
        return "other"
    if (
        "NIGHTCLUB" in part
        or "TAVERN" in part
        or "LOUNGE" in part
        or "CABARET" in part
        or "SPORTS ENTERTAINMENT" in part
        or (
            _BAR_RE.search(part)
            and "SERVICE BAR" not in part
            and "SNACK BAR" not in part
        )
    ):
        return "nightlife"
    if (
        "REST" in part
        or "ON PREMISES" in part
        or "PRIVATE CLUB" in part
        or ("CLUB" in part and "NON-CLUB" not in part)
        or "THEATER" in part
        or "THEATRE" in part
        or "SNACK BAR" in part
    ):
        return "on_premise"
    if (
        "BREWPUB" in part
        or "MICROBREW" in part
        or "BREWERY" in part
        or "WINERY" in part
        or "DISTILL" in part
        or "CRAFT DISTILL" in part
        or "TAPROOM" in part
        or "TASTING ROOM" in part
        or "PUBLIC HOUSE" in part
    ):
        return "hospitality_mfg"
    if (
        "CATERING" in part
        or "CATERER" in part
        or "EVENT" in part
        or "BANQUET" in part
    ):
        return "catering_event"
    if "HOTEL" in part or "MOTEL" in part:
        return "hotel"
    if (
        "GROCERY" in part
        or "SPECIALTY" in part
        or ("RETAILER" in part and "SHIP TO" not in part)
        or ("RESELLER" in part and "SHIP TO" not in part)
        or "OFF PREMISES" in part
        or "OFF-PREMISES" in part
        or "OFF PREM" in part
        or "STORE" in part
        or "TASTING" in part
        or "FARMER" in part
        or "DELIVERY" in part
        or "TAKEOUT" in part
        or "TO-GO" in part
        or "TO GO" in part
        or "GROWLERS" in part
        or "KEGS" in part
    ):
        return "off_premise"
    if (
        "DISTRIBUTOR" in part
        or "IMPORTER" in part
        or "EXPORTER" in part
        or "SHIPMENT" in part
        or "SHIPPER" in part
        or "SHIP TO" in part
        or "CERTIFICATE" in part
        or _COA_RE.search(part)
        or "WAREHOUSE" in part
        or "MANUFACTURER" in part
        or "CARRIER" in part
        or "BONDED" in part
    ):
        return "wholesale_mfg"
    if "SPECIAL OCCASION" in part or "TEMPORARY" in part:
        return "temporary"
    return "other"


def categorize(license_text: str | None) -> str:
    """Map a License Type string to one of the CATEGORIES in models.py.

    Multi-type strings (``;``-separated) resolve to the most
    nightlife-relevant category: nightlife > on_premise > hospitality_mfg >
    catering_event > hotel > off_premise > wholesale_mfg > temporary > other.
    Numeric privilege codes (e.g. ``"450"``) and anything unrecognized map to
    ``"other"``.
    """
    if not license_text:
        return "other"
    best = len(PRIORITY) - 1
    for raw_part in re.split(r"[;,]", license_text.upper()):
        part = raw_part.strip()
        if not part:
            continue
        rank = PRIORITY.index(_part_category(part))
        if rank < best:
            best = rank
            if best == 0:
                break
    return PRIORITY[best]


def _decode(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("windows-1252")


def _text(cell_html: str) -> str:
    text = _TAG_RE.sub("", cell_html)
    text = html.unescape(text).replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()


def _label(cell_html: str) -> str:
    # Change-of-location rows render the label as "\\ Application Type";
    # strip that leading junk so variant labels still match.
    label = _text(cell_html).rstrip(":").strip()
    return re.sub(r"^[^A-Za-z0-9(]+", "", label)


def _first(fields: dict[str, str], *names: str) -> str:
    """First non-empty value for any of the label names (New beats Current)."""
    for name in names:
        value = fields.get(name, "").strip()
        if value:
            return value
    return ""


def _tbody_rows(tbody_html: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for tr in _TR_RE.findall(tbody_html):
        cells = _TD_RE.findall(tr)
        if len(cells) < 2:
            continue
        label = _label(cells[0])
        value = _text(cells[1])
        if not label and not value:
            continue
        rows.append((label, value))
    return rows


def _iter_tbodies(text: str) -> Iterable[tuple[int, str]]:
    """Yield (offset, tbody html) for each <tbody>...</tbody> block."""
    low = text.lower()
    pos = 0
    end_tag = "</tbody>"
    while True:
        start = low.find("<tbody", pos)
        if start < 0:
            return
        end = low.find(end_tag, start)
        if end < 0:
            return
        end += len(end_tag)
        yield start, text[start:end]
        pos = end


def _section_at(offset: int, headers: list[tuple[int, str]]) -> str | None:
    current: str | None = None
    for pos, section in headers:
        if pos <= offset:
            current = section
        else:
            break
    return current


def _parse_location(value: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Split "street, city, ST ZIP" on commas; tolerate missing parts."""
    parts = [p.strip() for p in value.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None, None, None, None
    if len(parts) >= 3:
        address = ", ".join(parts[:-2]) or None
        city = parts[-2] or None
        state: str | None = None
        zip_code: str | None = None
        match = _STATE_ZIP_RE.match(parts[-1])
        if match:
            state = (match.group(1) or "").upper() or None
            zip_code = (match.group(2) or "").replace(" ", "") or None
            if len((match.group(1) or "")) != 2:
                # Last part isn't really "ST ZIP" (e.g. a second city word);
                # fold it back into the city.
                if city and parts[-1]:
                    city = f"{city}, {parts[-1]}"
                state, zip_code = None, None
        else:
            city = f"{city}, {parts[-1]}" if city else parts[-1]
        if city:
            # A trailing "ST ZIP" hiding in the city part (missing comma).
            trailing = _TRAILING_STATE_ZIP_RE.match(city)
            if trailing and not state and not zip_code:
                city = trailing.group(1).strip() or None
                state = trailing.group(2).upper()
                zip_code = trailing.group(3)
        return address, city, state, zip_code
    if len(parts) == 2:
        first, second = parts
        trailing = _TRAILING_STATE_ZIP_RE.match(second)
        if trailing:
            city = trailing.group(1).strip() or None
            return first or None, city, trailing.group(2).upper(), trailing.group(3)
        match = _STATE_ZIP_RE.match(second)
        if match and match.group(1) and len(match.group(1)) == 2:
            return first or None, None, match.group(1).upper(), (
                (match.group(2) or "").replace(" ", "") or None
            )
        return first or None, second or None, None, None
    only = parts[0]
    trailing = _TRAILING_STATE_ZIP_RE.match(only)
    if trailing:
        rest = trailing.group(1).strip()
        if re.search(r"\d", rest):
            return rest or None, None, trailing.group(2).upper(), trailing.group(3)
        return None, rest or None, trailing.group(2).upper(), trailing.group(3)
    return only or None, None, None, None


class WaLcbSource(Source):
    name = "wa_lcb_actions"
    title = "Washington LCB license applications/approvals/discontinuances (30 days)"
    state = "WA"
    homepage = "https://lcb.wa.gov/resources/licensing-actions"
    tracks_removals = False  # rolling 30-day window, not a stable pending list
    min_records = 50
    # The same action shows up as an application (license names, notification
    # date) and later as an approval (privilege codes, approval date), and
    # drops out after 30 days. Only a stage change is a real change.
    material_fields = ("status", "application_type")

    def fetch(self, http: Http) -> list[Snapshot]:
        return [http.get(URL)]

    def venue_history(self, http: Http, records: list[Record],
                      snapshots: list[Snapshot] | None = None,
                      today=None) -> dict:
        out = {}
        for rec in records:
            label = HISTORY_BY_TYPE.get((rec.application_type or "").upper())
            if label:
                out[rec.source_record_id] = history.History(label)
        return out

    def stage(self, rec: Record) -> str | None:
        # The report section: approved in this report means issued.
        return {_APPLICATION: stage.RECEIVED, _APPROVED: stage.LICENSED}.get(
            (rec.status or "").upper())

    def nightlife_license(self, rec: Record) -> tuple[str, ...]:
        text = (rec.license_description or rec.license_type or "").upper()
        return tuple(key for pattern, key in _NIGHTLIFE_TYPES if pattern.search(text))

    def contact(self, raw: dict) -> dict:
        people = "; ".join(
            p.strip() for p in (raw.get("Applicant(s)") or "").split(";") if p.strip())
        return {"phone": raw.get("Contact Phone") or None, "people": people or None}

    def parse(self, snapshots: list[Snapshot]) -> Iterable[Record]:
        # Group tbodies by (license_number, application_type) so a license
        # that moved through sections collapses to one record at the most
        # advanced stage.
        groups: dict[tuple[str, str], list[dict]] = {}
        order: list[tuple[str, str]] = []
        seen_tbodies: set[tuple[str | None, tuple]] = set()

        for snapshot in snapshots:
            text = _decode(snapshot.body)
            headers = sorted(
                (m.start(), section)
                for pattern, section in _HEADERS
                for m in pattern.finditer(text)
            )
            if not headers:
                continue
            for offset, tbody_html in _iter_tbodies(text):
                section = _section_at(offset, headers)
                if section is None:
                    continue
                rows = _tbody_rows(tbody_html)
                if not rows:
                    continue
                fields: dict[str, str] = {}
                raw: dict[str, str] = {}
                for label, value in rows:
                    if not label:
                        continue
                    raw.setdefault(label, value)
                    fields.setdefault(label.upper(), value)

                license_number = _WS_RE.sub(
                    " ", fields.get("LICENSE NUMBER", "")
                ).strip()
                if not license_number:
                    continue  # no stable id without a license number
                application_type = _WS_RE.sub(
                    " ", fields.get("APPLICATION TYPE", "")
                ).strip().upper()
                license_text = _WS_RE.sub(
                    " ", fields.get("LICENSE TYPE", "")
                ).strip().rstrip(", ")

                fingerprint = (section, tuple(sorted(raw.items())))
                if fingerprint in seen_tbodies:
                    continue  # exact duplicate tbody
                seen_tbodies.add(fingerprint)

                # Assumption/change records split some rows into Current/New
                # pairs; the New value is the lead-relevant one.
                business_name = (
                    _first(
                        fields,
                        "NEW BUSINESS NAME",
                        "BUSINESS NAME",
                        "CURRENT BUSINESS NAME",
                    )
                    or None
                )
                applicants_raw = _first(
                    fields,
                    "NEW APPLICANT(S)",
                    "APPLICANT(S)",
                    "CURRENT APPLICANT(S)",
                )
                first_applicant = next(
                    (p.strip() for p in applicants_raw.split(";") if p.strip()),
                    "",
                )
                address, city, state, zip_code = _parse_location(
                    _first(
                        fields,
                        "NEW BUSINESS LOCATION",
                        "BUSINESS LOCATION",
                        "CURRENT BUSINESS LOCATION",
                    )
                )

                section_dates = {
                    _APPLICATION: fields.get("NOTIFICATION DATE", ""),
                    _APPROVED: fields.get("APPROVED DATE", ""),
                    _DISCONTINUED: fields.get("DISCONTINUED DATE", ""),
                }
                entry = {
                    "section": section,
                    "status": section,
                    "notification_date": parse_date(
                        fields.get("NOTIFICATION DATE", "")
                    ),
                    "section_date": parse_date(section_dates[section]),
                    "legal_name": first_applicant or business_name,
                    "dba": business_name,
                    "address": address,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                    "license_text": license_text,
                    "raw": raw,
                }
                key = (license_number, application_type)
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(entry)

        for key in sorted(order):
            entries = groups[key]
            winner = max(entries, key=lambda e: _STAGE_RANK[e["status"]])
            # Prefer the first winner-stage entry for display fields.
            display = next(
                e for e in entries if e["status"] == winner["status"]
            )
            notification_dates = [
                e["notification_date"]
                for e in entries
                if e["notification_date"] is not None
            ]
            application_date = (
                notification_dates[0]
                if notification_dates
                else display["section_date"]
            )
            # Approvals often list bare privilege codes; keep the most
            # descriptive license text and the best category across stages.
            texts = [e["license_text"] for e in entries if e["license_text"]]
            worded = [t for t in texts if re.search(r"[A-Z]{3}", t.upper())]
            license_text = (worded or texts or [None])[0]
            category = min((categorize(t) for t in texts),
                           key=PRIORITY.index, default="other")
            license_number, application_type = key
            yield Record(
                source=self.name,
                source_record_id=f"{license_number}:{application_type}",
                source_url=URL,
                legal_name=display["legal_name"],
                dba=display["dba"],
                license_type=license_text,
                license_description=license_text,
                application_type=application_type or None,
                status=display["status"],
                application_date=application_date,
                address=display["address"],
                city=display["city"],
                state=display["state"],
                zip=display["zip"],
                county=None,
                category=category,
                raw={**display["raw"], "section": display["section"]},
            )
