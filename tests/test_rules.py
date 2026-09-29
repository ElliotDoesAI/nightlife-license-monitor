from licmon.metros import assign_metro
from licmon.models import Record
from licmon.qualify import qualify


def rec(**kw):
    base = dict(source="t", source_record_id="1", source_url="https://example.invalid",
                state="TX", county="Dallas", application_type="ORIGINAL",
                category="on_premise")
    base.update(kw)
    return Record(**base)


def test_metros():
    assert assign_metro("NY", "Kings", "Brooklyn") == "New York City"
    assert assign_metro("New York", "Nassau", None).startswith("NYC Suburbs")
    assert assign_metro("TX", "Harris", "Houston") == "Houston"
    assert assign_metro("TX", "TRAVIS COUNTY", None) == "Austin"
    assert assign_metro("TX", "Lubbock", "Lubbock") is None
    assert assign_metro("CA", "ORANGE", "IRVINE") == "Los Angeles / Orange County"
    assert assign_metro("CA", "SANTA CLARA", None) == "San Francisco Bay Area"
    assert assign_metro("WA", None, "Bellevue") == "Seattle-Tacoma-Bellevue"
    assert assign_metro("WA", None, "Spokane") is None
    assert assign_metro("IL", "Cook", "Chicago") == "Chicago"


def test_nightlife_new_application_is_tier_a():
    q = qualify(rec(category="nightlife", dba="The Velvet Lounge"), "Dallas-Fort Worth")
    assert q.qualified and q.tier == "A"
    assert "new application" in q.reason and "lounge" in q.reason


def test_plain_restaurant_new_is_qualified():
    q = qualify(rec(dba="Casa Fake LLC"), "Dallas-Fort Worth")
    assert q.qualified and q.tier in ("B", "C")


def test_exclusions():
    assert not qualify(rec(), None).qualified
    assert "outside" in qualify(rec(), None).reason
    assert not qualify(rec(category="off_premise"), "Houston").qualified
    assert not qualify(rec(category="wholesale_mfg"), "Houston").qualified
    assert not qualify(rec(category="temporary"), "Houston").qualified
    assert not qualify(rec(application_type="RENEWAL", category="nightlife"), "Houston").qualified
    assert not qualify(rec(dba="Quick Stop Food Mart"), "Houston").qualified
    assert not qualify(rec(dba="Shell Gas Station #12"), "Houston").qualified
    assert not qualify(rec(legal_name="University Of Fake Houston"), "Houston").qualified
    assert not qualify(rec(status="DISCONTINUED", application_type="NEW"), "Houston").qualified


def test_positive_name_overrides_exclusion_word():
    q = qualify(rec(dba="Market Street Cocktail Bar"), "Houston")
    assert q.qualified
    assert "exclusion" in q.reason


def test_ownership_change_and_hotel():
    q = qualify(rec(application_type="ASSUMPTION", category="nightlife"), "Seattle-Tacoma-Bellevue")
    assert q.qualified and "ownership change" in q.reason
    assert not qualify(rec(category="hotel", application_type="RENEWAL"), "Houston").qualified


def test_no_application_type_gets_partial_credit():
    q = qualify(rec(application_type=None, category="on_premise", dba="Fake Taproom"),
                "San Diego")
    assert q.qualified and "pending application" in q.reason


def test_material_change_detection():
    a = rec(status="Received")
    b = rec(status="received")  # case-only difference is not material
    c = rec(status="Approved")
    assert a.material_hash() == b.material_hash() != c.material_hash()
    assert rec(raw={"x": 1}).material_hash() == rec(raw={"x": 2}).material_hash()


def test_unclassified_license_needs_name_signal():
    plain = rec(category="other", application_type="ASSUMPTION", dba="Fake Holdings")
    assert not qualify(plain, "Seattle-Tacoma-Bellevue").qualified
    named = rec(category="other", application_type="ASSUMPTION", dba="Fake Taproom")
    q = qualify(named, "Seattle-Tacoma-Bellevue")
    assert q.qualified and q.tier == "C" and "not classified" in q.reason


def test_positive_words_are_specific():
    assert not qualify(rec(category="other", application_type="NEW",
                           dba="Fake Country Club"), "Houston").qualified
    assert not qualify(rec(category="other", application_type="NEW",
                           dba="Fake Dance Studio"), "Houston").qualified
    assert "comedy club" in qualify(rec(dba="Fake Comedy Club"), "Houston").reason
