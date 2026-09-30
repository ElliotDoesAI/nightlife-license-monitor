"""Daily run: fetch -> save raw -> parse -> dedupe/diff -> qualify -> venue
history -> queue."""

from __future__ import annotations

import logging
import os
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import psycopg

from . import db
from . import history as history_mod
from . import stage as stage_mod
from .http import Http, SourceHTTPError
from .metros import assign_metro
from .models import MATERIAL_FIELDS, Record, venue_key
from .qualify import apply_history, qualify
from .sources.base import Source

log = logging.getLogger("licmon")

# On a source's first run everything is "new"; only records whose application
# date is this recent go into the queue, the rest become a silent baseline.
# Sources without application dates (CA export) queue nothing on the first
# run; their genuinely new applications queue from the second run on.
BASELINE_RECENT_DAYS = int(os.environ.get("LICMON_BASELINE_RECENT_DAYS", "14"))


class SourceSanityError(RuntimeError):
    pass


@dataclass
class SourceResult:
    source: str
    status: str
    fetched: int = 0
    new: int = 0
    changed: int = 0
    removed: int = 0
    queued: int = 0
    baseline: bool = False
    duplicates: int = 0
    seconds: float = 0.0
    error_type: str | None = None
    safe_error: str | None = None  # safe for public logs


def _material_from_row(row: dict, fields: tuple[str, ...]) -> dict:
    out = {}
    for name in fields:
        value = row.get(name)
        if isinstance(value, date):
            value = value.isoformat()
        if isinstance(value, str):
            value = value.upper()
        out[name] = value
    return out


RECORD_COLUMNS = ("source_url", "legal_name", "dba", "license_type",
                  "license_description", "application_type", "status",
                  "application_date", "address", "city", "state", "zip", "county",
                  "category")


def _values(rec: Record) -> list:
    return [getattr(rec, c) for c in RECORD_COLUMNS]


def run_source(conn: psycopg.Connection, source: Source, http: Http, run_id: int,
               now: datetime | None = None) -> SourceResult:
    now = now or datetime.now(timezone.utc)
    t0 = time.monotonic()
    res = SourceResult(source=source.name, status="running")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO source_runs (run_id, source) VALUES (%s, %s) RETURNING id",
                    (run_id, source.name))
        sr_id = cur.fetchone()[0]
    conn.commit()

    try:
        snapshots = source.fetch(http)
        # PRD: save the original source data before modifying it.
        snap_ids = [db.store_snapshot(conn, source.name, s) for s in snapshots]
        with conn.cursor() as cur:
            cur.execute("UPDATE source_runs SET snapshot_ids=%s WHERE id=%s",
                        (snap_ids, sr_id))
        conn.commit()

        # Keep the first row per id on purpose; count repeats so they are visible.
        records: dict[str, Record] = {}
        for rec in source.parse(snapshots):
            if rec.source_record_id in records:
                res.duplicates += 1
            else:
                records[rec.source_record_id] = rec
        res.fetched = len(records)
        if res.fetched < source.min_records:
            raise SourceSanityError(
                f"parsed {res.fetched} records, below floor {source.min_records}; "
                "upstream format may have changed")
        last_snap = snap_ids[-1] if snap_ids else None
        _apply(conn, source, records, sr_id, last_snap, now, res, http=http,
               snapshots=snapshots)
        res.status = "success"
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE source_runs SET status='success', finished_at=now(),
                   is_baseline=%s, records_fetched=%s, records_new=%s,
                   records_changed=%s, records_removed=%s,
                   records_qualified_queued=%s WHERE id=%s""",
                (res.baseline, res.fetched, res.new, res.changed, res.removed,
                 res.queued, sr_id))
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - one source must not stop others
        conn.rollback()
        res.status = "failed"
        res.error_type = type(exc).__name__
        # Only our own error types carry messages known to be free of record data.
        if isinstance(exc, (SourceHTTPError, SourceSanityError)):
            res.safe_error = str(exc)[:300]
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE source_runs SET status='failed', finished_at=now(),
                   records_fetched=%s, error_type=%s, error_detail=%s WHERE id=%s""",
                (res.fetched or None, res.error_type, traceback.format_exc()[-8000:], sr_id))
        conn.commit()
    res.seconds = round(time.monotonic() - t0, 1)
    return res


def _apply(conn, source: Source, records: dict[str, Record], sr_id: int,
           snap_id: int | None, now: datetime, res: SourceResult, http=None,
           snapshots=None) -> None:
    recent_cutoff = (now - timedelta(days=BASELINE_RECENT_DAYS)).date()
    mfields = source.material_fields
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM source_runs WHERE source=%s AND status='success' LIMIT 1",
                    (source.name,))
        res.baseline = cur.fetchone() is None

        cols = ", ".join(("id", "source_record_id", "material_hash", "removed_at", "stage")
                         + MATERIAL_FIELDS)
        cur.execute(f"SELECT {cols} FROM records WHERE source=%s", (source.name,))
        names = [d.name for d in cur.description]
        existing = {r[1]: dict(zip(names, r)) for r in cur.fetchall()}

        inserts, updates, touched = [], [], []
        for srid, rec in records.items():
            metro = assign_metro(rec.state, rec.county, rec.city)
            q = qualify(rec, metro, source=source, today=now.date())
            old = existing.get(srid)
            if old is None:
                if res.baseline:
                    recent = bool(rec.application_date and rec.application_date >= recent_cutoff)
                    etype, queued = "baseline", q.qualified and recent
                else:
                    etype, queued = "new", q.qualified
                    res.new += 1
                inserts.append((rec, metro, q, etype, queued))
                continue

            changes = None
            if old["material_hash"] != rec.material_hash(mfields):
                before = _material_from_row(old, mfields)
                after = rec.material(mfields)
                changes = {k: [before[k], after[k]] for k in mfields
                           if before[k] != after[k]}
                old_stage = old["stage"] or _old_stage(source, srid, old)
                if stage_mod.rank(q.stage) > stage_mod.rank(old_stage):
                    # Read by the lead sheet and Slack as "Stage advanced".
                    changes["stage"] = [old_stage, q.stage]
            if old["removed_at"] is not None:
                changes = dict(changes or {}, relisted=[False, True])
            if changes:
                res.changed += 1
                updates.append((rec, metro, q, old["id"], changes))
            else:
                touched.append(old["id"])

        # Venue history for what reaches the queue today: qualified new and
        # changed records (a baseline run only its queued ones). Network, so
        # never for the silent baseline; a failure leaves them Unknown.
        need = ([rec for rec, _, q, _, queued in inserts if queued]
                + [rec for rec, _, q, _, _ in updates if q.qualified])
        hist = history_mod.lookup(source, http, need, snapshots, now.date()) if need else {}
        for rec, _, q, *_ in inserts + updates:
            h = hist.get(rec.source_record_id)
            if h:
                apply_history(q, h.label)

        for rec, metro, q, rid, changes in updates:
            h = hist.get(rec.source_record_id)
            cur.execute(
                f"""UPDATE records SET {', '.join(f'{c}=%s' for c in RECORD_COLUMNS)},
                    metro=%s, venue_key=%s, material_hash=%s, raw=%s, last_seen_at=%s,
                    last_changed_at=%s, removed_at=NULL, last_snapshot_id=%s,
                    qualified=%s, score=%s, tier=%s, qualify_reason=%s,
                    stage=%s, lead_score=%s, hot=%s, adult=%s{_HISTORY_SET if h else ''}
                    WHERE id=%s""",
                _values(rec) + [metro, venue_key(rec), rec.material_hash(mfields),
                                db.jsonb(rec.raw), now, now, snap_id, q.qualified, q.score,
                                q.tier, q.reason, q.stage, q.lead_score, q.hot, q.adult]
                + (_history_values(h) if h else []) + [rid])
        events = [(rid, sr_id, "changed", now, db.jsonb(changes), q.qualified)
                  for rec, metro, q, rid, changes in updates]

        if touched:
            cur.execute("UPDATE records SET last_seen_at=%s, last_snapshot_id=%s "
                        "WHERE id = ANY(%s)", (now, snap_id, touched))

        if inserts:
            placeholders = ", ".join(["%s"] * (len(RECORD_COLUMNS) + 24))
            cur.executemany(
                f"""INSERT INTO records (source, source_record_id,
                    {', '.join(RECORD_COLUMNS)}, metro, venue_key, material_hash, raw,
                    first_seen_at, last_seen_at, last_changed_at, first_snapshot_id,
                    last_snapshot_id, qualified, score, tier, qualify_reason,
                    review_status, review_notes, stage, lead_score, hot, adult,
                    venue_history, prior_licenses, prior_since)
                    VALUES ({placeholders}) RETURNING source_record_id, id""",
                [[rec.source, rec.source_record_id] + _values(rec)
                 + [metro, venue_key(rec), rec.material_hash(mfields), db.jsonb(rec.raw),
                    now, now, now,
                    snap_id, snap_id, q.qualified, q.score, q.tier, q.reason, "new", None,
                    q.stage, q.lead_score, q.hot, q.adult]
                 + _history_values(hist.get(rec.source_record_id))
                 for rec, metro, q, _, _ in inserts],
                returning=True)
            # Map ids by key rather than trusting result-set order.
            ids = {}
            while True:
                srid_, rid_ = cur.fetchone()
                ids[srid_] = rid_
                if not cur.nextset():
                    break
            for rec, _, _, etype, queued in inserts:
                events.append((ids[rec.source_record_id], sr_id, etype, now, None, queued))

        if source.tracks_removals:
            gone = [o["id"] for srid, o in existing.items()
                    if srid not in records and o["removed_at"] is None]
            if gone:
                cur.execute("UPDATE records SET removed_at=%s WHERE id = ANY(%s)",
                            (now, gone))
                events.extend((rid, sr_id, "removed", now, None, False) for rid in gone)
                res.removed = len(gone)

        if events:
            cur.executemany(
                """INSERT INTO record_events
                   (record_id, source_run_id, event_type, observed_at, changes, queued)
                   VALUES (%s, %s, %s, %s, %s, %s)""", events)
        res.queued = sum(1 for e in events if e[5])


_HISTORY_SET = ", venue_history=%s, prior_licenses=%s, prior_since=%s"


def _history_values(h) -> list:
    """(venue_history, prior_licenses, prior_since) for a History or None."""
    return [h.label, h.prior_licenses, h.prior_since] if h else [None, None, None]


def _old_stage(source: Source, srid: str, old: dict) -> str | None:
    """Stage of the stored version, for rows saved before stages existed."""
    try:
        return source.stage(Record(source=source.name, source_record_id=srid,
                                   source_url="", **{k: old[k] for k in MATERIAL_FIELDS}))
    except Exception:  # noqa: BLE001 - a label only; never fail the source
        return None


def run(sources: list[Source], *, trigger: str = "manual", conn=None, http=None,
        now: datetime | None = None) -> list[SourceResult]:
    own = conn is None
    conn = conn or db.connect()
    http = http or Http()
    try:
        db.init_schema(conn)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO runs (trigger, git_sha) VALUES (%s, %s) RETURNING id",
                        (trigger, os.environ.get("GITHUB_SHA")))
            run_id = cur.fetchone()[0]
        conn.commit()
        results = []
        for source in sources:
            log.info("source %s: starting", source.name)
            res = run_source(conn, source, http, run_id, now=now)
            results.append(res)
            log_result(res)
        failed = sum(r.status != "success" for r in results)
        status = "success" if not failed else "failed" if failed == len(results) else "partial"
        with conn.cursor() as cur:
            cur.execute("UPDATE runs SET status=%s, finished_at=now() WHERE id=%s",
                        (status, run_id))
        conn.commit()
        keep = int(os.environ.get("RAW_RETENTION_DAYS", "14"))
        pruned = db.prune_snapshots(conn, keep)
        log.info("run %s: %s; pruned %s old raw snapshot bodies", run_id, status, pruned)
        return results
    finally:
        if own:
            conn.close()


def log_result(res: SourceResult) -> None:
    """Counts only. Never log record contents: Actions logs are public."""
    if res.status == "success":
        log.info("source %s: ok in %ss fetched=%d new=%d changed=%d removed=%d "
                 "queued=%d dup_ids=%d%s", res.source, res.seconds, res.fetched, res.new,
                 res.changed, res.removed, res.queued, res.duplicates,
                 " (baseline run)" if res.baseline else "")
    else:
        log.error("source %s: FAILED in %ss (%s)%s", res.source, res.seconds,
                  res.error_type, f": {res.safe_error}" if res.safe_error else
                  " - details in source_runs.error_detail")
