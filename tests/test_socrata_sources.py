"""NY / TX / Chicago connectors against synthetic Socrata rows (no network)."""

import json
from datetime import date

from licmon.models import Snapshot
from licmon.sources import all_sources, socrata
from licmon.sources.chicago_bacp import ChicagoBacpSource
from licmon.sources.ny_sla import NySlaSource, categorize as ny_cat
from licmon.sources.tx_tabc import TxTabcSource


class FakeHttp:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append((url, params))
        return Snapshot(url=url, body=json.dumps(self.pages.pop(0)).encode())


def snap(rows):
    return [Snapshot(url="https://example.invalid", body=json.dumps(rows).encode())]


def test_registry_names_unique():
    names = [s.name for s in all_sources()]
    assert len(names) == len(set(names)) == 6


def test_socrata_paging():
    http = FakeHttp([[{"a": 1}, {"a": 2}], [{"a": 3}]])
    snaps = socrata.fetch_all(http, "data.example.gov", "abcd-1234", page_size=2)
    assert len(snaps) == 2
    assert [r["a"] for r in socrata.rows(snaps)] == [1, 2, 3]
    assert http.calls[1][1]["$offset"] == 2


def test_ny_parse():
    rows = [{
        "application_id": "NA-0340-26-000001", "premises_county": "Kings", "type": "1",
        "class": "340", "description": "Restaurant", "legalname": "Fake Eats LLC",
        "dba": "Fake Rooftop", "actual_address_of_premises": "1 Fake St",
        "additional_address_information": "Fl 2", "city": "Brooklyn",
        "state_name": "NY", "zip_code": "11201",
        "received_date": "2026-09-01T10:00:00.000", "status": "Under Review"}]
    [r] = NySlaSource().parse(snap(rows))
    assert r.source_record_id == "NA-0340-26-000001"
    assert r.application_date == date(2026, 9, 1)
    assert r.address == "1 Fake St Fl 2" and r.county == "Kings"
    assert r.category == "on_premise" and r.license_type == "340"
    assert "application_id=NA-0340-26-000001" in r.source_url
    assert ny_cat("Night Club") == "nightlife"
    assert ny_cat("Grocery Store") == "off_premise"
    assert ny_cat("Liquor Store") == "off_premise"
    assert ny_cat("Farm Brewer") == "hospitality_mfg"
    assert ny_cat("Wholesale Beer") == "wholesale_mfg"
    assert ny_cat("Restaurant Brewer") == "hospitality_mfg"


def test_tx_parse():
    rows = [{
        "applicationid": "600001.0", "license_type": "MB",
        "applicationstatus": "Pending \u2013 In Review", "primary_license_id": "1.0",
        "submission_date": "2026-09-02T00:00:00.000", "trade_name": "Fake Icehouse",
        "owner": "Fake Holdings LLC", "address": "2 Fake Rd", "city": "Austin",
        "state": "TX", "zip": "787011234", "county": "Travis"}]
    [r] = TxTabcSource().parse(snap(rows))
    assert r.source_record_id == "600001"
    assert r.dba == "Fake Icehouse" and r.legal_name == "Fake Holdings LLC"
    assert r.zip == "78701-1234" and r.category == "on_premise"
    assert r.license_description == "Mixed Beverage Permit"


def test_chicago_fetch_query_and_parse():
    http = FakeHttp([[]])
    ChicagoBacpSource(today=date(2026, 9, 28)).fetch(http)
    where = http.calls[0][1]["$where"]
    assert "'1470'" in where and "RENEW" in where and "2026-04-01" in where
    rows = [{
        "id": "999-20260901", "legal_name": "FAKE TAVERN INC",
        "doing_business_as_name": "FAKE TAVERN", "address": "3 FAKE AVE",
        "city": "CHICAGO", "state": "IL", "zip_code": "60601", "license_code": "1470",
        "license_description": "Tavern", "application_type": "C_LOC",
        "application_created_date": "2026-08-01T00:00:00.000", "license_status": "AAI"}]
    [r] = ChicagoBacpSource().parse(snap(rows))
    assert r.application_type == "CHANGE OF LOCATION"
    assert r.category == "nightlife" and r.county == "Cook"
