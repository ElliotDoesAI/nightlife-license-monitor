"""End-to-end pipeline behavior against a disposable Postgres, fake sources."""

import json
from datetime import date, datetime, timedelta, timezone

from licmon import db, pipeline
from licmon.http import SourceHTTPError
from licmon.models import Record, Snapshot
from licmon.sources.base import Source

DAY1 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
DAY2 = DAY1 + timedelta(days=1)
DAY3 = DAY2 + timedelta(days=1)


class FakeSource(Source):
    """Source whose 'upstream' is a list of dicts we mutate between runs."""

    name = "fake_tx"
    title = "fake"
    state = "TX"
    min_records = 1

    def __init__(self, rows, tracks_removals=True, fail=False):
        self.rows = rows
        self.tracks_removals = tracks_removals
        self.fail = fail

    def fetch(self, http):
        if self.fail:
            raise SourceHTTPError("HTTP 503 fetching https://example.invalid/x")
        body = json.dumps(self.rows, sort_keys=True).encode()
        return [Snapshot(url="https://example.invalid/x", body=body,
                         content_type="application/json", fetched_at=DAY1)]

    def parse(self, snapshots):
        for row in json.loads(snapshots[0].body):
            yield Record(source=self.name, source_record_id=row["id"],
                         source_url=f"https://example.invalid/x?id={row['id']}",
                         legal_name=row["name"], dba=row.get("dba"),
                         license_type="MB", license_description="Mixed Beverage Permit",
                         application_type="ORIGINAL", status=row.get("status", "Received"),
                         application_date=date.fromisoformat(row["date"]),
                         address="1 Test St", city="Austin", state="TX",
                         zip="78701", county=row.get("county", "Travis"),
                         category=row.get("category", "on_premise"), raw=row)


def rows_day1():
    return [
        # recent + qualified -> queued even on baseline
        {"id": "1", "name": "Fake Rooftop Bar LLC", "date": "2026-08-30"},
        # old application -> baseline, not queued
        {"id": "2", "name": "Old Lounge LLC", "date": "2026-01-15"},
        # recent but off-premise -> not qualified
        {"id": "3", "name": "Fake Food Mart", "date": "2026-08-31", "category": "off_premise"},
        # recent but outside metros
        {"id": "4", "name": "Rural Tavern", "date": "2026-08-31", "county": "Lubbock"},
    ]


def queue(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT source_record_id, event_type FROM review_queue ORDER BY 1, 2")
        return cur.fetchall()


def events(conn, etype):
    with conn.cursor() as cur:
        cur.execute("""SELECT r.source_record_id FROM record_events e JOIN records r
                       ON r.id=e.record_id WHERE e.event_type=%s ORDER BY 1""", (etype,))
        return [r[0] for r in cur.fetchall()]


def test_baseline_then_new_changed_removed(pg):
    src = FakeSource(rows_day1())
    [res] = pipeline.run([src], conn=pg, http=object(), now=DAY1, trigger="test")
    assert res.status == "success" and res.baseline
    assert (res.fetched, res.new, res.queued) == (4, 0, 1)
    assert queue(pg) == [("1", "baseline")]
    assert events(pg, "baseline") == ["1", "2", "3", "4"]

    # Day 2: record 2 status changes, record 3 disappears, record 5 is new.
    rows = rows_day1()
    rows[1]["status"] = "Pending - In Review"
    del rows[2]
    rows.append({"id": "5", "name": "New Cocktail Lounge", "date": "2026-09-01"})
    src.rows = rows
    [res] = pipeline.run([src], conn=pg, http=object(), now=DAY2, trigger="test")
    assert res.status == "success" and not res.baseline
    assert (res.new, res.changed, res.removed) == (1, 1, 1)
    assert set(queue(pg)) == {("1", "baseline"), ("2", "changed"), ("5", "new")}
    assert events(pg, "removed") == ["3"]
    with pg.cursor() as cur:
        cur.execute("""SELECT e.changes FROM record_events e JOIN records r ON r.id=e.record_id
                       WHERE r.source_record_id='2' AND e.event_type='changed'""")
        assert cur.fetchone()[0] == {"status": ["RECEIVED", "PENDING - IN REVIEW"],
                                     "stage": ["Received", "In review"]}
        cur.execute("SELECT stage FROM records WHERE source_record_id='2'")
        assert cur.fetchone()[0] == "In review"
        cur.execute("SELECT first_seen_at, last_seen_at FROM records WHERE source_record_id='1'")
        first, last = cur.fetchone()
        assert first == DAY1 and last == DAY2
        cur.execute("SELECT count(*) FROM records")
        assert cur.fetchone()[0] == 5  # no duplicates

    # Day 3: identical data -> nothing new; record 3 still gone. Then it relists.
    [res] = pipeline.run([src], conn=pg, http=object(), now=DAY3, trigger="test")
    assert (res.new, res.changed, res.removed, res.queued) == (0, 0, 0, 0)
    src.rows = rows + [rows_day1()[2]]
    [res] = pipeline.run([src], conn=pg, http=object(), now=DAY3, trigger="test")
    assert res.changed == 1
    with pg.cursor() as cur:
        cur.execute("SELECT removed_at FROM records WHERE source_record_id='3'")
        assert cur.fetchone()[0] is None


def test_raw_snapshots_dedup_and_prune(pg):
    src = FakeSource(rows_day1())
    pipeline.run([src], conn=pg, http=object(), now=DAY1)
    pipeline.run([src], conn=pg, http=object(), now=DAY2)
    with pg.cursor() as cur:
        cur.execute("SELECT count(*), bool_and(body_gz IS NOT NULL) FROM raw_snapshots")
        assert cur.fetchone() == (1, True)
        cur.execute("SELECT id FROM raw_snapshots")
        sid = cur.fetchone()[0]
    snap = db.load_snapshot(pg, sid)
    assert json.loads(snap.body)[0]["id"] == "1"
    # Latest successful run's snapshot survives pruning even when old.
    with pg.cursor() as cur:
        cur.execute("UPDATE raw_snapshots SET last_fetched_at = now() - interval '400 days'")
    pg.commit()
    assert db.prune_snapshots(pg, 14) == 0
    src.rows = rows_day1()[:2]
    pipeline.run([src], conn=pg, http=object(), now=DAY3)  # prunes at end of run
    with pg.cursor() as cur:
        cur.execute("UPDATE raw_snapshots SET last_fetched_at = now() - interval '400 days'")
    pg.commit()
    assert db.prune_snapshots(pg, 14) == 0
    with pg.cursor() as cur:
        cur.execute("SELECT id, body_gz IS NOT NULL, pruned_at IS NOT NULL "
                    "FROM raw_snapshots ORDER BY id")
        # old snapshot pruned (hash kept), latest kept
        assert [r[1:] for r in cur.fetchall()] == [(False, True), (True, False)]


def test_failed_source_is_visible_and_isolated(pg):
    bad = FakeSource([], fail=True)
    bad.name = "fake_bad"
    good = FakeSource(rows_day1())
    results = pipeline.run([bad, good], conn=pg, http=object(), now=DAY1)
    assert [r.status for r in results] == ["failed", "success"]
    assert results[0].safe_error.startswith("HTTP 503")
    with pg.cursor() as cur:
        cur.execute("SELECT status FROM runs")
        assert cur.fetchone()[0] == "partial"
        cur.execute("SELECT status, error_type, error_detail IS NOT NULL FROM source_runs "
                    "WHERE source='fake_bad'")
        assert cur.fetchone() == ("failed", "SourceHTTPError", True)


def test_sanity_floor_fails_instead_of_mass_removal(pg):
    src = FakeSource(rows_day1())
    pipeline.run([src], conn=pg, http=object(), now=DAY1)
    src.rows = []
    src.min_records = 2
    [res] = pipeline.run([src], conn=pg, http=object(), now=DAY2)
    assert res.status == "failed" and res.error_type == "SourceSanityError"
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM records WHERE removed_at IS NOT NULL")
        assert cur.fetchone()[0] == 0


def test_rolling_window_source_does_not_mark_removals(pg):
    src = FakeSource(rows_day1(), tracks_removals=False)
    pipeline.run([src], conn=pg, http=object(), now=DAY1)
    src.rows = rows_day1()[:1]
    [res] = pipeline.run([src], conn=pg, http=object(), now=DAY2)
    assert res.removed == 0


def test_logs_never_contain_record_data(pg, caplog):
    caplog.set_level("INFO")
    pipeline.run([FakeSource(rows_day1())], conn=pg, http=object(), now=DAY1)
    text = caplog.text
    for row in rows_day1():
        assert row["name"] not in text


def test_daily_leads_groups_one_venue(pg):
    rows = [{"id": "10", "name": "Fake Lounge LLC", "date": "2026-08-31"},
            {"id": "11", "name": "Fake Lounge LLC", "date": "2026-08-31"}]
    pipeline.run([FakeSource(rows)], conn=pg, http=object(), now=DAY1)
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM review_queue")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT source_record_ids, record_ids FROM daily_leads")
        [(ids, rids)] = cur.fetchall()
        assert ids == "10, 11" and len(rids.split()) == 2


def test_stage_score_stored_requalified_and_labelled(pg, monkeypatch):
    from licmon import cli

    rows = [{"id": "20", "name": "Fake Velvet Lounge LLC", "date": "2026-08-31"},
            {"id": "21", "name": "Fake Tavern LLC", "date": "2026-08-31"}]
    src = FakeSource(rows)
    pipeline.run([src], conn=pg, http=object(), now=DAY1)
    with pg.cursor() as cur:
        cur.execute("SELECT source_record_id, stage, lead_score, hot FROM records ORDER BY 1")
        # lounge: A 45 + Received 5 + original 10; tavern: B 25 + 5 + 10
        assert cur.fetchall() == [("20", "Received", 60, False), ("21", "Received", 40, False)]
        # Rows saved before stages existed: requalify fills them in.
        cur.execute("UPDATE records SET stage=NULL, lead_score=NULL, hot=NULL")
    pg.commit()
    class KeepOpen:  # cli closes its connection; the fixture owns this one
        def __enter__(self):
            return pg

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cli.db, "connect", KeepOpen)
    assert cli.main(["requalify"]) == 0
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM records WHERE stage='Received' AND lead_score > 0")
        assert cur.fetchone()[0] == 2

