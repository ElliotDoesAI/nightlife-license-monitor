"""Attio sync and Slack ping. No network: every HTTP call hits a fake session.
All rows are synthetic."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from licmon import attio, cli, leadsheet, slack


class FakeResp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {"data": {}}
        self.headers = headers or {}

    def json(self):
        return self._body


class FakeSession:
    """Records requests; `routes` maps (method, path suffix) -> response(s)."""

    def __init__(self, routes=None):
        self.headers = {}
        self.calls = []
        self.routes = routes or {}

    def request(self, method, url, json=None, params=None, timeout=None):
        self.calls.append((method, url.removeprefix(attio.API), json, params))
        for (m, suffix), resp in self.routes.items():
            if m == method and url.endswith(suffix):
                if isinstance(resp, list):
                    return resp.pop(0) if len(resp) > 1 else resp[0]
                return resp
        return FakeResp()

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url, json, None))
        return self.routes.get("post", FakeResp())


def client(routes=None):
    return attio.Client(key="test-key", session=FakeSession(routes), sleep=lambda s: None)


def row(i, priority="A", hot=False, score=60, **kw):
    base = {
        "venue_key": f"TX|78701|{i} FAKE ST", "priority": priority,
        "hot": "Hot" if hot else "", "lead_score": score,
        "business_name": f"Zebra Fake Lounge {i}", "company": f"Zebra Fake {i} LLC",
        "stage": "In review", "market": "Austin", "state": "TX", "city": "Austin",
        "address": f"{i} Fake St", "zip": "78701", "phone": None,
        "license": "Mixed Beverage Permit", "filing": "New application",
        "filed_on": date(2026, 9, 20),
        "first_seen": datetime(2026, 9, 21, 15, tzinfo=timezone.utc),
        "record_url": "https://example.invalid/r", "map_url": "https://example.invalid/m",
        "google_url": None, "instagram_url": None, "whats_new": leadsheet.NEW_FILING,
    }
    base.update(kw)
    return base


# --- Attio setup ---

def test_setup_dry_run_without_key_lists_schema_only():
    steps = attio.setup(None, write=False)
    assert steps[0] == "create object License Leads (license_leads)"
    assert "create attribute Venue key (text, unique)" in steps
    assert "  add option Moved to Targets" in steps
    assert not any("Zebra" in s for s in steps)


def test_setup_write_creates_object_attributes_and_options():
    c = client({("GET", "/objects/license_leads"): FakeResp(404),
                ("GET", "/objects/license_leads/attributes"):
                    FakeResp(body={"data": [{"api_slug": "name"}]})})
    steps = attio.setup(c, write=True)
    calls = c.session.calls
    assert calls[1] == ("POST", "/objects", {"data": {
        "api_slug": "license_leads", "singular_noun": "License Lead",
        "plural_noun": "License Leads"}}, None)
    attrs = [body["data"] for m, path, body, _ in calls
             if m == "POST" and path == "/objects/license_leads/attributes"]
    slugs = [a["api_slug"] for a in attrs]
    assert "name" not in slugs  # Attio already made it: kept, not recreated
    assert "keep attribute Venue (Attio made it)" in steps
    key = next(a for a in attrs if a["api_slug"] == "venue_key")
    assert key == {"title": "Venue key", "description": None, "api_slug": "venue_key",
                   "type": "text", "is_required": False, "is_unique": True,
                   "is_multiselect": False, "config": {}}
    assert {a["type"] for a in attrs} <= {"text", "number", "select", "date"}
    assert next(a for a in attrs if a["api_slug"] == "market")["type"] == "text"
    options = [(path, body["data"]["title"]) for m, path, body, _ in calls
               if path.endswith("/options")]
    assert ("/objects/license_leads/attributes/team_status/options", "New") in options
    assert ("/objects/license_leads/attributes/priority/options", "Hot") in options
    assert len([o for o in options if "/stage/" in o[0]]) == 4


def test_setup_stops_if_object_exists():
    c = client({("GET", "/objects/license_leads"): FakeResp(200, {"data": {}})})
    with pytest.raises(attio.AttioError, match="already exists"):
        attio.setup(c, write=True)
    assert [m for m, *_ in c.session.calls] == ["GET"]  # nothing written


# --- Attio sync ---

def test_values_on_create_and_update():
    created = attio.record_values(row(1, hot=True, score=85), create=True)
    assert created["name"] == "Zebra Fake Lounge 1"
    assert created["venue_key"] == "TX|78701|1 FAKE ST"
    assert created["priority"] == "Hot" and created["score"] == 85
    assert created["stage"] == "In review" and created["team_status"] == "New"
    assert created["filed_on"] == "2026-09-20" and created["first_seen"] == "2026-09-21"
    assert created["address"] == "1 Fake St, Austin, TX, 78701"
    assert "phone" not in created and "google_link" not in created  # blanks left out
    updated = attio.record_values(row(1), create=False)
    assert "team_status" not in updated  # never overwrite the team's Status
    assert updated["priority"] == "A"


def test_sync_upserts_hot_and_a_only_and_caps_new_records():
    rows = [row(1, hot=True, score=90), row(2, score=70), row(3, score=65),
            row(4, priority="B", score=99), row(5, score=50),
            row(1, hot=True, score=90)]  # same venue twice: one record
    existing = {"data": [{"values": {"venue_key": [{"value": "TX|78701|3 FAKE ST"}]}}]}
    c = client({("POST", "/records/query"): FakeResp(body=existing)})
    counts = attio.sync(c, rows, write=True, cap=2)
    assert counts == {"candidates": 4, "hot": 1, "created": 2, "updated": 1,
                      "over_cap": 1, "written": True}
    query = next(body for m, path, body, _ in c.session.calls if path.endswith("/query"))
    assert set(query["filter"]["venue_key"]["$in"]) == {
        "TX|78701|1 FAKE ST", "TX|78701|2 FAKE ST", "TX|78701|3 FAKE ST",
        "TX|78701|5 FAKE ST"}
    puts = [(params, body["data"]["values"]) for m, path, body, params in c.session.calls
            if m == "PUT"]
    assert all(p == {"matching_attribute": "venue_key"} for p, _ in puts)
    assert all(path == "/objects/license_leads/records"
               for m, path, _, _ in c.session.calls if m == "PUT")
    by_key = {v["venue_key"]: v for _, v in puts}
    # highest scores created; venue 5 (score 50) waits over the cap
    assert set(by_key) == {"TX|78701|1 FAKE ST", "TX|78701|2 FAKE ST", "TX|78701|3 FAKE ST"}
    assert by_key["TX|78701|1 FAKE ST"]["team_status"] == "New"
    assert "team_status" not in by_key["TX|78701|3 FAKE ST"]  # existing: update only


def test_sync_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setenv("ATTIO_DAILY_CAP", "1")
    counts = attio.sync(None, [row(1, score=80), row(2, score=70)], write=False)
    assert counts["created"] == 1 and counts["over_cap"] == 1 and not counts["written"]
    c = client()
    attio.sync(c, [row(1)], write=False)
    assert [m for m, *_ in c.session.calls] == ["POST"]  # the read-only query only


def test_sync_errors_are_value_free():
    c = client({("POST", "/records/query"): FakeResp(403, {"message": "Zebra secret"})})
    with pytest.raises(attio.AttioError) as ei:
        attio.sync(c, [row(1)], write=True)
    assert str(ei.value) == "attio failed (HTTP 403)"
    c = client({("POST", "/records/query"): FakeResp(404)})
    with pytest.raises(attio.AttioError, match="attio-setup"):
        attio.sync(c, [row(1)], write=True)


def test_client_retries_rate_limit():
    c = client({("POST", "/records/query"): [FakeResp(429, headers={"Retry-After": "2"}),
                                              FakeResp(body={"data": []})]})
    assert attio.sync(c, [row(1)], write=False)["created"] == 1
    assert len(c.session.calls) == 2


def test_settings(monkeypatch):
    for var in ("ATTIO_API_KEY", "ATTIO_WRITE_API_KEY", "ATTIO_DAILY_CAP"):
        monkeypatch.delenv(var, raising=False)
    assert not attio.configured() and attio.daily_cap() == 25
    monkeypatch.setenv("ATTIO_API_KEY", "read")
    monkeypatch.setenv("ATTIO_WRITE_API_KEY", "write")
    assert attio.api_key() == "write"
    monkeypatch.setenv("ATTIO_DAILY_CAP", "40")
    assert attio.daily_cap() == 40
    monkeypatch.setenv("ATTIO_DAILY_CAP", "lots")
    assert attio.daily_cap() == 25


def test_counts_file_roundtrip(tmp_path):
    path = tmp_path / "attio-counts.json"
    attio.write_counts(path, {"created": 3, "over_cap": 0})
    assert attio.read_counts(path) == {"created": 3, "over_cap": 0}
    assert attio.read_counts(tmp_path / "missing.json") is None


def test_cli_attio_sync_skips_when_not_configured(monkeypatch, caplog):
    for var in ("ATTIO_API_KEY", "ATTIO_WRITE_API_KEY", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)  # must not touch a DB
    with caplog.at_level("INFO", logger="licmon"):
        assert cli.main(["attio-sync", "--write"]) == 0
    assert "attio sync skipped (not configured)" in caplog.text


def test_cli_attio_sync_logs_counts_only(monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")
    monkeypatch.setattr(cli.db, "connect", lambda: _NullConn())
    monkeypatch.setattr(leadsheet, "load_rows", lambda conn, day, open_only=False: [
        row(1, hot=True, score=90), row(2, priority="B")])
    real_client = attio.Client
    fake = FakeSession({("POST", "/records/query"): FakeResp(body={"data": []})})
    monkeypatch.setattr(attio, "Client",
                        lambda: real_client(key="k", session=fake, sleep=lambda s: None))
    counts_file = tmp_path / "c.json"
    with caplog.at_level("INFO", logger="licmon"):
        assert cli.main(["attio-sync", "--write", "--counts", str(counts_file)]) == 0
    assert "created 1, updated 0, over daily cap 0" in caplog.text
    assert "Zebra" not in caplog.text and "FAKE ST" not in caplog.text
    assert json.loads(counts_file.read_text())["created"] == 1
    assert [m for m, *_ in fake.calls] == ["POST", "PUT"]  # query, then one upsert


class _NullConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- Slack ---

def test_slack_message_counts_and_top_hot_names():
    rows = [row(i, hot=True, score=80 + i, city="Houston", stage="Approved")
            for i in range(1, 8)]
    rows += [row(10, score=60), row(11, priority="B"), row(12, priority="B")]
    text = slack.compose(rows, {"created": 8, "over_cap": 0},
                         "https://app.attio.example/license-leads")
    lines = text.split("\n")
    assert lines[0] == "New license leads: 10 today (7 Hot, 1 A, 2 B)"
    assert lines[1].startswith("Hot: Zebra Fake Lounge 7, Houston (Approved) · ")
    assert lines[1].count("Zebra") == 5 and lines[1].endswith("· and 2 more")
    assert lines[2] == ("Added to Attio: 8 · Full list in today's email.  "
                        "<https://app.attio.example/license-leads|Open License Leads in Attio>")
    for private in ("Fake St", "78701", "LLC", "example.invalid", "Mixed Beverage"):
        assert private not in text
    assert "—" not in text


def test_slack_message_without_hot_or_attio_and_escaping():
    text = slack.compose([row(1, priority="B", business_name="Fake <Bar> & Co")])
    assert text == "New license leads: 1 today (1 B)\nFull list in today's email."
    hot = slack.compose([row(1, hot=True, business_name="Fake <Bar> & Co", city="Austin")],
                        {"created": 0, "over_cap": 3})
    assert "Fake &lt;Bar&gt; &amp; Co, Austin (In review)" in hot
    assert "3 more over today's Attio limit, in the spreadsheet" in hot


def test_slack_posts_only_on_news():
    assert slack.is_news([row(1, whats_new=leadsheet.STAGE_ADVANCED)])
    assert slack.is_news([row(1, whats_new=leadsheet.NEW_FILING)])
    assert not slack.is_news([row(1, whats_new=leadsheet.DETAILS_CHANGED)])
    assert not slack.is_news([])


def test_slack_post_and_errors():
    s = FakeSession()
    slack.post("hello", url="https://hooks.example.invalid/T/B/X", session=s)
    assert s.calls == [("POST", "https://hooks.example.invalid/T/B/X", {"text": "hello"}, None)]
    bad = FakeSession({"post": FakeResp(403)})
    with pytest.raises(slack.SlackError) as ei:
        slack.post("hello", url="https://hooks.example.invalid/T/B/SECRET", session=bad)
    assert str(ei.value) == "slack failed (HTTP 403)"
    assert "SECRET" not in str(ei.value)


def test_cli_slack_skips(monkeypatch, caplog):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with caplog.at_level("INFO", logger="licmon"):
        assert cli.main(["slack"]) == 0
    assert "slack skipped (not configured)" in caplog.text

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.invalid/x")
    monkeypatch.setattr(cli.db, "connect", lambda: _NullConn())
    monkeypatch.setattr(leadsheet, "load_rows", lambda conn, day, open_only=False: [
        row(1, whats_new=leadsheet.DETAILS_CHANGED)])
    posted = []
    monkeypatch.setattr(slack, "post", lambda text: posted.append(text))
    caplog.clear()
    with caplog.at_level("INFO", logger="licmon"):
        assert cli.main(["slack"]) == 0
    assert "slack skipped (no new or stage-advanced leads)" in caplog.text
    assert posted == []

    monkeypatch.setattr(leadsheet, "load_rows", lambda conn, day, open_only=False: [
        row(1, hot=True, score=90)])
    caplog.clear()
    with caplog.at_level("INFO", logger="licmon"):
        assert cli.main(["slack"]) == 0
    assert len(posted) == 1 and "Zebra Fake Lounge 1" in posted[0]
    assert "slack posted: 1 leads (1 hot)" in caplog.text
    assert "Zebra" not in caplog.text


def test_cli_slack_preview_refused_in_actions(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(SystemExit):
        cli.main(["slack", "--preview"])
