"""Shared data structures for source connectors and the pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

# Fields whose change counts as a "material" change (PRD: status, business
# name, DBA, address, license type, application date). Application type is
# included because a renewal turning into a change-of-location is meaningful.
MATERIAL_FIELDS = (
    "status",
    "legal_name",
    "dba",
    "address",
    "city",
    "zip",
    "license_type",
    "application_type",
    "application_date",
)

# License categories a connector may assign. qualify.py scores on these.
CATEGORIES = (
    "nightlife",  # bar, tavern, nightclub, cabaret, lounge, late-hour, amusement
    "on_premise",  # restaurant / on-premises consumption
    "hospitality_mfg",  # brewpub, taproom, tasting room, winery/distillery w/ retail
    "catering_event",  # caterer, event venue, special event
    "hotel",
    "off_premise",  # package/liquor store, grocery, convenience, drug store
    "wholesale_mfg",  # wholesaler, importer, manufacturer, shipper w/o hospitality
    "temporary",  # temporary / special one-day permits
    "other",
)


@dataclass
class Snapshot:
    """One raw payload exactly as fetched from an official source."""

    url: str
    body: bytes
    content_type: str = "application/octet-stream"
    fetched_at: datetime | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


@dataclass
class Record:
    """A normalized license-application record from any source."""

    source: str
    source_record_id: str
    source_url: str
    legal_name: str | None = None
    dba: str | None = None
    license_type: str | None = None  # source code(s), e.g. "MB" or "41,58"
    license_description: str | None = None  # human-readable type
    application_type: str | None = None  # NEW, RENEWAL, CHANGE OF LOCATION, ...
    status: str | None = None
    application_date: date | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    county: str | None = None
    category: str = "other"  # one of CATEGORIES, set by the connector
    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category {self.category!r}")
        for name in ("legal_name", "dba", "license_type", "license_description",
                     "application_type", "status", "address", "city", "state",
                     "zip", "county"):
            value = getattr(self, name)
            if isinstance(value, str):
                value = " ".join(value.split())
                setattr(self, name, value or None)

    def material(self, fields: tuple[str, ...] = MATERIAL_FIELDS) -> dict:
        out = {}
        for name in fields:
            value = getattr(self, name)
            if isinstance(value, date):
                value = value.isoformat()
            if isinstance(value, str):
                value = value.upper()
            out[name] = value
        return out

    def material_hash(self, fields: tuple[str, ...] = MATERIAL_FIELDS) -> str:
        blob = json.dumps(self.material(fields), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.application_date:
            d["application_date"] = self.application_date.isoformat()
        return d


_ADDR_WORDS = {
    "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "ROAD": "RD",
    "DRIVE": "DR", "LANE": "LN", "PLACE": "PL", "COURT": "CT", "PARKWAY": "PKWY",
    "HIGHWAY": "HWY", "EXPRESSWAY": "EXPY", "FREEWAY": "FWY", "SUITE": "STE",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "UNIT": "STE",
    "#": "STE",
}


def venue_key(rec: "Record") -> str:
    """Key that groups several license applications for one premises
    (e.g. a TX bar filing MB + FB + LH) into one lead."""
    street = re.sub(r"[^A-Z0-9# ]", " ", (rec.address or "").upper())
    words = [_ADDR_WORDS.get(w, w) for w in street.split()]
    zip5 = (rec.zip or "")[:5]
    if not words or not zip5:
        return f"{rec.source}|{rec.source_record_id}"
    return f"{(rec.state or '').upper()}|{zip5}|{' '.join(words)}"


def parse_date(value) -> date | None:
    """Parse the date formats seen in our sources; None if blank/unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
                "%m/%d/%Y", "%m/%d/%y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def clean_id(value) -> str | None:
    """Normalize numeric-looking ids like '585211.0' -> '585211'."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or None
