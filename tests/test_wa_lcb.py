"""Tests for the Washington LCB connector (no network; synthetic fixture)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from licmon.models import Snapshot
from licmon.sources.wa_lcb import URL, WaLcbSource, categorize

FIXTURE = Path(__file__).parent / "fixtures" / "wa_lcb_sample.html"


def _parse_fixture() -> list:
    src = WaLcbSource()
    body = FIXTURE.read_bytes()
    records = list(src.parse([Snapshot(url=URL, body=body)]))
    return sorted(records, key=lambda r: r.source_record_id)


def test_class_attrs():
    src = WaLcbSource()
    assert src.name == "wa_lcb_actions"
    assert src.title == (
        "Washington LCB license applications/approvals/discontinuances (30 days)"
    )
    assert src.state == "WA"
    assert src.homepage == "https://lcb.wa.gov/resources/licensing-actions"
    assert src.tracks_removals is False
    assert src.min_records == 50


def test_fetch_uses_single_get_and_preserves_bytes():
    body = b"<html>fake</html>"

    calls = []

    class FakeHttp:
        def get(self, url, params=None, headers=None):
            calls.append(url)
            return Snapshot(url=url, body=body)

    src = WaLcbSource()
    snapshots = src.fetch(FakeHttp())
    assert calls == [URL]
    assert len(snapshots) == 1
    assert snapshots[0].body == body
    assert snapshots[0].url == URL


def test_parse_record_count_and_ids():
    records = _parse_fixture()
    # 10 tbodies: one exact duplicate removed, one key merged across sections.
    assert [r.source_record_id for r in records] == [
        "900001:NEW APPLICATION",
        "900002:ASSUMPTION",
        "900002:DISC. LIQUOR SALES",
        "900003:NEW APPLICATION",
        "900004:RENEWAL",
        "900005:DISCONTINUED",
        "900006:ASSUMPTION",
        "900007:CHANGE OF LOCATION",
    ]


def test_parse_application_record_fields():
    records = {r.source_record_id: r for r in _parse_fixture()}
    rec = records["900001:NEW APPLICATION"]
    assert rec.source == "wa_lcb_actions"
    assert rec.status == "APPLICATION"
    assert rec.application_date == date(2026, 9, 20)
    assert rec.legal_name == "BLUE HERON LLC"
    assert rec.dba == "BLUE HERON TAVERN"
    assert rec.address == "123 FAKE ST SUITE 200"
    assert rec.city == "FAKETOWN"
    assert rec.state == "WA"
    assert rec.zip == "99901"
    assert rec.county is None
    assert rec.license_type == "TAVERN - BEER/WINE"
    assert rec.license_description == "TAVERN - BEER/WINE"
    assert rec.application_type == "NEW APPLICATION"
    assert rec.category == "nightlife"
    assert rec.source_url == URL
    assert rec.raw["Contact Phone"] == "555-0100"
    assert rec.raw["section"] == "APPLICATION"


def test_exact_duplicate_tbody_deduped():
    records = _parse_fixture()
    assert (
        len([r for r in records if r.source_record_id == "900001:NEW APPLICATION"])
        == 1
    )


def test_multi_type_license_picks_nightlife():
    records = {r.source_record_id: r for r in _parse_fixture()}
    rec = records["900002:ASSUMPTION"]
    assert rec.license_type == "CATERING; SPIRITS/BR/WN REST LOUNGE +"
    assert rec.category == "nightlife"
    assert rec.legal_name == "HARBOUR LIGHTS INC"


def test_stage_precedence_keeps_notification_date():
    records = {r.source_record_id: r for r in _parse_fixture()}
    rec = records["900003:NEW APPLICATION"]
    # Same key in APPLICATIONS and APPROVED: most advanced stage wins,
    # but the date comes from the Notification Date.
    assert rec.status == "APPROVED"
    assert rec.application_date == date(2026, 9, 18)
    assert rec.category == "hospitality_mfg"
    # Display fields come from the winning APPROVED entry, which has no
    # Applicant(s) row: legal_name falls back to the business name.
    assert rec.legal_name == "GOLDEN GRAIN BREWERY"
    assert rec.zip == "99903-1234"


def test_approved_and_discontinued_records():
    records = {r.source_record_id: r for r in _parse_fixture()}
    grocery = records["900004:RENEWAL"]
    assert grocery.status == "APPROVED"
    assert grocery.application_date == date(2026, 9, 24)
    assert grocery.category == "off_premise"
    assert grocery.legal_name == "MART FRESH MARKET"  # no applicants listed
    hotel = records["900005:DISCONTINUED"]
    assert hotel.status == "DISCONTINUED"
    assert hotel.application_date == date(2026, 9, 23)
    assert hotel.category == "hotel"
    lounge = records["900002:DISC. LIQUOR SALES"]
    assert lounge.status == "DISCONTINUED"
    assert lounge.category == "nightlife"


def test_current_new_variants_prefer_new():
    records = {r.source_record_id: r for r in _parse_fixture()}
    assumption = records["900006:ASSUMPTION"]
    assert assumption.dba == "NEW CORNER MARKET"
    assert assumption.legal_name == "NEW CORNER MARKET LLC"
    assert assumption.category == "off_premise"
    move = records["900007:CHANGE OF LOCATION"]
    assert move.application_type == "CHANGE OF LOCATION"
    assert move.address == "321 CEDAR AVE"
    assert move.city == "FAKETOWN"
    assert move.zip == "99907"
    assert move.category == "on_premise"


def test_no_phone_or_person_names_outside_raw():
    records = _parse_fixture()
    normalized = []
    for rec in records:
        normalized.extend(
            [
                rec.legal_name,
                rec.dba,
                rec.license_type,
                rec.license_description,
                rec.application_type,
                rec.status,
                rec.address,
                rec.city,
                rec.state,
                rec.zip,
                rec.county,
            ]
        )
    blob = " ".join(v for v in normalized if v)
    assert "555-" not in blob
    for person in ("JANE A DOE", "JOHN B DOE", "SAM R DOE", "ALEX R DOE"):
        assert person not in blob


def test_categorize():
    assert categorize("NIGHTCLUB") == "nightlife"
    assert categorize("SPIRITS/BR/WN REST LOUNGE +") == "nightlife"
    assert categorize("TAVERN - BEER/WINE") == "nightlife"
    assert categorize("CATERING; SPIRITS/BR/WN REST LOUNGE +") == "nightlife"
    assert categorize("SPORTS ENTERTAINMENT FACILITY") == "nightlife"
    assert categorize("BEER/WINE REST - BEER/WINE") == "on_premise"
    assert categorize("SPIRITS/BR/WN REST SERVICE BAR") == "on_premise"
    assert categorize("MICROBREWERY") == "hospitality_mfg"
    assert categorize("DOMESTIC WINERY < 250,000 LITERS") == "hospitality_mfg"
    assert categorize("CRAFT DISTILLERY; DISTILL / RECTIFY") == "hospitality_mfg"
    assert categorize("CATERING") == "catering_event"
    assert categorize("HOTEL") == "hotel"
    assert categorize("BEER/WINE SPECIALTY SHOP; HOTEL") == "hotel"
    assert categorize("GROCERY STORE - BEER/WINE") == "off_premise"
    assert categorize("SPIRITS RETAILER") == "off_premise"
    assert categorize("BEER/WINE SPECIALTY SHOP") == "off_premise"
    assert categorize("BEER DISTRIBUTOR; WINE DISTRIBUTOR") == "wholesale_mfg"
    assert categorize("WINE SHIPPER TO CONSUMER") == "wholesale_mfg"
    assert categorize("WINE CERTIFICATE OF APPROVAL") == "wholesale_mfg"
    assert categorize("AUTH REP US SPIRITS COA; SPIRITS COA") == "wholesale_mfg"
    assert categorize("SPECIAL OCCASION") == "temporary"
    assert categorize("450, ") == "other"
    assert categorize("337,") == "other"
    assert categorize("CANNABIS RETAILER") == "other"
    assert categorize(None) == "other"
    assert categorize("") == "other"


def test_merged_stages_keep_worded_license_text():
    from licmon.models import Snapshot
    from licmon.sources.wa_lcb import WaLcbSource

    def tbody(first_label, date, lic):
        return (
            "<tbody><tr><td><b>" + first_label + ":&nbsp;</b></td><td>" + date + "</td></tr>"
            "<tr><td><b>Business Name:&nbsp;</b></td><td>FAKE ALE HOUSE</td></tr>"
            "<tr><td><b>Business Location:&nbsp;</b></td>"
            "<td>1 FAKE ST,&nbsp;&nbsp;SEATTLE,&nbsp;WA&nbsp;98101</td></tr>"
            "<tr><td><b>License Type:</b></td><td>" + lic + "</td></tr>"
            "<tr><td><b>Application Type:</b></td><td>ASSUMPTION</td></tr>"
            "<tr><td><b>License Number:&nbsp;</b></td><td>900001</td></tr></tbody>")

    html = (
        "<table><thead><tr><th>STATEWIDE&nbsp;NEW LICENSE APPLICATIONS</th></tr></thead>"
        + tbody("Notification Date", "9/01/2026", "TAVERN - BEER/WINE") + "</table>"
        "<table><thead><tr><th>STATEWIDE&nbsp;RECENTLY APPROVED LICENSES</th></tr></thead>"
        + tbody("Approved Date", "9/20/2026", "450, ") + "</table>")
    recs = list(WaLcbSource().parse([Snapshot(url="u", body=html.encode())]))
    assert len(recs) == 1
    r = recs[0]
    assert r.status == "APPROVED"
    assert r.license_type == "TAVERN - BEER/WINE"
    assert r.category == "nightlife"
    assert WaLcbSource.material_fields == ("status", "application_type")
