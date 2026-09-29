"""Attio CRM: the separate "License Leads" object, and the daily sync into it.

Only Hot and tier A venues go to Attio, into their own object so the rest of
the CRM stays uncluttered. Attio is the owner's internal CRM: nothing here
contacts a business.

* ``setup`` creates the object and its attributes. It only ever creates new
  things: it stops if the object already exists and never touches any other
  object.
* ``sync`` upserts the day's Hot and A venues on the unique Venue key, so a
  venue is never created twice. The team's Status field is set to New on
  create only and is never overwritten. New records are capped per day
  (ATTIO_DAILY_CAP, default 25), highest score first.

Endpoints and payloads follow the Attio REST API v2 reference
(docs.attio.com, checked 2026-09-29). Public Actions logs must never hold lead
data, so errors carry the HTTP status or error type only (like
notify.NotifyError) and callers log counts only.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime

API = "https://api.attio.com/v2"
OBJECT_SLUG = "license_leads"
SINGULAR = "License Lead"
PLURAL = "License Leads"
MATCH_ATTRIBUTE = "venue_key"
STATUS_ATTRIBUTE = "team_status"
DEFAULT_DAILY_CAP = 25

STAGE_OPTIONS = ["Licensed", "Approved", "In review", "Received"]
PRIORITY_OPTIONS = ["Hot", "A"]
STATUS_OPTIONS = ["New", "Moved to Targets", "Not a fit", "Contacted"]

#: (api_slug, title, type, is_unique, select options). Attio has no URL
#: attribute type, so links are text. Market and State are text, not selects,
#: so a new state needs no workspace change.
ATTRIBUTES: list[tuple[str, str, str, bool, list[str] | None]] = [
    ("name", "Venue", "text", False, None),
    (MATCH_ATTRIBUTE, "Venue key", "text", True, None),
    ("priority", "Priority", "select", False, PRIORITY_OPTIONS),
    ("score", "Score", "number", False, None),
    ("stage", "Stage", "select", False, STAGE_OPTIONS),
    ("market", "Market", "text", False, None),
    ("state", "State", "text", False, None),
    ("address", "Address", "text", False, None),
    ("owner_company", "Owner / company", "text", False, None),
    ("phone", "Phone", "text", False, None),
    ("license", "License", "text", False, None),
    ("filing_type", "Filing type", "text", False, None),
    ("filed_on", "Filed on", "date", False, None),
    ("first_seen", "First seen", "date", False, None),
    ("official_record", "Official record", "text", False, None),
    ("map_link", "Map", "text", False, None),
    ("google_link", "Google", "text", False, None),
    ("instagram_link", "Instagram", "text", False, None),
    (STATUS_ATTRIBUTE, "Status", "select", False, STATUS_OPTIONS),
]


class AttioError(RuntimeError):
    """Attio failure with a value-free message (HTTP status or error type)."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def api_key() -> str:
    """ATTIO_WRITE_API_KEY if set (a key allowed to change the schema),
    else ATTIO_API_KEY."""
    return (os.environ.get("ATTIO_WRITE_API_KEY", "").strip()
            or os.environ.get("ATTIO_API_KEY", "").strip())


def configured() -> bool:
    return bool(api_key())


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("ATTIO_DAILY_CAP", "").strip()
                          or DEFAULT_DAILY_CAP))
    except ValueError:
        return DEFAULT_DAILY_CAP


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Client:
    """Small JSON client for Attio. http.py stays GET-only for the scrapers."""

    def __init__(self, key: str | None = None, session=None, sleep=time.sleep):
        import requests

        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {key or api_key()}",
                                     "Content-Type": "application/json"})
        self.sleep = sleep

    def request(self, method: str, path: str, *, body: dict | None = None,
                params: dict | None = None, allow_404: bool = False):
        for attempt in range(4):
            try:
                resp = self.session.request(method, API + path, json=body,
                                            params=params, timeout=30)
            except Exception as exc:  # noqa: BLE001 - type only, values stay private
                raise AttioError(f"attio failed ({type(exc).__name__})") from exc
            if resp.status_code == 429 and attempt < 3:
                try:
                    wait = min(float(resp.headers.get("Retry-After", "1")), 10.0)
                except ValueError:
                    wait = 1.0
                self.sleep(wait)
                continue
            if allow_404 and resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                raise AttioError(f"attio failed (HTTP {resp.status_code})")
            try:
                return resp.json()
            except ValueError as exc:
                raise AttioError("attio failed (bad JSON)") from exc
        raise AttioError("attio failed (HTTP 429)")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def attribute_payload(slug: str, title: str, kind: str, unique: bool) -> dict:
    return {"data": {"title": title, "description": None, "api_slug": slug,
                     "type": kind, "is_required": False, "is_unique": unique,
                     "is_multiselect": False, "config": {}}}


def setup(client: Client | None, write: bool) -> list[str]:
    """Create the License Leads object and its attributes. Dry run unless
    `write`. Returns plain step lines (schema names only, no lead data).
    Raises AttioError if the object already exists."""
    steps: list[str] = []
    if client is not None:
        if client.request("GET", f"/objects/{OBJECT_SLUG}", allow_404=True) is not None:
            raise AttioError(f"object {OBJECT_SLUG} already exists; nothing changed")
    steps.append(f"create object {PLURAL} ({OBJECT_SLUG})")
    if write:
        client.request("POST", "/objects", body={"data": {
            "api_slug": OBJECT_SLUG, "singular_noun": SINGULAR, "plural_noun": PLURAL}})
        listed = client.request("GET", f"/objects/{OBJECT_SLUG}/attributes") or {}
        have = {a.get("api_slug") for a in listed.get("data") or []}
    else:
        have = set()
    for slug, title, kind, unique, options in ATTRIBUTES:
        if slug in have:
            steps.append(f"keep attribute {title} (Attio made it)")
            continue
        steps.append(f"create attribute {title} ({kind}{', unique' if unique else ''})")
        if write:
            client.request("POST", f"/objects/{OBJECT_SLUG}/attributes",
                           body=attribute_payload(slug, title, kind, unique))
        for option in options or []:
            steps.append(f"  add option {option}")
            if write:
                client.request("POST",
                               f"/objects/{OBJECT_SLUG}/attributes/{slug}/options",
                               body={"data": {"title": option}})
    return steps


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def candidates(rows: list[dict]) -> list[dict]:
    """Hot and tier A venues with a venue key, highest score first."""
    picked = [r for r in rows if r.get("venue_key")
              and (r.get("hot") or r.get("priority") == "A")]
    return sorted(picked, key=lambda r: (-(r.get("lead_score") or 0),
                                         r.get("business_name") or ""))


def _day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def record_values(row: dict, *, create: bool) -> dict:
    """Attio values for one venue row. Blank fields are left out (an update
    never blanks a field). Status is set to New on create only."""
    address = ", ".join(p for p in (row.get("address"), row.get("city"),
                                    row.get("state"), row.get("zip")) if p)
    values = {
        "name": row.get("business_name"),
        MATCH_ATTRIBUTE: row.get("venue_key"),
        "priority": "Hot" if row.get("hot") else "A",
        "score": row.get("lead_score"),
        "stage": row.get("stage") if row.get("stage") in STAGE_OPTIONS else None,
        "market": row.get("market"),
        "state": row.get("state"),
        "address": address,
        "owner_company": row.get("company"),
        "phone": row.get("phone"),
        "license": row.get("license"),
        "filing_type": row.get("filing"),
        "filed_on": _day(row.get("filed_on")),
        "first_seen": _day(row.get("first_seen")),
        "official_record": row.get("record_url"),
        "map_link": row.get("map_url"),
        "google_link": row.get("google_url"),
        "instagram_link": row.get("instagram_url"),
    }
    if create:
        values[STATUS_ATTRIBUTE] = "New"
    return {k: v for k, v in values.items() if v not in (None, "")}


def existing_keys(client: Client, keys: list[str]) -> set[str]:
    """Venue keys already in Attio (read-only query, 100 keys per call)."""
    found: set[str] = set()
    for i in range(0, len(keys), 100):
        chunk = keys[i:i + 100]
        data = client.request(
            "POST", f"/objects/{OBJECT_SLUG}/records/query",
            body={"filter": {MATCH_ATTRIBUTE: {"$in": chunk}}, "limit": 500},
            allow_404=True)
        if data is None:
            raise AttioError(f"object {OBJECT_SLUG} not found; run licmon attio-setup")
        for rec in data.get("data") or []:
            for value in (rec.get("values") or {}).get(MATCH_ATTRIBUTE) or []:
                if value.get("value"):
                    found.add(value["value"])
    return found


def sync(client: Client | None, rows: list[dict], *, write: bool,
         cap: int | None = None) -> dict:
    """Upsert the day's Hot and A venues. Returns counts only:
    candidates, hot, created, updated, over_cap. Without a client (dry run
    with no key) every venue counts as new."""
    cap = daily_cap() if cap is None else cap
    picks = candidates(rows)
    # One row per venue: a venue queued twice in a day is one record.
    unique: dict[str, dict] = {}
    for row in picks:
        unique.setdefault(row["venue_key"], row)
    picks = list(unique.values())
    have = existing_keys(client, list(unique)) if client is not None else set()
    updates = [r for r in picks if r["venue_key"] in have]
    new = [r for r in picks if r["venue_key"] not in have]  # already score order
    creates, over = new[:cap], new[cap:]
    if write:
        for row, create in [(r, False) for r in updates] + [(r, True) for r in creates]:
            client.request("PUT", f"/objects/{OBJECT_SLUG}/records",
                           params={"matching_attribute": MATCH_ATTRIBUTE},
                           body={"data": {"values": record_values(row, create=create)}})
    return {"candidates": len(picks), "hot": sum(1 for r in picks if r.get("hot")),
            "created": len(creates), "updated": len(updates), "over_cap": len(over),
            "written": bool(write)}


def write_counts(path, counts: dict) -> None:
    """Counts-only hand-off to the Slack step (no lead data)."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(counts, fh)


def read_counts(path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
