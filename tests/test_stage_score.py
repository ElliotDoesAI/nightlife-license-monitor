"""Licensing stage per source, lead score and Hot. Synthetic records only."""

from datetime import date

from licmon import stage
from licmon.models import Record
from licmon.qualify import lead_score, qualify
from licmon.sources.ca_abc import CaAbcSource
from licmon.sources.chicago_bacp import ChicagoBacpSource
from licmon.sources.chicago_pending import ChicagoPendingSource
from licmon.sources.fl_abt import FlAbtSource
from licmon.sources.ny_sla import NySlaSource
from licmon.sources.tx_tabc import TxTabcSource
from licmon.sources.wa_lcb import WaLcbSource

TODAY = date(2026, 10, 1)


def rec(source, **kw):
    base = dict(source=source, source_record_id="1", source_url="https://example.invalid")
    base.update(kw)
    return Record(**base)


def test_shared_fallback_vocabulary():
    assert stage.from_status("Under Review") == stage.IN_REVIEW
    assert stage.from_status("IntakeComplete") == stage.RECEIVED
    assert stage.from_status("Transfer approved") == stage.APPROVED
    assert stage.from_status("Current (conditional)") == stage.APPROVED
    assert stage.from_status("Temporary certificate") == stage.LICENSED
    assert stage.from_status("ACTIVE,PEND") == stage.LICENSED
    assert stage.from_status("Withdrawn (application withdrawn)") is None
    assert stage.from_status("DISCONTINUED") is None
    assert stage.from_status(None) is None
    assert stage.best([None, stage.RECEIVED, stage.APPROVED]) == stage.APPROVED
    assert stage.rank(stage.LICENSED) > stage.rank(stage.RECEIVED) > stage.rank(None)


def test_stage_per_source():
    ny = NySlaSource()
    assert ny.stage(rec(ny.name, status="Under Review")) == stage.IN_REVIEW
    assert ny.stage(rec(ny.name, status="IntakeComplete")) == stage.RECEIVED
    tx = TxTabcSource()
    assert tx.stage(rec(tx.name, status="Received")) == stage.RECEIVED
    assert tx.stage(rec(tx.name, status="Pending – In Review")) == stage.IN_REVIEW
    cp = ChicagoPendingSource()
    assert cp.stage(rec(cp.name, status="PENDING NOTICE")) == stage.IN_REVIEW
    cb = ChicagoBacpSource()
    assert cb.stage(rec(cb.name, status="AAI")) == stage.LICENSED
    assert cb.stage(rec(cb.name, status="AAC")) is None
    wa = WaLcbSource()
    assert wa.stage(rec(wa.name, status="APPLICATION")) == stage.RECEIVED
    assert wa.stage(rec(wa.name, status="APPROVED")) == stage.LICENSED
    assert wa.stage(rec(wa.name, status="DISCONTINUED")) is None
    ca = CaAbcSource()
    assert ca.stage(rec(ca.name, status="PEND")) == stage.RECEIVED
    assert ca.stage(rec(ca.name, status="ACTIVE")) == stage.LICENSED
    assert ca.stage(rec(ca.name, status="ACTIVE,PEND")) == stage.LICENSED
    fl = FlAbtSource()
    assert fl.stage(rec(fl.name, status="Current")) == stage.LICENSED
    assert fl.stage(rec(fl.name, status="Temporary certificate")) == stage.LICENSED
    assert fl.stage(rec(fl.name, status="Transfer approved")) == stage.APPROVED
    assert fl.stage(rec(fl.name, status="Current (conditional)")) == stage.APPROVED
    assert fl.stage(rec(fl.name, status="Applicant (application in process)")) == stage.IN_REVIEW
    assert fl.stage(rec(fl.name, status="Escrow / Transfer pending")) == stage.IN_REVIEW


def test_florida_licensed_counts_only_when_recent():
    fl = FlAbtSource()
    assert fl.stage_counts(rec(fl.name, application_date=date(2026, 8, 15)), TODAY)
    assert not fl.stage_counts(rec(fl.name, application_date=date(2024, 1, 1)), TODAY)
    assert not fl.stage_counts(rec(fl.name), TODAY)
    assert ChicagoBacpSource().stage_counts(rec("x"), TODAY)  # base default


def test_nightlife_license_per_source():
    assert ChicagoBacpSource().nightlife_license(rec("c", license_type="1050")) == ("ppa",)
    assert ChicagoBacpSource().nightlife_license(rec("c", license_type="1471")) == ("late_hours",)
    assert ChicagoBacpSource().nightlife_license(rec("c", license_type="1475")) == ()
    assert ChicagoPendingSource().nightlife_license(
        rec("c", license_description="Public Place of Amusement")) == ("ppa",)
    assert ChicagoPendingSource().nightlife_license(
        rec("c", license_description="Late-Hour")) == ("late_hours",)
    assert TxTabcSource().nightlife_license(rec("t", license_type="LH")) == ("late_hours",)
    assert TxTabcSource().nightlife_license(rec("t", license_type="MB")) == ()
    assert CaAbcSource().nightlife_license(rec("a", license_type="41,48")) == ("public_premises",)
    assert CaAbcSource().nightlife_license(rec("a", license_type="90")) == ("music_venue",)
    assert NySlaSource().nightlife_license(
        rec("n", license_description="On Premises Liquor - Night Club")) == ("nightclub_cabaret",)
    assert FlAbtSource().nightlife_license(rec("f", license_type="4COP")) == ("full_liquor_bar",)
    assert FlAbtSource().nightlife_license(rec("f", license_type="4COP-SFS")) == ()
    assert WaLcbSource().nightlife_license(rec("w")) == ()


def test_ticketed_license_signals_per_source():
    ca = CaAbcSource()
    for code in ("64", "69", "71", "72"):
        assert ca.nightlife_license(rec("a", license_type=f"47,{code}")) == ("theater",), code
    assert ca.nightlife_license(rec("a", license_type="47")) == ()
    ny = NySlaSource()
    assert ny.nightlife_license(rec("n", license_description="Legitimate Theatre")) == ("theater",)
    assert ny.nightlife_license(rec("n", license_description="Summer Concert Hall")) == (
        "music_venue",)
    assert ny.nightlife_license(rec("n", license_description=(
        "Athletic/Sporting Event/Expositions/Large Gathering Venue"))) == ("sports_venue",)
    assert ny.nightlife_license(rec("n", license_description=(
        "Outdoor Athletic Fields and Stadiums"))) == ("sports_venue",)
    assert ny.nightlife_license(rec("n", license_description="Cabaret")) == ("nightclub_cabaret",)
    assert ny.nightlife_license(rec("n", license_description="Catering Establishment")) == ()
    assert ny.nightlife_license(rec("n", license_description="Club")) == ()
    wa = WaLcbSource()
    assert wa.nightlife_license(rec("w", license_description=(
        "SPIRITS/BR/WN REST LOUNGE +; NIGHTCLUB"))) == ("nightclub_cabaret",)
    assert wa.nightlife_license(rec("w", license_description=(
        "SPORTS ENTERTAINMENT FACILITY"))) == ("sports_venue",)
    assert wa.nightlife_license(rec("w", license_description="BEER/WINE THEATER")) == ("theater",)
    assert wa.nightlife_license(rec("w", license_description=(
        "NON-PROFIT ARTS ORGANIZATION"))) == ("theater",)
    assert wa.nightlife_license(rec("w", license_description="SPIRITS/BR/WN REST SERVICE BAR")) == ()
    fl = FlAbtSource()
    assert fl.nightlife_license(rec("f", license_type="11PA")) == ("theater",)
    assert fl.nightlife_license(rec("f", license_type="12RT")) == ("sports_venue",)
    assert fl.nightlife_license(rec("f", license_type="4COP-SCX")) == ("event_venue",)
    assert fl.nightlife_license(rec("f", license_type="4COP-SCF")) == ("event_venue",)
    assert fl.nightlife_license(rec("f", license_type="4COP-EVNT")) == ("event_venue",)
    assert fl.nightlife_license(rec("f", license_type="4COP-DEV")) == ("event_venue",)
    assert fl.nightlife_license(rec("f", license_type="4COP-SBX")) == ()  # bowling stays B


def test_ticketed_license_makes_an_unclear_name_tier_a():
    def q(source, dba, **kw):
        base = dict(application_type="NEW", status="Received", state="CA",
                    category="nightlife")
        base.update(kw)
        return qualify(rec(source, dba=dba, **base), "Los Angeles / Orange County", today=TODAY)

    theater = q("ca_abc_applications", "Fake Holdings", license_type="47,64",
                license_description="On-Sale General - Eating Place,Special On-Sale General "
                                    "for Nonprofit Theater Company", application_type=None,
                status="PEND", category="on_premise")
    assert theater.tier == "A" and "theater license" in theater.reason
    music = q("ca_abc_applications", "Fake Holdings", license_type="90",
              license_description="On-Sale General - Music Venue", application_type=None,
              status="PEND")
    assert music.tier == "A"
    # a restaurant name with a ticketed license is B, a cinema or bowling alley too
    grill = q("ca_abc_applications", "Fake Grill", license_type="90",
              license_description="On-Sale General - Music Venue", application_type=None,
              status="PEND")
    assert grill.tier == "B"
    cinema = q("fl_abt_licenses", "Fake Cinemas", license_type="11PA",
               license_description="Performing arts facility", state="FL",
               application_type="NEW LICENSE", status="Current", category="catering_event")
    assert cinema.tier == "B"


def test_plan_examples_80_85_60(monkeypatch):
    monkeypatch.delenv("HOT_MIN_SCORE", raising=False)
    # A club already licensed and newly filed: 45 + 25 + 10 = 80, Hot.
    club = rec("wa_lcb_actions", dba="Fake Nightclub", status="APPROVED",
               application_type="NEW APPLICATION", state="WA", category="nightlife")
    q = qualify(club, "Seattle-Tacoma-Bellevue", today=TODAY)
    assert (q.tier, q.stage, q.lead_score, q.hot) == ("A", stage.LICENSED, 80, True)
    # A PPA club in review: 45 + 20 + 10 + 10 = 85, Hot.
    ppa = rec("chicago_bacp_pending", dba="Fake Rooftop Bar", status="PENDING NOTICE",
              license_description="Public Place of Amusement", application_type="NEW",
              state="IL", city="CHICAGO", category="nightlife")
    q = qualify(ppa, "Chicago", today=TODAY)
    assert (q.tier, q.stage, q.lead_score, q.hot) == ("A", stage.IN_REVIEW, 85, True)
    # A lounge that just filed: 45 + 5 + 10 = 60, A but not Hot.
    lounge = rec("ny_sla_pending", dba="Fake Velvet Lounge", status="IntakeComplete",
                 application_type="NEW", license_description="On Premises Liquor",
                 state="NY", category="on_premise")
    q = qualify(lounge, "New York City", today=TODAY)
    assert (q.tier, q.stage, q.lead_score, q.hot) == ("A", stage.RECEIVED, 60, False)


def test_hot_threshold_is_a_setting(monkeypatch):
    lounge = rec("ny_sla_pending", dba="Fake Velvet Lounge", status="IntakeComplete",
                 application_type="NEW", state="NY", category="on_premise")
    monkeypatch.setenv("HOT_MIN_SCORE", "60")
    assert qualify(lounge, "New York City", today=TODAY).hot
    monkeypatch.setenv("HOT_MIN_SCORE", "not a number")
    assert not qualify(lounge, "New York City", today=TODAY).hot  # falls back to 75


def test_ppa_license_needs_a_club_or_ticketed_name_for_a():
    def score(dba, license_type="1050"):
        r = rec("chicago_bacp_liquor", dba=dba, license_type=license_type,
                license_description="Public Place of Amusement", application_type="NEW",
                status="AAI", state="IL", city="CHICAGO", category="nightlife")
        q = qualify(r, "Chicago", today=TODAY)
        return q.tier, q.lead_score

    assert score("Fake Event Space")[0] == "A"
    assert score("Fake Comedy Club")[0] == "A"
    assert score("Fake Theater Company")[0] == "A"  # theaters are ticketed now
    assert score("Fake Nightclub")[0] == "A"
    # a bar name with a PPA is B, but the PPA points rank it high within B
    assert score("Fake Cocktail Bar") == ("B", 25 + 20 + 25 + 10)
    assert score("Fake Tavern") == ("B", 25 + 20 + 25 + 10)
    assert score("Fake Cocktail Bar", license_type="1470") == ("B", 25 + 25 + 10)
    assert score("Fake Bowling Lanes")[0] == "B"  # bowling alleys hold PPAs too
    assert score("Fake Holdings")[0] == "B"  # unclear name: PPA license alone
    assert score("Fake Grill")[0] == "C"  # a restaurant name: PPA does not lift it


def test_florida_old_license_scores_no_stage_points():
    def score(day):
        r = rec("fl_abt_licenses", dba="Fake Nightclub", license_type="4COP",
                status="Current", application_type="NEW LICENSE", application_date=day,
                state="FL", category="nightlife")
        return qualify(r, "Miami", today=TODAY)

    fresh, old = score(date(2026, 9, 1)), score(date(2019, 5, 1))
    assert fresh.stage == old.stage == stage.LICENSED
    assert fresh.lead_score == 45 + 10 + 25 + 10
    assert old.lead_score == 45 + 10 + 10


def test_unqualified_records_keep_a_stage_but_no_score():
    r = rec("tx_tabc_pending", dba="Fake Food Mart", status="Received",
            application_type="ORIGINAL", state="TX", county="Harris", category="off_premise")
    q = qualify(r, "Houston", today=TODAY)
    assert not q.qualified and q.stage == stage.RECEIVED
    assert (q.lead_score, q.hot) == (0, False)


def test_unknown_source_uses_shared_fallback():
    r = rec("some_future_state", dba="Fake Tavern", status="Under Review",
            application_type="ORIGINAL", category="nightlife")
    q = qualify(r, "Houston", today=TODAY)
    assert q.stage == stage.IN_REVIEW and q.lead_score == 25 + 10 + 10


def test_lead_score_parts_and_cap():
    assert lead_score("C", (), None, True, "RENEWAL") == 5
    assert lead_score("B", ("late_hours", "ppa"), stage.APPROVED, True, "ASSUMPTION") == 25 + 20 + 20 + 5
    assert lead_score("A", ("ppa",), stage.LICENSED, True, None) == 100
    assert lead_score("A", ("ppa",), stage.LICENSED, False, "NEW") == 75
