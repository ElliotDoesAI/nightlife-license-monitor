"""The owner's lead spreadsheet: one clean row per venue, outreach first.

Built from the review queue plus contact details the official records
themselves publish (see Source.contact). No outside lookups: the "Look up"
column is a plain map-search link the owner clicks by hand.

Local and email use only. Never print rows in GitHub Actions (public logs).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from urllib.parse import quote_plus

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: (key, header, excel width). Order is the column order.
COLUMNS: list[tuple[str, str, int]] = [
    ("priority", "Priority", 9),
    ("business_name", "Business name", 34),
    ("company", "Company / owner", 34),
    ("business_type", "Business type", 26),
    ("filing", "Filing", 18),
    ("status", "Status", 12),
    ("filed_on", "Filed on", 12),
    ("phone", "Phone", 16),
    ("people", "Owner / applicant names", 34),
    ("address", "Address", 34),
    ("city", "City", 18),
    ("state", "State", 7),
    ("zip", "ZIP", 8),
    ("market", "Market", 24),
    ("mailing_address", "Mailing address", 40),
    ("license", "License applied for", 40),
    ("lookup_url", "Look up online", 14),
    ("record_url", "Official record", 14),
    ("lead_ids", "Lead ID", 12),
]
HEADERS = [h for _, h, _ in COLUMNS]

BUSINESS_TYPES = {
    "nightlife": "Bar / nightclub / lounge",
    "on_premise": "Restaurant / bar",
    "hospitality_mfg": "Brewery / taproom / winery",
    "catering_event": "Caterer / event venue",
    "hotel": "Hotel",
}
_TYPE_ORDER = list(BUSINESS_TYPES)

# (pattern on the upper-cased application type, plain label). First match wins.
_FILINGS = [
    (r"NEW LICENSE", "Newly licensed"),
    (r"\bNEW\b|ORIGINAL", "New application"),
    (r"ASSUMPTION|TRANSFER|CHANGE OF (OWNER|CORP|OFFICER|STOCK)|OWNERSHIP", "Change of owner"),
    (r"LOCATION|RELOC|C_LOC", "New location"),
    (r"TRADENAME|TRADE NAME|NAME CHANGE", "Name change"),
    (r"CLASS|IN LIEU|UPGRADE|ADDED PRIVILEGE", "License upgrade"),
]


def _filing(app_types: list[str], source: str) -> str:
    labels = []
    for t in app_types:
        up = t.upper()
        label = next((lab for pat, lab in _FILINGS if re.search(pat, up)), t.title())
        if label not in labels:
            labels.append(label)
    if not labels and source == "ca_abc_applications":
        return "New application"  # CA export lists pending applications only
    return ", ".join(labels)


def _status(statuses: list[str], source: str) -> str:
    up = " ".join(statuses).upper()
    if source == "fl_abt_licenses":
        return "Licensed"
    if "APPROV" in up:
        return "Approved"
    if re.search(r"\bPEND|APPLICATION|INTAKE|REVIEW|RECEIVED|NOTICE|APPLICANT", up):
        return "Pending"
    if re.search(r"SUREND|SURREND", up):
        return "Surrendered"
    if re.search(r"\bACTIVE|CURRENT|ISSUED", up):
        return "Licensed"
    return statuses[0].title() if statuses else ""


def _phone(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return (value or "").strip() or None


def _title(text: str | None) -> str:
    """Tidy ALL-CAPS names; leave mixed case as the source wrote it."""
    text = " ".join((text or "").split())
    if text and text == text.upper() and any(c.isalpha() for c in text):
        text = text.title()
        text = re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), text)
        text = re.sub(r"'S\b", "'s", text)
        text = re.sub(r"\b([A-Z][a-z])(?= \d{5})", lambda m: m.group(1).upper(), text)
    return re.sub(r"\b(Llc|Inc|Llp|Pllc|Ltd|Dba|Usa)\b", lambda m: m.group(1).upper(), text)


def _people(contacts: list[dict], names: tuple) -> str | None:
    """Owner/applicant names, minus entries that just repeat the business."""
    skip = {re.sub(r"\W", "", (n or "").upper()) for n in names if n}
    people = []
    for c in contacts:
        for p in (c.get("people") or "").split(";"):
            p = _title(p.strip())
            if p and re.sub(r"\W", "", p.upper()) not in skip and p not in people:
                people.append(p)
    return "; ".join(people) or None


def _uniq(values) -> list[str]:
    out: list[str] = []
    for v in values:
        v = (v or "").strip() if isinstance(v, str) else v
        if v and v not in out:
            out.append(v)
    return out


_SQL = """
SELECT q.queue_date, q.record_id, q.venue_key, q.tier, q.score, q.legal_name,
       q.dba, q.license_description, q.application_type, q.status,
       q.application_date, q.address, q.city, q.state, q.zip, q.metro,
       q.source, q.source_url, r.category, r.raw
FROM review_queue q JOIN records r ON r.id = q.record_id
WHERE (%(day)s::date IS NULL OR q.queue_date = %(day)s)
  AND (NOT %(open)s OR q.review_status = 'new')
ORDER BY q.queue_date DESC, q.score DESC, q.record_id
"""
_FIELDS = ["queue_date", "record_id", "venue_key", "tier", "score", "legal_name", "dba",
           "license_description", "application_type", "status", "application_date",
           "address", "city", "state", "zip", "metro", "source", "source_url",
           "category", "raw"]


def load_rows(conn, day: date | None, open_only: bool = False) -> list[dict]:
    """Queued leads for `day` (all days if None), one row per venue per day."""
    with conn.cursor() as cur:
        cur.execute(_SQL, {"day": day, "open": open_only})
        records = [dict(zip(_FIELDS, r)) for r in cur.fetchall()]
    return group_records(records)


def group_records(records: list[dict]) -> list[dict]:
    """Merge application records (best score first) into venue rows."""
    from .sources import all_sources

    by_source = {s.name: s for s in all_sources()}
    groups: dict[tuple, list[dict]] = {}
    for rec in records:
        groups.setdefault((rec["queue_date"], rec["venue_key"]), []).append(rec)

    rows = []
    for (queue_date, _), recs in groups.items():
        recs.sort(key=lambda r: (-(r.get("score") or 0), r["record_id"]))
        top = recs[0]
        contacts = []
        for rec in recs:
            src = by_source.get(rec["source"])
            try:
                contacts.append(src.contact(rec.get("raw") or {}) if src else {})
            except Exception:  # noqa: BLE001 - contact details are best effort
                contacts.append({})
        dates = [r["application_date"] for r in recs if r.get("application_date")]
        cats = sorted({r.get("category") for r in recs},
                      key=lambda c: _TYPE_ORDER.index(c) if c in _TYPE_ORDER else 99)
        name = top.get("dba") or top.get("legal_name")
        company = top.get("legal_name") if top.get("legal_name") != name else None
        address = ", ".join(p for p in (top.get("address"), top.get("city"),
                                        top.get("state"), top.get("zip")) if p)
        lookup_q = " ".join(p for p in (name, address) if p)
        rows.append({
            "queue_date": queue_date,
            "priority": min((r.get("tier") or "C") for r in recs),
            "score": top.get("score") or 0,
            "business_name": _title(name),
            "company": _title(company) or None,
            "business_type": BUSINESS_TYPES.get(cats[0], "Other") if cats else "Other",
            "filing": _filing(_uniq(r.get("application_type") for r in recs), top["source"]),
            "status": _status(_uniq(r.get("status") for r in recs), top["source"]),
            "filed_on": min(dates) if dates else None,
            "phone": ", ".join(_uniq(_phone(c.get("phone")) for c in contacts)) or None,
            "people": _people(contacts, (name, top.get("legal_name"))),
            "address": _title(top.get("address")),
            "city": _title(top.get("city")),
            "state": (top.get("state") or "").upper(),
            "zip": top.get("zip") or "",
            "market": top.get("metro") or "",
            "mailing_address": _title(next((c["mailing_address"] for c in contacts
                                            if c.get("mailing_address")), None)) or None,
            "license": "; ".join(_uniq(r.get("license_description") for r in recs)),
            "lookup_url": ("https://www.google.com/maps/search/?api=1&query="
                           + quote_plus(lookup_q)) if lookup_q else None,
            "record_url": top.get("source_url"),
            "lead_ids": " ".join(str(r["record_id"]) for r in
                                 sorted(recs, key=lambda r: r["record_id"])),
        })
    rows.sort(key=lambda r: (r["priority"], r["market"], -r["score"],
                             r["business_name"] or ""))
    return rows


def _cell(value):
    if isinstance(value, datetime):
        return value.date()
    return "" if value is None else value


def write_csv(rows: list[dict], out) -> None:
    w = csv.writer(out)
    w.writerow(HEADERS)
    for row in rows:
        w.writerow([_csv_safe(_cell(row.get(k))) for k, _, _ in COLUMNS])


def _csv_safe(value):
    """Stop spreadsheet apps from running a source string as a formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "@"):
        return "'" + value
    return value


def build_xlsx(rows: list[dict], title: str = "Leads") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", "-", title)[:31] or "Leads"
    ws.append(HEADERS)
    head_fill = PatternFill("solid", fgColor="1F2937")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 22
    fills = {"A": PatternFill("solid", fgColor="D1FAE5"),
             "B": PatternFill("solid", fgColor="FEF3C7"),
             "C": PatternFill("solid", fgColor="F3F4F6")}
    link_font = Font(color="1D4ED8", underline="single")
    link_cols = {"lookup_url": "Map", "record_url": "Record"}
    for i, row in enumerate(rows, start=2):
        for j, (key, _, _) in enumerate(COLUMNS, start=1):
            value = _cell(row.get(key))
            cell = ws.cell(row=i, column=j)
            if key in link_cols:
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    cell.value = link_cols[key]
                    cell.hyperlink = value
                    cell.font = link_font
                continue
            cell.value = value
            if cell.data_type == "f":
                cell.data_type = "s"  # never let a source string become a formula
            if isinstance(value, date):
                cell.number_format = "yyyy-mm-dd"
        prio = ws.cell(row=i, column=1)
        prio.alignment = Alignment(horizontal="center")
        if row.get("priority") in fills:
            prio.fill = fills[row["priority"]]
            prio.font = Font(bold=True)
    for j, (_, _, width) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(1, len(rows) + 1)}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
