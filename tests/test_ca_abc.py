"""Tests for the California ABC daily-export connector (no network).

Reads the committed synthetic fixture
``tests/fixtures/ca_abc_sample.zip`` (fake businesses only), which mirrors
the real export's BOM / title line / header quirks, plus in-memory zips for
edge cases.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from licmon.models import Snapshot
from licmon.sources.ca_abc import (
    EXPORT_URL,
    SOURCE_URL,
    CaAbcSource,
    categorize,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ca_abc_sample.zip"

HEADER = [
    "License Type", "File Number", "Lic or App", "Type Status",
    "Type Orig Iss Date", "Expir Date", "Fee Codes", "Dup Counts",
    "Master Ind", "Term in # of Months", "Geo Code", "District",
    "Primary Name", "Prem Addr 1", "Prem Addr 2", "Prem City",
    "Prem State", "Prem Zip", "DBA Name", "Mail Addr 1", "Mail Addr 2",
    "Mail City", "Mail State", "Mail Zip", "Prem County",
    "Prem Census Tract #",
]


def make_zip(rows: list[list[str]], title: str | None = None) -> bytes:
    """Build a synthetic export zip in memory (fake data only)."""
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM, like the real export
    buf.write((title or '"Updated Tuesday 29th of September 2026 03:50:28 AM"') + "\n")
    writer = csv.writer(buf)
    writer.writerow(HEADER)
    writer.writerows(rows)
    raw = buf.getvalue().encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ABC-DailyDataExport.csv", raw)
    return out.getvalue()


def row(lic_type="41", file_no="00000001", lic_or_app="APP", status="PEND",
        name="FAKE TEST LLC", addr1="1 FAKE ST", addr2=" ",
        city="FRESNO", zipc="93721", dba="FAKE DBA", county="FRESNO"):
    return [lic_type, file_no, lic_or_app, status, " ", " ", "P0", "  ",
            "Y", "12", "0101", "01", name, addr1, addr2, city, "CA", zipc,
            dba, "999 FAKE MAIL ST", " ", "NOWHERE", "CA", "90000",
            county, " "]


class FakeHttp:
    def __init__(self, body: bytes):
        self.body = body
        self.calls: list[str] = []

    def get(self, url, params=None, headers=None):
        self.calls.append(url)
        return Snapshot(url=url, body=self.body)


def parse_bytes(body: bytes):
    return list(CaAbcSource().parse([Snapshot(url=EXPORT_URL, body=body)]))


def test_class_attrs():
    src = CaAbcSource()
    assert src.name == "ca_abc_applications"
    assert src.title == "California ABC pending/new applications (daily export)"
    assert src.state == "CA"
    assert src.homepage == "https://www.abc.ca.gov/licensing/licensing-reports/"
    assert src.tracks_removals is True
    assert src.min_records == 1000


def test_fetch_single_get_unmodified_bytes():
    body = b"PK\x03\x04fake-bytes"
    http = FakeHttp(body)
    snapshots = CaAbcSource().fetch(http)  # type: ignore[arg-type]
    assert http.calls == [EXPORT_URL]
    assert len(snapshots) == 1
    assert snapshots[0].url == EXPORT_URL
    assert snapshots[0].body == body


def test_fixture_records():
    records = parse_bytes(FIXTURE.read_bytes())
    by_id = {r.source_record_id: r for r in records}
    # 17 synthetic rows: 1 LIC row excluded, 16 APP rows in 13 files.
    assert len(records) == 13
    assert "00007891" not in by_id  # LIC row excluded

    multi = by_id["00123456"]
    assert multi.license_type == "47,58"
    assert multi.license_description == (
        "On-Sale General - Eating Place,Caterer's Permit"
    )
    assert multi.status == "PEND"
    assert multi.category == "on_premise"  # 47 outranks 58
    assert multi.legal_name == "FAKE BURRITO BARN LLC"
    assert multi.dba == "FAKE BURRITO BARN"
    assert multi.address == "123 FAKE ST"  # blank addr2 dropped
    assert multi.city == "FRESNO"
    assert multi.state == "CA"
    assert multi.zip == "93721-1234"  # ZIP+4 kept
    assert multi.county == "FRESNO"
    assert multi.application_date is None
    assert multi.application_type is None
    assert multi.source == "ca_abc_applications"
    assert SOURCE_URL == EXPORT_URL
    assert multi.source_url.startswith("https://www.abc.ca.gov/licensing/license-lookup/single-license/?RPTTYPE=12&LICENSE=")
    assert not multi.source_url.endswith("=0")
    assert len(multi.raw["rows"]) == 2

    night = by_id["00007890"]
    assert night.source_record_id == "00007890"  # leading zeros kept
    assert night.source_url.endswith("RPTTYPE=12&LICENSE=7890")
    assert night.raw["export_url"] == EXPORT_URL
    assert night.license_type == "48"
    assert night.license_description == "On-Sale General - Public Premises"
    assert night.category == "nightlife"
    assert night.address == "9 FAKE AVE SUITE 9"  # addr1 + addr2 joined

    blank = by_id["00007892"]
    assert blank.dba is None  # " " blank -> None

    maker = by_id["00007893"]
    assert maker.category == "hospitality_mfg"
    assert maker.status == "ACTIVE"

    dual_night = by_id["00007894"]
    assert dual_night.license_type == "40,61"
    assert dual_night.category == "nightlife"

    assert by_id["00007895"].category == "off_premise"
    assert by_id["00007896"].category == "wholesale_mfg"
    assert by_id["00007897"].category == "hotel"
    assert by_id["00007898"].category == "hospitality_mfg"  # 75 brewpub
    assert by_id["00007899"].category == "catering_event"
    assert by_id["00007900"].category == "temporary"
    assert by_id["00007901"].category == "other"  # 54 boat

    mixed = by_id["00007902"]
    assert mixed.status == "ACTIVE,PEND"  # distinct, sorted
    assert mixed.category == "on_premise"


def test_categorize_priority():
    assert categorize(["48", "47"]) == "nightlife"
    assert categorize(["47", "58"]) == "on_premise"
    assert categorize(["75"]) == "hospitality_mfg"
    assert categorize(["58"]) == "catering_event"
    assert categorize(["66"]) == "hotel"
    assert categorize(["20"]) == "off_premise"
    assert categorize(["09"]) == "wholesale_mfg"
    assert categorize(["31"]) == "temporary"
    assert categorize(["54"]) == "other"
    assert categorize(["99"]) == "other"
    assert categorize([]) == "other"
    assert categorize(["  "]) == "other"


def test_lic_rows_excluded_and_empty_file_number_skipped():
    body = make_zip([
        row("20", "00000001", "LIC", "ACTIVE"),
        row("41", " ", "APP", "PEND"),
        row("41", "00000002", "APP", "PEND"),
    ])
    records = parse_bytes(body)
    assert [r.source_record_id for r in records] == ["00000002"]


def test_unknown_type_code_falls_back_to_code():
    body = make_zip([row("ZZ", "00000003", "APP", "PEND")])
    (record,) = parse_bytes(body)
    assert record.license_type == "ZZ"
    assert record.license_description == "ZZ"
    assert record.category == "other"


def test_empty_zip_parses_to_no_records():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("ABC-DailyDataExport.csv",
                         "\ufeff\"Updated ...\"\n" + ",".join(HEADER) + "\n")
    assert parse_bytes(out.getvalue()) == []
