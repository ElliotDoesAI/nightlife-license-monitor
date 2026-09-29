"""Postgres access. Real data lives only in the private database."""

from __future__ import annotations

import gzip
import os
from importlib import resources

import psycopg
from psycopg.types.json import Jsonb

from .models import Snapshot


def connect(url: str | None = None) -> psycopg.Connection:
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    return psycopg.connect(url, autocommit=False)


def init_schema(conn: psycopg.Connection) -> None:
    sql = resources.files("licmon").joinpath("schema.sql").read_text()
    with conn.cursor() as cur:
        # Serialize concurrent runs' DDL.
        cur.execute("SELECT pg_advisory_xact_lock(4242001)")
        cur.execute(sql)
    conn.commit()


def store_snapshot(conn: psycopg.Connection, source: str, snap: Snapshot) -> int:
    """Save raw bytes (gzip) once per unique content; return snapshot id."""
    body_gz = gzip.compress(snap.body, compresslevel=6)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw_snapshots
                (source, url, fetched_at, last_fetched_at, content_type, sha256,
                 byte_size, body_gz)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, sha256) DO UPDATE
                SET last_fetched_at = EXCLUDED.last_fetched_at,
                    body_gz = COALESCE(raw_snapshots.body_gz, EXCLUDED.body_gz),
                    pruned_at = CASE WHEN raw_snapshots.body_gz IS NULL THEN NULL
                                     ELSE raw_snapshots.pruned_at END
            RETURNING id
            """,
            (source, snap.url, snap.fetched_at, snap.fetched_at, snap.content_type,
             snap.sha256, len(snap.body), body_gz),
        )
        return cur.fetchone()[0]


def load_snapshot(conn: psycopg.Connection, snapshot_id: int) -> Snapshot | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT url, body_gz, content_type, fetched_at FROM raw_snapshots WHERE id=%s",
            (snapshot_id,))
        row = cur.fetchone()
    if not row or row[1] is None:
        return None
    return Snapshot(url=row[0], body=gzip.decompress(row[1]), content_type=row[2],
                    fetched_at=row[3])


def prune_snapshots(conn: psycopg.Connection, keep_days: int) -> int:
    """Drop raw bodies older than keep_days, but always keep each source's
    snapshots from its latest successful run. Metadata and hashes are kept."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest AS (
                SELECT DISTINCT ON (source) source, snapshot_ids
                FROM source_runs WHERE status = 'success'
                ORDER BY source, started_at DESC
            ), keep AS (
                SELECT unnest(snapshot_ids) AS id FROM latest
            )
            UPDATE raw_snapshots SET body_gz = NULL, pruned_at = now()
            WHERE body_gz IS NOT NULL
              AND last_fetched_at < now() - make_interval(days => %s)
              AND id NOT IN (SELECT id FROM keep)
            """,
            (keep_days,))
        n = cur.rowcount
    conn.commit()
    return n


def jsonb(value) -> Jsonb:
    return Jsonb(value)
