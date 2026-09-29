"""California ABC Daily Data Export connector (pending/new applications).

Source: California ABC Daily Data Export (CSV inside a zip), refreshed each
business day ~7am PT:
    https://www.abc.ca.gov/wp-content/uploads/DailyExport-CSV.zip

Format notes (verified against the real export 2026-09-28):
- The zip holds one file (ABC-DailyDataExport.csv, ~28 MB unzipped).
- First line is a title like
  ``"Updated Monday 28th of September 2026 03:50:28 AM"`` (UTF-8 BOM).
- Second line is the header; some header names carry leading spaces
  (e.g. ``" Prem Addr 2"``) so header names are stripped.
- Blank values are a single space (``" "``).
- Only rows with ``"Lic or App" == "APP"`` are applications; ``LIC`` rows
  are existing licenses and are excluded.
- Rows share a ``File Number`` when one application covers several license
  types; one Record is emitted per file number.

License-type descriptions were verified against the official list at
https://www.abc.ca.gov/licensing/license-types/ (fetched 2026-09-29).

Per-record deep links: ``source_url`` is the official single-license lookup
page, ``...single-license/?RPTTYPE=12&LICENSE=<file number without leading
zeros>``. Verified in a browser 2026-09-29 (renders the application's owner,
business name and address). The page sits behind Cloudflare bot protection,
so the pipeline never fetches it; it is only a link for the human reviewer.
The raw export URL is kept in ``raw["export_url"]``.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterable

from ..http import Http
from ..models import CATEGORIES, Record, Snapshot
from .base import Source

EXPORT_URL = "https://www.abc.ca.gov/wp-content/uploads/DailyExport-CSV.zip"

#: Human-facing per-record lookup (see module doc). Never fetched by the pipeline.
LOOKUP_URL = ("https://www.abc.ca.gov/licensing/license-lookup/single-license/"
              "?RPTTYPE=12&LICENSE={}")
SOURCE_URL = EXPORT_URL


def lookup_url(file_number: str) -> str:
    return LOOKUP_URL.format(int(file_number) if file_number.isdigit() else file_number)

#: Official license-type code -> human description (abc.ca.gov, 2026-09-29).
LICENSE_TYPES = {
    "01": "Beer Manufacturer",
    "02": "Winegrower",
    "03": "Brandy Manufacturer",
    "04": "Distilled Spirits Manufacturer",
    "05": "Distilled Spirits Manufacturer's Agent",
    "06": "Still",
    "07": "Rectifier",
    "08": "Wine Rectifier",
    "09": "Beer and Wine Importer",
    "10": "Beer and Wine Importer's General",
    "11": "Brandy Importer",
    "12": "Distilled Spirits Importer",
    "13": "Distilled Spirits Importer's General",
    "14": "Public Warehouse",
    "15": "Customs Broker",
    "16": "Wine Broker",
    "17": "Beer and Wine Wholesaler",
    "18": "Distilled Spirits Wholesaler",
    "19": "Industrial Alcohol Dealer",
    "20": "Off-Sale Beer & Wine",
    "21": "Off-Sale General",
    "22": "Wine Blender",
    "23": "Small Beer Manufacturer",
    "24": "Distilled Spirits Rectifier's General",
    "25": "California Brandy Wholesaler",
    "26": "Out-of-State Beer Manufacturer's Certificate",
    "27": "California Winegrower's Agent",
    "28": "Out-of-State Distilled Spirits Shipper's Certificate",
    "29": "Wine Grape Grower's Storage",
    "31": "Special Daily (beer, wine, distilled spirits)",
    "34": "Daily Beer and Wine",
    "37": "Daily General",
    "40": "On-Sale Beer",
    "41": "On-Sale Beer & Wine - Eating Place",
    "42": "On-Sale Beer & Wine - Public Premises",
    "43": "On-Sale Beer and Wine Train",
    "44": "On-Sale Beer Fishing Party Boat",
    "45": "On-Sale Beer and Wine Boat",
    "46": "On-Sale Beer and Wine Airplane",
    "47": "On-Sale General - Eating Place",
    "48": "On-Sale General - Public Premises",
    "49": "On-Sale General - Seasonal",
    "50": "On-Sale General Club",
    "51": "Club",
    "52": "Veteran\u2019s Club",
    "53": "On-Sale General Train",
    "54": "On-Sale General Boat",
    "55": "On-Sale General Airplane",
    "56": "On-Sale General Vessel 1000 Tons",
    "57": "Special On-Sale General",
    "58": "Caterer's Permit",
    "59": "On-Sale Beer and Wine - Seasonal",
    "60": "On-Sale Beer - Seasonal",
    "61": "On-Sale Beer - Public Premises",
    "62": "On-Sale General Dockside, 7000 tons",
    "63": "On-Sale Special Beer and Wine Hospital",
    "64": "Special On-Sale General for Nonprofit Theater Company",
    "65": "Special On-Sale Beer and Wine Symphony",
    "66": "Controlled Access Cabinet Permits",
    "67": "Bed and Breakfast Inn",
    "68": "Portable Bar License",
    "69": "Special On-Sale Beer and Wine Theater",
    "70": "On-Sale General - Restrictive Service",
    "71": "Special On-Sale General for a For-Profit Theater "
          "within the City and County of San Francisco",
    "72": "Special On-Sale General for a For-Profit Theater "
          "within the county of Napa",
    "73": "Special Non-Profit Sales License",
    "74": "Craft Distiller",
    "75": "Brewpub-Restaurant",
    "76": "On-Sale General Maritime Museum Association",
    "77": "Event Permit",
    "78": "On-Sale General for Wine, Food and Art Cultural Museum, "
          "and Educational Center",
    "79": "Certified Farmers' Market Permit",
    "80": "Bed and Breakfast Inn \u2013 General",
    "81": "Wine Sales Event Permit",
    "82": "Wine Direct Shipper Permit",
    "83": "General On-Sale License to Caterer",
    "84": "Certified Farmers' Market Beer Sales Permit",
    "85": "Limited Off-Sale - Wine License",
    "86": "Instructional Tasting License",
    "87": "Special On-Sale General License for Specified Census Tracts "
          "in the City/County of San Francisco",
    "88": "Special On-Sale General License for a For-Profit Cemetery "
          "with Specified Characteristics",
    "90": "On-Sale General \u2013 Music Venue",
    "91": "Beer Manufacturer\u2019s Caterer's Permit",
    "93": "Estate Tasting Event Permit",
    "94": "Craft Distillers Direct Shipper Permit",
    "99": "On-Sale General for Special Use",
}

# Category sets, checked in CATEGORY_PRIORITY order (most
# nightlife-relevant first). Type 75 (brewpub-restaurant) sits in
# hospitality_mfg: it is a manufacturer/retail hybrid with a tasting-room
# character, and hospitality_mfg explicitly covers brewpubs. Type 90 (music
# venue) is nightlife in spirit (bar/nightclub/amusement). Types 67/80
# (bed & breakfast inns) join 66/70 under hotel.
_NIGHTLIFE = {"40", "42", "48", "61", "90"}
_ON_PREMISE = {"41", "47", "49", "50", "51", "52", "57", "59", "60"}
_HOSPITALITY_MFG = {"01", "02", "04", "23", "74", "75"}
_CATERING_EVENT = {"58", "64", "77", "81", "83", "93"}
_HOTEL = {"66", "67", "70", "80"}
_OFF_PREMISE = {"20", "21", "79", "84", "85", "86"}
_WHOLESALE_MFG = {
    "03", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14",
    "15", "16", "17", "18", "19", "22", "24", "25", "26", "27", "28",
    "29", "82", "94",
}
_TEMPORARY = {"31", "34", "37"}

CATEGORY_PRIORITY: tuple[tuple[str, frozenset[str]], ...] = (
    ("nightlife", frozenset(_NIGHTLIFE)),
    ("on_premise", frozenset(_ON_PREMISE)),
    ("hospitality_mfg", frozenset(_HOSPITALITY_MFG)),
    ("catering_event", frozenset(_CATERING_EVENT)),
    ("hotel", frozenset(_HOTEL)),
    ("off_premise", frozenset(_OFF_PREMISE)),
    ("wholesale_mfg", frozenset(_WHOLESALE_MFG)),
    ("temporary", frozenset(_TEMPORARY)),
)

assert all(cat in CATEGORIES for cat, _ in CATEGORY_PRIORITY)


def categorize(codes: list[str]) -> str:
    """Map license-type codes to one of models.CATEGORIES.

    When a file carries several types, the most nightlife-relevant wins:
    nightlife > on_premise > hospitality_mfg > catering_event > hotel >
    off_premise > wholesale_mfg > temporary > other.
    """
    have = {str(code).strip() for code in codes if str(code).strip()}
    for category, members in CATEGORY_PRIORITY:
        if have & members:
            return category
    return "other"


def _clean(value: object) -> str | None:
    """Turn CSV blanks (``" "``) into None, else stripped text."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class CaAbcSource(Source):
    name = "ca_abc_applications"
    title = "California ABC pending/new applications (daily export)"
    state = "CA"
    homepage = "https://www.abc.ca.gov/licensing/licensing-reports/"
    tracks_removals = True
    min_records = 1000

    def contact(self, raw: dict) -> dict:
        for row in raw.get("rows") or []:
            parts = [_clean(row.get(k)) for k in ("Mail Addr 1", "Mail Addr 2")]
            street = " ".join(p for p in parts if p)
            if not street:
                continue
            city, state, zip_code = (_clean(row.get(k)) for k in
                                     ("Mail City", "Mail State", "Mail Zip"))
            tail = " ".join(p for p in (state, zip_code) if p)
            line = ", ".join(p for p in (street, city, tail) if p)
            return {"mailing_address": line}
        return {}

    def fetch(self, http: Http) -> list[Snapshot]:
        return [http.get(EXPORT_URL)]

    def parse(self, snapshots: list[Snapshot]) -> Iterable[Record]:
        for snapshot in snapshots:
            yield from self._parse_snapshot(snapshot)

    def _parse_snapshot(self, snapshot: Snapshot) -> Iterable[Record]:
        with zipfile.ZipFile(io.BytesIO(snapshot.body)) as archive:
            names = archive.namelist()
            csv_names = [n for n in names if n.lower().endswith(".csv")]
            picked = csv_names[0] if csv_names else (names[0] if names else None)
            if picked is None:
                return
            raw_bytes = archive.read(picked)
        # utf-8-sig consumes the BOM; replace keeps one bad byte from
        # killing a ~28 MB file.
        text = raw_bytes.decode("utf-8-sig", errors="replace")
        stream = io.StringIO(text)
        first = stream.readline()
        if "File Number" not in first:
            # Title line (e.g. '"Updated Monday ..."' ); header follows.
            pass
        else:  # pragma: no cover - defensive; real exports carry a title
            stream = io.StringIO(text)
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            return
        reader.fieldnames = [(h or "").strip() for h in reader.fieldnames]

        groups: dict[str, list[dict]] = {}
        for row in reader:
            lic_or_app = _clean(row.get("Lic or App"))
            if lic_or_app != "APP":
                continue
            file_number = _clean(row.get("File Number"))
            if not file_number:
                continue
            groups.setdefault(file_number, []).append(row)

        for file_number in sorted(groups):
            rows = groups[file_number]
            codes = sorted({
                code for code in
                (_clean(r.get("License Type")) for r in rows) if code
            })
            statuses = sorted({
                status for status in
                (_clean(r.get("Type Status")) for r in rows) if status
            })
            first_row = rows[0]
            addr1 = _clean(first_row.get("Prem Addr 1"))
            addr2 = _clean(first_row.get("Prem Addr 2"))
            if addr1 and addr2:
                address = f"{addr1} {addr2}"
            else:
                address = addr1
            yield Record(
                source=self.name,
                source_record_id=file_number,  # leading zeros kept
                source_url=lookup_url(file_number),
                legal_name=_clean(first_row.get("Primary Name")),
                dba=_clean(first_row.get("DBA Name")),
                license_type=",".join(codes) or None,
                license_description=",".join(
                    LICENSE_TYPES.get(code, code) for code in codes
                ) or None,
                application_type=None,  # the export carries none
                status=",".join(statuses) or None,
                application_date=None,  # the export carries none
                address=address,
                city=_clean(first_row.get("Prem City")),
                state=_clean(first_row.get("Prem State")) or "CA",
                zip=_clean(first_row.get("Prem Zip")),  # ZIP+4 kept as given
                county=_clean(first_row.get("Prem County")),
                category=categorize(codes),
                raw={"export_url": EXPORT_URL, "rows": rows},
            )
