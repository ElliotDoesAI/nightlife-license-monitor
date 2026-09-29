"""The owner's lead spreadsheet. Synthetic data only."""

import csv
import io
from datetime import date

from openpyxl import load_workbook

from licmon import leadsheet
from licmon.sources.ca_abc import CaAbcSource
from licmon.sources.fl_abt import FlAbtSource
from licmon.sources.wa_lcb import WaLcbSource

DAY = date(2026, 10, 1)


def rec(record_id, **kw):
    base = {
        "queue_date": DAY, "record_id": record_id, "venue_key": f"k{record_id}",
        "tier": "B", "score": 60, "legal_name": None, "dba": None,
        "license_description": "Mixed Beverage Permit", "application_type": "ORIGINAL",
        "status": "Received", "application_date": date(2026, 9, 20),
        "address": "1 FAKE ST", "city": "AUSTIN", "state": "TX", "zip": "78701",
        "metro": "Austin", "source": "tx_tabc_pending",
        "source_url": "https://example.invalid/r", "category": "on_premise", "raw": {},
    }
    base.update(kw)
    return base


def test_contact_hooks_use_only_the_official_row():
    wa = WaLcbSource().contact({"Contact Phone": "2065550100",
                                "Applicant(s)": "ZEBRA FAKE LLC; JANE Q TESTER"})
    assert wa == {"phone": "2065550100", "people": "ZEBRA FAKE LLC; JANE Q TESTER"}
    ca = CaAbcSource().contact({"rows": [
        {"Mail Addr 1": "", "Mail City": ""},
        {"Mail Addr 1": "PO BOX 1", "Mail Addr 2": "", "Mail City": "FAKEVILLE",
         "Mail State": "CA", "Mail Zip": "90000"}]})
    assert ca == {"mailing_address": "PO BOX 1, FAKEVILLE, CA 90000"}
    fl = FlAbtSource().contact({"Mail Address 1": "9 TEST WAY", "Mail Address 2": "STE 2",
                                "Mail City": "MIAMI", "Mail State": "FL", "Mail ZIP": "33101"})
    assert fl == {"mailing_address": "9 TEST WAY STE 2, MIAMI, FL 33101"}
    assert FlAbtSource().contact({}) == {}


def test_group_merges_venue_and_cleans_fields():
    rows = leadsheet.group_records([
        rec(1, venue_key="v", tier="A", score=80, legal_name="ZEBRA FAKE LLC",
            dba="ZEBRA FAKE LOUNGE", license_description="Late Hours Certificate",
            category="nightlife", application_date=date(2026, 9, 18)),
        rec(2, venue_key="v", tier="B", score=60, legal_name="ZEBRA FAKE LLC",
            dba="ZEBRA FAKE LOUNGE", status="Pending – In Review"),
        rec(3, legal_name="Other Fake Inc", dba=None, tier="C", score=45),
    ])
    assert [r["business_name"] for r in rows] == ["Zebra Fake Lounge", "Other Fake INC"]
    top = rows[0]
    assert top["priority"] == "A"
    assert top["company"] == "Zebra Fake LLC"
    assert top["business_type"] == "Nightclub / lounge"
    assert top["filing"] == "New application"
    assert top["status"] == "Pending"
    assert top["filed_on"] == date(2026, 9, 18)
    assert top["license"] == "Late Hours Certificate; Mixed Beverage Permit"
    assert top["lead_ids"] == "1 2"
    assert top["map_url"].startswith("https://www.google.com/maps/search/?api=1&query=ZEBRA")
    assert top["google_url"] == "https://www.google.com/search?q=ZEBRA+FAKE+LOUNGE+AUSTIN+TX"
    assert top["instagram_url"] == ("https://www.google.com/search?q="
                                    "site%3Ainstagram.com+ZEBRA+FAKE+LOUNGE")
    assert rows[1]["company"] is None  # no DBA: the name is the company


def test_wa_phone_and_people_without_repeating_business():
    [row] = leadsheet.group_records([rec(
        7, source="wa_lcb_actions", dba="ZEBRA FAKE BAR", legal_name=None,
        application_type="ASSUMPTION", status="APPROVED",
        raw={"Contact Phone": "206-555-0100",
             "Applicant(s)": "ZEBRA FAKE BAR; JANE Q TESTER; JOHN TESTER"})])
    assert row["phone"] == "(206) 555-0100"
    assert row["people"] == "Jane Q Tester; John Tester"
    assert row["filing"] == "Change of owner"
    assert row["status"] == "Approved"


def test_filing_and_status_labels():
    assert leadsheet._filing(["NEW LICENSE"], "fl_abt_licenses") == "Newly licensed"
    assert leadsheet._filing([], "ca_abc_applications") == "New application"
    assert leadsheet._filing(["ADDED/CHANGE OF TRADENAME"], "x") == "Name change"
    assert leadsheet._status(["Current"], "fl_abt_licenses") == "Licensed"
    assert leadsheet._status(["IntakeComplete"], "ny_sla_pending") == "Pending"
    assert leadsheet._status(["PEND"], "ca_abc_applications") == "Pending"


def test_xlsx_layout_links_and_no_formulas():
    rows = leadsheet.group_records([
        rec(1, tier="A", score=80, dba="=HYPERLINK(\"http://evil.invalid\")"),
        rec(2, dba="ZEBRA FAKE TAVERN")])
    wb = load_workbook(io.BytesIO(leadsheet.build_xlsx(rows, title="Leads 2026-10-01")))
    ws = wb.active
    assert ws.title == "Leads 2026-10-01"
    assert [c.value for c in ws[1]] == leadsheet.HEADERS
    assert ws.freeze_panes == "C2"
    assert ws.auto_filter.ref == "A1:U3"
    name_col = leadsheet.HEADERS.index("Business name") + 1
    evil = ws.cell(row=2, column=name_col)
    assert evil.data_type == "s" and evil.value.startswith("=")
    rec_col = leadsheet.HEADERS.index("Official record") + 1
    assert ws.cell(row=2, column=rec_col).value == "Record"
    assert ws.cell(row=2, column=rec_col).hyperlink.target == "https://example.invalid/r"
    date_col = leadsheet.HEADERS.index("Filed on") + 1
    assert ws.cell(row=2, column=date_col).value.date() == date(2026, 9, 20)


def test_csv_has_headers_and_neutralizes_formulas():
    rows = leadsheet.group_records([rec(1, dba="=1+1")])
    buf = io.StringIO()
    leadsheet.write_csv(rows, buf)
    out = list(csv.reader(io.StringIO(buf.getvalue())))
    assert out[0] == leadsheet.HEADERS
    assert out[1][leadsheet.HEADERS.index("Business name")] == "'=1+1"


def test_empty_sheet_is_valid():
    wb = load_workbook(io.BytesIO(leadsheet.build_xlsx([])))
    assert [c.value for c in wb.active[1]] == leadsheet.HEADERS
