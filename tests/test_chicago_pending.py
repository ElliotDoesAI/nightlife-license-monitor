"""Tests for the Chicago BACP pending-applications connector (no network)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from licmon.models import Snapshot
from licmon.sources.chicago_pending import (
    LIQUOR_URL,
    PPA_URL,
    ChicagoPendingSource,
    categorize,
)

FIXTURE = Path(__file__).parent / "fixtures" / "chicago_pending_sample.html"


def _parse_fixture(url: str = LIQUOR_URL) -> list:
    src = ChicagoPendingSource()
    body = FIXTURE.read_bytes()
    return list(src.parse([Snapshot(url=url, body=body)]))


def test_class_attrs():
    src = ChicagoPendingSource()
    assert src.name == "chicago_bacp_pending"
    assert src.title == (
        "Chicago BACP pending liquor/PPA applications (6-week notice list)"
    )
    assert src.state == "IL"
    assert src.homepage == "https://webapps1.chicago.gov/bacplicenseapplications/"
    assert src.tracks_removals is False
    assert src.min_records == 5


def test_fetch_gets_both_lists_and_preserves_bytes():
    bodies = {LIQUOR_URL: b"<html>liquor</html>", PPA_URL: b"<html>ppa</html>"}
    calls = []

    class FakeHttp:
        def get(self, url, params=None, headers=None):
            calls.append(url)
            return Snapshot(url=url, body=bodies[url])

    src = ChicagoPendingSource()
    snapshots = src.fetch(FakeHttp())
    assert calls == [LIQUOR_URL, PPA_URL]
    assert [(s.url, s.body) for s in snapshots] == [
        (LIQUOR_URL, bodies[LIQUOR_URL]),
        (PPA_URL, bodies[PPA_URL]),
    ]


def test_parse_record_count():
    assert len(_parse_fixture()) == 12


def test_parse_common_fields():
    records = _parse_fixture()
    rec = next(r for r in records if r.dba == "The Pretend Owl")
    assert rec.source == "chicago_bacp_pending"
    assert rec.legal_name == "Night Owl Tavern LLC"
    assert rec.address == "4500 N Makebelieve St, Suite/Apt: 101"
    assert rec.city == "CHICAGO"
    assert rec.state == "IL"
    assert rec.zip is None  # list addresses carry no ZIP
    assert rec.county == "Cook"
    assert rec.license_type == "Tavern"
    assert rec.license_description == "Tavern"
    assert rec.application_type == "NEW"
    assert rec.status == "PENDING NOTICE"
    assert rec.application_date == date(2026, 9, 8)
    assert rec.category == "nightlife"
    assert rec.source_url == (
        "https://webapps1.chicago.gov/bacplicenseapplications/"
        "ownership?acct=600003&site=1"
    )
    assert rec.raw["Legal Name"] == "Night Owl Tavern LLC"
    assert rec.raw["Doing Business As"] == "The Pretend Owl"
    assert rec.raw["Address"] == "4500 N Makebelieve St, Suite/Apt: 101"
    assert rec.raw["Application Applied for"] == "Tavern"
    assert rec.raw["Date of Payment"] == "09/08/2026"


def test_ids_bind_account_to_row_fields():
    records = _parse_fixture()
    harborline = [r for r in records if r.dba == "Harborline Taproom"]
    assert len(harborline) == 2
    # Same account+site, different license types -> distinct stable ids.
    ids = sorted(r.source_record_id for r in harborline)
    assert ids[0] != ids[1]
    assert all(i.startswith("600001-1-") for i in ids)
    # Same account+site+type but different payment dates -> distinct ids.
    hall = [r for r in records if r.dba == "Fictional Food Hall"]
    assert len(hall) == 2
    assert hall[0].source_record_id != hall[1].source_record_id
    assert {r.application_date for r in hall} == {
        date(2026, 9, 2), date(2026, 9, 3)}


def test_row_without_ownership_link_falls_back_to_list_url():
    (rec,) = [r for r in _parse_fixture() if r.dba == "Fable Corner Store"]
    assert rec.source_record_id.startswith("noid-")
    assert rec.source_url == LIQUOR_URL
    assert rec.category == "off_premise"


def test_ids_deterministic_regardless_of_row_order():
    body = FIXTURE.read_bytes()
    src = ChicagoPendingSource()
    forward = sorted(
        r.source_record_id
        for r in src.parse([Snapshot(url=LIQUOR_URL, body=body)])
    )
    # Reverse the tbody rows and re-parse: ids must not change.
    import re as _re
    head, rest = body.split(b"<tbody>", 1)
    inner, tail = rest.split(b"</tbody>", 1)
    rows = _re.findall(rb"<tr\b.*?</tr\s*>", inner, _re.S | _re.I)
    assert len(rows) == 12
    reversed_body = head + b"<tbody>" + b"".join(rows[::-1]) + b"</tbody>" + tail
    backward = sorted(
        r.source_record_id
        for r in src.parse([Snapshot(url=LIQUOR_URL, body=reversed_body)])
    )
    assert forward == backward


def test_parse_ppa_page_rows():
    records = {r.dba: r for r in _parse_fixture(url=PPA_URL)}
    assert records["The Fable Room"].category == "nightlife"
    assert records["The Fable Room"].license_type == (
        "Public Place Of Amusement"
    )
    assert records["Fable Winter Market"].category == "catering_event"
    # Fallback source_url uses the snapshot's own (PPA) list URL.
    assert records["Fable Corner Store"].source_url == PPA_URL


def test_categorize():
    assert categorize("Tavern") == "nightlife"
    assert categorize("Late Hour") == "nightlife"
    assert categorize("Late-Hour") == "nightlife"
    assert categorize("Public Place Of Amusement") == "nightlife"
    assert categorize("Consumption On Premises - Incidental Activity") == (
        "on_premise"
    )
    assert categorize("Outdoor Patio") == "on_premise"
    assert categorize("Caterer's Liquor License") == "catering_event"
    assert categorize("Indoor Special Event") == "catering_event"
    assert categorize("Package Goods") == "off_premise"
    assert categorize("Something Else Entirely") == "other"
    assert categorize(None) == "other"
    assert categorize("") == "other"


def test_categorize_multi_type_picks_most_nightlife_relevant():
    assert categorize("Outdoor Patio; Tavern") == "nightlife"
    assert categorize("Package Goods / Consumption On Premises") == "on_premise"
    assert categorize("Package Goods; Indoor Special Event") == "catering_event"
    assert categorize("Mystery License; Package Goods") == "off_premise"
