"""New York State Liquor Authority: current pending license applications.

Dataset: "Current SLA Pending Licenses" on data.ny.gov (f8i8-k2gm), a full
list of applications still pending. Pulled statewide once per day.
"""

from __future__ import annotations

import re
from typing import Iterable

from .. import stage
from ..http import Http
from ..models import Record, Snapshot, parse_date
from . import socrata
from .base import Source

DOMAIN = "data.ny.gov"
DATASET = "f8i8-k2gm"

# Keyed on the dataset's human "description" column (lower-cased).
_CATEGORY_WORDS = [
    # (substring, category) checked in order; first hit wins
    ("night club", "nightlife"),
    ("cabaret", "nightlife"),
    ("tavern", "nightlife"),
    ("bottle club", "nightlife"),
    ("concert hall", "nightlife"),
    ("legitimate theatre", "nightlife"),
    ("bowling", "nightlife"),
    ("club", "on_premise"),  # club / for-profit club / summer club
    ("restaurant brewer", "hospitality_mfg"),
    ("restaurant", "on_premise"),
    ("food & beverage", "on_premise"),
    ("vessel", "on_premise"),
    ("railroad car", "on_premise"),
    ("corporate dining", "on_premise"),
    ("hotel", "hotel"),
    ("bed & breakfast", "hotel"),
    ("catering", "catering_event"),
    ("caterer", "catering_event"),
    ("large gathering venue", "catering_event"),
    ("stadium", "catering_event"),
    ("golf", "catering_event"),
    ("ice skating", "catering_event"),
    ("farm brewer", "hospitality_mfg"),
    ("micro-brewer", "hospitality_mfg"),
    ("farm winery", "hospitality_mfg"),
    ("microfarm winery", "hospitality_mfg"),
    ("farm cidery", "hospitality_mfg"),
    ("farm distiller", "hospitality_mfg"),
    ("micro-distiller", "hospitality_mfg"),
    ("grocery", "off_premise"),
    ("drug store", "off_premise"),
    ("liquor store", "off_premise"),
    ("wine store", "off_premise"),
    ("farm market", "off_premise"),
    ("wholesale", "wholesale_mfg"),
    ("importer", "wholesale_mfg"),
    ("direct shipper", "wholesale_mfg"),
    ("brand owner", "wholesale_mfg"),
    ("distiller", "wholesale_mfg"),
    ("rectifier", "wholesale_mfg"),
    ("brewer", "wholesale_mfg"),
    ("winery", "wholesale_mfg"),
]


# Description wording -> qualify.NIGHTLIFE_LICENSE_POINTS keys. Seen in the
# dataset (probe, 2026-09-29): "Night Club", "Cabaret", "Legitimate Theatre",
# "Summer Concert Hall", "Athletic/Sporting Event/Expositions/Large Gathering
# Venue", "Outdoor Athletic Fields and Stadiums" (and Summer variants).
# "Club" / "For-Profit Club" are membership clubs, not ticketed: left out.
# "Catering Establishment" (banquet halls) is a B license in qualify.py.
_NIGHTLIFE_DESCRIPTIONS = (
    (re.compile(r"NIGHT ?CLUB|CABARET"), "nightclub_cabaret"),
    (re.compile(r"CONCERT HALL"), "music_venue"),
    (re.compile(r"LEGITIMATE THEAT"), "theater"),
    (re.compile(r"STADIUM|ATHLETIC|SPORTING EVENT|LARGE GATHERING|ARENA"), "sports_venue"),
)


def categorize(description: str | None) -> str:
    text = (description or "").lower()
    for word, category in _CATEGORY_WORDS:
        if word in text:
            return category
    return "other"


class NySlaSource(Source):
    name = "ny_sla_pending"
    title = "New York SLA pending license applications"
    state = "NY"
    homepage = f"https://{DOMAIN}/d/{DATASET}"
    tracks_removals = True
    min_records = 200

    def stage(self, rec: Record) -> str | None:
        status = (rec.status or "").upper().replace(" ", "")
        if status == "UNDERREVIEW":
            return stage.IN_REVIEW
        if status == "INTAKECOMPLETE":
            return stage.RECEIVED
        return stage.from_status(rec.status)

    def nightlife_license(self, rec: Record) -> tuple[str, ...]:
        text = (rec.license_description or "").upper()
        return tuple(key for pattern, key in _NIGHTLIFE_DESCRIPTIONS if pattern.search(text))

    def fetch(self, http: Http) -> list[Snapshot]:
        return socrata.fetch_all(http, DOMAIN, DATASET, order="application_id")

    def parse(self, snapshots: list[Snapshot]) -> Iterable[Record]:
        for row in socrata.rows(snapshots):
            app_id = (row.get("application_id") or "").strip()
            if not app_id:
                continue
            address = row.get("actual_address_of_premises")
            extra = row.get("additional_address_information")
            if extra:
                address = f"{address or ''} {extra}"
            yield Record(
                source=self.name,
                source_record_id=app_id,
                # Row-level link into the official dataset (SODA filter).
                source_url=(f"https://{DOMAIN}/resource/{DATASET}.json"
                            f"?application_id={app_id}"),
                legal_name=row.get("legalname"),
                dba=row.get("dba"),
                license_type=row.get("class"),
                license_description=row.get("description"),
                application_type="NEW",  # dataset holds pending applications
                status=row.get("status"),
                application_date=parse_date(row.get("received_date")),
                address=address,
                city=row.get("city"),
                state="NY",
                zip=row.get("zip_code"),
                county=row.get("premises_county"),
                category=categorize(row.get("description")),
                raw=row,
            )
