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
    assert q.qualified and q.tier == "B" and "not classified" in q.reason


def test_positive_words_are_specific():
    assert not qualify(rec(category="other", application_type="NEW",
                           dba="Fake Country Club"), "Houston").qualified
    assert not qualify(rec(category="other", application_type="NEW",
                           dba="Fake Dance Studio"), "Houston").qualified
    assert "comedy club" in qualify(rec(dba="Fake Comedy Club"), "Houston").reason


def tier(dba, **kw):
    q = qualify(rec(dba=dba, **kw), "Houston")
    return q.tier if q.qualified else None


def test_tiers_follow_ticketing_fit():
    # A: nightclubs
    assert tier("Fake Nightclub") == "A"
    assert tier("Velvet Fake Ultra Lounge") == "A"
    assert tier("Fake Hookah Lounge") == "A"
    assert tier("Fake Holdings", license_description="Cabaret") == "A"
    # B: obvious bars and event venues
    assert tier("Fake Tavern") == "B"
    assert tier("Fake Irish Pub") == "B"
    assert tier("Fake Brewing Co") == "B"
    assert tier("Fake Pizza and Sports Bar") == "B"
    assert tier("Fake Holdings", license_description="On-Sale General - Public Premises") == "B"
    assert tier("Fake K-Cafe & Lounge") == "B"
    # C: restaurants, even with a bar-sounding add-on or license
    assert tier("Casa Fake Mexican Restaurant") == "C"
    assert tier("Fake Sushi Bar") == "C"
    assert tier("Fake Bar & Grill") == "C"
    assert tier("Fake Burgers and Bar") == "C"
    assert tier("Fake Restaurant & Bar") == "C"
    assert tier("Fake Grill", license_description="Public Place of Amusement") == "C"
    assert tier("Fake Poke Bowl") == "C"
    # dropped: cafes, bakeries, dessert, chains
    assert tier("Fake Coffee Co") is None
    assert tier("The Fake Cafe") is None
    assert tier("Fake Bakery") is None
    assert tier("Fake Ice Cream") is None
    assert tier("Chipotle Mexican Grill #1") is None
    assert tier("Red Robin Gourmet Burgers & Brews") is None
    # a local name that contains a chain's name is kept
    assert tier("Don Fakey Chuy's Tacos") == "C"
    # a cafe that is also clearly a bar stays
    assert tier("Fake Coffee & Cocktail Bar") == "B"


def test_ticketed_venues_are_tier_a():
    for name in ("Fake Comedy House", "Fake Improv", "Fake Stadium", "Fake Arena",
                 "Fake Ballpark", "Fake Speedway", "Fake Raceway", "Fake Motorsports Park",
                 "Fake Sportsplex", "Fake Field House", "Fake Fieldhouse",
                 "Fake Amphitheater", "Fake Amphitheatre", "Fake Theater", "Fake Theatre",
                 "Fake Playhouse", "Fake Concert Hall", "Fake Music Hall", "Fake Ballroom",
                 "Fake Event Center", "Fake Events Center", "Fake Event Venue",
                 "Fake Live Music Bar", "Fake Jazz Club", "Fake Rodeo", "Fake Fairgrounds",
                 "Fake Expo Center", "Fake Convention Center", "Fake Performing Arts Center",
                 "Fake Opera House", "Fake Dayclub", "Fake Beach Club", "Fake Rooftop",
                 "Fake Supper Club", "Fake Cabaret", "Fake Coliseum"):
        assert tier(name) == "A", name


def test_not_quite_ticketed_venues_are_tier_b():
    assert tier("Fake Karaoke") == "B"
    assert tier("Fake KTV") == "B"
    assert tier("Fake Billiards") == "B"
    assert tier("Fake Pool Hall") == "B"
    assert tier("Fake Bowling Lanes") == "B"
    assert tier("Fake Cinemas") == "B"
    assert tier("Fake Movie Theater") == "B"  # cinemas sell tickets, but not ours
    assert tier("Fake Cinema Theatre") == "B"
    assert tier("Fake Drafthouse Cinema") == "B"
    assert tier("Fake Entertainment Center") == "B"
    assert tier("Punch Bowl Social Fake") == "B"
    assert tier("Pinstripes Fake") == "B"
    assert tier("Fake Bowl") != "A"  # "bowl" alone is too noisy (bowling, poke bowls)


def test_restaurant_names_never_make_a_lounge_tier_a():
    # Shapes seen in a real review day, with synthetic names.
    assert tier("Fakezzle Restaurant & Lounge") == "B"
    assert tier("The Fakejo Sushi & KTV Lounge") == "B"
    assert tier("Ola Fake, Cocina & Lounge") == "B"
    assert tier("Fake Grill & Lounge") == "B"
    assert tier("Fake Kitchen and Lounge") == "B"
    assert tier("Fake Bistro Lounge") == "B"
    assert tier("Fake Steakhouse & Lounge") == "B"
    assert tier("Fake Cafe & Lounge") == "B"
    assert tier("Fake Rooftop Kitchen") == "B"
    assert tier("Fake Comedy Club & Grill") == "B"
    # a plain restaurant with no bar or venue word stays C
    assert tier("Fake Cocina Mexicana") == "C"


def test_restaurant_with_ticketed_license_is_b_at_most():
    assert tier("Fake Grill", license_description="Night Club") == "B"
    assert tier("Fake Holdings", license_description="Night Club") == "A"


def test_fat_tuesday_is_a_chain():
    assert tier("Fat Tuesday") is None
    assert tier("Fat Tuesday Fake Mall") is None


def test_stadium_is_no_longer_an_exclusion_word():
    q = qualify(rec(dba="Fake Stadium"), "Houston")
    assert q.qualified and q.tier == "A" and "exclusion" not in q.reason
    # a college stadium: the venue word beats the college exclusion
    assert tier("Fake College Stadium") == "A"


def test_stadium_concessionaires_are_kept_and_tier_a():
    def conc(legal, dba):
        q = qualify(rec(legal_name=legal, dba=dba), "Houston")
        return (q.tier, q.reason) if q.qualified else (None, q.reason)

    # the operator is a concessionaire; the DBA names the venue
    for legal in ("Levy Premium Foodservice LP", "Aramark Sports and Entertainment LLC",
                  "Delaware North Sportservice Inc", "Sodexo Live! Fake LLC",
                  "Legends Hospitality LLC", "Centerplate Fake Inc", "Spectra Fake LLC",
                  "Oak View Group Fake LLC", "ASM Global Fake LLC",
                  "Live Nation Worldwide Inc", "AEG Presents Fake LLC"):
        tier_, reason = conc(legal, "Fake Stadium")
        assert tier_ == "A", legal
        assert "concession" in reason
    # a venue word on its own (Field, Park, Center) counts for a concessionaire
    assert conc("Levy Premium Foodservice LP", "Fake Field")[0] == "A"
    assert conc("Aramark Sports and Entertainment LLC", "Fake Center")[0] == "A"
    assert conc("Levy Restaurants LP", "Fake Arena")[0] == "A"  # "Restaurants" is the operator
    # plain Sodexo is institutional food service, not a stadium operator
    assert conc("Sodexo Fake Inc", "Fake Center")[0] != "A"
    # without a venue name the concessionaire is not a ticketing lead by itself
    assert conc("Aramark Fake LLC", "Fake Airport Terminal B")[0] is None


def test_adult_flag_keeps_tier_but_never_hot(monkeypatch):
    monkeypatch.setenv("HOT_MIN_SCORE", "0")
    for name in ("Fake Gentlemen's Club", "Fake Gentleman's Club", "Fake Gentlemens Cabaret",
                 "Fake Strip Club", "Fake Topless Bar", "Fake Bikini Bar",
                 "Fake Adult Cabaret", "Fake Adult Entertainment Lounge"):
        q = qualify(rec(dba=name, category="nightlife"), "Houston")
        assert q.qualified and q.adult, name
        assert q.tier in ("A", "B") and not q.hot, name
    q = qualify(rec(dba="Fake Nightclub", category="nightlife"), "Houston")
    assert not q.adult and q.hot
    assert not qualify(rec(dba="Fake Cabaret", category="nightlife"), "Houston").adult
    assert not qualify(rec(dba="Fake Gentlemen's Barbershop Bar"), "Houston").adult
