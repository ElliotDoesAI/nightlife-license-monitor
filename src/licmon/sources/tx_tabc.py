"""Texas Alcoholic Beverage Commission: pending original (new) applications.

Dataset: "Pending Original New Primary and Subordinate License Application(s)"
on data.texas.gov (mxm5-tdpj). Holds original applications with status
Received / In Review, as of midnight the prior day. Pulled statewide daily.
"""

from __future__ import annotations

from typing import Iterable

from .. import stage
from ..http import Http
from ..models import Record, Snapshot, clean_id, parse_date
from . import socrata
from .base import Source

DOMAIN = "data.texas.gov"
DATASET = "mxm5-tdpj"

# Verified against https://www.tabc.texas.gov/services/tabc-licenses-permits/
# tabc-license-permit-types/ (Sep 2026).
LICENSE_TYPES = {
    "MB": ("Mixed Beverage Permit", "on_premise"),
    "FB": ("Food and Beverage Certificate", "on_premise"),
    "LH": ("Late Hours Certificate", "nightlife"),
    "BG": ("Wine and Malt Beverage Retailer's Permit", "on_premise"),
    "BE": ("Retail Dealer's On-Premise License", "on_premise"),
    "BP": ("Brewpub License", "hospitality_mfg"),
    "N": ("Private Club Registration Permit", "on_premise"),
    "NE": ("Private Club Exemption Certificate", "on_premise"),
    "BQ": ("Wine and Malt Beverage Retailer's Off-Premise Permit", "off_premise"),
    "BF": ("Retail Dealer's Off-Premise License", "off_premise"),
    "P": ("Package Store Permit", "off_premise"),
    "Q": ("Wine-Only Package Store Permit", "off_premise"),
    "LP": ("Local Distributor's Permit", "wholesale_mfg"),
    "BW": ("Brewer's License", "hospitality_mfg"),
    "G": ("Winery Permit", "hospitality_mfg"),
    "D": ("Distiller's and Rectifier's Permit", "hospitality_mfg"),
    "DS": ("Out-of-State Winery Direct Shipper's Permit", "wholesale_mfg"),
    "BN": ("Nonresident Brewer's License", "wholesale_mfg"),
    "S": ("Nonresident Seller's Permit", "wholesale_mfg"),
    "BB": ("General Distributor's License", "wholesale_mfg"),
    "BC": ("Branch Distributor's License", "wholesale_mfg"),
    "W": ("Wholesaler's Permit", "wholesale_mfg"),
    "X": ("General Class B Wholesaler's Permit", "wholesale_mfg"),
    "J/JD": ("Bonded Warehouse Permit", "wholesale_mfg"),
    "E": ("Local Cartage Permit", "wholesale_mfg"),
    "ET": ("Third-Party Local Cartage Permit", "wholesale_mfg"),
    "PR": ("Promotional Permit", "wholesale_mfg"),
    "NT": ("Nonprofit Entity Temporary Event Permit", "temporary"),
}


def categorize(code: str | None) -> str:
    return LICENSE_TYPES.get((code or "").strip().upper(), (None, "other"))[1]


class TxTabcSource(Source):
    name = "tx_tabc_pending"
    title = "Texas TABC pending original applications"
    state = "TX"
    homepage = f"https://{DOMAIN}/d/{DATASET}"
    tracks_removals = True
    min_records = 100

    def stage(self, rec: Record) -> str | None:
        # Dataset holds "Received" and "Pending - In Review" (en dash upstream).
        status = (rec.status or "").upper()
        if "REVIEW" in status:
            return stage.IN_REVIEW
        if "RECEIVED" in status:
            return stage.RECEIVED
        return stage.from_status(rec.status)

    def nightlife_license(self, rec: Record) -> tuple[str, ...]:
        return ("late_hours",) if (rec.license_type or "").upper() == "LH" else ()

    def fetch(self, http: Http) -> list[Snapshot]:
        return socrata.fetch_all(http, DOMAIN, DATASET, order="applicationid")

    def parse(self, snapshots: list[Snapshot]) -> Iterable[Record]:
        for row in socrata.rows(snapshots):
            app_id = clean_id(row.get("applicationid"))
            if not app_id:
                continue
            code = (row.get("license_type") or "").strip().upper()
            address = row.get("address")
            if row.get("address_2"):
                address = f"{address or ''} {row['address_2']}"
            zip_code = (row.get("zip") or "").strip()
            if len(zip_code) == 9 and zip_code.isdigit():
                zip_code = f"{zip_code[:5]}-{zip_code[5:]}"
            yield Record(
                source=self.name,
                source_record_id=app_id,
                source_url=(f"https://{DOMAIN}/resource/{DATASET}.json"
                            f"?applicationid={row.get('applicationid')}"),
                legal_name=row.get("owner"),
                dba=row.get("trade_name"),
                license_type=code or None,
                license_description=LICENSE_TYPES.get(code, (code, None))[0],
                application_type="ORIGINAL",
                status=row.get("applicationstatus"),
                application_date=parse_date(row.get("submission_date")),
                address=address,
                city=row.get("city"),
                state=row.get("state") or "TX",
                zip=zip_code or None,
                county=row.get("county"),
                category=categorize(code),
                raw=row,
            )
