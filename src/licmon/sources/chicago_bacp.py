"""City of Chicago BACP business licenses: liquor and amusement applications.

Dataset: "Business Licenses" on data.cityofchicago.org (r5kz-chrr). Rows are
license applications (new issue, change of location, expansion, ...). The city
publishes rows around issuance, so this is a rolling window of recent
non-renewal liquor/amusement applications rather than a pending list.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from .. import stage
from ..http import Http
from ..models import Record, Snapshot, parse_date
from . import socrata
from .base import Source

DOMAIN = "data.cityofchicago.org"
DATASET = "r5kz-chrr"
WINDOW_DAYS = 180

LICENSE_CODES = {
    "1470": "nightlife",  # Tavern
    "1471": "nightlife",  # Late Hour
    "1050": "nightlife",  # Public Place of Amusement
    "1475": "on_premise",  # Consumption on Premises - Incidental Activity
    "1477": "on_premise",  # Outdoor Patio
    "1058": "catering_event",  # Indoor Special Event
    "1481": "catering_event",  # Caterer's Liquor License
    "1474": "off_premise",  # Package Goods
}

APPLICATION_TYPES = {
    "ISSUE": "NEW",
    "C_LOC": "CHANGE OF LOCATION",
    "C_EXPA": "EXPANSION",
    "C_CAPA": "CHANGE OF ACTIVITY",
    "C_SBA": "CHANGE OF BUSINESS ACTIVITY",
    "RENEW": "RENEWAL",
}


# license_status values seen in the dataset (probe, 2026-09-29): AAI = issued
# and active, AAC = cancelled. Every row in the window already carries
# date_issued, and conditional_approval (Y/N) is set on issued rows too, so
# a row here is a license that has been issued.
LICENSED_STATUSES = {"AAI"}

# Nightlife license codes -> qualify.NIGHTLIFE_LICENSE_POINTS keys.
NIGHTLIFE_CODES = {"1050": "ppa", "1471": "late_hours"}


def categorize(code: str | None) -> str:
    return LICENSE_CODES.get((code or "").strip(), "other")


class ChicagoBacpSource(Source):
    name = "chicago_bacp_liquor"
    title = "Chicago BACP liquor & amusement license applications"
    state = "IL"
    homepage = f"https://{DOMAIN}/d/{DATASET}"
    tracks_removals = False  # rolling window
    min_records = 10

    def __init__(self, today: date | None = None):
        self.today = today

    def stage(self, rec: Record) -> str | None:
        status = (rec.status or "").strip().upper()
        if status in LICENSED_STATUSES:
            return stage.LICENSED
        return stage.from_status(rec.status)  # AAC (cancelled) -> None

    def nightlife_license(self, rec: Record) -> tuple[str, ...]:
        key = NIGHTLIFE_CODES.get((rec.license_type or "").strip())
        return (key,) if key else ()

    def fetch(self, http: Http) -> list[Snapshot]:
        since = ((self.today or date.today()) - timedelta(days=WINDOW_DAYS)).isoformat()
        codes = ",".join(f"'{c}'" for c in sorted(LICENSE_CODES))
        where = (
            f"license_code in ({codes}) AND application_type != 'RENEW' AND "
            f"(application_created_date >= '{since}' OR date_issued >= '{since}')"
        )
        return socrata.fetch_all(http, DOMAIN, DATASET, where=where, order="id")

    def parse(self, snapshots: list[Snapshot]) -> Iterable[Record]:
        for row in socrata.rows(snapshots):
            rid = (row.get("id") or "").strip()
            if not rid:
                continue
            app_type = (row.get("application_type") or "").strip().upper()
            yield Record(
                source=self.name,
                source_record_id=rid,
                source_url=f"https://{DOMAIN}/resource/{DATASET}.json?id={rid}",
                legal_name=row.get("legal_name"),
                dba=row.get("doing_business_as_name"),
                license_type=row.get("license_code"),
                license_description=row.get("license_description"),
                application_type=APPLICATION_TYPES.get(app_type, app_type or None),
                status=row.get("license_status"),
                application_date=parse_date(row.get("application_created_date")),
                address=row.get("address"),
                city=row.get("city"),
                state=row.get("state") or "IL",
                zip=row.get("zip_code"),
                county="Cook",
                category=categorize(row.get("license_code")),
                raw=row,
            )
