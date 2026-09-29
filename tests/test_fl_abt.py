"""Tests for the Florida ABT retail-license connector (no network).

Reads the committed synthetic fixture ``tests/fixtures/fl_abt_sample.csv``
(fake businesses only), which mirrors the real extract's all-quoted CRLF
layout, plus in-memory CSVs for edge cases.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

from licmon.metros import assign_metro
from licmon.models import Snapshot
from licmon.qualify import qualify
from licmon.sources.fl_abt import (
    EXPORT_URL,
    SOURCE_URL,
    FlAbtSource,
    categorize,
    county_name,
    license_description,
    license_type_code,
    status_text,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fl_abt_sample.csv"

HEADER = ["Board", "Profession", "Owner Name", "Series", "Modifier",
          "Mail Address 1", "Mail Address 2", "Mail Address 3", "Mail City",
          "Mail State", "Mail ZIP", "Mail County", "DBA",
          "Location Address 1", "Location Address 2", "Location Address 3",
          "Location City", "Location State", "Location ZIP",
          "Location County", "License Number", "Primary Status",
          "Secondary Status", "Original Licensure Date", "Effective Date",
          "Expiration Date", "Tax Stamp Designation", "Smoking Designation",
          "Retail Tobacco Indicator"]


def make_csv(rows: list[list[str]]) -> bytes:
    """Build a synthetic extract in memory (fake data only)."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(HEADER)
    writer.writerows(rows)
    return buf.getvalue().encode("latin-1")


def row(owner="FAKE TEST LLC", series="4COP", mod="", dba="FAKE BAR",
        a1="1 FAKE ST", a2="", a3="", city="MIAMI", zipc="33130",
        county="23", lic="TST2399999", ps="20", ss="20", orig="09/12/2026"):
    cells = ["400", "4006", owner, series, mod, "9 FAKE MAIL ST", "", "",
             "MIAMI", "FL", "33130", "23", dba, a1, a2, a3, city, "FL",
             zipc, county, lic, ps, ss, orig, "09/15/2026", "09/30/2027",
             "", "", ""]
    assert len(cells) == len(HEADER)
    return cells


class FakeHttp:
    def __init__(self, body: bytes):
        self.body = body
        self.calls: list[str] = []

    def get(self, url, params=None, headers=None):
        self.calls.append(url)
        return Snapshot(url=url, body=self.body)


def parse_bytes(body: bytes):
    return list(FlAbtSource().parse([Snapshot(url=EXPORT_URL, body=body)]))


def test_class_attrs():
    src = FlAbtSource()
    assert src.name == "fl_abt_licenses"
    assert src.title == "Florida ABT retail alcoholic beverage licenses (daily extract)"
    assert src.state == "FL"
    assert src.homepage == ("https://www2.myfloridalicense.com/alcoholic-beverages-and-tobacco/"
                            "daily-license-status-reporting-data/")
    assert src.tracks_removals is True
    # Full extract is ~50k rows; the floor guards against format changes.
    # Small fixtures test parse() directly, never the floor.
    assert src.min_records == 20000


def test_fetch_single_get_unmodified_bytes():
    body = '"Board","Profession"\r\n"400","4006"\r\n'.encode("latin-1")
    http = FakeHttp(body)
    snapshots = FlAbtSource().fetch(http)  # type: ignore[arg-type]
    assert http.calls == [EXPORT_URL]
    assert len(snapshots) == 1
    assert snapshots[0].url == EXPORT_URL
    assert snapshots[0].body == body
    assert SOURCE_URL == EXPORT_URL


def test_fixture_records():
    records = parse_bytes(FIXTURE.read_bytes())
    assert len(records) == 15
    by_id = {r.source_record_id: r for r in records}
    assert len(by_id) == 15  # one record per license number

    bar = by_id["TST2300001"]
    assert bar.source == "fl_abt_licenses"
    assert bar.source_url == EXPORT_URL
    assert bar.legal_name == "NEON PALMS LOUNGE LLC"
    assert bar.dba == "NEON PALMS COCKTAIL LOUNGE"
    assert bar.license_type == "4COP"
    assert "Quota liquor" in (bar.license_description or "")
    assert bar.category == "nightlife"
    assert bar.application_type == "NEW LICENSE"
    assert bar.application_date == date(2026, 9, 12)
    assert bar.status == "Current"  # secondary Active is folded in
    assert bar.address == "900 BISCAYNE BAY TERRACE SUITE 200"
    assert bar.city == "MIAMI"
    assert bar.state == "FL"
    assert bar.zip == "33130"
    assert bar.county == "MIAMI-DADE"  # code 23
    assert bar.raw["License Number"] == "TST2300001"

    restaurant = by_id["TST1600002"]
    assert restaurant.license_type == "4COP-SFS"
    assert restaurant.category == "on_premise"
    assert restaurant.county == "BROWARD"

    package = by_id["TST2600003"]
    assert package.license_type == "2APS"
    assert package.category == "off_premise"
    assert package.county == "DUVAL"

    assert by_id["TST5800004"].category == "on_premise"  # 2COP
    caterer = by_id["TST3900005"]
    assert caterer.category == "catering_event"
    # All three location-address lines joined with spaces.
    assert caterer.address == ("4400 BAYSHORE GARDENS PKWY BUILDING B "
                               "STORAGE ROOM 4")
    assert by_id["TST6200006"].category == "hotel"  # 4COP-S
    assert by_id["TST4700007"].category == "on_premise"  # 11C club
    assert by_id["TST4700007"].county == "LEON"
    assert by_id["TST6000008"].category == "on_premise"  # 11CG golf
    assert by_id["TST6900009"].category == "off_premise"  # 1APS
    assert by_id["TST5900010"].category == "off_premise"  # 3PS
    assert by_id["TST4500011"].category == "on_premise"  # 5COP-SFS
    assert by_id["TST2000012"].category == "other"  # 12RT pari-mutuel
    assert by_id["TST2000012"].application_date is None  # blank orig date
    assert by_id["TST2000012"].status == "Current / Inactive"
    escrow = by_id["TST6100013"]
    assert escrow.status == "Escrow / Transfer pending"
    assert escrow.category == "catering_event"  # 11PA
    assert by_id["TST3700014"].category == "hotel"  # 7COP-S
    revoked = by_id["TST6500015"]
    assert revoked.status == "Revoked / Inactive"
    assert revoked.county == "ST. JOHNS"  # code 65


def test_county_codes():
    assert county_name("23") == "MIAMI-DADE"
    assert county_name("16") == "BROWARD"
    assert county_name("39") == "HILLSBOROUGH"
    assert county_name("60") == "PALM BEACH"
    assert county_name("62") == "PINELLAS"
    assert county_name("65") == "ST. JOHNS"
    assert county_name("58") == "ORANGE"
    assert county_name("12") == "BAKER"
    assert county_name("99") is None  # unknown code
    assert county_name("") is None
    assert county_name(None) is None


def test_categorize_mapping():
    assert categorize("4COP", "") == "nightlife"
    assert categorize("5COP", "") == "nightlife"
    assert categorize("6COP", "") == "nightlife"
    assert categorize("4COP", "NULL") == "nightlife"  # real-file quirk
    assert categorize("4COP", "SFS") == "on_premise"
    assert categorize("4COP", "SR") == "on_premise"
    assert categorize("2COP", "") == "on_premise"
    assert categorize("1COP", "") == "on_premise"
    assert categorize("4COP", "S") == "hotel"
    assert categorize("8COP", "SH") == "hotel"
    assert categorize("4COP", "SBX") == "on_premise"
    assert categorize("4COP", "SCX") == "catering_event"
    assert categorize("4COP", "SPX") == "other"
    assert categorize("4COP", "SAL") == "other"
    assert categorize("4COP", "SAX") == "other"
    assert categorize("4COP", "ZZZ") == "other"  # unknown modifier: conservative
    assert categorize("2APS", "") == "off_premise"
    assert categorize("1APS", "") == "off_premise"
    assert categorize("3PS", "") == "off_premise"
    assert categorize("3DPS", "") == "off_premise"
    assert categorize("11C", "") == "on_premise"
    assert categorize("11CG", "") == "on_premise"
    assert categorize("11AL", "") == "on_premise"
    assert categorize("13CT", "") == "catering_event"
    assert categorize("11PA", "") == "catering_event"
    assert categorize("12RT", "") == "other"
    assert categorize("14BC", "") == "other"
    assert categorize("RTS", "") == "other"
    assert categorize("HBX", "") == "other"
    assert categorize("ODP", "") == "temporary"
    assert categorize("TSE", "") == "temporary"
    assert categorize("", "") == "other"
    assert categorize(None, None) == "other"


def test_license_type_and_status_helpers():
    assert license_type_code("4COP", "") == "4COP"
    assert license_type_code("4COP", "SFS") == "4COP-SFS"
    assert license_type_code("4COP", "NULL") == "4COP"
    assert license_type_code("", "") is None
    assert "Quota liquor" in (license_description("4COP", "SFS") or "")
    assert "restaurant" in (license_description("4COP", "SFS") or "").lower()
    assert license_description("ZZ", "") == "ZZ"
    assert status_text("20", "20") == "Current"
    assert status_text("20", "") == "Current"
    assert status_text("11", "20") == "Withdrawn (application withdrawn)"
    assert status_text("61", "10") == "Revoked / Inactive"
    assert status_text("", "") is None


def test_assign_metro_on_parsed_counties():
    records = parse_bytes(FIXTURE.read_bytes())
    by_id = {r.source_record_id: r for r in records}
    assert assign_metro("FL", by_id["TST2300001"].county, "MIAMI") == \
        "Miami-Fort Lauderdale-West Palm Beach"
    assert assign_metro("FL", by_id["TST1600002"].county, None) == \
        "Miami-Fort Lauderdale-West Palm Beach"
    assert assign_metro("FL", by_id["TST5800004"].county, "ORLANDO") == "Orlando"
    assert assign_metro("FL", by_id["TST5900010"].county, None) == "Orlando"
    assert assign_metro("FL", by_id["TST3900005"].county, "TAMPA") == \
        "Tampa-St. Petersburg"
    assert assign_metro("FL", by_id["TST6200006"].county, None) == \
        "Tampa-St. Petersburg"
    assert assign_metro("FL", by_id["TST2600003"].county, "JACKSONVILLE") == \
        "Jacksonville"
    assert assign_metro("FL", by_id["TST6500015"].county, None) == "Jacksonville"
    assert assign_metro("FL", by_id["TST4700007"].county, "TALLAHASSEE") is None
    # Variant spellings still resolve.
    assert assign_metro("FL", "Dade", None) == "Miami-Fort Lauderdale-West Palm Beach"
    assert assign_metro("FL", "St Johns", None) == "Jacksonville"


def test_qualify_new_4cop_bar_in_miami_dade():
    records = parse_bytes(FIXTURE.read_bytes())
    bar = next(r for r in records if r.source_record_id == "TST2300001")
    metro = assign_metro(bar.state, bar.county, bar.city)
    assert metro == "Miami-Fort Lauderdale-West Palm Beach"
    q = qualify(bar, metro)
    assert q.qualified
    assert "new application" in q.reason

    # A revoked license in a metro does not qualify.
    revoked = next(r for r in records if r.source_record_id == "TST6500015")
    q_revoked = qualify(revoked, assign_metro(revoked.state, revoked.county,
                                              revoked.city))
    assert not q_revoked.qualified

    # A package store in a metro is excluded by category.
    package = next(r for r in records if r.source_record_id == "TST2600003")
    q_pkg = qualify(package, assign_metro(package.state, package.county,
                                          package.city))
    assert not q_pkg.qualified


def test_blank_license_number_skipped_and_duplicates_keep_latest_date():
    body = make_csv([
        row(lic="", dba="NO LICENSE NUMBER"),
        row(lic="TST2399999", dba="OUTGOING HOLDER", ps="20", ss="35",
            orig="01/01/1999"),
        row(lic="TST2399999", dba="INCOMING HOLDER", ps="21", ss="34",
            orig="09/09/2026"),
    ])
    records = parse_bytes(body)
    assert [r.dba for r in records] == ["INCOMING HOLDER"]
    assert records[0].application_date == date(2026, 9, 9)
    assert records[0].status == "Temporary certificate / Code 34"


def test_duplicate_tie_keeps_first_row():
    body = make_csv([
        row(lic="TST2399999", dba="FIRST SEEN"),
        row(lic="TST2399999", dba="TIED DATE DROPPED"),
    ])
    records = parse_bytes(body)
    assert [r.dba for r in records] == ["FIRST SEEN"]
